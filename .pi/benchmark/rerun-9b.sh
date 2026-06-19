#!/bin/bash
# Wait for the round-2 sweep to finish, then re-run just the 9b coder model.
set -e
cd "$(dirname "$0")/../.."

# Wait for the current sweep's DONE sentinel.
while [ ! -f .pi/benchmark-results/DONE ]; do
  sleep 30
done

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] round-2 done; archiving and starting 9b-only re-run"

# Archive round-2 results.
mv .pi/benchmark-results/results.md      .pi/benchmark-results/results-round2.md
mv .pi/benchmark-results/results.jsonl   .pi/benchmark-results/results-round2.jsonl
mv .pi/benchmark-results/run.log         .pi/benchmark-results/run-round2.log
mv .pi/benchmark-results/DONE            .pi/benchmark-results/DONE-round2

# Swap in the 9b-only model list.
cat > .pi/benchmark-models.json <<'EOF'
[
  { "label": "qwopus3.5-9b-coder-q8-rerun", "model": "qwopus3.5-9b-coder-q8_0" }
]
EOF

python .pi/benchmark/run.py
