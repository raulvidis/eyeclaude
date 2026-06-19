---
summary: "Known issues and workarounds for EyeClaude"
read_when:
  - "Something isn't working"
  - "Getting error messages from EyeClaude"
  - "Statusline not showing the indicator"
  - "Hooks not firing in Claude Code"
---

# Troubleshooting

## Statusline not showing indicator

- Verify `eyeclaude-statusline` is on PATH: `where eyeclaude-statusline`
- Check `~/.claude/settings.local.json` for `statusLine.command` entry
- If it shows a `bash -c` command, run `eyeclaude start` again to replace it

## Hooks not firing

- Check `~/.eyeclaude/hooks.log` for pipe write errors
- Verify EyeClaude is running: `eyeclaude status`
- Confirm Claude Code hooks are installed: check `~/.claude/settings.local.json`

## Gaze not detecting correctly

- Run `eyeclaude calibrate` again
- Ensure good lighting on face
- Check webcam index: `eyeclaude config --webcam-index 1` (if using a different camera)

## Focus switching doesn't work

- Ensure EyeClaude has focus permissions on Windows
- Try running Claude Code with administrator privileges
- Check that the terminal window is not minimized

## Multi-monitor quadrant wrong

- This is a known issue — quadrant assignment may use primary screen metrics
- A fix is in progress: per-monitor quadrant calculation
