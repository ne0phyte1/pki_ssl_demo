import ssl
import socket

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 4433

def main():
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)

    context.load_verify_locations("ca-chain.crt")

    context.load_cert_chain(
        certfile="client/client.crt",
        keyfile="client/client.key"
    )

    sock = socket.create_connection((SERVER_HOST, SERVER_PORT))
    tls = context.wrap_socket(sock, server_hostname="localhost")

    print("[✓] TLS Handshake OK")
    print("Server Cert:", tls.getpeercert())

    tls.sendall(b"Hello TLS Server!")
    data = tls.recv(1024)
    print("Received:", data.decode())

    tls.close()

if __name__ == "__main__":
    main()
