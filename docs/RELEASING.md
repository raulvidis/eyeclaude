---
summary: "Step-by-step release checklist for EyeClaude"
read_when:
  - "Preparing to make a release"
  - "Bumping the version"
  - "Creating a git tag or GitHub Release"
---

# Releasing EyeClaude

## Checklist

1. Move items from `## [Unreleased]` to a new versioned section in CHANGELOG.md
2. Bump the version in `pyproject.toml`
3. Commit the version bump: `git commit -m "chore: bump version to X.Y.Z"`
4. Create the git tag: `git tag vX.Y.Z`
5. Push the tag: `git push origin vX.Y.Z`
6. Verify: tag exists on GitHub

## Notes

- No PyPI publish yet — this is pre-release territory
- No automated CI — manual verification required
- After tagging, open a fresh `## [Unreleased]` section in CHANGELOG.md
