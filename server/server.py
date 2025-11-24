import ssl
import socket

HOST = "0.0.0.0"
PORT = 4433

def main():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

    context.load_cert_chain(
        "server/server_fullchain.crt",
        "server/server.key"
    )

    context.load_verify_locations("ca/certs/root.crt")

    context.verify_mode = ssl.CERT_REQUIRED

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((HOST, PORT))
    sock.listen(5)
    print(f"[*] TLS Server running on port {PORT} ...")

    while True:
        client_socket, addr = sock.accept()
        print(f"[+] Connection from {addr}")

        try:
            tls_conn = context.wrap_socket(client_socket, server_side=True)
            print("[✓] TLS Handshake OK with:", tls_conn.getpeercert())

            while True:
                data = tls_conn.recv(1024)
                if not data:
                    break
                print("Received:", data.decode())
                tls_conn.sendall(b"Echo: " + data)

        except ssl.SSLError as e:
            print("[!] TLS Error:", e)
        finally:
            client_socket.close()

if __name__ == "__main__":
    main()
