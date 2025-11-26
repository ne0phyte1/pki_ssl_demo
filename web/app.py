# web/app.py
import os
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_socketio import SocketIO, emit
from werkzeug.middleware.proxy_fix import ProxyFix

# ---------------- 基础配置 ----------------
app = Flask(__name__)
app.secret_key = os.urandom(24)  # 简单用随机 secret，正式可以写死

# 让 SocketIO 用 eventlet 作为异步引擎
socketio = SocketIO(app, async_mode="threading")

# 数据库初始化
def init_db():
    """初始化SQLite数据库 - 分别创建用户数据库和聊天记录数据库"""
    # 确保db目录存在
    os.makedirs('./web/db', exist_ok=True)
    
    # 初始化用户数据库
    users_conn = sqlite3.connect('./web/db/users.db')
    users_cursor = users_conn.cursor()
    
    users_cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    users_conn.commit()
    users_conn.close()
    
    # 初始化聊天记录数据库
    chat_conn = sqlite3.connect('./web/db/chat_messages.db')
    chat_cursor = chat_conn.cursor()
    
    chat_cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    chat_conn.commit()
    chat_conn.close()

# 初始化数据库
init_db()

# 记录在线用户：sid -> username
online_users = {}

# ---------------- 用户认证函数 ----------------

def register_user(username, password):
    """注册新用户"""
    conn = sqlite3.connect('./web/db/users.db')
    cursor = conn.cursor()
    try:
        password_hash = generate_password_hash(password)
        cursor.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', 
                      (username, password_hash))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # 用户名已存在
    finally:
        conn.close()

def authenticate_user(username, password):
    """验证用户凭据"""
    conn = sqlite3.connect('./web/db/users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT password_hash FROM users WHERE username = ?', (username,))
    result = cursor.fetchone()
    conn.close()
    
    if result and check_password_hash(result[0], password):
        return True
    return False

def save_chat_message(username, message):
    """保存聊天消息到数据库"""
    conn = sqlite3.connect('./web/db/chat_messages.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO chat_messages (username, message) VALUES (?, ?)', 
                  (username, message))
    conn.commit()
    conn.close()

def load_chat_history(limit=100):
    """从数据库加载聊天历史"""
    conn = sqlite3.connect('./web/db/chat_messages.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT username, message, timestamp 
        FROM chat_messages 
        ORDER BY timestamp DESC 
        LIMIT ?
    ''', (limit,))
    messages = cursor.fetchall()
    conn.close()
    
    # 转换为与之前兼容的格式
    history = []
    for username, message, timestamp in reversed(messages):
        # 将timestamp转换为时间字符串
        if isinstance(timestamp, str):
            time_str = timestamp.split(' ')[1] if ' ' in timestamp else timestamp
        else:
            time_str = timestamp.strftime("%H:%M:%S")
        history.append({
            "user": username,
            "text": message,
            "time": time_str
        })
    return history

# ---------------- HTTP 路由：登录 / 注册 / 聊天页 ----------------

@app.route("/", methods=["GET", "POST"])
def login():
    """用户登录"""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        
        if not username or not password:
            return render_template("login.html", error="用户名和密码不能为空")
        
        if authenticate_user(username, password):
            session["username"] = username
            return redirect(url_for("chat"))
        else:
            return render_template("login.html", error="用户名或密码错误")

    # 已登录用户直接跳转到聊天页
    if "username" in session:
        return redirect(url_for("chat"))

    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    """用户注册"""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        
        if not username or not password:
            return render_template("register.html", error="用户名和密码不能为空")
        
        if password != confirm_password:
            return render_template("register.html", error="两次输入的密码不一致")
        
        if len(password) < 6:
            return render_template("register.html", error="密码长度至少6位")
        
        if register_user(username, password):
            session["username"] = username
            return redirect(url_for("chat"))
        else:
            return render_template("register.html", error="用户名已存在")

    return render_template("register.html")


@app.route("/chat")
def chat():
    """聊天主界面"""
    if "username" not in session:
        return redirect(url_for("login"))

    # 从数据库加载聊天历史
    history = load_chat_history()

    return render_template(
        "chat.html",
        username=session["username"],
        history=history,
    )


@app.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("login"))


# ---------------- Socket.IO 事件：在线用户 & 聊天 ----------------

@socketio.on("connect")
def handle_connect():
    """有浏览器建立 WebSocket 连接时触发"""
    username = session.get("username")
    if not username:
        # 没登录的连接直接拒绝
        return False

    online_users[request.sid] = username
    print(f"[+] {username} connected, sid={request.sid}")

    # 广播系统消息 & 在线列表
    emit(
        "system_message",
        {"text": f"{username} 加入了聊天室"},
        broadcast=True,
    )
    emit_online_users()


@socketio.on("disconnect")
def handle_disconnect():
    username = online_users.pop(request.sid, None)
    if username:
        print(f"[-] {username} disconnected, sid={request.sid}")
        emit(
            "system_message",
            {"text": f"{username} 离开了聊天室"},
            broadcast=True,
        )
        emit_online_users()


def emit_online_users():
    """广播在线用户列表"""
    users = sorted(set(online_users.values()))
    emit("online_users", users, broadcast=True)


@socketio.on("chat_message")
def handle_chat_message(data):
    """处理聊天消息"""
    username = session.get("username", "匿名")
    text = (data or {}).get("text", "").strip()
    if not text:
        return

    # 保存消息到数据库
    save_chat_message(username, text)

    # 构建消息对象用于广播
    msg = {
        "user": username,
        "text": text,
        "time": datetime.now().strftime("%H:%M:%S"),
    }

    # 广播聊天消息
    emit("chat_message", msg, broadcast=True)


# ---------------- 入口：启用 TLS 运行 ----------------

if __name__ == "__main__":
    # 复用你第二阶段生成的服务器证书
    cert_path = os.path.join("server", "server_fullchain.crt")
    key_path  = os.path.join("server", "server.key")

    # 8443 只是避免和原来 4433 的原生 TLS 聊天端口冲突
    socketio.run(
        app,
        host="0.0.0.0",
        port=8443,
        ssl_context=(cert_path, key_path),
    )
