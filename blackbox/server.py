import socket
import threading
import secrets
import os
import time
import shutil
from winpty import PtyProcess

from .protocol import send_message, recv_message
from .recorder import BlackBox

HOST = '127.0.0.1'
PORT = 9999
TOKEN_FILE = 'secret.txt'

def generate_token():
    """Creates a random secret token and saves it to a file."""
    token = secrets.token_hex(16)
    with open(TOKEN_FILE, 'w') as f:
        f.write(token)
    print(f"[Server] Generated new security token: {token}")
    return token

def handle_client(conn, proc, box):
    """Handles the data flow between the client socket and the PTY."""

    # Thread 1: Read from PTY -> Send to Client
    def pty_to_socket():
        try:
            while True:
                data = proc.read()
                if not data:
                    break
                # Send output to the client
                send_message(conn, {"type": "output", "data": data})
        except Exception:
            print(f"[Server] PTY reader error: {e}")
        finally:
            print("[Server] PTY reader stopped.")
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        threading.Thread(target=pty_to_socket, daemon=True).start()

        # Main Loop: Read from the Clinet -> Write to PTY
        try:
            while proc.isalive():
                msg = recv_message(conn)
                if msg is None:
                    print("[Server] Client disconnected.")
                    break
                if msg["type"] == "input":
                    proc.write(msg["data"])
                elif msg["type"] == "ping":
                    send_message(conn, {"type": "pong"})
        except Exception as e:
            print(f"[Server] Connection error: {e}")
        finally:
            print("[Server] Client session ended.")
            conn.close()
            # Note: We don't kill the PTY here, so the black box keeps recording even if the client closes!

def start_server():
    token = generate_token()

    # Get terminal size for pyte
    cols, rows = shutil.get_terminal_size((120, 30))
    box = BlackBox(rows, cols)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(1)

    print(f"[Server] Listening on {HOST}:{PORT}")

    while True:
        conn, addr = server.accept()
        print(f"[Server] Connection from {addr}")

         # 1. Security Handshake
        msg = recv_message(conn)
        if not msg or msg.get("type") != "auth" or msg.get("token") != token:
            print("[Server] Authentication failed. Dropping connection.")
            conn.close()
            continue

        print("[Server] Authentication successful. Spawning PTY...")
        
        # Tell the client we are booting
        send_message(conn, {"type": "status", "data": "Booting PowerShell..."})
        
        # 2. Spawn the PTY
        proc = PtyProcess.spawn("powershell.exe", dimensions=(rows, cols))
        
        # NEW: Give PowerShell a moment to boot and print its banner
        time.sleep(1.0)
        
        # 3. Handle the I/O
        handle_client(conn, proc, box)

if __name__=="__main__":
    start_server()
