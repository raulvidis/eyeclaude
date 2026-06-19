"""Standalone benchmark orchestrator — drives an OpenAI-compatible endpoint
(llama-swap) through the 5-task eyeclaude critical-fixes plan, for each model
listed in .pi/benchmark-models.json.

Usage:
    python .pi/benchmark/run.py             # all models, all tasks
    python .pi/benchmark/run.py --task 3    # all models, only task 3
    python .pi/benchmark/run.py --model qwen3-30b-q4   # one model, all tasks

Runs sequentially: all 5 tasks for one model before moving to the next.
Resets the repo to BASELINE_SHA before each task and starts a fresh
conversation, so models don't share context across tasks.

Writes:
    .pi/benchmark-results/run.log         streaming text log
    .pi/benchmark-results/results.md      markdown table (one row per task)
    .pi/benchmark-results/results.jsonl   raw structured metrics
    .pi/benchmark-results/DONE            sentinel file when finished
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tools import TOOLS, TOOL_SCHEMAS, REPO_ROOT  # noqa: E402

BASELINE_SHA = "2fd7d38"
PROMPTS_DIR = REPO_ROOT / ".pi" / "benchmark-prompts"
MODELS_FILE = REPO_ROOT / ".pi" / "benchmark-models.json"
SERVER_CONFIG = REPO_ROOT / ".pi" / "llama-server.json"
RESULTS_DIR = REPO_ROOT / ".pi" / "benchmark-results"
LOG_FILE = RESULTS_DIR / "run.log"
MD_FILE = RESULTS_DIR / "results.md"
JSONL_FILE = RESULTS_DIR / "results.jsonl"
DONE_FILE = RESULTS_DIR / "DONE"

TASK_TIMEOUT_SEC = 15 * 60
MAX_AGENT_ITERATIONS = 80
HTTP_TIMEOUT_SEC = 600

SCOPE_FORBIDDEN_FILES = [
    "src/eyeclaude/calibration_overlay.py",
    "src/eyeclaude/overlay.py",
]

EXPECTED_COMMIT_MSG = {
    1: "fix: quadrant assignment uses window's own monitor work area",
    2: "fix: verify MediaPipe model SHA-256 before use",
    3: "fix: replace shell-interpolated statusline command with python entry point",
    4: "fix: log hook pipe-write failures to ~/.eyeclaude/hooks.log",
    5: "fix: prune dead terminals from shared state in main loop",
}


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_endpoint() -> str:
    cfg = json.loads(SERVER_CONFIG.read_text(encoding="utf-8"))
    url = cfg["url"].rstrip("/")
    return f"{url}/v1/chat/completions"


def load_models() -> list[dict]:
    if not MODELS_FILE.exists():
        raise SystemExit(
            f"Missing {MODELS_FILE}. Create it as a JSON array of "
            '{"label": "...", "model": "..."} objects.'
        )
    data = json.loads(MODELS_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise SystemExit(f"{MODELS_FILE} must be a non-empty JSON array")
    for row in data:
        if "label" not in row or "model" not in row:
            raise SystemExit(f"Each row needs 'label' and 'model': {row}")
    return data


def load_prompts() -> tuple[str, dict[int, str]]:
    preamble = (PROMPTS_DIR / "preamble.md").read_text(encoding="utf-8")
    tasks = {}
    for i in range(1, 6):
        tasks[i] = (PROMPTS_DIR / f"task-{i}.md").read_text(encoding="utf-8")
    return preamble, tasks


def git(*args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def reset_repo() -> None:
    code, _, err = git("reset", "--hard", BASELINE_SHA)
    if code != 0:
        raise RuntimeError(f"git reset failed: {err}")
    # Clean untracked .py files left from earlier failed task attempts so the
    # model starts from a deterministic baseline. We do NOT touch .pi/, docs/, etc.
    git("clean", "-fd", "src/", "tests/")


def head_sha() -> str:
    code, out, _ = git("rev-parse", "HEAD")
    return out if code == 0 else ""


def head_message() -> str:
    code, out, _ = git("log", "-1", "--pretty=%s")
    return out if code == 0 else ""


def http_post_json(url: str, payload: dict, timeout: float) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_agent_loop(
    endpoint: str,
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    deadline: float,
) -> tuple[str, int, str]:
    """Run the OpenAI tool-using agent loop until the model returns a final
    text message or the deadline passes. Returns (final_text, iterations, stop_reason)."""
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    for iteration in range(1, MAX_AGENT_ITERATIONS + 1):
        if time.monotonic() > deadline:
            return ("", iteration, "deadline")

        payload = {
            "model": model_name,
            "messages": messages,
            "tools": TOOL_SCHEMAS,
            "tool_choice": "auto",
            "temperature": 0.6,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        # Retry transient server errors (5xx, connection closed). Don't retry
        # timeouts — those mean the model is stuck and re-sending won't help.
        resp = None
        last_err = ""
        max_retries = 3
        for attempt in range(max_retries):
            if time.monotonic() > deadline:
                return ("", iteration, "deadline")
            try:
                resp = http_post_json(endpoint, payload, timeout=HTTP_TIMEOUT_SEC)
                break
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                last_err = f"http {e.code}: {err_body[:500]}"
                if e.code < 500 or attempt == max_retries - 1:
                    return ("", iteration, last_err)
                log(f"  iter {iteration} attempt {attempt+1}/{max_retries}: {last_err[:120]} — retrying")
                time.sleep(2 * (attempt + 1))
            except (TimeoutError, OSError) as e:
                last_err = f"http error: {e}"
                msg_str = str(e).lower()
                # "timed out" is the urllib timeout — don't retry that
                if "timed out" in msg_str or attempt == max_retries - 1:
                    return ("", iteration, last_err)
                log(f"  iter {iteration} attempt {attempt+1}/{max_retries}: {last_err[:120]} — retrying")
                time.sleep(2 * (attempt + 1))
            except Exception as e:
                return ("", iteration, f"http error: {e}")
        if resp is None:
            return ("", iteration, last_err or "no response")

        choice = resp.get("choices", [{}])[0]
        msg = choice.get("message", {})
        finish = choice.get("finish_reason", "")
        tool_calls = msg.get("tool_calls") or []
        text = msg.get("content") or ""

        # Always append the assistant message verbatim (preserves tool_call IDs).
        assistant_msg = {"role": "assistant", "content": text}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        if not tool_calls:
            return (text, iteration, finish or "stop")

        for tc in tool_calls:
            tc_id = tc.get("id", "")
            fn = tc.get("function", {})
            name = fn.get("name", "")
            raw_args = fn.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}
            handler = TOOLS.get(name)
            if handler is None:
                result = f"Error: unknown tool '{name}'"
            else:
                try:
                    result = handler(args)
                except Exception as e:  # noqa: BLE001
                    result = f"Tool '{name}' raised: {e}\n{traceback.format_exc()}"
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result,
                }
            )

    return ("", MAX_AGENT_ITERATIONS, "max_iterations")


def measure_task(
    task_num: int, model_label: str, start_sha: str, duration_ms: int, stop_reason: str
) -> dict:
    end_sha = head_sha()
    committed = bool(end_sha) and end_sha != start_sha
    commit_msg = head_message() if committed else ""
    expected = EXPECTED_COMMIT_MSG[task_num]
    msg_matches = commit_msg == expected

    pytest_proc = subprocess.run(
        ["python", "-m", "pytest", "-q", "--tb=line"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=300,
    )
    tests_pass = pytest_proc.returncode == 0
    tests_summary = ""
    for line in reversed(pytest_proc.stdout.splitlines()):
        if line.strip():
            tests_summary = line.strip()
            break

    # Diff stats vs baseline.
    diff_proc = subprocess.run(
        ["git", "diff", "--shortstat", f"{BASELINE_SHA}..HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    stats = parse_shortstat(diff_proc.stdout)

    name_proc = subprocess.run(
        ["git", "diff", "--name-only", f"{BASELINE_SHA}..HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    touched = [s for s in name_proc.stdout.split("\n") if s.strip()]
    scope_violations = [f for f in touched if f in SCOPE_FORBIDDEN_FILES]
    scope_clean = len(scope_violations) == 0

    # Placeholder leak.
    leak_proc = subprocess.run(
        ["git", "grep", "-l", "PASTE_", "--", "src/", "tests/"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    placeholder_leak = leak_proc.returncode == 0

    score = score_task(
        committed=committed,
        tests_pass=tests_pass,
        scope_clean=scope_clean,
        msg_matches=msg_matches,
        placeholder_leak=placeholder_leak,
        duration_ms=duration_ms,
    )

    return {
        "task": task_num,
        "model": model_label,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": duration_ms,
        "stop_reason": stop_reason,
        "committed": committed,
        "commit_sha": end_sha,
        "commit_msg": commit_msg,
        "commit_msg_matches": msg_matches,
        "tests_pass": tests_pass,
        "tests_summary": tests_summary,
        "scope_clean": scope_clean,
        "scope_violations": scope_violations,
        "files_changed": stats["files_changed"],
        "lines_added": stats["lines_added"],
        "lines_removed": stats["lines_removed"],
        "placeholder_leak": placeholder_leak,
        "score": score,
    }


def parse_shortstat(s: str) -> dict:
    import re

    out = {"files_changed": 0, "lines_added": 0, "lines_removed": 0}
    if m := re.search(r"(\d+) files? changed", s):
        out["files_changed"] = int(m.group(1))
    if m := re.search(r"(\d+) insertions?\(\+\)", s):
        out["lines_added"] = int(m.group(1))
    if m := re.search(r"(\d+) deletions?\(-\)", s):
        out["lines_removed"] = int(m.group(1))
    return out


def score_task(
    *,
    committed: bool,
    tests_pass: bool,
    scope_clean: bool,
    msg_matches: bool,
    placeholder_leak: bool,
    duration_ms: int,
) -> int:
    if not committed:
        return 0
    score = 15  # committed at all
    score += 40 if tests_pass else 0
    score += 25 if scope_clean else 0
    score += 10 if msg_matches else 0
    score -= 20 if placeholder_leak else 0
    minutes = duration_ms / 60000
    if minutes < 1:
        score += 10
    elif minutes < 3:
        score += 7
    elif minutes < 6:
        score += 4
    elif minutes < 12:
        score += 1
    return max(0, min(100, score))


def ensure_results_files() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if not MD_FILE.exists():
        MD_FILE.write_text(
            "# eyeclaude benchmark results\n\n"
            "| When (UTC) | Model | Task | Score | Duration (s) | Tests | Scope | "
            "Commit msg ✓ | Files | +/− | Stop | Commit msg |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|\n",
            encoding="utf-8",
        )


def append_results(row: dict) -> None:
    md_line = (
        f"| {row['started_at']} | {row['model']} | {row['task']} | {row['score']} | "
        f"{row['duration_ms']/1000:.1f} | {'✓' if row['tests_pass'] else '✗'} | "
        f"{'✓' if row['scope_clean'] else '✗ ' + ','.join(row['scope_violations'])} | "
        f"{'✓' if row['commit_msg_matches'] else '✗'} | {row['files_changed']} | "
        f"+{row['lines_added']}/-{row['lines_removed']} | {row['stop_reason']} | "
        f"{row['commit_msg']} |\n"
    )
    with MD_FILE.open("a", encoding="utf-8") as f:
        f.write(md_line)
    with JSONL_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=int, default=0, help="run only this task (1..5)")
    parser.add_argument("--model", type=str, default="", help="run only this model label")
    args = parser.parse_args()

    if DONE_FILE.exists():
        DONE_FILE.unlink()

    endpoint = load_endpoint()
    models = load_models()
    if args.model:
        models = [m for m in models if m["label"] == args.model]
        if not models:
            raise SystemExit(f"No model with label '{args.model}' in {MODELS_FILE}")

    preamble, prompts = load_prompts()
    tasks = [args.task] if args.task else [1, 2, 3, 4, 5]

    ensure_results_files()
    log(f"endpoint={endpoint} models={[m['label'] for m in models]} tasks={tasks}")

    total_started = time.monotonic()
    for m in models:
        log(f"=== model={m['label']} (id={m['model']}) ===")
        for task_num in tasks:
            log(f"  task {task_num}: reset to {BASELINE_SHA}")
            try:
                reset_repo()
            except Exception as e:  # noqa: BLE001
                log(f"  reset failed: {e}")
                continue
            start_sha = head_sha()
            user_prompt = prompts[task_num]
            t0 = time.monotonic()
            deadline = t0 + TASK_TIMEOUT_SEC
            log(f"  task {task_num}: starting agent loop")
            final_text, iterations, stop_reason = run_agent_loop(
                endpoint, m["model"], preamble, user_prompt, deadline
            )
            duration_ms = int((time.monotonic() - t0) * 1000)
            log(
                f"  task {task_num}: done iterations={iterations} stop={stop_reason} "
                f"duration={duration_ms}ms"
            )
            row = measure_task(task_num, m["label"], start_sha, duration_ms, stop_reason)
            row["iterations"] = iterations
            row["final_text_preview"] = (final_text or "")[:200]
            append_results(row)
            log(
                f"  task {task_num}: score={row['score']}/100 committed={row['committed']} "
                f"tests={row['tests_pass']} scope={row['scope_clean']}"
            )

    elapsed_min = (time.monotonic() - total_started) / 60
    log(f"sweep complete in {elapsed_min:.1f} min")
    DONE_FILE.write_text(
        json.dumps(
            {
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "elapsed_minutes": elapsed_min,
                "models": [m["label"] for m in models],
                "tasks": tasks,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        log(f"FATAL: {e}\n{traceback.format_exc()}")
        sys.exit(1)
