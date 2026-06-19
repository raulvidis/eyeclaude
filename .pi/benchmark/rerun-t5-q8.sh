#!/bin/bash
# After the 9b rerun finishes, re-run task 5 only on the Q8 A3B models that
# previously hit the 600s HTTP timeout. No timeout change, just trying again.
set -e
cd "$(dirname "$0")/../.."

# Wait until both prior phases have produced their DONE sentinels and been
# archived. The 9b rerun script archives round-2 then leaves a fresh DONE.
# We watch for results-round2.md (proves round 2 was archived) AND the
# current DONE (proves 9b rerun finished).
while true; do
  if [ -f .pi/benchmark-results/results-round2.md ] && [ -f .pi/benchmark-results/DONE ]; then
    break
  fi
  sleep 30
done

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] 9b rerun complete; starting T5-only Q8 A3B reruns"

# Archive 9b rerun results.
mv .pi/benchmark-results/results.md      .pi/benchmark-results/results-round3-9brerun.md
mv .pi/benchmark-results/results.jsonl   .pi/benchmark-results/results-round3-9brerun.jsonl
mv .pi/benchmark-results/run.log         .pi/benchmark-results/run-round3-9brerun.log
mv .pi/benchmark-results/DONE            .pi/benchmark-results/DONE-round3-9brerun

# Q8 A3B models to retry T5 on.
cat > .pi/benchmark-models.json <<'EOF'
[
  { "label": "qwopus3.6-35b-a3b-v1-q8-t5rerun", "model": "qwopus3.6-35b-a3b-v1-q8_0" }
]
EOF

python .pi/benchmark/run.py --task 5
