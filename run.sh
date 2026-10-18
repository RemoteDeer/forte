#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python scripts/dev.py
fi
exec python3 scripts/dev.py
