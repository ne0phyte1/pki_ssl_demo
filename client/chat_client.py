import ssl
import socket
import threading

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 4433

# 这里先用你的通用客户端证书；以后可以为每个用户生成不同证书
CLIENT_CERT = "client/client_fullchain.crt"
CLIENT_KEY = "client/client.key"
CA_ROOT = "ca/certs/root.crt"


def recv_loop(tls_sock: ssl.SSLSocket):
    """后台线程：收消息并打印"""
    try:
        while True:
            data = tls_sock.recv(4096)
            if not data:
                print("[*] Server closed connection.")
                break
            print(data.decode("utf-8"), end="")
    except Exception as e:
        print("[!] Receive error:", e)


def main():
    username = input("请输入聊天昵称（和 LOGIN:<username> 相同最好）: ").strip()
    if not username:
        print("用户名不能为空")
        return

    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    context.load_verify_locations(CA_ROOT)
    context.load_cert_chain(certfile=CLIENT_CERT, keyfile=CLIENT_KEY)

    sock = socket.create_connection((SERVER_HOST, SERVER_PORT))
    tls = context.wrap_socket(sock, server_hostname="localhost")

    print("[✓] TLS handshake OK.")
    print("Server cert:", tls.getpeercert())

    # 登录
    tls.sendall(f"LOGIN:{username}\n".encode("utf-8"))

    # 收消息线程
    t = threading.Thread(target=recv_loop, args=(tls,), daemon=True)
    t.start()

    # 主线程读键盘、发消息
    try:
        while True:
            msg = input()
            if not msg:
                continue
            tls.sendall((msg + "\n").encode("utf-8"))
            if msg.lower() == "/quit":
                break
    finally:
        tls.close()


if __name__ == "__main__":
    main()
