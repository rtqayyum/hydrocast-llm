# HydroCast-LLM — HPC research starter (Phase 0)

**Status: CODE IS REAL; scientific training/results are NOT.** This release is a runnable,
resumable, standard-library-only dataset provenance and water-quality observation audit.
It deliberately does **not** claim to train Qwen, provide full daily weather, or establish
water-quality forecasting accuracy. GPU training is disabled until the full dataset,
leakage-safe splits, and competitive non-LLM baselines are independently validated.

## Research goal

Regime-aware cross-basin transfer for probabilistic river water-quality forecasting,
with censoring/missingness preservation and low-data adaptation. The full roadmap is in
`RESEARCH_ROADMAP.md`. Our first gate is the complete data census, not a synthetic paper result.

## Fixed HPC directory

`/home/tariq.qayyum/hpc/hydrocast-llm`

Your HPC guide contains two paths; we intentionally use **the more restrictive final
path** (`.../hpc/<PROJECT_NAME>/`) for *every* project path. The `Batch` file MUST be
at `/home/tariq.qayyum/hpc/hydrocast-llm/Batch`. Everything—virtual environment,
logs, data, temporary files, reports and checkpoints—is kept below that directory.
`Batch` is CPU-only (`longq`, 8 CPUs, 32 GB memory, 23 hours). No GPUs are requested.

## 1. On your Mac: extract and upload

After configuring `HYDROCAST_SSH_HOST` privately on your Mac:

```bash
cd ~/Downloads
git clone https://github.com/rtqayyum/hydrocast-llm.git
ssh tariq.qayyum@${HYDROCAST_SSH_HOST} 'mkdir -p /home/tariq.qayyum/hpc/hydrocast-llm/logs'
rsync -az --progress \
  --exclude='.git/' --exclude='.venv/' --exclude='.tools/' \
  --exclude='logs/' --exclude='results/' --exclude='outputs/' \
  --exclude='data/raw/' --exclude='checkpoints/' --exclude='cache/' \
  ~/Downloads/hydrocast-llm/ \
  tariq.qayyum@${HYDROCAST_SSH_HOST}:/home/tariq.qayyum/hpc/hydrocast-llm/
```

If cloning from your GitHub repository instead, clone **inside this same exact path**.
Do not combine with another research project's code or data.

## 2. On the HPC login node: bootstrap and fetch the *lite* pilot observations

```bash
ssh tariq.qayyum@${HYDROCAST_SSH_HOST}
cd /home/tariq.qayyum/hpc/hydrocast-llm
bash scripts/bootstrap.sh
# Phase 0 works with cluster Anaconda Python 3.9+; bootstrap registers
# src/ inside the project-local .venv so later CLI commands work directly.
# Requests ~641 MB compressed for wqms-csv.zip, plus small metadata.
# Uses Zenodo checksums and resumes partial HTTP downloads where supported.
# INTERNET ACCESS MAY BE BLOCKED on login nodes; if so, download on your Mac
# to ~/Downloads/hydrocast-lite and rsync those exact files into data/raw/lite/.
.venv/bin/python -m hydrocast.cli --root "$PWD" fetch-lite --observations
```

This fetches **water-quality observations and metadata only**, not the full release,
not daily meteorological forcing. The full dataset DOI is
<https://doi.org/10.24416/UU01-39ZXC4>. The lite archive comes from pinned
<https://zenodo.org/records/21337532>. We do not automate full release acquisition
until the actual file list, download conditions, and license constraints are confirmed.

If your login node cannot reach Zenodo, download its files using a browser on your Mac;
use the exact official file names and upload them with:

```bash
rsync -avP ~/Downloads/hydrocast-lite/ \
  tariq.qayyum@${HYDROCAST_SSH_HOST}:/home/tariq.qayyum/hpc/hydrocast-llm/data/raw/lite/
```

The HPC code reads the source ZIP in-place without loading the entire
water-quality observation corpus into memory. Each constituent produces its own resumable JSON and worker log.

## 3. Submit the CPU audit

```bash
ssh tariq.qayyum@${HYDROCAST_SSH_HOST}
cd /home/tariq.qayyum/hpc/hydrocast-llm
bash -n Batch
sbatch /home/tariq.qayyum/hpc/hydrocast-llm/Batch
```

**Copy the actual job ID printed by Slurm.** No job ID is available until you submit.
If the source ZIP is absent, Batch exits nonzero, preserving its partial report and
explaining why no real observations were audited. Each successful run is resumable:

