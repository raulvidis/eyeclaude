#!/bin/bash
# Phase 4: after phase 3 finishes (T5-only Q8 reruns at default 600s timeout),
# re-run task 5 on qwopus3.6-35b-a3b-v1-q8 with a 15-min HTTP timeout.
set -e
cd "$(dirname "$0")/../.."

# Wait for phase 3's archive sentinel: results-round3-9brerun.md must already
# exist (phase 2 -> phase 3 archive boundary) AND a fresh DONE in results/.
while true; do
  if [ -f .pi/benchmark-results/results-round3-9brerun.md ] && [ -f .pi/benchmark-results/DONE ]; then
    break
  fi
  sleep 30
done

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] phase 3 done; archiving and starting phase 4 (15-min timeout)"

# Archive phase 3 results as round 4 (T5 Q8 reruns at default 600s).
mv .pi/benchmark-results/results.md      .pi/benchmark-results/results-round4-t5q8.md
mv .pi/benchmark-results/results.jsonl   .pi/benchmark-results/results-round4-t5q8.jsonl
mv .pi/benchmark-results/run.log         .pi/benchmark-results/run-round4-t5q8.log
mv .pi/benchmark-results/DONE            .pi/benchmark-results/DONE-round4-t5q8

# Bump HTTP_TIMEOUT_SEC to 900 (15 min).
python -c "
import re, pathlib
p = pathlib.Path('.pi/benchmark/run.py')
src = p.read_text()
new = re.sub(r'HTTP_TIMEOUT_SEC = \d+', 'HTTP_TIMEOUT_SEC = 900', src, count=1)
p.write_text(new)
print('patched HTTP_TIMEOUT_SEC = 900')
"

# Phase 4: just qwopus3.6-35b-a3b-v1-q8, T5 only, 15-min timeout.
cat > .pi/benchmark-models.json <<'EOF'
[
  { "label": "qwopus3.6-35b-a3b-v1-q8-t5-15min", "model": "qwopus3.6-35b-a3b-v1-q8_0" }
]
EOF

python .pi/benchmark/run.py --task 5

# Restore default timeout.
python -c "
import re, pathlib
p = pathlib.Path('.pi/benchmark/run.py')
src = p.read_text()
new = re.sub(r'HTTP_TIMEOUT_SEC = \d+', 'HTTP_TIMEOUT_SEC = 600', src, count=1)
p.write_text(new)
print('restored HTTP_TIMEOUT_SEC = 600')
"
