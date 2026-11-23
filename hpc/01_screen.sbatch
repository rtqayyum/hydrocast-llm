#!/usr/bin/env bash
#SBATCH --job-name=hc_screen
#SBATCH --partition=longq
#SBATCH --time=23:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --output=/home/tariq.qayyum/hpc/hydrocast-llm/logs/%x_%j.out
#SBATCH --error=/home/tariq.qayyum/hpc/hydrocast-llm/logs/%x_%j.err
set -Eeuo pipefail
ROOT=/home/tariq.qayyum/hpc/hydrocast-llm
cd "$ROOT"
mkdir -p "$ROOT"/{logs,logs/workers,results,reports,outputs/screen/shards,tmp,cache}
export HYDROCAST_ROOT="$ROOT" HYDROCAST_EXPECTED_ROOT="$ROOT"
export TMPDIR="$ROOT/tmp" TMP="$ROOT/tmp" TEMP="$ROOT/tmp" XDG_CACHE_HOME="$ROOT/cache"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
failure() { rc="$1"; printf '{"status":"failed","exit_code":%s,"job_id":"%s"}\n' "$rc" "\${SLURM_JOB_ID:-unknown}" > "$ROOT/results/phase0b_failure.json"; exit "$rc"; }
trap 'failure "$?"' ERR
if ! type module >/dev/null 2>&1 && [[ -f /etc/profile.d/modules.sh ]]; then
  source /etc/profile.d/modules.sh
fi
module load anaconda3
bash "$ROOT/scripts/bootstrap.sh"
unset PYTHONPATH
srun --ntasks=1 --cpus-per-task="\${SLURM_CPUS_PER_TASK:-4}" \
  "$ROOT/.venv/bin/python" -m hydrocast.cli --root "$ROOT" screen --workers "\${SLURM_CPUS_PER_TASK:-4}"
echo "SUCCESS Phase 0b station support screen finished; no model trained."
echo "REPORT $ROOT/reports/PHASE0B_STATION_SUPPORT.md"
