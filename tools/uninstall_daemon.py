import subprocess

TASK_NAME = "TerminalBlackBoxDaemon"

def uninstall():
    print(f"Removing daemon '{TASK_NAME}' from Task Scheduler...")
    command = ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]
    
    try:
        subprocess.run(command, check=True, capture_output=True)
        print("SUCCESS: Daemon removed.")
    except subprocess.CalledProcessError:
        print("Daemon is not currently installed.")

if __name__ == "__main__":
    uninstall()