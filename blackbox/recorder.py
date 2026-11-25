import json
import os
import threading
import time
from collections import deque
from datetime import datetime

try:
    import pyte
except ImportError:
    pyte = None

BUFFER_SIZE = 1000
LOG_DIR = "logs"

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
