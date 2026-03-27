"""Hook helper — sends status events to EyeClaude from Claude Code hooks."""

import json
import os
import sys

import win32file


PIPE_NAME = r"\\.\pipe\eyeclaude"


def main():
    if len(sys.argv) < 3:
        print("Usage: eyeclaude-hooks status <idle|working|finished|error>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    if command != "status":
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)

    state = sys.argv[2]
    pid = os.getpid()

    # Read stdin for hook input (Claude Code sends JSON)
    stdin_data = ""
    try:
        if not sys.stdin.isatty():
            stdin_data = sys.stdin.read()
    except Exception:
        pass

    # Detect error state from hook input
    if stdin_data:
        try:
            hook_input = json.loads(stdin_data)
            event = hook_input.get("hook_event_name", "")
            if event == "StopFailure":
                state = "error"
        except json.JSONDecodeError:
            pass

    message = json.dumps({
        "type": "status",
        "pid": pid,
        "state": state,
    }).encode("utf-8")

    try:
        handle = win32file.CreateFile(
            PIPE_NAME,
            win32file.GENERIC_WRITE,
            0, None,
            win32file.OPEN_EXISTING,
            0, None,
        )
        win32file.WriteFile(handle, message)
        win32file.CloseHandle(handle)
    except Exception:
        pass  # EyeClaude may not be running — fail silently

    sys.exit(0)


if __name__ == "__main__":
    main()
