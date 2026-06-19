# eyeclaude benchmark extension

A Pi project-local extension that drives a local model through the 5-task
critical-fixes plan, captures per-task metrics, and writes a comparison table.

## Layout

```
.pi/
├── extensions/
│   └── eyeclaude-benchmark.ts    # registers /benchmark command
├── benchmark-prompts/
│   ├── preamble.md               # ground rules sent before each task
│   └── task-{1..5}.md            # one self-contained prompt per task
├── benchmark-results.md          # auto-appended results table
├── llama-server.json             # existing llama-server endpoint config
└── README.md                     # this file
```

## Usage

Inside Pi, with the model you want to benchmark loaded:

```
/benchmark <model-label>          # all 5 tasks
/benchmark <model-label> 3        # just task 3
```

`<model-label>` is free-text — use whatever name you want to appear in the
results table (e.g. `qwen3-30b-q4`, `gpt-oss-20b`, `claude-opus-4.7`).

## What the harness does per task

1. `git reset --hard 2fd7d38` — restore the broken baseline.
2. `ctx.newSession()` — fresh model context, zero priors.
3. Inject the task prompt (preamble + task-N.md) as a user message.
4. Poll `git rev-parse HEAD` every 2 s until a new commit appears, or 15-min timeout.
5. Capture:
   - **durationMs** — wall clock from prompt send to commit
   - **committed** — did HEAD advance at all
   - **commitMsg** + **commitMsgMatches** — exact-match against the plan's expected message
   - **testsPass** — `pytest -q` exit code 0
   - **scopeClean** — none of `calibration_overlay.py` / `overlay.py` touched
   - **filesChanged / linesAdded / linesRemoved** — `git diff --shortstat` vs baseline
   - **placeholderLeak** — any `PASTE_` string left in committed code
6. Score 0–100 (transparent rubric below).
7. Append a row to `benchmark-results.md`.

## Scoring rubric

| Component | Points |
|---|---|
| Committed at all | 15 |
| Tests pass | 40 |
| Scope clean (no out-of-scope edits) | 25 |
| Commit message verbatim matches plan | 10 |
| Speed: <1 min | +10, <3 min +7, <6 min +4, <12 min +1 |
| Penalty: placeholder string leaked | −20 |
| Penalty: not committed | score = 0 |

Maximum: 100.

This is a deliberately mechanical scoring — it doesn't try to judge code style
or subtle correctness. Run your own review on the diffs afterward for the
qualitative side.

## Comparing models

Each `/benchmark <label>` run appends rows tagged with that label. Just
re-run with different labels for each model, then read the table:

```bash
cat .pi/benchmark-results.md
```

Or pipe through any markdown viewer to get a sortable view.

## Caveats

- The extension assumes `python -m pytest` is on PATH and the editable install
  of eyeclaude is current. If you switch Python environments, re-run
  `pip install -e .` before benchmarking.
- The harness does NOT change the model — you do that in Pi's UI before
  invoking `/benchmark`. The `<label>` argument is just what we tag rows with.
- Task 3 requires `pip install -e .` to register the new entry point. If the
  model forgets that step, its test for the statusline composer may still pass
  but `eyeclaude start` would fail on first launch. The benchmark won't catch
  this because pytest doesn't shell out to the entry point — flag it manually.
- Polling sleeps 2 s between checks. A genuinely fast model could land a commit
  in <2 s and we'd over-report duration by up to that margin. Live with it.
