# EyeClaude

Eye-tracking focus manager for [Claude Code](https://claude.com/claude-code). When you run multiple Claude Code terminals side by side, EyeClaude uses your webcam to detect which one you're looking at and automatically brings it to the foreground.

> **Platform:** Windows only (uses Win32 APIs for window focus and hotkeys).

## How it works

1. A MediaPipe face-landmarker reads your webcam and estimates gaze direction.
2. A 2-point calibration maps your gaze bounds (top-left / bottom-right of screen) to screen coordinates.
3. Each detected terminal window is assigned a screen quadrant.
4. When your gaze dwells on a quadrant for ~400 ms, EyeClaude calls `SetForegroundWindow` on that terminal (using `AttachThreadInput` so the focus switch actually grants keyboard input).
5. Claude Code hooks feed per-terminal status (idle / working / finished / error) back into a statusline indicator.

## Requirements

- Windows 10/11
- Python 3.12+
- A webcam

## Install

```bash
git clone https://github.com/raulvidis/eyeclaude.git
cd eyeclaude
pip install -e .
```

This installs three console scripts:

- `eyeclaude` — main CLI
- `eyeclaude-hooks` — invoked by Claude Code hooks to report status
- `eyeclaude-statusline` — optional statusline wrapper

## Usage

```bash
eyeclaude start
```

On first run, a fullscreen calibration overlay appears:

1. Look at the **top-left** corner of your screen, press `SPACE`.
2. Look at the **bottom-right** corner, press `SPACE`.
3. `ESC` to finish — tracking starts.

Hotkeys while running:

- `F8` — pause/resume tracking
- `F9` — recalibrate
- `Ctrl+C` — stop

Other commands:

```bash
eyeclaude calibrate            # re-run calibration only
eyeclaude stop                 # signal a running instance to exit
eyeclaude status               # check if the daemon is reachable
eyeclaude config --dwell-time 400 --webcam-index 0
```

## Configuration

Config lives at `~/.eyeclaude/config.json`:

| Key | Default | Meaning |
|---|---|---|
| `dwell_time_ms` | 400 | How long gaze must rest on a quadrant before switching focus |
| `webcam_index` | 0 | OpenCV device index |
| `border_thickness_px` | 4 | (reserved for the overlay renderer) |
| `finished_flash_duration_ms` | 2000 | How long a finished-state flash lasts |

The MediaPipe face-landmarker model is downloaded on first run to `~/.eyeclaude/face_landmarker.task`.

## Claude Code integration

Running `eyeclaude start` installs hooks into `~/.claude/settings.local.json`:

- `PreToolUse` → status `working`
- `Stop` → status `finished`
- `StopFailure` → status `error`
- `UserPromptSubmit` → status `idle`

These are removed by `eyeclaude stop`. The statusline indicator is a shell one-liner that prepends a colored dot (🟢 🔵 🟡 🔴) plus a `◀` marker to whichever terminal is currently focused, so you can tell at a glance which Claude instance is active.

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

Project layout:

```
src/eyeclaude/
  cli.py                   # CLI entry, main loop, hotkeys
  eye_tracker.py           # webcam + MediaPipe + dwell tracking
  calibration_overlay.py   # fullscreen Tk calibration UI
  calibration.py           # calibration persistence + console flow
  pipe_server.py           # named-pipe IPC for hook status
  window_manager.py        # Win32 focus switching
  status_monitor.py        # per-terminal status transitions
  statusline_wrapper.py    # statusline output combiner
  terminal_discovery.py    # find candidate terminal windows
  shared_state.py          # in-process state shared across threads
  hooks.py                 # `eyeclaude-hooks` entry point
  config.py                # config load/save
```

## License

MIT — see `LICENSE`.
