"""Portable process inventory embedded in the native smoke subprocesses.

This is source text, not an import: the smoke tests prepend it to the child
program they write out, so the child needs no path setup to ask the operating
system what is running. Each row is ``pid ppid detail``, where ``detail`` is
the command line -- callers identify multiprocessing's resource tracker and
the inventory command itself by what is in it.
"""

PROCESS_ROWS_PROGRAM = '''
def process_rows():
    import json
    import subprocess
    import sys

    if sys.platform != "win32":
        return subprocess.check_output(
            ["ps", "-axo", "pid=,ppid=,command="], text=True, timeout=15
        ).splitlines()

    output = subprocess.check_output(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "Get-CimInstance Win32_Process | "
         "Select-Object ProcessId,ParentProcessId,Name,CommandLine | "
         "ConvertTo-Json -Compress"],
        text=True,
        timeout=15,
    )
    records = json.loads(output)
    if isinstance(records, dict):
        records = [records]

    rows = []
    for record in records:
        pid, parent = record.get("ProcessId"), record.get("ParentProcessId")
        name = record.get("Name") or ""
        if pid is None or parent is None:
            continue
        # The shell asking the question is a child of the caller, so it would
        # otherwise read as a leaked process.
        if name.lower() == "powershell.exe":
            continue
        # A protected process reports no command line, and its name has to do.
        detail = record.get("CommandLine") or name
        rows.append("%d %d %s" % (pid, parent, detail.replace("\\n", " ")))
    return rows
'''
