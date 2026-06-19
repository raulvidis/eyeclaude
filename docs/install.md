---
summary: "Full installation instructions for EyeClaude"
read_when:
  - "Installing on a new machine"
  - "Troubleshooting installation issues"
---

# Installation

## Prerequisites

- Windows 10/11
- Python 3.12+
- A webcam

## Install

```bash
git clone https://github.com/raulvidis/eyeclaude.git
cd eyeclaude
pip install -e .
```

## Verify

```bash
eyeclaude status
```

Expected: "EyeClaude is not running" (if no instance is active).
