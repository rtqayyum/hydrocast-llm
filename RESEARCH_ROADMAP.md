# Research roadmap and hard go/no-go gates

This is an implementation plan, not a claim that experiments were run.

| Gate | Requirement | Current status |
| --- | --- | --- |
| G0 | Full Caravan-Qual files with DAILY ERA5-Land weather, checksums, licenses, site metadata | NOT VERIFIED |
| G1 | Exact per-constituent and basin forecast-pair eligibility from observed target dates | NOT STARTED |
| G2 | Locked chrono × basin folds, source deduplication, strict future-weather policy, strong XGBoost and LSTM baselines | NOT STARTED |
| G3 | Pretrained Qwen versus no-LLM, random-transformer, frozen-LLM, and equal-compute controls | NOT STARTED |
| G4 | Regime-conditioning, censoring-aware likelihood, and low-data adaptation ablations | NOT STARTED |
| G5 | External held-out-source replication, catchment-level CIs and calibrated event detection | NOT STARTED |

## Proposed training after G0–G2

- S1: a global Qwen2.5 1.5B/3B pretrained base checkpoint with *all parameters*
  trainable, plus a causal numeric encoder and calibrated output heads. Adapt
  the **same global checkpoint** using a preregistered historical support set.
- S2: global checkpoint, no target-specific updates; excludes held-out region labels.
- S3: trained on target region historical slice only, with matched architecture.
- S4: strictly unseen region (no water-quality supervision) and no adaptation.
- S5: S4 plus 1/5/10/20% historical target records, future test dates untouched.

### Three proposed innovations

1. Regime-aware gate: learned soft hydrological regime conditioning from *past*
   flow, rainfall and catchment features, not labels from future/test data.
2. Censoring-aware probabilistic target head: use the left-censor event
   `P(Y <= detection_limit)`, rather than the pre-imputed `obs` value as an
   exact concentration.
3. Data-efficient site/region adaptation: historical support only; keep a
   zero-shot control, an encoder-only control and adapter ablations.

### Mandatory baseline challenge

Persistence/seasonal climatology, generalized additive/seasonal regression,
XGBoost, LSTM/GRU-D/TCN, PatchTST, and an identical numeric encoder with no
language-model backbone. Qwen is not assumed to add value.

### No leaked future inputs

- All training targets must have an actually observed future timestamp.
- Observed water quality and hydrometeorology after origin `t` cannot be used.
- Realized future meteorology is banned from the operational forecast input.
- If issued forecasts are unavailable, use history-only; label any diagnostic
  using future realized weather as non-deployable oracle.
- Fit scaling on training partitions only, group spatially connected basins,
  and keep ambiguous aliases out of cross-fold comparisons.

## GPU stage

**NOT ENABLED.** Once G2 is documented, add a *separate* Slurm training entrypoint
requesting `--partition=gpuq` and `--gres=gpu:2`, only after verifying GPU queue
`MaxTime`, both H100 allocations and GPU VRAM on the actual HPC cluster.
Do not turn the current CPU `Batch` into a GPU job.
