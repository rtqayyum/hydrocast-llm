#!/usr/bin/env bash
#SBATCH --job-name=hc_yoda_download
#SBATCH --partition=longq
#SBATCH --time=20-00:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=/home/tariq.qayyum/hpc/hydrocast-llm/logs/%x_%j.out
#SBATCH --error=/home/tariq.qayyum/hpc/hydrocast-llm/logs/%x_%j.err
set -Eeuo pipefail
ROOT=/home/tariq.qayyum/hpc/hydrocast-llm
cd "$ROOT"
mkdir -p "$ROOT"/{logs,results,reports,data_manifest,outputs/full_download,tmp,cache,data/raw/full/yoda_original}
export TMPDIR="$ROOT/tmp" TMP="$ROOT/tmp" TEMP="$ROOT/tmp" XDG_CACHE_HOME="$ROOT/cache"
export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
failure() {
  local rc="$1"
  printf '{"status":"failed","job_id":"%s","exit_code":%s}\n' "$SLURM_JOB_ID" "$rc" > "$ROOT/results/yoda_download_failure.json"
  exit "$rc"
}
trap 'failure "$?"' ERR
if ! type module >/dev/null 2>&1 && [[ -f /etc/profile.d/modules.sh ]]; then
  source /etc/profile.d/modules.sh
fi
module load anaconda3
bash "$ROOT/scripts/bootstrap.sh"
unset PYTHONPATH
# Safety cap limits total local dataset bytes. Increase only after checking YOUR quota.
CAP_GIB="\${HC_MAX_DOWNLOAD_GIB:-500}"
if ! [[ "$CAP_GIB" =~ ^[0-9]+$ ]] || (( CAP_GIB < 1 )); then
  echo "FATAL invalid HC_MAX_DOWNLOAD_GIB (positive integer required)" >&2
  exit 2
fi
srun --ntasks=1 --cpus-per-task=2 "$ROOT/.venv/bin/python" \
  "$ROOT/scripts/yoda_full.py" download --max-download-gib "$CAP_GIB"
echo "SUCCESS source transfer complete. Scientific G0 remains CLOSED pending hashes/licenses/content audit."
echo "SUMMARY $ROOT/results/full_yoda_download.json"
