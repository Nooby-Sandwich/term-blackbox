import ctypes
import msvcrt
import os
import re
import shutil
import socket
import sys
import threading
import time

from .protocol import send_message, recv_message
from .server import TOKEN_FILE, HOST, PORT


HANDSHAKE = re.compile(r"\x1b\[(?:\?(?:1004|9001)[hl]|[>=]?\d*c|[\d;]*t|[56]n)")


# Windows scan codes to VT100 sequences (arrow keys, etc.)
EXTENDED_KEYS = {
    "H": "\x1b[A", "P": "\x1b[B", "M": "\x1b[C", "K": "\x1b[D",
    "G": "\x1b[H", "O": "\x1b[F", "R": "\x1b[2~", "S": "\x1b[3~",
    "I": "\x1b[5~", "Q": "\x1b[6~",
}

# Several threads send (keyboard + resize watcher). Two concurrent sendall()
# calls can interleave bytes and corrupt the length-prefixed framing.
SEND_LOCK = threading.Lock()


def safe_send(sock, message):
    with SEND_LOCK:
        send_message(sock, message)


def enable_vt_mode():
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def detach(sock, code=0):
    sys.stdout.write("\x1b[0m\x1b[?25h\n[Client] Detached. The shell keeps running.\n")
    sys.stdout.flush()
    try:
        sock.close()
    except OSError:
        pass
    os._exit(code)


def receive_loop(sock):
    """Server -> screen."""
    try:
        while True:
            msg = recv_message(sock)
            if msg is None:
                print("\n[Client] Server disconnected.")
                break
            kind = msg.get("type")
            if kind == "output":
                sys.stdout.write(HANDSHAKE.sub("", msg["data"]))
                sys.stdout.flush()
            elif kind == "status" and "exited" in msg.get("data", ""):
                print(f"\n[Server] {msg['data']}")
    except Exception as e:
        print(f"\n[Client] Receive error: {e}")
    os._exit(0)


def resize_watcher(sock, last):
    """Report terminal size changes to the server."""
    while True:
        time.sleep(0.25)
        size = tuple(shutil.get_terminal_size((120, 30)))
        if size != last:
            last = size
            try:
                safe_send(sock, {"type": "resize", "cols": size[0], "rows": size[1]})
            except OSError:
                return


def send_loop(sock):
    """Keyboard -> server. Ctrl+C detaches; it is NOT forwarded to the shell."""
    try:
        while True:
            pieces = []
            ch = msvcrt.getwch()
            while True:  # drain everything already waiting (pastes)
                if ch == "\x03":
                    detach(sock)
                if ch in ("\x00", "\xe0"):
                    pieces.append(EXTENDED_KEYS.get(msvcrt.getwch(), ""))
                elif ch == "\x08":
                    pieces.append("\x7f")
                else:
                    pieces.append(ch)
                if not msvcrt.kbhit():
                    break
                ch = msvcrt.getwch()
            payload = "".join(pieces)
            if payload:
                safe_send(sock, {"type": "input", "data": payload})
    except Exception as e:
        print(f"\n[Client] Send error: {e}")
        os._exit(1)


def start_client():
    enable_vt_mode()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if not os.path.exists(TOKEN_FILE):
        print(f"[Client] {TOKEN_FILE} not found. Is the server running?")
        return
    with open(TOKEN_FILE, "r") as f:
        token = f.read().strip()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((HOST, PORT))
    except ConnectionRefusedError:
        print("[Client] Could not connect. Is the server running?")
        return

    safe_send(sock, {"type": "auth", "token": token})

    # Start from a clean screen so the server's absolute cursor positions line
    # up with our terminal, then announce our size; the server answers with a
    # repaint of the current shell screen.
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.flush()
    cols, rows = shutil.get_terminal_size((120, 30))
    safe_send(sock, {"type": "resize", "cols": cols, "rows": rows})

    threading.Thread(target=receive_loop, args=(sock,), daemon=True).start()
    threading.Thread(target=resize_watcher, args=(sock, (cols, rows)), daemon=True).start()
    send_loop(sock)  # main thread: keyboard


if __name__ == "__main__":
    start_client()
