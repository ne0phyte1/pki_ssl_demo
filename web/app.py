# web/app.py
import os
import sqlite3
import secrets
import string
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.middleware.proxy_fix import ProxyFix

# ---------------- 基础配置 ----------------
app = Flask(__name__)
app.secret_key = os.urandom(24)  # 简单用随机 secret，正式可以写死

# 让 SocketIO 用 eventlet 作为异步引擎
socketio = SocketIO(app, async_mode="threading")

# 生成随机token函数
def generate_token(length=10):
    """生成指定长度的随机token"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

# 数据库初始化
def init_db():
    """初始化SQLite数据库 - 分别创建用户数据库、聊天记录数据库、聊天室和私人消息数据库"""
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
            room_id TEXT DEFAULT 'general',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 创建聊天室表 - 增加room_type和token字段
    chat_cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_by TEXT NOT NULL,
            room_type TEXT DEFAULT 'public',
            token TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 创建私人消息表
    chat_cursor.execute('''
        CREATE TABLE IF NOT EXISTS private_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user TEXT NOT NULL,
            to_user TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 创建用户-聊天室关系表
    chat_cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            room_id TEXT NOT NULL,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(username, room_id)
        )
    ''')
    
    # 插入默认聊天室（公共）
    chat_cursor.execute('''
        INSERT OR IGNORE INTO chat_rooms (name, created_by, room_type) 
        VALUES ('general', 'system', 'public')
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
    conn = None
    try:
        conn = sqlite3.connect('./web/db/users.db')
        cursor = conn.cursor()
        password_hash = generate_password_hash(password)
        cursor.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', 
                      (username, password_hash))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # 用户名已存在
    except Exception as e:
        print(f"注册用户时出错: {e}")
        return False
    finally:
        if conn:
            conn.close()

def authenticate_user(username, password):
    """验证用户凭据"""
    conn = None
    try:
        conn = sqlite3.connect('./web/db/users.db')
        cursor = conn.cursor()
        cursor.execute('SELECT password_hash FROM users WHERE username = ?', (username,))
        result = cursor.fetchone()
        
        if result and check_password_hash(result[0], password):
            return True
        return False
    except Exception as e:
        print(f"用户认证时出错: {e}")
        return False
    finally:
        if conn:
            conn.close()

def save_chat_message(username, message, room_id='general'):
    """保存聊天消息到数据库"""
    conn = None
    try:
        conn = sqlite3.connect('./web/db/chat_messages.db')
        cursor = conn.cursor()
        cursor.execute('INSERT INTO chat_messages (username, message, room_id) VALUES (?, ?, ?)', 
                      (username, message, room_id))
        conn.commit()
    except Exception as e:
        print(f"保存聊天消息时出错: {e}")
    finally:
        if conn:
            conn.close()

def load_chat_history(room_id='general', limit=100):
    """从数据库加载指定聊天室的历史"""
    conn = None
    try:
        conn = sqlite3.connect('./web/db/chat_messages.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT username, message, timestamp 
            FROM chat_messages 
            WHERE room_id = ?
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (room_id, limit))
        messages = cursor.fetchall()
        
        # 转换为与之前兼容的格式
        history = []
        for username, message, timestamp in reversed(messages):
            # 安全处理时间戳转换
            try:
                if timestamp is None:
                    time_str = "未知时间"
                elif isinstance(timestamp, str):
                    # 尝试从字符串中提取时间部分
                    if ' ' in timestamp:
                        time_str = timestamp.split(' ')[1]
                    else:
                        time_str = timestamp
                else:
                    # 假设是datetime对象
                    time_str = timestamp.strftime("%H:%M:%S")
            except Exception:
                time_str = "时间错误"
                
            history.append({
                "user": username,
                "text": message,
                "time": time_str
            })
        return history
    except Exception as e:
        print(f"加载聊天历史时出错: {e}")
        return []
    finally:
        if conn:
            conn.close()

def create_chat_room(room_name, created_by):
    """创建新聊天室"""
    conn = None
    try:
        conn = sqlite3.connect('./web/db/chat_messages.db')
        cursor = conn.cursor()
        cursor.execute('INSERT INTO chat_rooms (name, created_by) VALUES (?, ?)', 
                      (room_name, created_by))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # 聊天室名已存在
    except Exception as e:
        print(f"创建聊天室时出错: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_chat_rooms():
    """获取所有聊天室列表"""
    conn = None
    try:
        conn = sqlite3.connect('./web/db/chat_messages.db')
        cursor = conn.cursor()
        cursor.execute('SELECT name, created_by, created_at FROM chat_rooms ORDER BY created_at DESC')
        rooms = cursor.fetchall()
        return [{"name": name, "created_by": created_by, "created_at": created_at} 
                for name, created_by, created_at in rooms]
    except Exception as e:
        print(f"获取聊天室列表时出错: {e}")
        return []
    finally:
        if conn:
            conn.close()

def join_chat_room(username, room_id):
    """用户加入聊天室"""
    conn = None
    try:
        conn = sqlite3.connect('./web/db/chat_messages.db')
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO user_rooms (username, room_id) VALUES (?, ?)', 
                      (username, room_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"加入聊天室时出错: {e}")
        return False
    finally:
        if conn:
            conn.close()

def leave_chat_room(username, room_id):
    """用户离开聊天室"""
    conn = None
    try:
        conn = sqlite3.connect('./web/db/chat_messages.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM user_rooms WHERE username = ? AND room_id = ?', 
                      (username, room_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"离开聊天室时出错: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_user_rooms(username):
    """获取用户加入的聊天室"""
    conn = None
    try:
        conn = sqlite3.connect('./web/db/chat_messages.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT room_id FROM user_rooms 
            WHERE username = ? 
            ORDER BY joined_at DESC
        ''', (username,))
        rooms = cursor.fetchall()
        return [room[0] for room in rooms]
    except Exception as e:
        print(f"获取用户聊天室时出错: {e}")
        return []
    finally:
        if conn:
            conn.close()

def save_private_message(from_user, to_user, message):
    """保存私人消息到数据库"""
    try:
        conn = sqlite3.connect('./web/db/chat_messages.db')
        cursor = conn.cursor()
        cursor.execute('INSERT INTO private_messages (from_user, to_user, message) VALUES (?, ?, ?)', 
                      (from_user, to_user, message))
        conn.commit()
    except Exception as e:
        print(f"保存私人消息失败: {e}")
        return False
    finally:
        conn.close()
    return True

def load_private_messages(user1, user2, limit=50):
    """加载两个用户之间的私人消息历史"""
    conn = None
    try:
        conn = sqlite3.connect('./web/db/chat_messages.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT from_user, to_user, message, timestamp 
            FROM private_messages 
            WHERE (from_user = ? AND to_user = ?) OR (from_user = ? AND to_user = ?)
            ORDER BY timestamp ASC 
            LIMIT ?
        ''', (user1, user2, user2, user1, limit))
        messages = cursor.fetchall()
        
        history = []
        for from_user, to_user, message, timestamp in messages:
            # 安全处理时间戳转换
            try:
                if timestamp is None:
                    time_str = "未知时间"
                elif isinstance(timestamp, str):
                    # 尝试从字符串中提取时间部分
                    if ' ' in timestamp:
                        time_str = timestamp.split(' ')[1]
                    else:
                        time_str = timestamp
                else:
                    # 假设是datetime对象
                    time_str = timestamp.strftime("%H:%M:%S")
            except Exception:
                time_str = "时间错误"
                
            history.append({
                "user": from_user,  # 使用发送者作为显示用户
                "text": message,
                "time": time_str
            })
        return history
    except Exception as e:
        print(f"加载私人消息历史时出错: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_private_chats(username):
    """获取用户的私聊会话列表"""
    conn = None
    try:
        conn = sqlite3.connect('./web/db/chat_messages.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT DISTINCT 
                CASE 
                    WHEN from_user = ? THEN to_user 
                    ELSE from_user 
                END as chat_partner,
                MAX(timestamp) as last_message_time
            FROM private_messages 
            WHERE from_user = ? OR to_user = ?
            GROUP BY chat_partner
            ORDER BY last_message_time DESC
        ''', (username, username, username))
        chats = cursor.fetchall()
        
        return [{"partner": partner, "last_message_time": last_time} 
                for partner, last_time in chats]
    except Exception as e:
        print(f"获取私聊会话列表时出错: {e}")
        return []
    finally:
        if conn:
            conn.close()

# ---------------- 私有聊天室相关函数 ----------------

def create_chat_room_with_type(room_name, created_by, room_type='public'):
    """创建新聊天室（支持公共/私有类型）"""
    conn = sqlite3.connect('./web/db/chat_messages.db')
    cursor = conn.cursor()
    try:
        if room_type == 'private':
            # 为私有聊天室生成唯一token，重试3次以避免token重复
            max_retries = 3
            for attempt in range(max_retries):
                token = generate_token()
                try:
                    cursor.execute('INSERT INTO chat_rooms (name, created_by, room_type, token) VALUES (?, ?, ?, ?)', 
                                  (room_name, created_by, room_type, token))
                    conn.commit()
                    return {'success': True, 'token': token}
                except sqlite3.IntegrityError:
                    # 可能是token重复或房间名重复，如果是最后一次重试，返回错误
                    if attempt == max_retries - 1:
                        return {'success': False, 'error': '聊天室名已存在或token生成失败，请重试'}
                    # 否则重试生成token
                    continue
        else:
            cursor.execute('INSERT INTO chat_rooms (name, created_by, room_type) VALUES (?, ?, ?)', 
                          (room_name, created_by, room_type))
            conn.commit()
            return {'success': True, 'token': None}
    except sqlite3.IntegrityError:
        return {'success': False, 'error': '聊天室名已存在'}
    finally:
        conn.close()

def get_chat_rooms_public_only():
    """获取所有公共聊天室列表（私有聊天室不显示）"""
    conn = None
    try:
        conn = sqlite3.connect('./web/db/chat_messages.db')
        cursor = conn.cursor()
        cursor.execute('SELECT name, created_by, created_at FROM chat_rooms WHERE room_type = "public" ORDER BY created_at DESC')
        rooms = cursor.fetchall()
        return [{"name": name, "created_by": created_by, "created_at": created_at} 
                for name, created_by, created_at in rooms]
    except Exception as e:
        print(f"获取公共聊天室列表时出错: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_chat_room_by_token(token):
    """通过token获取私有聊天室信息"""
    conn = None
    try:
        conn = sqlite3.connect('./web/db/chat_messages.db')
        cursor = conn.cursor()
        cursor.execute('SELECT name, created_by, room_type FROM chat_rooms WHERE token = ?', (token,))
        result = cursor.fetchone()
        if result:
            return {"name": result[0], "created_by": result[1], "room_type": result[2]}
        return None
    except Exception as e:
        print(f"通过token获取聊天室信息时出错: {e}")
        return None
    finally:
        if conn:
            conn.close()

def join_chat_room_by_token(username, token):
    """通过token加入私有聊天室"""
    try:
        room_info = get_chat_room_by_token(token)
        if not room_info:
            return {'success': False, 'error': '无效的token'}
        
        room_name = room_info['name']
        
        # 加入数据库记录
        if join_chat_room(username, room_name):
            return {'success': True, 'room_name': room_name}
        else:
            return {'success': False, 'error': '加入聊天室失败'}
    except Exception as e:
        print(f"通过token加入聊天室时出错: {e}")
        return {'success': False, 'error': '加入聊天室时发生错误'}

def delete_chat_room(room_name, username):
    """删除聊天室（只有创建者可以删除）"""
    conn = None
    try:
        conn = sqlite3.connect('./web/db/chat_messages.db')
        cursor = conn.cursor()
        
        # 检查用户是否是创建者
        cursor.execute('SELECT created_by FROM chat_rooms WHERE name = ?', (room_name,))
        result = cursor.fetchone()
        
        if not result:
            return {'success': False, 'error': '聊天室不存在'}
        
        if result[0] != username:
            return {'success': False, 'error': '只有创建者可以删除聊天室'}
        
        # 不能删除默认聊天室
        if room_name == 'general':
            return {'success': False, 'error': '不能删除默认聊天室'}
        
        # 删除聊天室
        cursor.execute('DELETE FROM chat_rooms WHERE name = ?', (room_name,))
        # 删除用户-聊天室关系
        cursor.execute('DELETE FROM user_rooms WHERE room_id = ?', (room_name,))
        # 删除聊天消息
        cursor.execute('DELETE FROM chat_messages WHERE room_id = ?', (room_name,))
        
        conn.commit()
        return {'success': True}
    except Exception as e:
        print(f"删除聊天室时出错: {e}")
        return {'success': False, 'error': str(e)}
    finally:
        if conn:
            conn.close()

def get_user_created_rooms(username):
    """获取用户创建的聊天室"""
    conn = None
    try:
        conn = sqlite3.connect('./web/db/chat_messages.db')
        cursor = conn.cursor()
        cursor.execute('SELECT name, room_type, token FROM chat_rooms WHERE created_by = ? ORDER BY created_at DESC', (username,))
        rooms = cursor.fetchall()
        return [{"name": name, "room_type": room_type, "token": token} 
                for name, room_type, token in rooms]
    except Exception as e:
        print(f"获取用户创建的聊天室时出错: {e}")
        return []
    finally:
        if conn:
            conn.close()

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
            return redirect(url_for("dashboard"))
        else:
            return render_template("login.html", error="用户名或密码错误")

    # 已登录用户直接跳转到仪表盘
    if "username" in session:
        return redirect(url_for("dashboard"))

    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    """仪表盘页面 - 用户可以选择进入聊天室或开始私人聊天"""
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]
    
    # 获取公共聊天室和在线用户信息
    public_rooms = get_chat_rooms_public_only()
    user_rooms = get_user_rooms(username)
    
    # 确保用户至少加入默认聊天室
    if 'general' not in user_rooms:
        join_chat_room(username, 'general')
        user_rooms = get_user_rooms(username)
    
    # 获取在线用户列表（从数据库查询活跃用户）
    conn = sqlite3.connect('./web/db/users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT username FROM users ORDER BY username')
    all_users = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    # 移除当前用户
    other_users = [user for user in all_users if user != username]

    return render_template(
        "dashboard.html",
        username=username,
        public_rooms=public_rooms,
        user_rooms=user_rooms,
        other_users=other_users
    )

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
            return redirect(url_for("dashboard"))
        else:
            return render_template("register.html", error="用户名已存在")

    return render_template("register.html")


@app.route("/chat")
def chat():
    """聊天主界面"""
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]
    
    # 获取所有聊天室和用户加入的聊天室
    all_rooms = get_chat_rooms()
    user_rooms = get_user_rooms(username)
    
    # 确保用户至少加入默认聊天室
    if 'general' not in user_rooms:
        join_chat_room(username, 'general')
        user_rooms = get_user_rooms(username)
    
    # 从数据库加载默认聊天室的历史
    history = load_chat_history('general')

    return render_template(
        "chat.html",
        username=username,
        history=history,
        all_rooms=all_rooms,
        user_rooms=user_rooms
    )


@app.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("login"))


# 记录用户当前所在的聊天室：sid -> room_id
user_current_rooms = {}

# ---------------- Socket.IO 事件：在线用户 & 聊天 ----------------

@socketio.on("connect")
def handle_connect():
    """有浏览器建立 WebSocket 连接时触发"""
    username = session.get("username")
    if not username:
        # 没登录的连接直接拒绝
        return False

    online_users[request.sid] = username
    user_current_rooms[request.sid] = 'general'  # 默认加入general聊天室
    
    # 加入默认聊天室的Socket.IO房间
    join_room('general')
    print(f"[+] {username} connected, sid={request.sid}, joined room: general")

    # 发送聊天室列表给新连接的用户（只显示公共聊天室）
    emit("chat_rooms_list", get_chat_rooms_public_only())
    
    # 发送用户加入的聊天室列表
    emit("user_rooms_list", get_user_rooms(username))
    
    # 发送私聊会话列表
    emit("private_chats_list", get_private_chats(username))

    # 广播系统消息 & 在线列表
    emit(
        "system_message",
        {"text": f"{username} 加入了聊天室"},
        room='general',
        broadcast=True,
    )
    emit_online_users()


@socketio.on("disconnect")
def handle_disconnect():
    username = online_users.pop(request.sid, None)
    user_current_rooms.pop(request.sid, None)
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

    current_room = user_current_rooms.get(request.sid, 'general')
    
    # 保存消息到数据库
    save_chat_message(username, text, current_room)

    # 构建消息对象用于广播
    msg = {
        "user": username,
        "text": text,
        "time": datetime.now().strftime("%H:%M:%S"),
        "room": current_room
    }

    # 广播聊天消息到当前聊天室的所有用户
    emit("chat_message", msg, room=current_room, broadcast=True)


@socketio.on("create_room")
def handle_create_room(data):
    """创建新聊天室"""
    username = session.get("username")
    room_name = (data or {}).get("room_name", "").strip()
    
    if not username or not room_name:
        return
    
    if create_chat_room(room_name, username):
        # 自动加入创建的聊天室
        join_chat_room(username, room_name)
        
        # 离开当前房间，加入新房间
        current_room = user_current_rooms.get(request.sid, 'general')
        if current_room != room_name:
            leave_room(current_room)
            join_room(room_name)
            user_current_rooms[request.sid] = room_name
        
        # 通知所有用户更新聊天室列表
        emit("chat_rooms_list", get_chat_rooms(), broadcast=True)
        emit("user_rooms_list", get_user_rooms(username))
        
        # 发送系统消息到新房间
        emit(
            "system_message",
            {"text": f"{username} 创建了聊天室 '{room_name}'"},
            room=room_name,
            broadcast=True,
        )
        
        # 加载新聊天室的历史
        history = load_chat_history(room_name)
        emit("room_history", {"room": room_name, "history": history})
    else:
        emit("system_message", {"text": f"聊天室 '{room_name}' 已存在"})


@socketio.on("join_room")
def handle_join_room(data):
    """加入聊天室"""
    username = session.get("username")
    room_name = (data or {}).get("room_name", "").strip()
    
    if not username or not room_name:
        return
    
    # 检查聊天室是否存在
    rooms = get_chat_rooms()
    room_exists = any(room["name"] == room_name for room in rooms)
    
    if not room_exists:
        emit("system_message", {"text": f"聊天室 '{room_name}' 不存在"})
        return
    
    # 加入数据库记录
    join_chat_room(username, room_name)
    
    # 离开当前房间，加入新房间
    current_room = user_current_rooms.get(request.sid, 'general')
    if current_room != room_name:
        leave_room(current_room)
        join_room(room_name)
        user_current_rooms[request.sid] = room_name
    
    # 更新用户聊天室列表
    emit("user_rooms_list", get_user_rooms(username))
    
    # 发送系统消息到新房间
    emit(
        "system_message",
        {"text": f"{username} 加入了聊天室 '{room_name}'"},
        room=room_name,
        broadcast=True,
    )
    
    # 加载新聊天室的历史
    history = load_chat_history(room_name)
    emit("room_history", {"room": room_name, "history": history})


@socketio.on("leave_room")
def handle_leave_room(data):
    """离开聊天室"""
    username = session.get("username")
    room_name = (data or {}).get("room_name", "").strip()
    
    if not username or not room_name:
        return
    
    # 不能离开默认聊天室
    if room_name == 'general':
        emit("system_message", {"text": "不能离开默认聊天室"})
        return
    
    # 离开聊天室
    leave_chat_room(username, room_name)
    
    # 如果当前在这个聊天室，切换到默认聊天室并离开Socket.IO房间
    if user_current_rooms.get(request.sid) == room_name:
        leave_room(room_name)  # 离开Socket.IO房间
        user_current_rooms[request.sid] = 'general'
        join_room('general')   # 加入默认聊天室
        
        # 加载默认聊天室的历史
        history = load_chat_history('general')
        emit("room_history", {"room": 'general', "history": history})
    
    # 更新用户聊天室列表
    emit("user_rooms_list", get_user_rooms(username))
    
    # 发送系统消息
    emit(
        "system_message",
        {"text": f"{username} 离开了聊天室 '{room_name}'"},
        room=room_name,
        broadcast=True,
    )


@socketio.on("switch_room")
def handle_switch_room(data):
    """切换当前聊天室"""
    username = session.get("username")
    room_name = (data or {}).get("room_name", "").strip()
    
    if not username or not room_name:
        return
    
    # 检查用户是否加入了该聊天室
    user_rooms = get_user_rooms(username)
    if room_name not in user_rooms:
        emit("system_message", {"text": f"您还没有加入聊天室 '{room_name}'"})
        return
    
    # 离开当前房间，加入新房间
    current_room = user_current_rooms.get(request.sid, 'general')
    if current_room != room_name:
        leave_room(current_room)
        join_room(room_name)
        user_current_rooms[request.sid] = room_name
    
    # 加载新聊天室的历史
    history = load_chat_history(room_name)
    emit("room_history", {"room": room_name, "history": history})
    
    emit("system_message", {"text": f"已切换到聊天室 '{room_name}'"})


@socketio.on("private_message")
def handle_private_message(data):
    """处理私人消息"""
    username = session.get("username")
    to_user = (data or {}).get("to_user", "").strip()
    text = (data or {}).get("text", "").strip()
    
    if not username or not to_user or not text:
        return
    
    # 保存私人消息（无论用户是否在线）
    save_private_message(username, to_user, text)
    
    # 构建私人消息对象
    msg = {
        "from_user": username,
        "to_user": to_user,
        "text": text,
        "time": datetime.now().strftime("%H:%M:%S"),
        "type": "private"
    }
    
    # 发送给发送者
    emit("private_message", msg)
    
    # 如果目标用户在线，发送给接收者
    if to_user in set(online_users.values()):
        for sid, online_username in online_users.items():
            if online_username == to_user:
                emit("private_message", msg, room=sid)
                break
    else:
        # 发送系统消息通知发送者用户不在线，但消息已保存
        emit("system_message", {"text": f"用户 '{to_user}' 不在线，消息已保存"})


@socketio.on("load_private_history")
def handle_load_private_history(data):
    """加载私人消息历史"""
    username = session.get("username")
    other_user = (data or {}).get("other_user", "").strip()
    
    if not username or not other_user:
        return
    
    # 加载私人消息历史
    history = load_private_messages(username, other_user)
    emit("private_history", {"other_user": other_user, "history": history})


# ---------------- 私有聊天室相关Socket.IO事件 ----------------

@socketio.on("create_room_with_type")
def handle_create_room_with_type(data):
    """创建新聊天室（支持公共/私有类型）"""
    username = session.get("username")
    room_name = (data or {}).get("room_name", "").strip()
    room_type = (data or {}).get("room_type", "public")
    
    if not username or not room_name:
        return
    
    # 创建聊天室
    result = create_chat_room_with_type(room_name, username, room_type)
    
    if result['success']:
        # 自动加入创建的聊天室
        join_chat_room(username, room_name)
        
        # 离开当前房间，加入新房间
        current_room = user_current_rooms.get(request.sid, 'general')
        if current_room != room_name:
            leave_room(current_room)
            join_room(room_name)
            user_current_rooms[request.sid] = room_name
        
        # 通知所有用户更新聊天室列表（只显示公共聊天室）
        emit("chat_rooms_list", get_chat_rooms_public_only(), broadcast=True)
        emit("user_rooms_list", get_user_rooms(username))
        
        # 发送系统消息到新房间
        emit(
            "system_message",
            {"text": f"{username} 创建了{room_type}聊天室 '{room_name}'"},
            room=room_name,
            broadcast=True,
        )
        
        # 加载新聊天室的历史
        history = load_chat_history(room_name)
        emit("room_history", {"room": room_name, "history": history})
        
        # 返回创建结果（包括私有聊天室的token）
        emit("room_created", {
            "success": True,
            "room_name": room_name,
            "room_type": room_type,
            "token": result.get('token')
        })
    else:
        emit("room_created", {
            "success": False,
            "error": result.get('error', '创建聊天室失败')
        })


@socketio.on("join_room_by_token")
def handle_join_room_by_token(data):
    """通过token加入私有聊天室"""
    username = session.get("username")
    token = (data or {}).get("token", "").strip()
    
    if not username or not token:
        emit("join_by_token_result", {
            "success": False,
            "error": "请输入有效的token"
        })
        return
    
    # 通过token加入聊天室
    result = join_chat_room_by_token(username, token)
    
    if result['success']:
        room_name = result['room_name']
        
        # 离开当前房间，加入新房间
        current_room = user_current_rooms.get(request.sid, 'general')
        if current_room != room_name:
            leave_room(current_room)
            join_room(room_name)
            user_current_rooms[request.sid] = room_name
        
        # 更新用户聊天室列表
        emit("user_rooms_list", get_user_rooms(username))
        
        # 发送系统消息到新房间
        emit(
            "system_message",
            {"text": f"{username} 通过token加入了聊天室 '{room_name}'"},
            room=room_name,
            broadcast=True,
        )
        
        # 加载新聊天室的历史
        history = load_chat_history(room_name)
        emit("room_history", {"room": room_name, "history": history})
        
        emit("join_by_token_result", {
            "success": True,
            "room_name": room_name
        })
    else:
        emit("join_by_token_result", {
            "success": False,
            "error": result.get('error', '加入聊天室失败')
        })


@socketio.on("get_user_created_rooms")
def handle_get_user_created_rooms():
    """获取用户创建的聊天室"""
    username = session.get("username")
    
    if not username:
        return
    
    # 获取用户创建的聊天室
    rooms = get_user_created_rooms(username)
    emit("user_created_rooms", {"rooms": rooms})


@socketio.on("delete_chat_room")
def handle_delete_chat_room(data):
    """删除聊天室"""
    username = session.get("username")
    room_name = (data or {}).get("room_name", "").strip()
    
    if not username or not room_name:
        emit("room_deleted", {
            "success": False,
            "error": "参数错误"
        })
        return
    
    # 删除聊天室
    result = delete_chat_room(room_name, username)
    
    if result['success']:
        # 如果当前在这个聊天室，切换到默认聊天室
        if user_current_rooms.get(request.sid) == room_name:
            leave_room(room_name)
            user_current_rooms[request.sid] = 'general'
            join_room('general')
            
            # 加载默认聊天室的历史
            history = load_chat_history('general')
            emit("room_history", {"room": 'general', "history": history})
        
        # 通知所有用户更新聊天室列表
        emit("chat_rooms_list", get_chat_rooms_public_only(), broadcast=True)
        emit("user_rooms_list", get_user_rooms(username))
        
        # 发送系统消息到默认聊天室
        emit(
            "system_message",
            {"text": f"聊天室 '{room_name}' 已被 {username} 删除"},
            room='general',
            broadcast=True,
        )
        
        emit("room_deleted", {
            "success": True,
            "room_name": room_name
        })
    else:
        emit("room_deleted", {
            "success": False,
            "error": result.get('error', '删除聊天室失败')
        })


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
