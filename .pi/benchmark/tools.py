"""Minimal tool implementations exposed to the model under test.

Each tool is a simple function that takes the parsed arguments dict and returns
a string result the model will see as the tool's output. Errors are stringified
and returned (not raised) so the model can react.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_OUTPUT_CHARS = 20_000


def _truncate(s: str) -> str:
    if len(s) <= MAX_OUTPUT_CHARS:
        return s
    head = s[: MAX_OUTPUT_CHARS // 2]
    tail = s[-MAX_OUTPUT_CHARS // 2 :]
    return f"{head}\n\n... [truncated {len(s) - MAX_OUTPUT_CHARS} chars] ...\n\n{tail}"


def _resolve(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return p.resolve()


def tool_bash(args: dict) -> str:
    cmd = args.get("command", "")
    timeout = float(args.get("timeout", 120))
    if not cmd:
        return "Error: 'command' is required"
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=REPO_ROOT,
        )
        out = (
            f"exit_code: {proc.returncode}\n"
            f"--- stdout ---\n{proc.stdout}\n"
            f"--- stderr ---\n{proc.stderr}"
        )
        return _truncate(out)
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


def tool_read(args: dict) -> str:
    path = args.get("path", "")
    if not path:
        return "Error: 'path' is required"
    try:
        p = _resolve(path)
        text = p.read_text(encoding="utf-8")
        return _truncate(text)
    except Exception as e:
        return f"Error reading {path}: {e}"


def tool_write(args: dict) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    if not path:
        return "Error: 'path' is required"
    try:
        p = _resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"Error writing {path}: {e}"


def tool_edit(args: dict) -> str:
    path = args.get("path", "")
    old = args.get("old_string", "")
    new = args.get("new_string", "")
    replace_all = bool(args.get("replace_all", False))
    if not path or not old:
        return "Error: 'path' and 'old_string' are required"
    try:
        p = _resolve(path)
        text = p.read_text(encoding="utf-8")
        if replace_all:
            new_text = text.replace(old, new)
            count = text.count(old)
        else:
            count = text.count(old)
            if count == 0:
                return "Error: old_string not found in file"
            if count > 1:
                return (
                    f"Error: old_string occurs {count} times; "
                    "make it unique or use replace_all=true"
                )
            new_text = text.replace(old, new, 1)
        p.write_text(new_text, encoding="utf-8")
        return f"replaced {count} occurrence(s) in {path}"
    except Exception as e:
        return f"Error editing {path}: {e}"


TOOLS = {
    "bash": tool_bash,
    "read": tool_read,
    "write": tool_write,
    "edit": tool_edit,
}


# OpenAI tool schema definitions (what we send in the chat completion request).
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "Run a shell command from the repo root and return stdout, "
                "stderr, and exit code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {
                        "type": "number",
                        "description": "Timeout in seconds (default 120)",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read a file and return its contents.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write",
            "description": "Write content to a file, overwriting if it exists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit",
            "description": (
                "Replace exact-match text in a file. By default the old_string "
                "must occur exactly once; set replace_all=true to replace every "
                "occurrence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
]