```bash
sbatch /home/tariq.qayyum/hpc/hydrocast-llm/Batch
```

Completed constituent shards are checked against source size/mtime/ZIP CRC and
not recomputed. Never delete a shard from another project.

## 4. Monitor

```bash
squeue -u tariq.qayyum
sacct -j <JOB_ID> --format=JobID,JobName,State,ExitCode,Elapsed,MaxRSS,AllocTRES%30
sstat -j <JOB_ID>.batch --format=JobID,AveCPU,MaxRSS,MaxVMSize
# One line for each completed constituent (100 expected if all available):
find /home/tariq.qayyum/hpc/hydrocast-llm/outputs/audit/shards -name '*.json' | wc -l
# Worker errors and detailed per-constituent logs:
grep -RniE 'error|fatal|failed|traceback|oom|killed|timeout' /home/tariq.qayyum/hpc/hydrocast-llm/logs/ || true
grep -E 'PROGRESS|ERROR|REPORT|SUMMARY|SUCCESS' /home/tariq.qayyum/hpc/hydrocast-llm/logs/hc_phase0_<JOB_ID>.out | tail -30
# Slurm worker-level CPU usage and memory if supported by cluster job accounting:
sstat -j <JOB_ID>.batch --format=JobID,AveCPU,MaxRSS,MaxVMSize
```

Additional cluster/accounting commands (live after submission):

```bash
tail -f /home/tariq.qayyum/hpc/hydrocast-llm/logs/hc_phase0_<JOB_ID>.out
tail -f /home/tariq.qayyum/hpc/hydrocast-llm/logs/hc_phase0_<JOB_ID>.err
```

## 5. Results

- `reports/PHASE0_AUDIT.md`: human-readable observations-by-constituent report.
- `results/phase0_summary.json`: machine-readable status, counts, gaps and blockers.
- `results/preflight.json`: project-local path/environment checks.
- `outputs/audit/progress.json`: current worker progress (machine-readable).
- `outputs/audit/shards/*.json`: completed shards, safe to reuse.
- `logs/workers/*.log`: separate per-constituent worker logs.
- `results/last_job_failure.json`: job wrapper failure status, when applicable.

All paths above are relative to the fixed HPC root.

## 6. Full release gate (not auto-passed)

The full release including daily meteorological forcing requires an independent
inventory and source-specific license review. Only after the real data are locally
present, record them with path, SHA256, scientific role and license in
`data_manifest/FULL_ARCHIVE_MANIFEST.csv`. Record a signed-off review in
`data_manifest/LICENSE_REVIEW.json` (examples supplied). The audit verifies the
hashes and presence of critical roles. That flag is a **necessary but not sufficient**
condition for model training; observation eligibility and scientific leakage tests
still have to be completed. Never relabel the lite archive as full.

## GitHub repository and privacy

The source repository is `rtqayyum/hydrocast-llm`. Its current visibility is
**public**. Do not commit university HPC login IPs, passwords, tokens, raw source
data, licensed material, or runtime outputs. The host is intentionally specified
only through `HYDROCAST_SSH_HOST` on the user's machine; set it to the cluster
address before using the SSH/rsync examples. This variable is not committed.

For future code updates, run `git pull --ff-only` in the project root on HPC.

## Test on a laptop or login node

```bash
cd /path/to/hydrocast-llm
bash scripts/validate_local.sh
```

Unit tests use tiny **synthetic fixtures** solely for software correctness. They
never appear in the scientific report or get interpreted as observations.

### One-time publication from Mac (GitHub CLI)

After extracting the bundle, sign in to the GitHub CLI with your own account
and publish this **dedicated private** repository; never force-push another
repository and never commit data/results.

```bash
cd ~/Downloads/hydrocast-llm
gh auth login
git init -b main
git add .
git commit -m "Initialize HydroCast Phase 0 audit and HPC Slurm entrypoint"
gh repo create rtqayyum/hydrocast-llm --private --source=. --remote=origin --push
```

If `gh` is unavailable, create `rtqayyum/hydrocast-llm` at
<https://github.com/new>, then use:

```bash
cd ~/Downloads/hydrocast-llm
git init -b main
git add .
git commit -m "Initialize HydroCast Phase 0 audit and HPC Slurm entrypoint"
git remote add origin https://github.com/rtqayyum/hydrocast-llm.git
git push -u origin main
```

If the repository already exists, inspect it before using these commands.
No GitHub repository is created by the HPC `Batch` job.
