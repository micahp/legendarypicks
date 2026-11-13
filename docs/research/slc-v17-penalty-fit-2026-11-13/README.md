# V1.7 fitted penalty proposal layer

This directory contains the first **research-only** penalty fit, its fit and
source manifests, and historical holdout scores. The model was fitted on 9,614
retained 2021–2024 opportunities. It is not release validated: official-match
coverage is outcome-dependent and the 2025 pre-snap calibration gap is
material. See [the fit report](../SLC-V1.7-FIRST-PENALTY-FIT-2026-11-13.md).

`PenaltySampler.from_artifacts` loads the fitted model into the V1.7 proposal
layer, verifies the canonical model hash, source-manifest SHA-256, fit metadata
and training cutoff, and returns an enabled sampler. These checks establish
artifact consistency; they do not establish that a retrospective source was
available point-in-time, nor that the model is calibrated. Its dedicated RNG
stream leaves the V1.6 generator's RNG untouched.

Run an isolated proposal:

```bash
python3 scripts/nfl_sequence/run_penalty_layer.py \
  --as-of-utc 2026-11-13T00:00:00Z --season 2026 \
  --offense WAS --defense NYG --down 2 --to-go 8 --yardline-100 60 \
  --phase pre_snap --play-class pre_snap --seed 460 --opportunity-key demo-play-1
```

For this fitted artifact and seed, the proposal is `offense:false_start`. The
bounded `penalty_transition.transition` API can enforce that proposal given an
explicit accepted ruling: second-and-8 at the offense's 40 becomes
second-and-13 at its 35. The focused test exercises the real fitted artifact
through proposal and enforcement.

**This is not a full-game penalty model.** The proposal layer is not wired into
full-game transitions; acceptance, clock handling, statistics and unsupported
fouls are not complete. A penalty-enabled V1.7 forecast must not be claimed on
the basis of this isolated proposal. The source and fit manifests are retained
as generated and may include paths from the machine that produced the fit;
the files are identified by hashes, not by those paths.
