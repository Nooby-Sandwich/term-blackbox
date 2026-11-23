# term-blackbox

A terminal flight recorder that captures PTY output into a bounded, replayable
log.

## Terminal Black Box
A continuous terminal flight recorder for Windows. It runs silently in the background, capturing the last N commands and outputs so you can replay them in the event of a crash.

## Features
- **PTY Capture:** Uses `pywinpty` to intercept raw terminal streams.
- **Circular Buffer:** Maintains a rolling memory buffer (`deque`) to prevent disk bloat.
- **JSONL Storage:** Safe, line-by-line serialization.
- **Replay Tool:** Reconstructs terminal sessions with ANSI code stripping.

## Setup
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install pywinpty
