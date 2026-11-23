# HydroCast-LLM — one-page HPC checklist

Use **only** `/home/tariq.qayyum/hpc/hydrocast-llm` on the cluster.

Set `HYDROCAST_SSH_HOST` to the cluster address privately on your Mac before running the SSH examples. The public repository intentionally excludes the internal IP.

## Step A: move code from Mac

```bash
cd ~/Downloads
git clone https://github.com/rtqayyum/hydrocast-llm.git
ssh tariq.qayyum@${HYDROCAST_SSH_HOST} 'mkdir -p /home/tariq.qayyum/hpc/hydrocast-llm/logs'
rsync -az --progress --exclude='.git/' --exclude='.venv/' \
 --exclude='logs/' --exclude='results/' --exclude='outputs/' \
 --exclude='data/raw/' --exclude='checkpoints/' --exclude='cache/' \
 ~/Downloads/hydrocast-llm/ \
 tariq.qayyum@${HYDROCAST_SSH_HOST}:/home/tariq.qayyum/hpc/hydrocast-llm/
```

## Step B: bootstrap and obtain lite pilot source

```bash
ssh tariq.qayyum@${HYDROCAST_SSH_HOST}
cd /home/tariq.qayyum/hpc/hydrocast-llm
bash scripts/bootstrap.sh
# Confirm the local package works after PYTHONPATH is removed:
env -u PYTHONPATH .venv/bin/python -m hydrocast.cli --root "$PWD" preflight
.venv/bin/python -m hydrocast.cli --root "$PWD" fetch-lite --observations
```

This downloads the checked *lite* observation CSV ZIP + metadata for auditing.
For scientific global training we still need the **full** archive including daily
weather and its verified license inventory.

## Step C: submit

```bash
cd /home/tariq.qayyum/hpc/hydrocast-llm
bash -n Batch
scontrol show partition longq | grep -Ei 'PartitionName|MaxTime|State'
sbatch /home/tariq.qayyum/hpc/hydrocast-llm/Batch
```

The second line shows the real queue time limit. If it is below 23:00:00,
adjust `#SBATCH --time=` before submitting; avoid silently exceeding partition MaxTime.

**Allocation:** CPU only: `longq`, 1 Slurm task using up to 8 CPUs in a
local process pool, 32 GiB requested RAM, 23-hour time limit, **0 GPUs**.
A 2×H100 training job will be a separate later phase after data and baselines.

## Step D: monitor (replace 123456 with actual job number)

```bash
squeue -u tariq.qayyum
sacct -j 123456 --format=JobID,JobName,State,ExitCode,Elapsed,MaxRSS,AllocTRES%30
sstat -j 123456.batch --format=JobID,AveCPU,MaxRSS,MaxVMSize
tail -f /home/tariq.qayyum/hpc/hydrocast-llm/logs/hc_phase0_123456.out
tail -f /home/tariq.qayyum/hpc/hydrocast-llm/logs/hc_phase0_123456.err
find /home/tariq.qayyum/hpc/hydrocast-llm/outputs/audit/shards -name '*.json' | wc -l
grep -E 'PROGRESS|ERROR|REPORT|SUMMARY' /home/tariq.qayyum/hpc/hydrocast-llm/logs/hc_phase0_123456.out | tail -30
grep -RniE 'error|fatal|failed|traceback|oom|killed|timeout' /home/tariq.qayyum/hpc/hydrocast-llm/logs/ || true
```

## Step E: results and recovery

- Report: `reports/PHASE0_AUDIT.md`
- JSON: `results/phase0_summary.json`
- Progress: `outputs/audit/progress.json`
- Worker logs: `logs/workers/*.log`
- Completed constituent shards: `outputs/audit/shards/*.json`
- Experiments trained at this stage: **0**

If a job fails, fix its error and rerun:

```bash
cd /home/tariq.qayyum/hpc/hydrocast-llm
sbatch /home/tariq.qayyum/hpc/hydrocast-llm/Batch
```

No completed shard is overwritten when source fingerprints match.

## Phase 0b: station support screen (after successful Phase 0)

```bash
cd /home/tariq.qayyum/hpc/hydrocast-llm
git pull --ff-only origin main
bash scripts/bootstrap.sh
bash -n hpc/01_screen.sbatch
sbatch /home/tariq.qayyum/hpc/hydrocast-llm/hpc/01_screen.sbatch
```

Requested: `longq`, 4 CPUs, 32 GB RAM, 23 hours, zero GPUs.
This only counts training-only *candidate* stations, not valid forecast pairs.
The output is `reports/PHASE0B_STATION_SUPPORT.md` with JSON
`results/phase0b_summary.json`. Progress is in `outputs/screen/progress.json`,
worker logs are `logs/workers/screen_*.log`, and Slurm logs are
`logs/hc_screen_<JOB_ID>.out` and `.err`. Re-submit after correcting failures;
completed shards are reused. Never commit or publish raw data or job logs.

## Phase 0c: Full archive access check

The official full Caravan-Qual release (daily weather) is hosted at
https://doi.org/10.24416/UU01-39ZXC4. Use this metadata-only test:

```bash
cd /home/tariq.qayyum/hpc/hydrocast-llm
git pull --ff-only origin main
bash scripts/bootstrap.sh
.venv/bin/python scripts/probe_full_archive.py
cat reports/FULL_ARCHIVE_ACCESS.md
df -h .
quota -s 2>/dev/null || true
```

No GPU, no large transfer, and no dataset claims. Output:
`results/full_archive_probe.json`, `reports/FULL_ARCHIVE_ACCESS.md`,
and if reachable, `outputs/full_probe/landing.html`. Disk free space
reported by the probe is *not* your university quota. If access fails or the
file links are JavaScript-generated, inspect the official DOI in a browser and
supply real download file links before adding the full-release downloader.
