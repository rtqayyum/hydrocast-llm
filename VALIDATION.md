# Local validation log — 23 November 2026

The following checks were run in the assistant's temporary sandbox. They are
**not university HPC execution** and do not prove Zenodo/Utrecht downloads work
from the university network.

- `bash -n` on `Batch` and setup shell scripts — passed.
- `python -m py_compile` for all project source and tests — passed.
- Five stdlib `unittest` tests using **tiny synthetic CSV fixtures** — passed.
- Synthetic fixture exercises observed, left-censored, non-detect and other
  flagged rows, missing values, per-constituent ZIP ingestion, resume logic,
  missing-source failure, schema failure, and symlink-root escape protection.
- Static safety checks — passed: no GPUs requested, local venv, fixed output
  root, 23-hour resource line, project-local temp and logs, failure trap.

**Not tested:** HPC SSH, Slurm submission / queue MaxTime / account limits,
cluster modules, installed Python version, network download speed or limits,
full Utrecht release contents, 96-million-row throughput, licenses, and all
model-training or scientific claims.
