"""Install the Black Box server as a per-user Task Scheduler task (starts at logon).

Run once from an elevated PowerShell. The task itself runs NON-elevated.
"""

import os
import subprocess
import sys

TASK_NAME = "TerminalBlackBoxDaemon"


def ps_quote(value):
    """Quote a string as a PowerShell single-quoted literal."""
    return "'" + value.replace("'", "''") + "'"


def install():
    python_exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    if not os.path.exists(python_exe):
        print(f"ERROR: {python_exe} not found. Run this from inside your venv.")
        return

    print("Installing daemon...")
    print(f"Executable:  {python_exe}")
    print(f"Project dir: {project_dir}")

    script = f"""
$ErrorActionPreference = 'Stop'
$me = "$env:USERDOMAIN\\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute {ps_quote(python_exe)} `
    -Argument '-m blackbox.server' -WorkingDirectory {ps_quote(project_dir)}
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $me
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName {ps_quote(TASK_NAME)} -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
"""

    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("\nERROR: Failed to install daemon.")
        print(result.stderr or result.stdout)
        return

    print("\nSUCCESS: Daemon installed. It starts at your next logon.")
    print(f"Start it now with:  schtasks /run /tn {TASK_NAME}")
    print(f"Check it with:      Get-ScheduledTaskInfo -TaskName {TASK_NAME}")


if __name__ == "__main__":
    install()