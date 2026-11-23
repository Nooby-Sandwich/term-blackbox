import json
import time
import re

# Regex to strip standard ANSI escape codes and the DA response
ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]')
DA_RESPONSE = re.compile(r'\x1b\[?[0-9]+;[0-9]+c')

def clean_text(text):
    text = ANSI_ESCAPE.sub('', text)
    text = DA_RESPONSE.sub('', text)
    # Remove carriage returns that mess up line breaks
    return text.replace('\r', '')

def replay_log(filename):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"File {filename} not found.")
        return
        
    if not lines:
        print("Log is empty.")
        return
        
    prev_timestamp = json.loads(lines[0])["timestamp"]
    
    print("--- Starting Replay ---\n")
    for line in lines:
        entry = json.loads(line)
        
        # Calculate how long to wait between chunks
        time_diff = entry["timestamp"] - prev_timestamp
        if time_diff > 0:
            # Cap sleep at 0.1s so it doesn't take forever if you paused
            time.sleep(min(time_diff, 0.1)) 
            
        clean_data = clean_text(entry["data"])
        if clean_data:
            print(clean_data, end="", flush=True)
        
        prev_timestamp = entry["timestamp"]
    
    print("\n--- Replay Finished ---")

if __name__ == "__main__":
    replay_log("logs/blackbox_log.jsonl")