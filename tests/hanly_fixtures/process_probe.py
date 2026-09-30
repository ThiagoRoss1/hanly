"""Probe process identity with a self-contained child and no fixture imports.

PID, parent PID, and full command line distinguish resource trackers and the
probe itself. Missing, refused, or timed-out inspection raises unavailable,
never an empty result that could falsely prove retirement.
"""

#: Raised in the child when the host will not say what is running. Its name is
#: what a consumer matches on, because the child and the test share no module.
PROBE_UNAVAILABLE = "ProcessInspectionUnavailable"

#: The ``ps`` format this probe asks for. Unique enough to recognize the
#: inventory command's own row by, and named here so a consumer's ignore list
#: cannot drift from the command the way a hand-written ``"ps -axo"`` did.
PS_FORMAT = "pid=,ppid=,command="

#: What a benign row is. The resource tracker outlives every child by design,
#: and the inventory command is a child of the process asking the question.
IGNORED_COMMANDS = ("resource_tracker", PS_FORMAT)

PROCESS_ROWS_PROGRAM = f'''
#: Defined here rather than in each child that prepends this, so an ignore
#: list cannot drift from the command whose rows it is filtering.
IGNORED_COMMANDS = {IGNORED_COMMANDS!r}


class ProcessInspectionUnavailable(RuntimeError):
    """The operating system refused to say what is running."""


def process_rows():
    import sys

    if sys.platform != "win32":
        # ``-ww`` because ps truncates the command to 80 columns when stdout is
        # a pipe, which cut "...multiprocessing.resource_tracker import main"
        # down to "from multi" and made the tracker read as a leaked window.
        return _rows_from(
            ["ps", "-ww", "-axo", "{PS_FORMAT}"],
            lambda output: output.splitlines(),
        )

    return _rows_from(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "Get-CimInstance Win32_Process | "
         "Select-Object ProcessId,ParentProcessId,Name,CommandLine | "
         "ConvertTo-Json -Compress"],
        _windows_rows,
    )


def _rows_from(command, parse):
    """Run one inventory command, or say why the host would not answer."""

    import subprocess

    try:
        output = subprocess.check_output(command, text=True, timeout=15)
    except FileNotFoundError as error:
        raise ProcessInspectionUnavailable(
            "%s is not on this host: %s" % (command[0], error)
        ) from error
    except PermissionError as error:
        raise ProcessInspectionUnavailable(
            "%s is not permitted here: %s" % (command[0], error)
        ) from error
    except subprocess.TimeoutExpired as error:
        raise ProcessInspectionUnavailable(
            "%s did not answer in time" % command[0]
        ) from error
    except subprocess.CalledProcessError as error:
        raise ProcessInspectionUnavailable(
            "%s exited with status %d" % (command[0], error.returncode)
        ) from error
    return parse(output)


def _windows_rows(output):
    import json

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

__all__ = ["IGNORED_COMMANDS", "PROBE_UNAVAILABLE", "PROCESS_ROWS_PROGRAM", "PS_FORMAT"]
