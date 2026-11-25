import socket
import sys
import msvcrt
import threading
import os
import ctypes

from .protocol import send_message, recv_message

HOST = '127.0.0.1'
PORT = 9999
TOKEN_FILE = 'secret.txt'

# Windows scan codes to VT100 sequences (for Arrow keys, etc.)
EXTENDED_KEYS = {
    "H": "\x1b[A", "P": "\x1b[B", "M": "\x1b[C", "K": "\x1b[D",
    "G": "\x1b[H", "O": "\x1b[F", "R": "\x1b[2~", "S": "\x1b[3~",
    "I": "\x1b[5~", "Q": "\x1b[6~",
}

def enable_vt_mode():
    """Make the local terminal interpret ANSI/VT escape sequences."""
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass

def receive_loop(sock):
    """Listens for incoming data from the server and prints it."""
    while True:
        try:
            msg = recv_message(sock)
            if msg is None:
                print("\n[Client] Server disconnected.")
                break
            
            if msg["type"] == "output":
                sys.stdout.write(msg["data"])
                sys.stdout.flush()
            elif msg["type"] == "status":
                print(f"\n[Server] {msg['data']}")
                
        except Exception as e:
            print(f"\n[Client] Receive error: {e}")
            break
            
    os._exit(0) # Force exit if connection drops

def send_loop(sock):
    """Listens to the keyboard and sends keystrokes to the server."""
    try:
        while True:
            pieces = []
            ch = msvcrt.getwch()
            
            # Drain all waiting keystrokes
            while True:
                if ch == '\x03': # Ctrl+C
                    # We send the Ctrl+C to the server, then exit the client
                    send_message(sock, {"type": "input", "data": "\x03"})
                    print("\n[Client] Detaching...")
                    sock.close()
                    os._exit(0)
                
                if ch in ("\x00", "\xe0"):
                    pieces.append(EXTENDED_KEYS.get(msvcrt.getwch(), ""))
                elif ch == "\x08":
                    pieces.append("\x7f") # Backspace
                else:
                    pieces.append(ch)
                    
                if not msvcrt.kbhit():
                    break
                ch = msvcrt.getwch()
            
            # Send the keystrokes to the server
            payload = "".join(pieces)
            if payload:
                send_message(sock, {"type": "input", "data": payload})
                
    except Exception as e:
        print(f"\n[Client] Send error: {e}")
        os._exit(1)

def start_client():
    enable_vt_mode()
    
    # 1. Get the token
    if not os.path.exists(TOKEN_FILE):
        print(f"[Client] Error: {TOKEN_FILE} not found. Is the server running?")
        return

    with open(TOKEN_FILE, "r") as f:
        token = f.read().strip()

    # 2. Connect to server
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((HOST, PORT))
    except ConnectionRefusedError:
        print("[Client] Error: Could not connect to server. Is it running?")
        return

    # 3. Authenticate
    send_message(sock, {"type": "auth", "token": token})
    
    # 4. Start the threads
    print("[Client] Connected and authenticated. Press Ctrl+C to detach.\n")
    
    recv_thread = threading.Thread(target=receive_loop, args=(sock,), daemon=True)
    recv_thread.start()
    
    # The main thread handles keyboard input (blocking)
    send_loop(sock)

if __name__ == "__main__":
    start_client()