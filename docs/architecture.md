---
summary: "Module architecture, entry points, and data flow"
read_when:
  - "Understanding how EyeClaude works"
  - "Adding a new module or feature"
  - "Debugging a component"
---

# Architecture

## Modules

| Module | Purpose |
|---|---|
| `cli.py` | CLI entry, main loop, hotkeys |
| `eye_tracker.py` | Webcam + MediaPipe + dwell tracking |
| `calibration_overlay.py` | Fullscreen Tk calibration UI |
| `calibration.py` | Calibration persistence + console flow |
| `pipe_server.py` | Named-pipe IPC for hook status |
| `window_manager.py` | Win32 focus switching |
| `status_monitor.py` | Per-terminal status transitions |
| `statusline_wrapper.py` | Statusline output combiner |
| `terminal_discovery.py` | Find candidate terminal windows |
| `shared_state.py` | In-process state shared across threads |
| `hooks.py` | `eyeclaude-hooks` entry point |
| `config.py` | Config load/save |
| `statusline_command.py` | Statusline composer (no shell) |

## Entry points

- `eyeclaude` → `cli:main`
- `eyeclaude-hooks` → `hooks:main`
- `eyeclaude-statusline` → `statusline_command:main`

## Data flow

1. **Calibration**: calibration overlay captures 2 points → saves to `~/.eyeclaude/config.json`
2. **Tracking**: `eye_tracker.py` runs MediaPipe → computes quadrant → pipes to `pipe_server.py`
3. **Focus**: `window_manager.py` calls `SetForegroundWindow` on the detected terminal
4. **Status**: Claude Code hooks → `eyeclaude-hooks` → pipe → `status_monitor.py` updates indicator
5. **Statusline**: `eyeclaude-statusline` reads indicator + `ccstatusline` → outputs combined line
