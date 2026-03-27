# EyeClaude v2 — Redesigned Registration & Calibration

## Problem

The current registration process requires running `/eyeclaude-register` manually inside each Claude Code terminal. There are no visual cues, no feedback, and the process isn't intuitive. Registration and calibration are separate steps with a manual "press ENTER" gate between them. The status overlay hacks the window title bar, which is fragile and ugly.

## Solution

Replace the entire registration + calibration flow with a single, visual, guided experience:

1. **Auto-discovery** — EyeClaude finds all Claude Code terminals automatically
2. **Visual calibration overlay** — a full-screen Tkinter window with live gaze pointer and clickable terminal rectangles
3. **Statusline integration** — status indicators live inside Claude Code's built-in status bar, not the window title

The `/eyeclaude-register` and `/eyeclaude-unregister` slash commands are eliminated entirely.

## New Startup Flow

1. User runs `eyeclaude start`
2. EyeClaude auto-discovers all visible Windows Terminal windows via `EnumWindows` + `CASCADIA_HOSTING_WINDOW_CLASS`
3. Installs Claude Code hooks globally in `~/.claude/settings.local.json` (idempotent — skips if already present)
4. Starts the pipe server for receiving status updates from hooks
5. Opens the calibration overlay immediately
6. After calibration, enters normal tracking mode

No manual registration step. No "press ENTER when ready" prompt.

## Calibration Overlay

### The Window

- Full-screen, topmost Tkinter window with semi-transparent black background (~70% opacity)
- Draws outlined rectangles matching the exact screen positions of each discovered terminal window
- Each rectangle is labeled (e.g., "Terminal 1", "Terminal 2")
- Rectangles are clickable — clicking selects a terminal for calibration

### Live Gaze Pointer

- Webcam + MediaPipe start immediately when the overlay opens
- A small colored dot/crosshair moves on the overlay in real-time, showing where EyeClaude detects the user is looking
- This serves as both a calibration tool and a confidence check — if the pointer is wildly off, the user knows before recording
- The gaze pointer is **only visible during the calibration overlay**, never during normal operation

### Real-Time Window Tracking

- The overlay polls `GetWindowRect` on each discovered HWND at ~100ms intervals
- If the user alt-tabs, moves, or resizes terminal windows during calibration, the rectangle placeholders update in real-time to match
- If a terminal window is closed, its rectangle disappears
- If a new terminal window is opened, its rectangle appears

### Calibration Flow Per Terminal

1. User sees the overlay with all terminal rectangles and the live gaze pointer
2. User **clicks** a terminal rectangle to select it (rectangle highlights)
3. User looks at the terminal area and presses **Start** (key or button)
4. User moves their eyes naturally around the terminal while the system records gaze samples
5. User presses **End** — recording stops, gaze samples are averaged and stored
6. Rectangle turns green to indicate it's calibrated
7. User repeats for remaining terminals, or presses **Escape** to close the overlay and begin tracking

### Post-Calibration New Terminal Detection

- A background thread polls for new Windows Terminal windows every few seconds
- When a new terminal is detected, EyeClaude notifies the user (e.g., system tray toast or statusline message): "New terminal detected — calibrate?"
- If the user agrees, the calibration overlay reopens showing the new terminal plus existing ones (already-calibrated terminals shown as green/done)
- Gaze-to-screen mapping from existing calibration data is used to infer approximate mapping for the new terminal's position, but explicit calibration is offered for accuracy

## Status Indicator via Statusline

### Current Approach (Eliminated)

Window title hacking with emoji prefixes (`🟢 IDLE`, `🔵 WORKING`) — fragile, ugly, overwrites useful title info.

### New Approach

Integrate into Claude Code's built-in status line by wrapping the existing `ccstatusline` package.

**How it works:**

1. EyeClaude main process writes per-terminal status to `~/.eyeclaude/status/<HWND>.json`:
   ```json
   {"status": "idle", "active": true}
   ```
2. A statusline wrapper script replaces the `ccstatusline` command in `~/.claude/settings.json`
3. The wrapper:
   - Reads stdin (Claude Code session JSON)
   - Identifies which terminal it's in by calling `GetConsoleWindow()` to get the HWND (same approach the hooks already use)
   - Reads the EyeClaude status file for this terminal's HWND
   - Pipes stdin through `ccstatusline` to get normal status line output
   - Prepends the EyeClaude indicator to the ccstatusline output
