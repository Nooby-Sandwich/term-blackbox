# Terminal Black Box

A crash-resilient terminal flight recorder for Windows. A background daemon owns a hidden PowerShell session, records everything it prints, and lets you **detach and reattach** from any terminal, much like `tmux`. If your terminal or machine dies, the last stretch of the session is already on disk.

- Runs at logon via Task Scheduler. No console window or admin rights are needed at runtime.
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

**Server ([`blackbox/server.py`](blackbox/server.py)):** Spawns PowerShell once at startup and reads it from a single pump thread for the lifetime of the daemon. Every chunk goes to the recorder. If a client is attached, the chunk is also forwarded to it.

**Client ([`blackbox/client.py`](blackbox/client.py)):** Reads keyboard input, translates Windows scan codes to VT sequences (arrows, Home/End, Delete, and others), sends it to the server, and writes the server's output directly to the console. The terminal performs the ANSI rendering; the client does not strip color or cursor escape sequences.

**Recorder ([`blackbox/recorder.py`](blackbox/recorder.py)):** Keeps the newest chunks in a ring buffer (`collections.deque`) and feeds the same stream into a [`pyte`](https://github.com/selectel/pyte) virtual screen. Logs are rewritten atomically (temporary file plus `os.replace`) every few seconds and during shutdown, reducing the risk of corrupt output after a crash.

**Protocol ([`blackbox/protocol.py`](blackbox/protocol.py)):** Uses a 4-byte big-endian length header followed by a UTF-8 JSON body, with a 10 MB size limit.

| Direction | `type` | Fields | Purpose |
|---|---|---|---|
| client → server | `auth` | `token` | First message; the connection is dropped if the token is wrong |
| client → server | `input` | `data` | Keystrokes for the shell |
| client → server | `resize` | `rows`, `cols` | Terminal size; the first resize triggers a screen repaint |
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
git clone https://github.com/Nooby-Sandwich/term-blackbox.git
cd term-blackbox
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Register the background task once. Run it from an elevated PowerShell if Windows reports "access denied"; the installed task itself runs with normal user privileges.

```powershell
python tools/install_daemon.py
```

The installer creates a per-user Task Scheduler task that starts at logon, restarts on failure, and remains active on battery power and beyond 72 hours.

## Usage

Start the daemon now (or wait until the next logon):

```powershell
schtasks /run /tn TerminalBlackBoxDaemon
```

Give the daemon a few seconds to start, then attach:

```powershell
python -m blackbox.client
```

Use PowerShell normally: command history, colors, and terminal resizing are supported.

| Key | Action |
|---|---|
| `Ctrl+C` | **Detach.** The shell keeps running in the background. It is not sent to the shell. |
| `exit` | Ends the shell and stops the daemon |

To run the server in a visible window for debugging:

```powershell
python -m blackbox.server
```

## Logs and Replay

Each daemon run writes `logs/blackbox_<YYYYmmdd_HHMMSS>.jsonl`, with one JSON object per line:

```json
{"type": "output", "timestamp": 1795523764.36, "data": "PS C:\\Users\\you> "}
{"type": "screen", "timestamp": 1795523790.01, "lines": ["PS C:\\Users\\you> dir", "..."]}
```

- `output`: A raw chunk from the PTY, including ANSI sequences. Only the newest `BUFFER_SIZE` chunks are retained.
- `screen`: A final snapshot of the pyte virtual screen, represented as plain text.

Print the latest log's final screen state:

```powershell
python tools/replay.py
```

List available logs or replay one in real time:

```powershell
# List logs newest first
python tools/replay.py --list

# Replay the newest log at original timing
python tools/replay.py --live

# Replay a specific log twice as fast
python tools/replay.py --live path\to\blackbox.jsonl --speed 2.0
```

## Testing

The project uses `pytest` for protocol, recorder, and replay coverage.

```powershell
python -m pip install pytest
python -m pytest
```

**32 tests pass.** The suite covers fragmented TCP delivery, concurrent ring-buffer writes, ANSI handshake filtering, replay behavior, and CLI arguments.

## Configuration

These constants are declared in the source modules:

| Constant | File | Default | Meaning |
|---|---|---|---|
| `HOST`, `PORT` | `server.py` | `127.0.0.1`, `9999` | Listen address |
| `SHELL` | `server.py` | `powershell.exe` | Program launched inside the PTY |
| `AUTOSAVE_INTERVAL` | `server.py` | `5.0` seconds | How often the log is rewritten |
| `BUFFER_SIZE` | `recorder.py` | `1000` | Number of output chunks retained |

## Security Notes

- The server listens only on `127.0.0.1` and requires a random token stored in `%LOCALAPPDATA%\term-blackbox\secret.txt`. Authentication comparisons use `hmac.compare_digest`.
- **This is not a sandbox.** Any program running as your Windows user can read the token and obtain a shell with that user's privileges. Do not run the daemon elevated.
- **Logs are plain text.** They contain command output, paths, and anything else that appears on screen. Keep `logs/` out of source control and cloud-synchronized folders.

## Troubleshooting

**`Could not connect. Is the server running?`**

1. Wait a few seconds after `schtasks /run`; the daemon needs time to start.
2. Check the Task Scheduler state:
   ```powershell
   Get-ScheduledTaskInfo -TaskName TerminalBlackBoxDaemon |
       Select-Object LastRunTime, LastTaskResult
   Get-Process pythonw -ErrorAction SilentlyContinue
   ```
   `LastTaskResult` of `0` means the launch succeeded. `267009` means the task is already running.
3. Run `python -m blackbox.server` in a visible window to see tracebacks. When running under `pythonw`, console output is redirected to the server log instead.

**The screen looks offset or garbled after attaching.** Run `cls` and attach again. The client clears the terminal on connect so the server's absolute cursor positions can align.

**Backspace misbehaves.** The client sends `\x7f` for Backspace. Some ConPTY builds prefer `\x08`; change the Backspace branch in `send_loop`.

## Uninstall

```powershell
python tools/uninstall_daemon.py
```

If the daemon is still running, stop the specific Python process through Task Manager or close it from PowerShell after confirming the process belongs to Terminal Black Box.

## Project Structure

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
├── test/                # Pytest suite
├── logs/                # Session logs
├── main.py              # CLI entry point
└── requirements.txt
```

## Limitations

- One client at a time; a new connection replaces the old one.
- The shell has shared state: typing `exit` stops the daemon too.
- Reattaching repaints the screen as plain text, so colors from before the attach are restored only when the shell redraws them.
- The log is a rolling window of recent output, not a complete session history.

## Roadmap

- Byte-bounded buffering, such as a 50 MB cap, instead of a fixed chunk count
- Secret redaction before log entries are written
- Optional `AF_UNIX` socket support in place of TCP
