# web/app.py
import os
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit
from werkzeug.middleware.proxy_fix import ProxyFix

# ---------------- 基础配置 ----------------
app = Flask(__name__)
app.secret_key = os.urandom(24)  # 简单用随机 secret，正式可以写死

# 让 SocketIO 用 eventlet 作为异步引擎
socketio = SocketIO(app, async_mode="threading")

# 记录在线用户：sid -> username
online_users = {}

# 简单聊天记录（内存，最多保存 100 条）
chat_history = []  # 每条：{"user": "...", "text": "...", "time": "HH:MM:SS"}

# ---------------- HTTP 路由：登录 / 聊天页 ----------------

@app.route("/", methods=["GET", "POST"])
def login():
    """简单登录：只要求输入一个昵称，不做密码。
       你后面想加密码/证书绑定可以再扩展。
    """
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        if not username:
            return render_template("login.html", error="昵称不能为空")

        # 把昵称放到 session 里，后面 WebSocket 用
        session["username"] = username
        return redirect(url_for("chat"))

    # 已登录用户直接跳转到聊天页
    if "username" in session:
        return redirect(url_for("chat"))

    return render_template("login.html")


@app.route("/chat")
def chat():
    """聊天主界面"""
    if "username" not in session:
        return redirect(url_for("login"))

    return render_template(
        "chat.html",
        username=session["username"],
        history=chat_history,
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

    msg = {
        "user": username,
        "text": text,
        "time": datetime.now().strftime("%H:%M:%S"),
    }

    chat_history.append(msg)
    if len(chat_history) > 100:
        chat_history.pop(0)

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
