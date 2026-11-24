"""Interactive Windows PTY wrapper ("Terminal Black Box").

Architecture
------------
    keyboard thread --(VT bytes)--> PTY --> PowerShell
    reader thread   <--(raw VT)---- PTY
         |
         v  queue.Queue
    main thread: record to ring buffer + pyte screen, write RAW output to console

* The real console (VS Code / Windows Terminal) is the terminal emulator that
  renders colours, cursor moves, backspaces and line clears. We never strip
  escape codes; we only make sure VT processing is enabled and pass them through.
* pyte (optional) keeps an in-memory virtual screen so the log can also contain
  a clean, human-readable snapshot of what was on screen.
* Blocking reads live in a daemon thread, so the main thread never blocks and
  can react to Ctrl+C / signals instantly.

Install:  pip install pywinpty pyte
"""

import ctypes
import json
import msvcrt
import os
import queue
import re
import shutil
import signal
import sys
import threading
import time
from collections import deque
from datetime import datetime

from winpty import PtyProcess


HANDSHAKE = re.compile(r"\x1b\[(?:\?1004[hl]|\?9001[hl]|c|\d*t)")

try:
    import pyte  # optional: virtual screen for clean snapshots
except ImportError:
    pyte = None

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
SHELL = "powershell.exe"
LOG_DIR = "logs"
BUFFER_SIZE = 1000          # newest N output chunks kept in the ring buffer
AUTOSAVE_INTERVAL = 5.0     # seconds; protects against hard kills / window close
FORCE_QUIT_KEY = "\x03"     # Ctrl+C. Use "\x1d" (Ctrl+]) if you'd rather forward
                            # Ctrl+C to the shell and use a different quit key.

STOP_EVENT = threading.Event()

# msvcrt.getwch() returns a prefix ('\x00' or '\xe0') then a scan code for
# non-character keys. Translate them to the VT sequences a terminal would send.
EXTENDED_KEYS = {
    "H": "\x1b[A",   # Up
    "P": "\x1b[B",   # Down
    "M": "\x1b[C",   # Right
    "K": "\x1b[D",   # Left
    "G": "\x1b[H",   # Home
    "O": "\x1b[F",   # End
    "R": "\x1b[2~",  # Insert
    "S": "\x1b[3~",  # Delete
    "I": "\x1b[5~",  # Page Up
    "Q": "\x1b[6~",  # Page Down
}


# --------------------------------------------------------------------------- #
# Console setup
# --------------------------------------------------------------------------- #
def enable_vt_mode():
    """Make the Windows console interpret ANSI/VT escape sequences."""
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass  # Already enabled in most modern terminals (VS Code, Windows Terminal)


