# PR #47 validation run report

**Date:** 2026-11-15  
**Branch under validation:** `2ebd051e064643c6a5a9137ed163214b59919db0`  
**Fast-host output directory:** `/root/ot-sim-out/v17-pr47-validation-2026-11-15`

## Outcome

- The exact 47 seeds preserved from the original `v1.7-1000-pr43` failure set were replayed on the PR #47 code. The strict verifier passed: **47/47 mechanically valid full games**, zero remaining failures, zero blocked-before-regulation games. The replay kept `research_release_approval=false`, as required for the research-only penalty model.
- A separate fresh batch used seeds **20262112–20263111**, disjoint from the original 1,000-seed range. It was stopped at the user's request after **576 seeds** had completed. The last ledger record was seed `20262687`, status `complete_regulation`. The last logged checkpoint was 550/1,000 with zero errors. No final aggregate report was produced; the partial seed and box-score ledgers remain on the fast host.
- **PR #47's 1,000-seed gate is incomplete.**

## Inputs and procedure

Both PR #47 runs used the frozen WAS–NYG snapshot and fast-host database, the V1.7 candidate profile, conditional pass labels, the pinned play-call artifact and streak file, the fitted penalty model and its fit/source manifests, research-only penalty rulings, and the five pinned blocker fixes. The original materialized history cache was rejected because its classifier predated PR #47; a separate cache was rebuilt from the frozen database under PR #47 code. The original cache and source run were left untouched.

The targeted run used `--games 47` and the committed `failed-seeds.json` seed list. The fresh run used `--games 1000 --seed-start 20262112`. Both exported box scores to new output files.

Both simulator invocations used the following shared inputs and settings (with separate output paths):

```bash
PYTHONPATH=scripts/nfl_sequence /usr/bin/python3 scripts/nfl_sequence/simulate_pregame_batch.py \
  --snapshot-file /root/slc-was-nyg-tnf-2026-11-12-final-0013Z/snapshot.json \
  --db /root/legendarypicks/backend/data/picks.dev.db \
  --slc-profile v1_7_candidate \
  --playcall-artifact docs/research/SLC-PLAYCALL-ARTIFACT-v1.json \
  --playcall-streak-file /root/slc-was-nyg-tnf-2026-11-12-final-0013Z/run-inputs/wl-streaks-through-week9.json \
  --slc-materialized-history /root/ot-sim-out/v17-pr47-validation-2026-11-15/slc-history-v17-pr47.sqlite \
  --playcall-pass-label-mode conditional \
  --slc-penalty-model docs/research/slc-v17-penalty-fit-2026-11-13/model.json \
  --slc-penalty-manifest docs/research/slc-v17-penalty-fit-2026-11-13/fit-manifest.json \
  --slc-penalty-source-manifest docs/research/slc-v17-penalty-fit-2026-11-13/source-manifest.json \
  --slc-penalty-ruling-policy research \
  --slc-blocker-fix run_scramble_backoff \
  --slc-blocker-fix long_field_goal_feasibility \
  --slc-blocker-fix blocked_kick_source_audit \
  --slc-blocker-fix blocked_kick_geometry \
  --slc-blocker-fix safety_free_kick_boundaries \
  [seed-count-and-selection-options] \
  --progress-every [10 for the 47-seed replay; 50 for the fresh batch] \
  --export-boxscores \
  --out [new report path]
```

For the targeted replay, `[seed-count-and-selection-options]` were `--games 47 --seed-list-file docs/research/slc-v17-failure-repairs-2026-11-13/failed-seeds.json`. For the fresh batch they were `--games 1000 --seed-start 20262112`. The run used `nice` and CPU affinity on the fast host; the fresh batch was stopped with `kill` after the user requested stopping it.

The strict audit command was:

```bash
PYTHONPATH=scripts/nfl_sequence /usr/bin/python3 scripts/nfl_sequence/verify_v17_seed_repairs.py \
  --failed-seeds docs/research/slc-v17-failure-repairs-2026-11-13/failed-seeds.json \
  --replay-report /root/ot-sim-out/v17-pr47-validation-2026-11-15/was-nyg-v17-repair-47.json \
  --audit-out /root/ot-sim-out/v17-pr47-validation-2026-11-15/was-nyg-v17-repair-47-audit.json
```

## Verification

- PR #47 focused regression suite: **10 tests passed**.
- PR #47 regression command: `PYTHONPATH=scripts/nfl_sequence /usr/bin/python3 -m unittest scripts.nfl_sequence.test_penalty_v17_failure_repairs -v`.
- Strict saved-result verifier: **passed**, with `failed_seeds=[]`, `still_failing=0`, and `mechanically_verified_full_games=47`.
- The verifier recorded source snapshot SHA-256 `144bed3f807aff2d3c3fd7c12045413d48be13370c1d8aa1e132fa4aa6d9023f`, matching the frozen source snapshot.

## Artifacts

Fast-host artifacts:

- Exact 47-seed replay: `was-nyg-v17-repair-47.json`
- Strict verifier audit: `was-nyg-v17-repair-47-audit.json`
- Exact replay log: `was-nyg-v17-repair-47.log`
- Fresh batch partial ledger: `was-nyg-v17-repair-fresh-1000.seeds.jsonl`
- Fresh batch partial box scores: `was-nyg-v17-repair-fresh-1000.boxscores.jsonl`
- Fresh batch log: `was-nyg-v17-repair-fresh-1000.log`

All are under `/root/ot-sim-out/v17-pr47-validation-2026-11-15` on the fast host. The fresh batch has no completed summary JSON because it was stopped before reaching 1,000 seeds.

## PR #44 work in the same session

- Compiled the replay/model entrypoints and ran the PR #44 test suite: **9 tests passed**.
- PR #44 test command: `PYTHONPATH=backend /usr/bin/python3 -m unittest -v test_replay_was_nyg_player_models`.
- The requested 4,000-draw replay was started, then stopped at the user's direction before producing replay outputs. No 4,000-draw results were reviewed or included.
- PR #44 was merged into `slc-v2` as merge commit `96b04030bbb1a17bc8a856e21f22625c4c40aea6`.
