/**
 * eyeclaude-benchmark — Pi extension that runs the 5-task eyeclaude critical-fixes
 * plan against the currently-loaded model, tracking time, correctness, and scope
 * compliance per task. Results append to .pi/benchmark-results.md.
 *
 * Usage (inside Pi):
 *   /benchmark <model-label>     run all 5 tasks
 *   /benchmark <model-label> 3   run just task 3
 *
 * Baseline: the repo is reset to BASELINE_SHA before each task.
 */

import type {
  ExtensionAPI,
  ExtensionCommandContext,
} from "@earendil-works/pi-coding-agent";
import * as fs from "node:fs";
import * as path from "node:path";

const BASELINE_SHA = "2fd7d38";
const PROMPTS_DIR = ".pi/benchmark-prompts";
const RESULTS_FILE = ".pi/benchmark-results.md";
const TASK_TIMEOUT_MS = 15 * 60 * 1000;
const POLL_INTERVAL_MS = 2000;

const SCOPE_FORBIDDEN_FILES = [
  "src/eyeclaude/calibration_overlay.py",
  "src/eyeclaude/overlay.py",
];

const EXPECTED_COMMIT_MSG: Record<number, string> = {
  1: "fix: quadrant assignment uses window's own monitor work area",
  2: "fix: verify MediaPipe model SHA-256 before use",
  3: "fix: replace shell-interpolated statusline command with python entry point",
  4: "fix: log hook pipe-write failures to ~/.eyeclaude/hooks.log",
  5: "fix: prune dead terminals from shared state in main loop",
};

interface TaskMetrics {
  task: number;
  model: string;
  startedAt: string;
  durationMs: number;
  committed: boolean;
  commitSha: string;
  commitMsg: string;
  commitMsgMatches: boolean;
  testsPass: boolean;
  testsSummary: string;
  scopeClean: boolean;
  scopeViolations: string[];
  filesChanged: number;
  linesAdded: number;
  linesRemoved: number;
  placeholderLeak: boolean;
  score: number;
  notes: string;
}

export default function (pi: ExtensionAPI) {
  pi.registerCommand("benchmark", {
    description:
      "Run the 5-task eyeclaude critical-fixes benchmark against the current model",
    handler: async (args, ctx) => {
      const parts = args.trim().split(/\s+/).filter(Boolean);
      if (parts.length === 0) {
        ctx.ui.notify(
          "Usage: /benchmark <model-label> [task-number]",
          "warning",
        );
        return;
      }
      const modelLabel = parts[0];
      const onlyTask = parts[1] ? Number(parts[1]) : undefined;
      if (onlyTask !== undefined && (onlyTask < 1 || onlyTask > 5)) {
        ctx.ui.notify("task-number must be 1..5", "warning");
        return;
      }
      await runBenchmark(pi, ctx, modelLabel, onlyTask);
    },
  });
}

