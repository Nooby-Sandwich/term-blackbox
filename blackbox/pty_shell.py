import os
import sys
import time
from collections import deque
from winpty import PtyProcess
import threading
import msvcrt
import json

# ---------------------------------------------------------
# 1. The Circular Buffer
# ---------------------------------------------------------
# A deque with maxlen automatically discards the oldest item
# when it is full. This is your "rolling buffer".
BUFFER = deque(maxlen=1000)

def forward_keyboard(proc):
    """Listens to the keyboard and sends it to the pseudo-terminal."""
    while proc.isalive():
        if msvcrt.kbhit():
            char = msvcrt.getwch()
            
            # Handle Enter
            if char == '\r':
                proc.write('\r\n')
                
            # Handle Backspace (Send back, space, back to erase visually)
            elif char == '\x08':
                proc.write('\x08 \x08')
                
            # Handle Arrow keys / Special keys (they send two characters)
            elif char == '\xe0' or char == '\x00':
                # Ignore the prefix, wait for the next char to get the actual key
                continue
                
            # Everything else
            else:
                proc.write(char)


def start_shell():
    # On Windows, we spawn PowerShell or cmd. 
    # You can change this to 'cmd.exe' if you prefer.
    shell = "powershell.exe"
    
    print(f"Starting Black Box shell: {shell}")
    print("Type 'exit' to leave the shell and flush the buffer to disk.\n")

    # Spawn the process inside a pseudo-terminal (ConPTY)
    proc = PtyProcess.spawn(shell)

    # Start the background thread to handle typing
    input_thread = threading.Thread(target=forward_keyboard, args=(proc,), daemon=True)
    input_thread.start()

    try:
        # Main capture loop
        while proc.isalive():
            # read() blocks until there is new output from the terminal.
            # It returns a string (Unicode) on Windows.
            data = proc.read()
            
            if data:
                # 1. Get the current timestamp
                timestamp = time.time()
                
                # 2. Add the timestamp and data to our circular buffer
                # We store it as a tuple: (time, text)
                BUFFER.append((timestamp, data))
                
                # 3. Echo the data back to the user's screen so they
                # can actually see what they are typing!
                sys.stdout.write(data)
                sys.stdout.flush()

    except KeyboardInterrupt:
        # When the user presses Ctrl+C
        print("\n[Black Box] KeyboardInterrupt detected. Stopping capture...")
    finally:
        # Ensure the process is killed cleanly
        if proc.isalive():
            proc.terminate()
            
        # Flush the buffer to disk
        flush_to_disk()

def flush_to_disk():
    """Save the circular buffer to a file for later replay."""
    filename = "logs/blackbox_log.jsonl"
    print(f"\n[Black Box] Flushing {len(BUFFER)} chunks to {filename}...")
    
    if len(BUFFER) == 0:
        return

    try:
        os.makedirs("logs", exist_ok=True)
        with open(filename, "w", encoding="utf-8") as f:
            for timestamp, data in BUFFER:
                # Create a python dictionary
                entry = {"timestamp": timestamp, "data": data}
                # Let json.dumps handle the escaping and double quotes
                f.write(json.dumps(entry) + "\n")
        print("[Black Box] Flush complete.")
    except OSError as e:
        print(f"[Black Box] Failed to save log: {e}")

if __name__ == "__main__":
    start_shell()