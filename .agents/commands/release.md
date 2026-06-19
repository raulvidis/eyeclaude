---
description: "Full release pipeline."
---
Follow docs/RELEASING.md exactly:
1) Move items from `## [Unreleased]` to a new versioned section in CHANGELOG.md
2) Bump the version in the repo's version file(s)
3) Commit the version bump (Conventional Commit)
4) Create the git tag (match the repo's tag convention)
5) Create the GitHub Release with the changelog body
6) Publish to the package registry / deploy, if applicable
7) Verify: tag exists, release exists, package/deploy live
8) Re-open a fresh `## [Unreleased]` section

Do NOT push, publish, or deploy without explicit confirmation.
