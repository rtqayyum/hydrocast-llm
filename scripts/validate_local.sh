#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src"
export TMPDIR="$ROOT/tmp" TMP="$ROOT/tmp" TEMP="$ROOT/tmp"
mkdir -p "$ROOT/tmp"
bash -n "$ROOT/Batch" "$ROOT/scripts/bootstrap.sh" "$ROOT/scripts/validate_local.sh"
find "$ROOT/hpc" -name '*.sbatch' -type f -print0 | xargs -0 -r bash -n
find "$ROOT/src" "$ROOT/tests" -name '*.py' -type f -print0 | xargs -0 -r python -m py_compile
python -m unittest discover -s "$ROOT/tests" -v
# Exercise the persistent import without relying on PYTHONPATH.
python -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" "$ROOT/scripts/register_local_source.py" "$ROOT"
(cd "$ROOT/tmp" && env -u PYTHONPATH "$ROOT/.venv/bin/python" -c 'import hydrocast, hydrocast.cli; print("package import OK:", hydrocast.__version__)')
python "$ROOT/scripts/check_safety.py" "$ROOT"
