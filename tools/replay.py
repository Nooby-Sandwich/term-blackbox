import argparse
import json
import os
import re
import sys
import time

from blackbox.client import HANDSHAKE


try:
    import pyte
except ImportError:
    print("Error: 'pyte' is required. Run: pip install pyte")
    sys.exit(1)

LOG_DIR = "logs"
DEFAULT_ROWS, DEFAULT_COLS = 30, 120


def get_log_files():
    if not os.path.exists(LOG_DIR):
        return []
    return sorted(
        [os.path.join(LOG_DIR, f) for f in os.listdir(LOG_DIR) if f.endswith(".jsonl")],
        key=os.path.getmtime,
        reverse=True,
    )


def iter_entries(filename):
    """Yield parsed log entries, skipping blank or damaged lines.

    A crash can leave a truncated last line; one bad line shouldn't make the
    whole log unreadable.
    """
    with open(filename, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                print(f"[replay] skipping unreadable line {lineno}", file=sys.stderr)


def show_snapshot(filename):
    """Print the final screen: the saved snapshot if present, else rebuild it."""
    entries = list(iter_entries(filename))

    saved_lines = None
    rows, cols = DEFAULT_ROWS, DEFAULT_COLS
    for entry in entries:
        if entry.get("type") == "screen":
            saved_lines = entry.get("lines")
            rows = entry.get("rows", rows)
            cols = entry.get("cols", cols)

    if saved_lines:
        lines = saved_lines
        source = "saved snapshot"
    else:
        # No snapshot (e.g. hard crash): rebuild by replaying output through pyte.
        # Note: the log only holds the newest chunks, so state from before the
        # window is unknown and the result may be incomplete.
        screen = pyte.Screen(cols, rows)
        stream = pyte.Stream(screen)
        for entry in entries:
            if entry.get("type") == "output":
                try:
                    stream.feed(entry.get("data", ""))
                except Exception:
                    pass
        lines = list(screen.display)
        source = "reconstructed from output"

    lines = [line.rstrip() for line in lines]
    while lines and not lines[-1]:  # drop trailing blank rows
        lines.pop()

    print(f"\n--- Final Screen State ({source}): {os.path.basename(filename)} ---\n")
    for line in lines:
        print(line)
    print("\n--------------------------------------------------")


def play_live(filename, speed=1.0):
    """Replay the raw terminal output in real time."""
    print(f"\n--- Live Playback: {os.path.basename(filename)} ---\n")
    time.sleep(0.5)
    sys.stdout.write("\x1b[2J\x1b[H")  # clean screen so cursor positions line up

    prev_timestamp = None
    try:
        for entry in iter_entries(filename):
            if entry.get("type") != "output":
                continue
            current_time = entry.get("timestamp")
            if prev_timestamp is not None and current_time is not None:
                delay = (current_time - prev_timestamp) / speed
                if delay > 0:
                    time.sleep(min(delay, 0.5))  # cap long idle gaps
            sys.stdout.write(HANDSHAKE.sub("", entry.get("data", "")))
            sys.stdout.flush()
            prev_timestamp = current_time
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h\n")  # reset colors, show cursor
        sys.stdout.flush()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Terminal Black Box Replay Tool")
    parser.add_argument("file", nargs="?", help="Path to a specific .jsonl log file")
    parser.add_argument("--list", action="store_true", help="List all available log files")
    parser.add_argument("--live", action="store_true", help="Replay the session in real-time")
    parser.add_argument(
        "--speed", type=float, default=1.0,
        help="Playback speed multiplier (e.g., 2.0 is double speed)",
    )
    args = parser.parse_args()

    logs = get_log_files()

    if args.list:
        if not logs:
            print("No log files found in ./logs")
            return
        print("\nAvailable Logs (Newest First):")
        for i, log in enumerate(logs):
            size_kb = os.path.getsize(log) / 1024
            print(f"  [{i}] {os.path.basename(log)} ({size_kb:.1f} KB)")
        print()
        return

    if args.file:
        if not os.path.exists(args.file):
            print(f"Error: File '{args.file}' not found.")
            return
        target_file = args.file
    else:
        if not logs:
            print("No logs found. Did you run the server?")
            return
        target_file = logs[0]
        print(f"Auto-selecting latest log: {target_file}")

    if args.live:
        play_live(target_file, speed=args.speed)
    else:
        show_snapshot(target_file)


if __name__ == "__main__":
    main()