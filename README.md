# Terminal Black Box

A continuous, crash-resilient terminal flight recorder for Windows. It wraps PowerShell in a native Windows Pseudo-Terminal (ConPTY), intercepts input and output streams in real time, stores recent activity in a rolling in-memory buffer, and writes crash-safe logs to disk for post-mortem troubleshooting.

## Features

- **Native VT100 / ANSI Processing:** Enables Windows Console Virtual Terminal processing via `ctypes` (`Win32 API`) so colors, cursor positioning, and screen-clearing sequences render accurately.
- **Multithreaded Queue Architecture:** Decouples blocking PTY reads and keyboard input into dedicated threads communicating over `queue.Queue`, keeping the main loop responsive to `Ctrl+C` and OS signals.
- **Keyboard Translation Layer:** Captures raw Windows console keystrokes (`msvcrt`) and translates scan codes into standard ANSI/VT escape sequences for arrow keys, backspace, and extended navigation keys.
- **Virtual Screen Snapshots:** Feeds output into an in-memory `pyte` terminal emulator so every saved session includes both the raw ANSI stream and a clean, human-readable snapshot of the final screen state.
- **Atomic JSONL Persistence:** Writes session logs to a temporary file before atomically swapping it into place with `os.replace()`, preventing partial or corrupted logs if the process exits unexpectedly.
- **Rolling Circular Buffer:** Maintains the most recent output chunks in memory using `collections.deque(maxlen=1000)` to bound memory growth.

## Architecture

```text
keyboard thread ──(VT/ANSI bytes)──► ConPTY (pywinpty) ──► PowerShell
reader thread   ◄──(raw VT stream)── ConPTY (pywinpty)
      │
      ▼ queue.Queue
main thread ──► circular buffer (deque) + pyte virtual screen
            ──► live raw output to Windows console
            ──► atomic JSONL flush on exit
```

## Setup

**Requirements:** Windows 10/11 and Python 3.10+

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install pywinpty pyte
```

## Usage

1. Start the Black Box shell wrapper:
   ```powershell
   python blackbox/pty_shell.py
   ```
2. Use PowerShell normally—arrow-key history, ANSI colors, and `Ctrl+C` work inside the wrapped session.
3. Type `exit` (or press `Ctrl+C` twice) to close the session. The rolling buffer and final screen snapshot are automatically flushed to:
   ```text
   logs/blackbox_<timestamp>.jsonl
   ```

## Replay & Log Inspection

Replay a recorded session with ANSI escape codes stripped for readability:

```powershell
python tools/replay.py
```

> **Note:** `replay.py` reads the raw JSONL event stream. To inspect the clean virtual screen snapshot directly, check the final line of the generated `.jsonl` file containing the `"type": "screen"` array.

## Planned Improvements

- Byte-bounded circular buffer (e.g., 50 MB cap) instead of fixed chunk count
- Periodic asynchronous background flushing for sudden power-loss resilience
- Timed playback controls (`--speed`, pause/resume) in `tools/replay.py`