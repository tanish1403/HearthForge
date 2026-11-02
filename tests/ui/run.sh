#!/usr/bin/env bash
# Usage: tests/ui/run.sh   (needs node 18+ and python deps installed)
set -euo pipefail
cd "$(dirname "$0")"
[ -d node_modules ] || npm install --silent
export HF_UI_TMP="$(mktemp -d)" HF_UI_PORT="${HF_UI_PORT:-8798}"
python3 serve.py & PID=$!
trap 'kill $PID 2>/dev/null || true' EXIT
for _ in $(seq 1 40); do curl -sf "http://127.0.0.1:$HF_UI_PORT/auth?token=tok" -o /dev/null -w '' && break || sleep 0.25; done
node journey.mjs
