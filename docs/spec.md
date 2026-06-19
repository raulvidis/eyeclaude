---
summary: "Design constraints: goals, non-goals, compatibility, and packaging rules"
read_when:
  - "Evaluating a feature for inclusion"
  - "Deciding between two implementation approaches"
  - "Reviewing compatibility commitments"
---

# Spec

## Goals

- Eye-tracking focus management for Claude Code on Windows
- Multi-monitor support (quadrant assignment per window's monitor)
- Claude Code hook integration (status reporting)
- Statusline indicator with EyeClaude marker

## Non-goals

- macOS/Linux support (pywin32 dependency)
- Multi-user support (single-user config at `~/.eyeclaude/`)
- Cloud sync of config
- Real-time gaze heatmap or analytics

## Compatibility

- Python 3.12+ — no older versions supported
- Windows 10/11 — no older versions supported
- MediaPipe FaceLandmarker v0.10.33+ — model pinned by SHA-256

## Packaging

- Setuptools (editable install)
- No PyPI release yet (version 0.1.0 is pre-release)
- Console scripts: `eyeclaude`, `eyeclaude-hooks`, `eyeclaude-statusline`
