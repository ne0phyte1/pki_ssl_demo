import ssl
import socket
import threading

HOST = "0.0.0.0"
PORT = 4433

# 保存在线用户：username -> (conn, addr)
clients = {}
lock = threading.Lock()


def broadcast(sender, msg: str):
    """给所有在线用户广播消息"""
    with lock:
        for username, (conn, _) in clients.items():
            # 自己也想看到自己发的，可改成 if username != sender
            try:
                conn.sendall(f"[{sender}] {msg}\n".encode("utf-8"))
            except Exception:
                pass


def handle_client(conn: ssl.SSLSocket, addr):
    print(f"[+] TLS connection from {addr}")

    try:
        # 第一句话要求客户端发送：LOGIN:用户名
        conn.sendall(b"Please login: send 'LOGIN:<username>'\n")
        first = conn.recv(1024).decode("utf-8").strip()
        if not first.startswith("LOGIN:"):
            conn.sendall(b"Invalid login format. Bye.\n")
            conn.close()
            return

        username = first.split(":", 1)[1].strip()
        if not username:
            conn.sendall(b"Empty username. Bye.\n")
            conn.close()
            return

        with lock:
            if username in clients:
                conn.sendall(b"Username already in use.\n")
                conn.close()
                return
            clients[username] = (conn, addr)

        conn.sendall(f"Welcome, {username}! You can start chatting.\n".encode("utf-8"))
        broadcast("SYSTEM", f"{username} joined the chat.")

        # 循环收消息
        while True:
            data = conn.recv(1024)
            if not data:
                break
            msg = data.decode("utf-8").strip()
            if msg.lower() == "/quit":
                break
            broadcast(username, msg)

    except Exception as e:
        print(f"[!] Error with client {addr}: {e}")
    finally:
        with lock:
            # 从在线表删掉
            for u, (c, _) in list(clients.items()):
                if c is conn:
                    del clients[u]
                    broadcast("SYSTEM", f"{u} left the chat.")
                    break
        conn.close()
        print(f"[-] Connection from {addr} closed.")


def main():
    # TLS 服务器上下文
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

    # 用第二阶段的 fullchain 和私钥
    context.load_cert_chain(
        certfile="server/server_fullchain.crt",
        keyfile="server/server.key"
    )

    # 验证客户端证书（仍然是双向认证）
    context.load_verify_locations("ca/certs/root.crt")
    context.verify_mode = ssl.CERT_REQUIRED

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((HOST, PORT))
    sock.listen(5)
    print(f"[*] Chat TLS server listening on {HOST}:{PORT} ...")

    try:
        while True:
            client_sock, addr = sock.accept()
            # 升级为 TLS
            try:
                tls_conn = context.wrap_socket(client_sock, server_side=True)
            except ssl.SSLError as e:
                print(f"[!] TLS handshake failed from {addr}: {e}")
                client_sock.close()
                continue

            t = threading.Thread(target=handle_client, args=(tls_conn, addr), daemon=True)
            t.start()
    finally:
        sock.close()


if __name__ == "__main__":
    main()
