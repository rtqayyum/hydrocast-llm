#!/usr/bin/env bash
# On cluster login node, after rsync. Ensure Slurm's log destination exists before sbatch.
set -Eeuo pipefail
ROOT=/home/tariq.qayyum/hpc/hydrocast-llm
cd "$ROOT"
mkdir -p "$ROOT"/{logs,logs/workers,results,outputs,outputs/audit/shards,figures,reports,checkpoints,tmp,cache,models,data/raw/lite,data/raw/full,data_manifest}
if ! type module >/dev/null 2>&1 && [[ -f /etc/profile.d/modules.sh ]]; then
  # shellcheck disable=SC1091
  source /etc/profile.d/modules.sh
fi
module load anaconda3
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  python -m venv "$ROOT/.venv"
fi
export HYDROCAST_ROOT="$ROOT" HYDROCAST_EXPECTED_ROOT="$ROOT"
export TMPDIR="$ROOT/tmp" TMP="$ROOT/tmp" TEMP="$ROOT/tmp"
export PYTHONPATH="$ROOT/src" XDG_CACHE_HOME="$ROOT/cache"
export PIP_CACHE_DIR="$ROOT/cache/pip" HF_HOME="$ROOT/cache/huggingface"
export PYTHONDONTWRITEBYTECODE=1
"$ROOT/.venv/bin/python" -m hydrocast.cli --root "$ROOT" preflight
printf 'Ready for source downloads; no files were installed into shared Anaconda.\n'
