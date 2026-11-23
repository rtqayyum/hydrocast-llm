"""Static safety gates for paths, Slurm resource selection and shared installation."""
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
expected = '/home/tariq.qayyum/hpc/hydrocast-llm'
slurm = (root / 'Batch').read_text()
boot = (root / 'scripts/bootstrap.sh').read_text()
checks = {
    'has_cpu_partition': bool(re.search(r'^#SBATCH --partition=longq$', slurm, re.M)),
    'no_gpu_allocation': '#SBATCH --gres=gpu:' not in slurm and '#SBATCH --gpus' not in slurm,
    'max_23hour_request': '#SBATCH --time=23:00:00' in slurm,
    'has_srun': bool(re.search(r'\bsrun\b', slurm)),
    'root_path_correct': f'ROOT={expected}' in slurm and f'ROOT={expected}' in boot,
    'logs_inside_project': f'{expected}/logs/%x_%j.out' in slurm and f'{expected}/logs/%x_%j.err' in slurm,
    'venv_local': ('"$ROOT/.venv/bin/activate"' in slurm and '"$ROOT/.venv"' in boot and 'register_local_source.py' in boot),
    'has_report': 'reports/PHASE0_AUDIT.md' in slurm,
    'no_shared_conda_write': not bool(re.search(r'(pip install|conda install|mkdir|touch|rm)\s+[^\n]*?/cm/shared/apps/anaconda3', slurm + boot)),
    'uses_project_tmpdir': 'TMPDIR="$ROOT/tmp"' in slurm,
    'has_failure_trap': 'trap ' in slurm,
    'has_resume_shards': 'outputs/audit/shards' in slurm,
}
summary = {'checks': checks, 'all_passed': all(checks.values())}
print(json.dumps(summary, indent=2))
if not summary['all_passed']:
    sys.exit(1)
