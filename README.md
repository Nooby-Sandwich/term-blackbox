# Terminal Black Box

A crash-resilient terminal flight recorder for Windows. A background daemon owns a hidden PowerShell session, records everything it prints, and lets you **detach and reattach** from any terminal, much like `tmux`. If your terminal or machine dies, the last stretch of the session is already on disk.

- Runs at logon via Task Scheduler. No console window, no admin rights needed at runtime.
- Keeps recording while no client is attached.
- Stores raw output **and** a clean text snapshot of the screen.
- Replays a session after a crash.

> **Windows only.** Built on ConPTY via [`pywinpty`](https://github.com/andfoy/pywinpty) and `msvcrt`.

## How it works

```text
 VISIBLE TERMINAL (client)                      BACKGROUND DAEMON (server)

 keyboard (msvcrt.getwch)                       socket.accept + token check
        │  keystrokes                                    │
        ▼                                                ▼
 ┌────────────────┐   length-prefixed JSON    ┌────────────────────┐
 │  TCP socket    │◄═════════════════════════►│  TCP socket        │
 │ 127.0.0.1:9999 │   input / output / resize │  127.0.0.1:9999    │
 └───────┬────────┘                           └─────────┬──────────┘
         │ output                                       │ proc.write / proc.read
         ▼                                              ▼
 sys.stdout (console renders ANSI)             ┌────────────────────┐
                                               │ PowerShell (ConPTY)│
                                               └─────────┬──────────┘
                                                         │ raw VT stream
                                                         ▼
                                               ring buffer + pyte screen
                                                         │
                                                         ▼
                                               logs/blackbox_<time>.jsonl
```

**Server (`blackbox/server.py`)**: spawns PowerShell once, at startup, and reads it from a single pump thread for the lifetime of the daemon. Every chunk goes to the recorder. If a client is attached, the chunk is also forwarded to it.

**Client (`blackbox/client.py`)**: reads your keyboard, translates Windows scan codes to VT sequences (arrows, Home/End, Delete, ...), sends them to the server, and writes the server's output straight to your console. Your terminal does the ANSI rendering; the client never strips escape codes.

**Recorder (`blackbox/recorder.py`)**: keeps the newest chunks in a ring buffer (`collections.deque`) and feeds the same stream into a [`pyte`](https://github.com/selectel/pyte) virtual screen. Logs are rewritten atomically (temp file + `os.replace`) every few seconds and on shutdown, so a crash never leaves a corrupt file.

**Protocol (`blackbox/protocol.py`)**: 4-byte big-endian length header followed by a UTF-8 JSON body, with a 10 MB size cap.

| Direction | `type` | Fields | Purpose |
|---|---|---|---|
| client → server | `auth` | `token` | First message; the connection is dropped if it is wrong |
| client → server | `input` | `data` | Keystrokes for the shell |
| client → server | `resize` | `rows`, `cols` | Terminal size; the first one triggers a screen repaint |
| client → server | `ping` | | Keep-alive |
| server → client | `output` | `data` | Raw terminal output |
| server → client | `status` | `data` | Notices such as "Shell exited." |
| server → client | `pong` | | Reply to `ping` |

## Requirements

- Windows 10 or 11
- Python 3.10+
- `pywinpty` and `pyte` (see `requirements.txt`)

## Installation

```powershell
git clone https://github.com/YourUsername/TerminalBlackBox.git
cd TerminalBlackBox
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Register the background task. Run this **once** from an elevated PowerShell if you get "access denied". The task itself runs with normal user rights.

```powershell
python tools/install_daemon.py
```

The installer creates a per-user Task Scheduler task that starts at logon, restarts on failure, and is not stopped on battery power or after 72 hours.

## Usage

Start the daemon now (or just log in again):

```powershell
schtasks /run /tn TerminalBlackBoxDaemon
```

Give it a couple of seconds to start, then attach:

```powershell
python -m blackbox.client
```

Use PowerShell normally: history, colors and window resizing all work.

| Key | Action |
|---|---|
| `Ctrl+C` | **Detach.** The shell keeps running in the background. It is *not* sent to the shell. |
| `exit` (in the shell) | Ends the shell, which stops the daemon |

To run the server in a visible window for debugging:

```powershell
python -m blackbox.server
```

## Logs and replay

Each daemon run writes `logs/blackbox_<YYYYmmdd_HHMMSS>.jsonl`, one JSON object per line:

```json
{"type": "output", "timestamp": 1795523764.36, "data": "PS C:\\Users\\you> "}
{"type": "screen", "timestamp": 1795523790.01, "lines": ["PS C:\\Users\\you> dir", "..."]}
```

- `output`: a raw chunk from the PTY, ANSI sequences included. Only the newest `BUFFER_SIZE` chunks are kept.
- `screen`: one final snapshot of the pyte virtual screen, as plain text.

To see what the terminal looked like in the most recent log:

```powershell
python tools/replay.py
```

## Configuration

These constants live at the top of the modules:

| Constant | File | Default | Meaning |
|---|---|---|---|
| `HOST`, `PORT` | `server.py` | `127.0.0.1`, `9999` | Listen address |
| `SHELL` | `server.py` | `powershell.exe` | Program to run in the PTY |
| `AUTOSAVE_INTERVAL` | `server.py` | `5.0` s | How often the log is rewritten |
| `BUFFER_SIZE` | `recorder.py` | `1000` | Output chunks kept in the ring buffer |

## Security notes

- The server only listens on `127.0.0.1` and requires a random token, stored in `%LOCALAPPDATA%\term-blackbox\secret.txt` and compared in constant time.
- **This is not a sandbox.** Any program running as *your* user can read the token and get a shell as you. Do not run the daemon elevated.
- **Logs are plain text.** They contain everything the shell printed: command output, paths, and any secret that appears on screen. Keep `logs/` out of version control and out of cloud sync folders.

## Troubleshooting

**`Could not connect. Is the server running?`**

1. Wait a few seconds after `schtasks /run`, since the daemon needs time to start.
2. Check that it launched:
   ```powershell
   Get-ScheduledTaskInfo -TaskName TerminalBlackBoxDaemon | Select LastRunTime, LastTaskResult
   Get-Process pythonw -ErrorAction SilentlyContinue
   ```
   `LastTaskResult` of `0` means it launched. `267009` means it is still running.
3. Run `python -m blackbox.server` in a visible window to see any traceback. Under `pythonw` there is no console, so errors are otherwise invisible.

**Screen looks offset or garbled after attaching.** Clear the terminal (`cls`) and attach again. The client clears the screen on connect so the server's cursor positions line up.

**Backspace misbehaves.** The client sends `\x7f` for Backspace. Some ConPTY builds prefer `\x08`; change it in `send_loop`.

## Uninstall

```powershell
python tools/uninstall_daemon.py
```

If the daemon is still running afterwards, stop it with `Stop-Process -Name pythonw`.

## Project structure

```text
TerminalBlackBox/
├── blackbox/
│   ├── client.py        # Attachable terminal viewer
│   ├── protocol.py      # Length-prefixed JSON framing
│   ├── recorder.py      # Ring buffer, pyte screen, atomic JSONL logging
│   └── server.py        # Background PTY daemon
├── tools/
│   ├── install_daemon.py
│   ├── uninstall_daemon.py
│   └── replay.py        # Log replay
├── logs/                # Session logs (git-ignored)
├── main.py              # CLI entry point
└── requirements.txt
```

## Limitations

- One client at a time; a new connection replaces the old one.
- The shell is shared state: if you type `exit`, the daemon stops too.
- Reattaching repaints the screen as plain text, so colors from before the attach are not restored until the shell redraws.
- The log is a rolling window of recent output, not a full session history.

## Roadmap

- Byte-bounded buffer (for example a 50 MB cap) instead of a fixed chunk count
- Timed replay controls (`--speed`, pause/resume)
- Secret redaction before logs are written
- Optional `AF_UNIX` socket in place of TCP
- Protocol tests using `socket.socketpair()`
