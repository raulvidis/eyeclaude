# eyeclaude benchmark results

| When (UTC) | Model | Task | Score | Duration (s) | Tests | Scope | Commit msg ✓ | Files | +/− | Stop | Commit msg |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-06-18T10:47:41.451882+00:00 | qwopus3.6-35b-v1-q4km-8081 | 1 | 100 | 43.6 | ✓ | ✓ | ✓ | 2 | +28/-5 | stop | fix: quadrant assignment uses window's own monitor work area |
| 2026-06-18T10:48:33.942001+00:00 | qwopus3.6-35b-v1-q4km-8081 | 2 | 100 | 48.3 | ✓ | ✓ | ✓ | 2 | +41/-1 | stop | fix: verify MediaPipe model SHA-256 before use |
| 2026-06-18T10:50:01.735473+00:00 | qwopus3.6-35b-v1-q4km-8081 | 3 | 97 | 83.6 | ✓ | ✓ | ✓ | 4 | +95/-19 | stop | fix: replace shell-interpolated statusline command with python entry point |
| 2026-06-18T10:50:46.918367+00:00 | qwopus3.6-35b-v1-q4km-8081 | 4 | 100 | 40.9 | ✓ | ✓ | ✓ | 2 | +82/-2 | stop | fix: log hook pipe-write failures to ~/.eyeclaude/hooks.log |
| 2026-06-18T10:51:25.192884+00:00 | qwopus3.6-35b-v1-q4km-8081 | 5 | 0 | 34.1 | ✓ | ✓ | ✗ | 0 | +0/-0 | http 500: {"error":{"code":500,"message":"The model produced output that does not match the expected peg-native format","type":"server_error"}} |  |