# --------------------------------------------------------------------------- #
# Black box: ring buffer + optional virtual screen + crash-safe logging
# --------------------------------------------------------------------------- #
class BlackBox:
    def __init__(self, rows, cols):
        self.buffer = deque(maxlen=BUFFER_SIZE)
        self.lock = threading.Lock()
        self.dirty = False
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = os.path.join(LOG_DIR, f"blackbox_{stamp}.jsonl")

        self.screen = None
        self.stream = None
        if pyte is not None:
            self.screen = pyte.Screen(cols, rows)
            self.stream = pyte.Stream(self.screen)

    def record(self, data):
        """Store raw output and feed the virtual screen."""
        with self.lock:
            self.buffer.append((time.time(), data))
            self.dirty = True
            if self.stream is not None:
                try:
                    self.stream.feed(data)
                except Exception:
                    pass  # never let emulation bugs kill the recorder

    def resize(self, rows, cols):
        with self.lock:
            if self.screen is not None:
                self.screen.resize(rows, cols)

    def flush(self, force=False):
        """Rewrite the session log atomically (no duplicate entries).

        Writes to a temp file then os.replace()s it, so a crash mid-write
        never leaves a corrupt log.
        """
        with self.lock:
            if not self.buffer or (not self.dirty and not force):
                return
            try:
                os.makedirs(LOG_DIR, exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    for ts, data in self.buffer:
                        f.write(json.dumps(
                            {"type": "output", "timestamp": ts, "data": data}
                        ) + "\n")
                    if self.screen is not None:
                        lines = [line.rstrip() for line in self.screen.display]
                        f.write(json.dumps(
                            {"type": "screen", "timestamp": time.time(), "lines": lines}
                        ) + "\n")
                os.replace(tmp, self.path)
                self.dirty = False
            except OSError as e:
                print(f"\n[Black Box] Failed to save log: {e}")


# --------------------------------------------------------------------------- #
# Worker threads
# --------------------------------------------------------------------------- #
def pty_reader(proc, out_q):
    """Blocking PTY reads live here so the main thread never blocks."""
    try:
        while not STOP_EVENT.is_set():
            data = proc.read(4096)
            if data:
                out_q.put(data)
            elif not proc.isalive():
                break
            else:
                time.sleep(0.005)
    except (EOFError, OSError):
        pass
    except Exception:
        pass
    finally:
        out_q.put(None)  # sentinel: shell closed


def forward_keyboard(proc):
    """Read keys (blocking, low latency) and forward them as terminal input."""
    while not STOP_EVENT.is_set():
        pieces = []
        ch = msvcrt.getwch()
        # Drain everything already waiting so pastes go out as one write.
        while True:
            if ch == FORCE_QUIT_KEY:
                STOP_EVENT.set()
                return
            if ch in ("\x00", "\xe0"):
                pieces.append(EXTENDED_KEYS.get(msvcrt.getwch(), ""))
            elif ch == "\x08":
                pieces.append("\x7f")  # Backspace as terminals send it
            else:
                pieces.append(ch)
            if not msvcrt.kbhit():
                break
            ch = msvcrt.getwch()
        try:
            proc.write("".join(pieces))
        except Exception:
            STOP_EVENT.set()
            return


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def start_shell():
    enable_vt_mode()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    cols, rows = shutil.get_terminal_size((120, 30))
    box = BlackBox(rows, cols)

    print(f"Starting Black Box shell: {SHELL}")
    print("Type 'exit' to leave. Press Ctrl+C to force quit the wrapper.\n")

    sys.stdout.write("\x1b[2J\x1b[H")  # clear + home so ConPTY's absolute coords match
    sys.stdout.flush()

    proc = PtyProcess.spawn(SHELL, dimensions=(rows, cols))

    # We read the first chunk of output (the banner) before starting the keyboard
    startup_data = proc.read(4096)
    if startup_data:
        # Print it to the screen and save it to the buffer
        sys.stdout.write(startup_data)
        sys.stdout.flush()

    # Signals only set a flag; the main thread does the actual cleanup.
    # (Doing I/O + locks inside a signal handler can deadlock.)
    for name in ("SIGINT", "SIGBREAK", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, lambda s, f: STOP_EVENT.set())
            except (ValueError, OSError):
                pass

    out_q = queue.Queue()
    threading.Thread(target=pty_reader, args=(proc, out_q), daemon=True).start()
    threading.Thread(target=forward_keyboard, args=(proc,), daemon=True).start()

    
    last_save = time.monotonic()
    last_size = (cols, rows)

    try:
        while not STOP_EVENT.is_set():
            try:
                data = out_q.get(timeout=0.1)  # wakes 10x/sec -> always responsive
            except queue.Empty:
                data = ""

            if data is None:  # shell exited
                break
            if data:
                box.record(data)
                sys.stdout.write(data)  # RAW: the console renders the escape codes
                sys.stdout.flush()

            now = time.monotonic()
            if now - last_save >= AUTOSAVE_INTERVAL:
                box.flush()
                last_save = now

            size = tuple(shutil.get_terminal_size((cols, rows)))
            if size != last_size:
                last_size = size
                try:
                    proc.setwinsize(size[1], size[0])
                except Exception:
                    pass
                box.resize(size[1], size[0])
    except KeyboardInterrupt:
        pass
    finally:
        STOP_EVENT.set()

        # Capture any output that arrived just before shutdown.
        while True:
            try:
                data = out_q.get_nowait()
            except queue.Empty:
                break
            if data:
                box.record(data)

        # Reset colours/cursor in case the shell died mid-sequence.
        sys.stdout.write("\x1b[0m\x1b[?25h")
        print("\n[Black Box] Shutting down...")
        try:
            if proc.isalive():
                proc.terminate(force=True)
        except Exception:
            pass
        box.flush(force=True)
        print(f"[Black Box] Log saved to {box.path}")
        sys.stdout.flush()
        # Daemon threads may be stuck in blocking C calls (getwch / read);
        # hard-exit so the process can never hang here.
        os._exit(0)


if __name__ == "__main__":
    start_shell()