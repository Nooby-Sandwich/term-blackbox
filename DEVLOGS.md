# Devlog: Terminal Black Box

## Session 1: The Core Capture Engine
**Date:** November 24, 2026

### Goals for Today
- Set up the project structure.
- Build a raw PTY (Pseudo-Terminal) capture engine on Windows.
- Implement a circular buffer to prevent memory overflow.
- Serialize captured data to a file.
- Build a basic replay tool.

### What We Built
1. **`blackbox/pty_shell.py`**: 
   - Used `pywinpty` to spawn a PowerShell process. 
   - Created a background thread using `threading` and `msvcrt` to forward keystrokes from the user to the PTY (solving the "frozen terminal" issue).
   - Implemented a `collections.deque(maxlen=1000)` to act as a rolling circular buffer, ensuring we never exceed memory limits.
2. **JSONL Serialization**: 
   - Decided against a standard `.json` array because a crash during writing would corrupt the whole file. 
   - Used `.jsonl` (JSON Lines) where each line is a valid JSON object. Even if the program crashes, the previous lines are safe.
3. **`tools/replay.py`**: 
   - Built a playback tool that reads the `.jsonl` file, calculates the time difference between events, and replays them in real-time.
   - Implemented a Regular Expression (Regex) to strip out ANSI escape sequences (e.g., `\x1b[?61;4c`) so the output is human-readable.

### Challenges & Learnings
- **The Keyboard Block**: `pywinpty` doesn't automatically forward user keystrokes. We had to use `msvcrt.getwch()` in a separate thread to bridge the gap between the physical keyboard and the virtual terminal.
- **JSON vs. JSONL**: Learned that Python's `repr()` produces single quotes, which breaks JSON parsing. Switched to `json.dumps()` to ensure strict double-quote formatting and safe escaping of terminal control characters.
- **ANSI Escape Codes**: Discovered that terminal output isn't just text; it's full of invisible control codes. We built a regex cleaner to make the replay readable.

### Next Steps
- **Phase 2**: Build the daemonization process so the black box runs silently in the background on system startup.
- **Phase 3**: Implement a crash-detection signal so the buffer flushes to disk automatically if the system shuts down unexpectedly.


## Session 2: Robust PTY Emulation & Threading
**Date:** November 24, 2026

### Goals for Today
- Fix the keyboard jitter and backspace/arrow key issues.
- Fix the blocking `Ctrl+C` bug (where the app required an extra keystroke to exit).
- Prevent ANSI escape codes from garbling the screen while keeping them in the log.
- Implement clean screen snapshots.

### What We Built / Upgraded
1. **Windows VT100 Processing (`enable_vt_mode`)**: 
   - Used `ctypes` to call `SetConsoleMode` via the Windows Kernel32 API. This forces the console to interpret ANSI/VT escape sequences natively.
   - *Result:* The terminal now correctly renders colors, clears screens, and handles cursor movements without garbling.
2. **Decoupled Architecture using `queue.Queue`**:
   - Moved the blocking `proc.read()` call into a dedicated daemon thread (`pty_reader`).
   - The main thread now pulls data from the queue. This solved the `Ctrl+C` issue entirely, allowing the main thread to respond to signals instantly.
3. **Keyboard Translation Layer (`EXTENDED_KEYS`)**:
   - Mapped Windows scan codes (`\xe0` + key) to actual VT sequences (e.g., `\x1b[A` for Up Arrow). Backspace was remapped to `\x7f`.
   - *Result:* Arrow keys, backspace, and cursor movement inside the shell now work perfectly.
4. **Virtual Screen Buffer (`pyte`)**:
   - Integrated `pyte`, a Python terminal emulator. As raw VT data streams in, it updates a virtual matrix. When the session ends, the logger saves a clean, human-readable snapshot of the screen (stripped of ANSI codes) alongside the raw telemetry.
5. **Atomic File Writes**:
   - Modified the `BlackBox.flush()` method to write to a `.tmp` file first, then use `os.replace()`.
   - *Result:* If the system crashes while saving, the log file will never be corrupted.

### Challenges & Learnings
- **The ANSI Desync**: Tried stripping ANSI codes with regex to make the screen look clean, but this completely broke cursor tracking and backspacing. *Lesson learned:* Let the console handle the rendering; only strip codes when saving to the log.
- **Blocking I/O vs. Signals**: Python cannot process a `SIGINT` (Ctrl+C) if it is stuck in a C-level `read()` call. The only reliable fix is to move the blocking read to a background thread.

### Next Steps
- **Daemonization**: Turn the wrapper into a background service that runs silently on system startup.
- **Crash Recovery**: Automatically detect if the previous session crashed (by checking if the log file ended abruptly) and offer a replay.

## Session 3: Daemonization & Background Services
**Date:** November 24, 2026

### Goals for Today
- Turn the terminal wrapper into a silent Windows Service (Daemon).
- Verify that the background service can record telemetry without a visible console.

### What We Built / Upgraded
1. **NSSM Integration (Non-Sucking Service Manager)**:
   - Downloaded and configured NSSM to wrap the virtual environment's Python executable.
   - Installed `TerminalBlackBox` as a native Windows Service pointing to `blackbox/pty_shell.py`.
2. **Background Execution**:
   - Started the service via `Start-Service TerminalBlackBox`. 
   - Verified that the service ran silently in the background (Session 0) without any visible terminal window.
