---
description: "Full release pipeline."
---
Follow docs/RELEASING.md exactly:
1) Move items from `## [Unreleased]` to a new versioned section in CHANGELOG.md
2) Bump `version` in `pyproject.toml`
3) Commit the version bump: `git commit -m "chore: bump version to X.Y.Z"`
4) Create the git tag: `git tag vX.Y.Z`
5) Push the tag: `git push origin vX.Y.Z`
6) Verify: tag exists on GitHub
7) Re-open a fresh `## [Unreleased]` section in CHANGELOG.md

Release = git tag only. No PyPI publish, no GitHub Release, no CI (pre-release).
Do NOT push or tag without explicit confirmation.