4. `eyeclaude start` updates `settings.json` to use the wrapper; `eyeclaude stop` restores the original

**Status indicators:**

| Emoji | Status | Meaning |
|-------|--------|---------|
| 🟢 | idle | Waiting for input |
| 🔵 | working | Processing / tool use |
| 🟡 | finished | Just completed (flashes ~2s then idle) |
| 🔴 | error | Error occurred |
| ◀ | active | This terminal has eye-focus |

**Hook flow:** Claude Code hooks fire → `eyeclaude-hooks` sends status via named pipe → EyeClaude main process updates `~/.eyeclaude/status/<HWND>.json` → statusline wrapper picks it up on next refresh.

## What Changes

### Eliminated

- `/eyeclaude-register` slash command (`~/.claude/commands/eyeclaude-register.md`)
- `/eyeclaude-unregister` slash command (`~/.claude/commands/eyeclaude-unregister.md`)
- `register` CLI command and `_register_one_window()` in `cli.py`
- `unregister` CLI command in `cli.py`
- Window-title-based status overlay (`overlay.py` title-setting logic)
- Manual "Press ENTER here when all terminals are registered" prompt in `start`

### Kept but Modified

- **`cli.py` `start` command** — now auto-discovers terminals and launches calibration overlay
- **`pipe_server.py`** — still handles status messages from hooks; registration messages no longer come from external commands
- **`_install_claude_hooks()` / `_remove_claude_hooks()`** — called automatically during `start` / `stop`
- **`calibration.py`** — rewritten to use the new overlay-based flow
- **`overlay.py`** — gutted and repurposed or replaced

### New Files

- **`calibration_overlay.py`** — Tkinter full-screen overlay with live gaze pointer, clickable rectangles, Start/End recording, real-time window position tracking
- **`terminal_discovery.py`** — auto-detection of terminal windows via Win32 API, real-time position polling
- **`statusline_wrapper.py`** — wraps `ccstatusline` with EyeClaude status indicator prefix
- **`~/.eyeclaude/status/`** directory — per-terminal status JSON files

### Updated CLI Interface

| Command | Description |
|---------|-------------|
| `eyeclaude start` | Auto-discover terminals, install hooks, open calibration overlay, start tracking |
| `eyeclaude stop` | Shut down, remove hooks, restore statusline config, clean up status files |
| `eyeclaude calibrate` | Re-open the calibration overlay for recalibration |
| `eyeclaude status` | Show discovered terminals and their current states |
| `eyeclaude config` | Adjust settings (dwell time, border thickness, colors) |

## Communication

Named pipe (`\\.\pipe\eyeclaude`) remains the communication channel. Message types:

```json
{"type": "status", "window_handle": 12345, "state": "working"}
{"type": "status", "window_handle": 12345, "state": "idle"}
{"type": "status", "window_handle": 12345, "state": "finished"}
{"type": "status", "window_handle": 12345, "state": "error"}
{"type": "shutdown"}
```

The `register` and `unregister` message types are removed — terminal discovery is automatic.

## Tech Stack

No new dependencies beyond what's already in the project:

- **Python 3.13**
- **Tkinter** (stdlib) — calibration overlay
- **MediaPipe** — face mesh / iris tracking (already used)
- **OpenCV** — webcam capture (already used)
- **pywin32** — Win32 API (already used)
- **Click** — CLI framework (already used)

## Error Handling

- **No terminals found** — overlay shows message "No Windows Terminal windows detected. Open some terminals and they'll appear automatically." (real-time detection means they appear as soon as opened)
- **Webcam not found** — clear error on startup, exit gracefully
- **Gaze pointer way off** — user sees it live and can reposition / adjust before recording
- **Terminal closed during calibration** — rectangle disappears, calibration data for that terminal discarded
- **Named pipe unreachable from hooks** — fail silently (EyeClaude may not be running), same as current behavior
- **Status file stale** — statusline wrapper checks file age, falls back to no indicator if too old
