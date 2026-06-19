You are implementing a critical-fixes branch on the eyeclaude repo at the current working directory.

I will give you ONE task at a time. For each task:
- Execute every numbered step in order.
- Run `pytest -v` before committing; commit only if green.
- Use the exact `git commit -m "..."` message I give you.
- Do not modify files outside the task's "Files:" list.
- Do not modify `src/eyeclaude/calibration_overlay.py` or `src/eyeclaude/overlay.py` — they are explicitly out of scope.
- HWND-as-PID is intentional in this codebase: terminals are registered with `pid=hwnd`. Never introduce `psutil.pid_exists`, `os.kill`, or any check that treats a window handle as a PID.
- Test files: append to them, do not rewrite them.
- No placeholders in committed code.

When the task is committed, reply "Task N done." and stop.
