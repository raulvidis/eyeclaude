---
summary: "Manual test procedures for EyeClaude"
read_when:
  - "Testing EyeClaude behavior that can't be automated"
  - "Verifying multi-monitor quadrant assignment"
  - "Checking Claude Code hook integration"
  - "Validating statusline indicator"
---

# Manual Tests

## Calibration

1. Run `eyeclaude calibrate`
2. Verify overlay appears fullscreen
3. Look at top-left → SPACE → look at bottom-right → SPACE → ESC
4. Verify `~/.eyeclaude/config.json` has `calibration` keys

## Multi-monitor quadrant

1. Open two Windows Terminal windows on different monitors
2. Run `eyeclaude start`
3. Look at the terminal on the secondary monitor
4. Verify it gets focused (quadrant assigned correctly)

## Claude Code hooks

1. Run `eyeclaude start` in one terminal
2. In another Claude Code session, run a tool
3. Verify statusline shows EyeClaude indicator (🟢 ◀)
4. Stop the tool → verify status changes to 🔵 (finished)

## Statusline

1. Run `eyeclaude start`
2. In Claude Code, observe statusline — should show `🟢◀ <ccstatusline output>`
3. Stop EyeClaude → verify statusline returns to prior state

## Status monitoring

1. Run `eyeclaude start` with two Claude Code terminals
2. Use one terminal, then switch to the other
3. Verify the statusline indicator follows the active terminal