async function runBenchmark(
  pi: ExtensionAPI,
  ctx: ExtensionCommandContext,
  modelLabel: string,
  onlyTask?: number,
) {
  const cwd = ctx.cwd;
  const preamble = readFile(path.join(cwd, PROMPTS_DIR, "preamble.md"));
  const tasks = onlyTask ? [onlyTask] : [1, 2, 3, 4, 5];

  ensureResultsHeader(cwd);
  ctx.ui.notify(
    `Benchmark starting: model=${modelLabel}, tasks=[${tasks.join(",")}]`,
    "info",
  );

  for (const taskNum of tasks) {
    ctx.ui.setWorkingMessage(`benchmark task ${taskNum} (${modelLabel})`);
    const taskPrompt = readFile(
      path.join(cwd, PROMPTS_DIR, `task-${taskNum}.md`),
    );
    const fullPrompt = `${preamble}\n\n---\n\n${taskPrompt}`;

    // Reset repo to baseline.
    const resetResult = await pi.exec("git", ["reset", "--hard", BASELINE_SHA], {
      timeout: 30000,
    });
    if (resetResult.code !== 0) {
      ctx.ui.notify(`git reset failed: ${resetResult.stderr}`, "error");
      return;
    }
    const startSha = await getHeadSha(pi);

    // Fresh session per task — drops all prior context.
    const t0 = Date.now();
    let sessionCancelled = false;

    await ctx.newSession({
      withSession: async () => {
        // Inject the task prompt and let the model take a turn.
        pi.sendUserMessage(fullPrompt, { deliverAs: "followUp" });

        // Wait until a new commit appears OR timeout. Polling is more
        // robust than event sniffing because the model may emit multiple
        // turns / tool calls before settling.
        const deadline = Date.now() + TASK_TIMEOUT_MS;
        while (Date.now() < deadline) {
          await sleep(POLL_INTERVAL_MS);
          const currentSha = await getHeadSha(pi);
          if (currentSha && currentSha !== startSha) {
            // Commit landed. Give the model ~3s to wrap up its reply.
            await sleep(3000);
            return;
          }
        }
      },
    }).then((res) => {
      sessionCancelled = res.cancelled;
    });

    const durationMs = Date.now() - t0;
    const metrics = await measureTask(
      pi,
      cwd,
      taskNum,
      modelLabel,
      startSha,
      durationMs,
      sessionCancelled,
    );
    appendResultRow(cwd, metrics);
    ctx.ui.notify(
      `Task ${taskNum}: score=${metrics.score}/100 (${metrics.durationMs}ms, committed=${metrics.committed}, tests=${metrics.testsPass})`,
      metrics.score >= 80 ? "info" : "warning",
    );
  }

  ctx.ui.setWorkingMessage(undefined);
  ctx.ui.notify(
    `Benchmark complete: model=${modelLabel}. Results: ${RESULTS_FILE}`,
    "info",
  );
}

async function measureTask(
  pi: ExtensionAPI,
  cwd: string,
  taskNum: number,
  modelLabel: string,
  startSha: string,
  durationMs: number,
  sessionCancelled: boolean,
): Promise<TaskMetrics> {
  const startedAt = new Date().toISOString();
  const endSha = await getHeadSha(pi);
  const committed = !!endSha && endSha !== startSha;
  let commitMsg = "";
  if (committed) {
    const r = await pi.exec("git", ["log", "-1", "--pretty=%s", endSha]);
    commitMsg = r.stdout.trim();
  }
  const expectedMsg = EXPECTED_COMMIT_MSG[taskNum];
  const commitMsgMatches = commitMsg === expectedMsg;

  // Test suite.
  const testsResult = await pi.exec(
    "python",
    ["-m", "pytest", "-q", "--tb=line"],
    { timeout: 120000 },
  );
  const testsPass = testsResult.code === 0;
  const testsSummary = lastNonEmptyLine(
    `${testsResult.stdout}\n${testsResult.stderr}`,
  );

  // Diff stats.
  const diffStat = await pi.exec("git", [
    "diff",
    "--shortstat",
    `${BASELINE_SHA}..HEAD`,
  ]);
  const { filesChanged, linesAdded, linesRemoved } = parseShortstat(
    diffStat.stdout,
  );

  // Files touched, for scope check.
  const filesOut = await pi.exec("git", [
    "diff",
    "--name-only",
    `${BASELINE_SHA}..HEAD`,
  ]);
  const touched = filesOut.stdout
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  const scopeViolations = touched.filter((f) =>
    SCOPE_FORBIDDEN_FILES.includes(f),
  );
  const scopeClean = scopeViolations.length === 0;

  // Placeholder leak detection.
  const placeholderGrep = await pi.exec("git", [
    "grep",
    "-l",
    "PASTE_",
    "--",
    "src/",
    "tests/",
  ]);
  const placeholderLeak = placeholderGrep.code === 0;

  const notes: string[] = [];
  if (sessionCancelled) notes.push("session cancelled");
  if (!commitMsgMatches && committed)
    notes.push(`msg≠expected (${commitMsg})`);
  if (placeholderLeak) notes.push("placeholder leak");

  const score = scoreTask({
    committed,
    testsPass,
    scopeClean,
    commitMsgMatches,
    placeholderLeak,
    durationMs,
  });

  return {
    task: taskNum,
    model: modelLabel,
    startedAt,
    durationMs,
    committed,
    commitSha: endSha,
    commitMsg,
    commitMsgMatches,
    testsPass,
    testsSummary,
    scopeClean,
    scopeViolations,
    filesChanged,
    linesAdded,
    linesRemoved,
    placeholderLeak,
    score,
    notes: notes.join("; "),
  };
}

