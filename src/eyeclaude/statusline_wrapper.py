# src/eyeclaude/statusline_wrapper.py
"""Statusline wrapper — prepends EyeClaude indicator to ccstatusline output."""

import json
import subprocess
import sys
from pathlib import Path

STATUS_DIR = Path.home() / ".eyeclaude" / "status"

STATUS_EMOJI = {
    "idle": "\U0001f7e2",      # green circle
    "working": "\U0001f535",    # blue circle
    "finished": "\U0001f7e1",   # yellow circle
    "error": "\U0001f534",      # red circle
}

ACTIVE_INDICATOR = "\u25c0"  # left pointer


def build_indicator(status_file: Path) -> str:
    """Read a status JSON file and return the indicator string."""
    try:
        data = json.loads(status_file.read_text(encoding="utf-8"))
        status = data.get("status", "idle")
        active = data.get("active", False)
        emoji = STATUS_EMOJI.get(status, "")
        if not emoji:
            return ""
        if active:
            return emoji + ACTIVE_INDICATOR
        return emoji
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return ""


def _get_terminal_hwnd() -> int:
    """Get the terminal window handle for this process."""
    try:
        import win32console
        hwnd = win32console.GetConsoleWindow()
        if hwnd:
            return hwnd
    except Exception:
        pass
    try:
        import win32gui
        return win32gui.GetForegroundWindow()
    except Exception:
        return 0


def main():
    """Entry point: read stdin, prepend indicator, pipe through ccstatusline."""
    stdin_data = ""
    try:
        if not sys.stdin.isatty():
            stdin_data = sys.stdin.read()
    except Exception:
        pass

    # Get indicator for this terminal
    hwnd = _get_terminal_hwnd()
    indicator = ""
    if hwnd:
        status_file = STATUS_DIR / f"{hwnd}.json"
        indicator = build_indicator(status_file)

    # Run ccstatusline with the original stdin
    try:
        result = subprocess.run(
            ["npx", "-y", "ccstatusline@latest"],
            input=stdin_data, capture_output=True, text=True, timeout=10,
        )
        ccoutput = result.stdout.strip()
    except Exception:
        ccoutput = ""

    # Combine: indicator + space + ccstatusline output
    if indicator and ccoutput:
        print(f"{indicator} {ccoutput}")
    elif indicator:
        print(indicator)
    elif ccoutput:
        print(ccoutput)


if __name__ == "__main__":
    main()
