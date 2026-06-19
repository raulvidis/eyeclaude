---
summary: "All EyeClaude configuration options"
read_when:
  - "Configuring EyeClaude"
  - "Tuning gaze detection behavior"
  - "Setting up Claude Code integration"
---

# Configuration

Config lives at `~/.eyeclaude/config.json`:

| Key | Default | Meaning |
|---|---|---|
| `dwell_time_ms` | 400 | How long gaze must rest on a quadrant before switching focus |
| `webcam_index` | 0 | OpenCV device index |
| `border_thickness_px` | 4 | (reserved for the overlay renderer) |
| `finished_flash_duration_ms` | 2000 | How long a finished-state flash lasts |

## Claude Code hooks

Running `eyeclaude start` installs hooks into `~/.claude/settings.local.json`:

- `PreToolUse` → status `working`
- `Stop` → status `finished`
- `StopFailure` → status `error`
- `UserPromptSubmit` → status `idle`

These are removed by `eyeclaude stop`.

## Statusline

The statusline indicator is installed via `eyeclaude-statusline` — a pure-Python entry point that composes an EyeClaude indicator with `ccstatusline` output. No shell interpolation.
