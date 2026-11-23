#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src"
export TMPDIR="$ROOT/tmp" TMP="$ROOT/tmp" TEMP="$ROOT/tmp"
mkdir -p "$ROOT/tmp"
bash -n "$ROOT/Batch" "$ROOT/scripts/bootstrap.sh" "$ROOT/scripts/validate_local.sh"
find "$ROOT/src" "$ROOT/tests" -name '*.py' -type f -print0 | xargs -0 -r python -m py_compile
python -m unittest discover -s "$ROOT/tests" -v
python "$ROOT/scripts/check_safety.py" "$ROOT"
