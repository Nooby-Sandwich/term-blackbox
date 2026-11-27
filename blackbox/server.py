"""Black Box daemon: owns the PTY, records everything, serves one client at a time.

The shell is spawned ONCE at server start and a single pump thread reads it for
the whole life of the server. Clients attach/detach freely; recording never stops.
"""

import hmac
import os
import secrets
import socket
import sys
import threading
import time
from winpty import PtyProcess

from .protocol import send_message, recv_message
from .recorder import BlackBox

HOST = "127.0.0.1"
PORT = 9999
SHELL = "powershell.exe"
DEFAULT_SIZE = (30, 120)  # rows, cols until a client reports its real size
AUTOSAVE_INTERVAL = 5.0

# Per-user directory: other Windows accounts can't read the token.
TOKEN_FILE = os.path.join(
    os.environ.get("LOCALAPPDATA", "."), "term-blackbox", "secret.txt"
)


def generate_token():
    token = secrets.token_hex(16)
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        f.write(token)
    print(f"[Server] Token written to {TOKEN_FILE}")  # never print the token itself
    return token


class ClientSlot:
    """Holds the currently attached client (or None) and serializes sends to it."""

    def __init__(self):
        self.conn = None
        self.lock = threading.Lock()

    def attach(self, conn):
        with self.lock:
            old, self.conn = self.conn, conn
        if old is not None:  # a newer client replaces the older one
            try:
                old.close()
            except OSError:
                pass

    def detach(self, conn):
        with self.lock:
            if self.conn is conn:
                self.conn = None

    def send(self, message):
        with self.lock:
            if self.conn is None:
                return
            try:
                send_message(self.conn, message)
            except OSError:
                self.conn = None


def screen_snapshot(box):
    """Repaint the pyte virtual screen so a newly attached client sees the
    current state (banner, prompt, whatever is on screen)."""
    screen = getattr(box, "screen", None)
    if screen is None:
        return ""
    with box.lock:
        lines = [line.rstrip() for line in screen.display]
        cx, cy = screen.cursor.x, screen.cursor.y
    out = ["\x1b[2J"]
    for i, line in enumerate(lines):
        if line:
            out.append(f"\x1b[{i + 1};1H{line}")
    out.append(f"\x1b[{cy + 1};{cx + 1}H")
    return "".join(out)


def pty_pump(proc, box, slot, stop):
    """PTY -> recorder + (optional) client. Runs for the life of the server."""
    try:
        while not stop.is_set():
            data = proc.read(4096)
            if data:
                box.record(data)
                slot.send({"type": "output", "data": data})
            elif not proc.isalive():
                break
            else:
                time.sleep(0.005)
    except (EOFError, OSError):
        pass
    except Exception as e:
        print(f"[Server] PTY reader error: {e}")
    finally:
        print("[Server] Shell exited.")
        slot.send({"type": "status", "data": "Shell exited."})
        stop.set()


def autosave(box, stop):
    while not stop.wait(AUTOSAVE_INTERVAL):
        box.flush()


def authenticate(conn, token):
    conn.settimeout(5.0)  # don't let a silent connection hold a thread forever
    try:
        msg = recv_message(conn)
    except Exception:
        return False
    ok = (
        isinstance(msg, dict)
        and msg.get("type") == "auth"
        and hmac.compare_digest(str(msg.get("token", "")), token)
    )
    conn.settimeout(None)
    return ok


def serve_client(conn, proc, box, slot, token):
    """Client -> PTY. One thread per connection."""
    if not authenticate(conn, token):
        print("[Server] Authentication failed. Dropping connection.")
        conn.close()
        return

    print("[Server] Client attached.")
    slot.attach(conn)
    snapshot_sent = False
    try:
        while True:
            msg = recv_message(conn)
            if msg is None:
                break
            kind = msg.get("type")
            if kind == "input":
                proc.write(msg.get("data", ""))
            elif kind == "resize":
                rows, cols = int(msg["rows"]), int(msg["cols"])
                proc.setwinsize(rows, cols)
                box.resize(rows, cols)
                if not snapshot_sent:  # first size message == client is ready
                    snapshot_sent = True
                    slot.send({"type": "output", "data": screen_snapshot(box)})
            elif kind == "ping":
                slot.send({"type": "pong"})
    except Exception as e:
        print(f"[Server] Connection error: {e}")
    finally:
        slot.detach(conn)
        conn.close()
        print("[Server] Client detached (shell keeps running).")


def start_server():

    # Redirect standard output to a log file if running headless (via pythonw)
    if sys.stdout is None or sys.stderr is None:
        log_path = os.path.join(os.path.dirname(TOKEN_FILE), "server.log")
        sys.stdout = sys.stderr = open(log_path, "a", buffering=1, encoding="utf-8")

    token = generate_token()
    rows, cols = DEFAULT_SIZE
    box = BlackBox(rows, cols)
    slot = ClientSlot()
    stop = threading.Event()

    proc = PtyProcess.spawn(SHELL, dimensions=(rows, cols))
    threading.Thread(target=pty_pump, args=(proc, box, slot, stop), daemon=True).start()
    threading.Thread(target=autosave, args=(box, stop), daemon=True).start()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)
    # accept() with no timeout can't be interrupted by Ctrl+C on Windows.
    server.settimeout(1.0)
    print(f"[Server] Listening on {HOST}:{PORT}. Ctrl+C to stop.")

    try:
        while not stop.is_set():
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            print(f"[Server] Connection from {addr}")
            threading.Thread(
                target=serve_client, args=(conn, proc, box, slot, token), daemon=True
            ).start()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        print("[Server] Shutting down...")
        try:
            server.close()
        except OSError:
            pass
        try:
            if proc.isalive():
                proc.terminate(force=True)
        except Exception:
            pass
        box.flush(force=True)
        print("[Server] Log flushed.")
        os._exit(0)


if __name__ == "__main__":
    start_server()
