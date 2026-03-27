# EyeClaude — Eye-Tracking Focus Manager for Claude Code

## Problem

When running 4 Claude Code instances in a split-screen (one per quadrant), switching focus between terminals requires mouse clicks or keyboard shortcuts. This breaks flow and adds cognitive overhead.

## Solution

A Python CLI app that tracks eye movement via webcam and automatically switches window focus to the Claude Code terminal you're looking at. Integrates with Claude Code via slash commands and hooks to surface real-time instance status through colored border overlays.

## Architecture

Four core modules running as concurrent threads in a single process, communicating via shared state:

```
Webcam → Eye Tracker → Gaze Quadrant ──→ Window Manager → Focus + Border Overlay
              ↑                                ↑
       Calibration Data                 Status Monitor
                                             ↑
                                    Claude Code Hooks (socket)
```

### 1. Eye Tracker

- Uses **MediaPipe Face Mesh** to extract iris landmarks from webcam feed via OpenCV
- Runs at ~30fps on CPU, no GPU required
- Maps iris positions to screen quadrants using calibration data
- Compares current iris position against 4 calibrated reference points using nearest-neighbor

### 2. Calibration Engine

- Triggered on first run or via `eyeclaude calibrate`
- Displays a fullscreen overlay with a dot at the center of each quadrant
- Dots highlight one at a time — user looks at the dot and presses Space
- Records iris position for each quadrant (4 calibration points total)
- Saves calibration to `~/.eyeclaude/calibration.json`
- Loaded automatically on subsequent startups — no recalibration needed unless desired

### 3. Window Manager

**Focus switching:**
- Dwell-based activation: gaze must remain in a quadrant for a configurable duration (default 400ms) before focus switches
- Calls `SetForegroundWindow` via Win32 API to focus the target terminal
- Only switches if target quadrant differs from currently focused one
- When gaze leaves the screen entirely, focus stays on the last active quadrant

**Colored border overlay:**
- Transparent, click-through, always-on-top window via win32gui (using WS_EX_LAYERED + WS_EX_TRANSPARENT extended styles)
- Draws a 3-4px colored border around the active quadrant
- Border color reflects Claude Code status:
  - **Green** — idle/waiting for input
  - **Pulsing blue** — working/thinking
  - **Yellow flash** (~2 seconds, then green) — just finished a task
  - **Red** — error/needs attention
- Passes all mouse/keyboard input through — never interferes with work

**Quadrant assignment:**
- Auto-assigned based on window position on screen
- When a terminal registers, EyeClaude checks its screen coordinates and snaps it to the nearest quadrant

### 4. Status Monitor

- Receives status events from Claude Code instances via hooks over a local socket
- Claude Code hooks emit events for:
  - **Prompt ready** → idle (green)
  - **Tool execution / response streaming** → working (pulsing blue)
  - **Response complete** → finished flash (yellow → green)
  - **Error** → error (red)
- Hooks are installed per-session when the user runs `/eyeclaude-register` inside Claude Code

## Registration Model

Terminals opt-in explicitly — no auto-discovery.

**From inside Claude Code:**
- `/eyeclaude-register` — registers the current terminal with EyeClaude and installs Claude Code hooks for the session. Sends window handle + PID to EyeClaude via local named pipe/socket.
- `/eyeclaude-unregister` — removes the terminal from EyeClaude tracking and cleans up hooks.

**Slash command implementation:**
- Custom commands in `.claude/commands/eyeclaude-register.md` and `.claude/commands/eyeclaude-unregister.md`
- These invoke a small CLI helper (`eyeclaude register` / `eyeclaude unregister`) that communicates with the main EyeClaude process

## Communication

- **Local named pipe** (`\\.\pipe\eyeclaude`) on Windows
- Main EyeClaude process listens on the pipe
- Registration commands and hook status events are sent as JSON messages:

```json
{"type": "register", "window_handle": 12345, "pid": 6789}
{"type": "unregister", "pid": 6789}
{"type": "status", "pid": 6789, "state": "working"}
{"type": "status", "pid": 6789, "state": "idle"}
{"type": "status", "pid": 6789, "state": "finished"}
{"type": "status", "pid": 6789, "state": "error", "message": "..."}
```

## CLI Interface

| Command | Where | Description |
|---|---|---|
| `eyeclaude start` | Any terminal | Launch the main app (webcam + eye tracking + pipe listener) |
| `eyeclaude stop` | Any terminal | Shut down the app |
| `eyeclaude calibrate` | Any terminal | Run/re-run calibration |
| `eyeclaude status` | Any terminal | Show registered terminals and their current states |
| `eyeclaude config` | Any terminal | Adjust settings (dwell time, border thickness, colors) |
| `/eyeclaude-register` | Inside Claude Code | Register this session with EyeClaude |
| `/eyeclaude-unregister` | Inside Claude Code | Unregister this session |

## Configuration

Stored in `~/.eyeclaude/config.json`:

```json
{
  "dwell_time_ms": 400,
  "border_thickness_px": 4,
  "border_colors": {
    "idle": "#00FF00",
    "working": "#0088FF",
    "finished": "#FFD700",
    "error": "#FF0000"
  },
  "finished_flash_duration_ms": 2000,
  "webcam_index": 0
}
```

## Tech Stack

- **Python 3.13**
- **MediaPipe** — face mesh / iris tracking
- **OpenCV** — webcam capture
- **pywin32** — Win32 API (SetForegroundWindow, window enumeration, named pipes)
- **win32gui** — transparent click-through overlay for border rendering
- **Click** — CLI framework

## Project Structure

```
eyeclaude/
├── pyproject.toml
├── src/
│   └── eyeclaude/
│       ├── __init__.py
│       ├── cli.py              # CLI entry point (start, stop, calibrate, etc.)
│       ├── eye_tracker.py      # MediaPipe iris tracking + quadrant mapping
│       ├── calibration.py      # Calibration flow + persistence
│       ├── window_manager.py   # Win32 focus switching + quadrant assignment
│       ├── overlay.py          # Transparent border overlay rendering
│       ├── status_monitor.py   # Receives hook events, tracks instance states
│       ├── pipe_server.py      # Named pipe listener for registration + status
│       ├── shared_state.py     # Thread-safe shared state between modules
│       └── config.py           # Configuration loading/saving
├── commands/
│   ├── eyeclaude-register.md   # Claude Code slash command
│   └── eyeclaude-unregister.md # Claude Code slash command
└── tests/
    ├── test_eye_tracker.py
    ├── test_calibration.py
    ├── test_window_manager.py
    ├── test_status_monitor.py
    └── test_pipe_server.py
```

## Error Handling

- **Webcam not found** — clear error message on startup, exit gracefully
- **No calibration data** — prompt user to run calibration before starting tracking
- **Named pipe connection lost** — terminal is auto-unregistered, log a warning
- **MediaPipe face not detected** — keep last known quadrant focus (same as looking away)
- **Window handle becomes invalid** — auto-unregister the terminal, log a warning

## Testing Strategy

- **Unit tests** for each module with mocked dependencies
- **Integration test** for the pipe server ↔ status monitor communication
- **Manual testing** for eye tracking accuracy and calibration flow (hardware-dependent)

## Future Enhancements (out of scope for v1)

- System tray GUI with controls
- Auto-register hook on Claude Code session start
- Support for more than 4 quadrants (arbitrary grid)
- Cross-platform support (macOS, Linux)
- Gaze heatmap / analytics
