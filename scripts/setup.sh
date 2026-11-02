#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
echo "Done. Start with: scripts/run.sh"