3. **Graceful Shutdown**:
   - Stopped the service via `Stop-Service`.
   - Verified that NSSM successfully sent a `Ctrl+C` signal to the Python script, triggering the `finally` block to flush the buffer and save the `.jsonl` log file.
4. **Virtual Screen Snapshot Verification**:
   - Inspected the generated log file. Confirmed that the `pyte` virtual screen successfully captured the hidden background prompt state and saved it as a `{"type": "screen"}` JSON object.

### Challenges & Learnings
- **The Invisible Shell**: Realized that a daemonized PTY runs completely hidden, meaning it cannot currently accept user input. To interact with the daemon, we must transition the architecture from a monolithic script to a **Client-Server model**.
- **Session 0 Isolation**: Learned that Windows Services run in Session 0 and cannot interact with the desktop, reinforcing the need for a separate client application to send commands over a local socket.

### Next Steps
- **Phase 3 (Client-Server Architecture)**: 
  - Refactor `pty_shell.py` into `server.py` (handles PTY and listens on a local TCP port) and `client.py` (connects to the port, sends keystrokes, and renders output).
  - Restructure the project folder for better modularity (`main.py`, `blackbox/server.py`, `blackbox/client.py`).

  ## Session 4: Client-Server Architecture (WIP)
**Date:** November 25, 2026

### Goals for Today
- Refactor the monolithic wrapper into a Client-Server model.
- Decouple the logger from the PTY.
- Implement a secure socket connection with token authentication.

### What We Built / Upgraded
1. **Custom Network Protocol (`protocol.py`)**:
   - Implemented a length-prefixed JSON framing protocol over TCP to prevent packet fragmentation. Each message is prepended with a 4-byte header defining its length.
2. **The Daemon Server (`server.py`)**:
   - Generates a random security token (`secret.txt`) on startup to prevent unauthorized local access.
   - Listens on `127.0.0.1:9999` for incoming client connections.
   - Spawns the hidden PTY only after successful authentication.
3. **The Client (`client.py`)**:
   - Connects to the server, reads the `secret.txt` token, and authenticates.
   - Bridges the local keyboard (`msvcrt`) to the server via the socket protocol.
   - Receives output from the server and prints it to the local screen.
4. **Architecture Refactor**:
   - Moved the `BlackBox` logging logic into `recorder.py`.
   - Created a `main.py` entry point to route commands (`python main.py server` vs `python main.py client`).

### Challenges & Learnings
- **The Indentation Bug**: The server appeared to "hang" on startup. We originally thought it was a `pywinpty` ConPTY quirk. Claude correctly identified a Python indentation bug: the thread execution and the receive loop were accidentally indented *inside* the nested `pty_to_socket` function definition, meaning they were never executed.
- **The Single PTY Architecture**: Refactored the server to spawn the PTY only *once* at startup. Clients attach and detach dynamically. The server maintains the `pyte` virtual screen in memory, so when a client reconnects, the server repaints the current screen state immediately.
- **Concurrency & Framing**: Implemented a `ClientSlot` class with a `threading.Lock` to ensure that the PTY reader thread and the client message loop don't interleave socket writes and corrupt the length-prefixed JSON protocol.
- **Seamless Reattachment**: The client now sends a resize event on connection. The server uses this as a trigger to repaint the `pyte` screen buffer, meaning the prompt appears instantly without waiting for new output.

### Next Steps (Project Finalization)
- **Remove NSSM**: Delete the old `TerminalBlackBox` service.
- **Task Scheduler**: Create a Task Scheduler job that runs `pythonw.exe -m blackbox.server` at user logon so the daemon runs invisibly and automatically.
- **Log Viewer Tool (`tools/view_logs.py`)**: Write a utility that parses the `.jsonl` file and prints the final `{"type": "screen"}` snapshot so the user can see exactly what was on the screen before a crash.
- **Code Documentation**: Thoroughly read and add docstrings to `server.py`, `client.py`, and `protocol.py` for interview readiness.

## Session 5: Daemonization, Replay, & Final Polish
**Date:** November 27, 2026

### What We Built
- **Task Scheduler Automation**: Abandoned NSSM due to Session 0 isolation. Created `tools/install_daemon.py` which uses `Register-ScheduledTask` to run the server invisibly at user logon using `pythonw.exe`, bypassing UAC elevation.
- **Crash Logging**: Redirected `sys.stdout` and `sys.stderr` to `server.log` for headless debugging.
- **The Replay Tool (`tools/replay.py`)**: Rewrote the playback tool to feed the `.jsonl` logs into the `pyte` virtual screen, rendering a perfect, readable snapshot of the terminal state at the time of a crash.
- **Resolved Socket Errors**: Identified that `WinError 10053` during client detach is a benign artifact of terminating the socket without a TCP FIN packet.

### Next Steps
- **Log Viewing (`tools/replay.py`)**: Expand the replay tool into a proper log viewer with timed playback controls (`--speed`), pause/resume, and the ability to list available logs.
- **Code Documentation**: Thoroughly read through `client.py`, `server.py`, and `protocol.py`, adding detailed docstrings and inline comments to ensure every line can be explained in a technical interview.
- **Unit Testing**: Write `pytest` tests for the custom `protocol.py` to verify message framing and connection dropping.