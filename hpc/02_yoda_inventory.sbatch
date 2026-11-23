#!/usr/bin/env bash
#SBATCH --job-name=hc_yoda_inventory
#SBATCH --partition=longq
#SBATCH --time=00:30:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --output=/home/tariq.qayyum/hpc/hydrocast-llm/logs/%x_%j.out
#SBATCH --error=/home/tariq.qayyum/hpc/hydrocast-llm/logs/%x_%j.err
set -Eeuo pipefail
ROOT=/home/tariq.qayyum/hpc/hydrocast-llm
cd "$ROOT"
mkdir -p "$ROOT"/{logs,results,reports,data_manifest,outputs/full_download,tmp,cache}
export TMPDIR="$ROOT/tmp" TMP="$ROOT/tmp" TEMP="$ROOT/tmp" XDG_CACHE_HOME="$ROOT/cache"
export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
failure() {
  local rc="$1"
  printf '{"status":"failed","job_id":"%s","exit_code":%s}\n' "$SLURM_JOB_ID" "$rc" > "$ROOT/results/yoda_inventory_failure.json"
  exit "$rc"
}
trap 'failure "$?"' ERR
if ! type module >/dev/null 2>&1 && [[ -f /etc/profile.d/modules.sh ]]; then
  source /etc/profile.d/modules.sh
fi
module load anaconda3
bash "$ROOT/scripts/bootstrap.sh"
unset PYTHONPATH
srun --ntasks=1 --cpus-per-task=1 "$ROOT/.venv/bin/python" \
  "$ROOT/scripts/yoda_full.py" inventory
echo "SUCCESS Yoda publisher file manifest inventory; no large downloads started."
echo "REPORT $ROOT/reports/FULL_YODA_INVENTORY.md"