function scoreTask(m: {
  committed: boolean;
  testsPass: boolean;
  scopeClean: boolean;
  commitMsgMatches: boolean;
  placeholderLeak: boolean;
  durationMs: number;
}): number {
  if (!m.committed) return 0;
  let score = 0;
  score += m.testsPass ? 40 : 0;
  score += m.scopeClean ? 25 : 0;
  score += 15; // committed at all
  score += m.commitMsgMatches ? 10 : 0;
  score -= m.placeholderLeak ? 20 : 0;
  // Speed bonus, max 10.
  const min = m.durationMs / 60000;
  if (min < 1) score += 10;
  else if (min < 3) score += 7;
  else if (min < 6) score += 4;
  else if (min < 12) score += 1;
  return Math.max(0, Math.min(100, score));
}

async function getHeadSha(pi: ExtensionAPI): Promise<string> {
  const r = await pi.exec("git", ["rev-parse", "HEAD"]);
  return r.stdout.trim();
}

function parseShortstat(s: string): {
  filesChanged: number;
  linesAdded: number;
  linesRemoved: number;
} {
  // e.g. " 3 files changed, 47 insertions(+), 5 deletions(-)"
  const out = { filesChanged: 0, linesAdded: 0, linesRemoved: 0 };
  const filesMatch = s.match(/(\d+) files? changed/);
  if (filesMatch) out.filesChanged = Number(filesMatch[1]);
  const insMatch = s.match(/(\d+) insertions?\(\+\)/);
  if (insMatch) out.linesAdded = Number(insMatch[1]);
  const delMatch = s.match(/(\d+) deletions?\(-\)/);
  if (delMatch) out.linesRemoved = Number(delMatch[1]);
  return out;
}

function lastNonEmptyLine(s: string): string {
  const lines = s.split("\n").map((l) => l.trim()).filter(Boolean);
  return lines[lines.length - 1] ?? "";
}

function readFile(p: string): string {
  return fs.readFileSync(p, "utf8");
}

function ensureResultsHeader(cwd: string) {
  const p = path.join(cwd, RESULTS_FILE);
  if (fs.existsSync(p)) return;
  const header = `# eyeclaude benchmark results

| When (UTC) | Model | Task | Score | Duration (s) | Tests | Scope | Commit msg ✓ | Files | +/− | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
`;
  fs.writeFileSync(p, header, "utf8");
}

function appendResultRow(cwd: string, m: TaskMetrics) {
  const p = path.join(cwd, RESULTS_FILE);
  const row =
    `| ${m.startedAt} | ${m.model} | ${m.task} | ${m.score} | ${
      (m.durationMs / 1000).toFixed(1)
    } | ${m.testsPass ? "✓" : "✗"} | ${
      m.scopeClean ? "✓" : `✗ ${m.scopeViolations.join(",")}`
    } | ${m.commitMsgMatches ? "✓" : "✗"} | ${m.filesChanged} | +${m.linesAdded}/-${m.linesRemoved} | ${
      m.notes || ""
    } |\n`;
  fs.appendFileSync(p, row, "utf8");
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}
