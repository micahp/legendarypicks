# SLC Week 8 execution and calibration handoff

- **Prepared:** 2026-10-29
- **Checkout:** `/root/lp-slc-preevent`
- **Branch:** `research/slc-decision-layer-2026-10-29`
- **Branch HEAD:** `5e6c8de15edffe6aeee983ee0b643b976f188b02`; remote matched at inspection.
- **Base commit:** `5e6c8de15edffe6aeee983ee0b643b976f188b02`; the pushed branch matched this commit when this change set was reviewed.
- **Run status:** the all-layer execution smoke and corrected exact-yardline paired replay completed. Hermes2 resumed the Week 8 10K work through tmux pane `shell:0.0` after the exact result was saved. No production promotion or deployment was performed.
- **Current calibration verdict:** no full-stack calibration. See [layer calibration audit](research/SLC-LAYER-CALIBRATION-AUDIT-2026-10-29.md).

## What the latest evidence says

- The corrected 2024 red-zone replay finds 3.294 trips per team-game in SLC and 3.311 actual; the interval includes zero. Conversion is low (0.495 versus 0.583 touchdowns per trip) and red-zone play volume is high (10.350 versus 9.669 plays per team-game). Do not report a red-zone trip deficit.
- The 2025 replay has about 10% too many scrimmage plays. This remains a system-level blocker for scoring, possession and player-volume calibration.
- The 2024-fit/2025-held-out Dirichlet-multinomial share model improves joint log scores by 4.303 targets and 5.543 carries per team-game on returning players with same-team history. Zero rates and lower/median count quantiles remain miscalibrated.
- Receiver-conditioned event and completion-result scores improve on the 2025 holdout. QB target-role and completion-result scores regress; rushing results are inconclusive.
- Team outcomes, formation, coverage, playbook, point and streak results are small exploratory paired runs. They do not establish calibrated team scores or winner probabilities.
- The old exact-yardline claim is invalid: its trip definition, touchdown classification and incomplete-seed handling were inconsistent. The corrected replay completed with 228 matched game clusters, 433 common game-seed pairs, 442 complete game-seeds and 16 incomplete seeds per arm, and zero engine errors. Exact-minus-default was +0.043 touchdowns per trip [0.018, 0.067] and -0.728 red-zone plays per team-game [-1.037, -0.422]. Exact conversion remains 0.537 versus 0.583 actual; play volume is 9.578 versus 9.669 actual. Intervals use 10,000 game-cluster resamples and omit separate seed uncertainty. Full result: `/tmp/lp-slc-week8-10k-20261029/SLC-SCORING-REDZONE-EXACT-YARDLINE-CALIBRATION-2024.json`, 909,437 bytes, SHA-256 `f09d79a77a3e02d190e84017756dcdeffd6b7d42ce9a84e6dfa0e849b13c0109`; log: `/tmp/lp-slc-week8-10k-20261029/logs/exact-yardline-2024.log`.
- No target CAR–GB game outcome was read. The current-streak input uses only games before the frozen Week 8 cutoff. All fitted SLC sources in the smoke are cut before 2026 Week 1.

## Executable engine evidence

The batch runner completed seed 1 on the frozen `2026_08_CAR_GB` snapshot with every available SLC feature enabled: one complete regulation game, 150 decisions, no blocked game and no simulation/validation errors. The output labels all 17 feature booleans as enabled and records source cutoffs, model versions, input hashes and integration-code hashes.

- Output: [all-layer engine smoke](research/SLC-ALL-LAYERS-ENGINE-SMOKE-2026_08_CAR_GB-2026-10-29.json)
- Seed ledger: [smoke seed ledger](research/SLC-ALL-LAYERS-ENGINE-SMOKE-2026_08_CAR_GB-2026-10-29.seeds.jsonl)
- Frozen snapshot SHA-256: `35a295d98022e5b5ec9ac0fded4bbe04cf94e50c962cd8da6d6e2c1a4a2f6e77`
- Observed reference SHA-256: `0f793fd0edf5c20f8c1d00aeaa5782b7069b2acc8b2d01150f32f65fe223b6a6`
- Play-call artifact identity SHA-256: `27c02afd6d9f6f80a38b3bc7ae278b1efebcc7caa5664688c64c55bc0c698ac7`
- Pregame streak input SHA-256: `691c7d4a5b66ca7e9f7e5643571e0df8da89fa36084a0273ea286b4fe7cf0b50`
- Smoke output SHA-256: `4fee19c6809ce7dc1918f496ddab47b5d92a9c33c9ce9113995409a90f927bb4`
- Seed ledger SHA-256: `81201706895db916962df32db8e20237e8b2b1a5724ca81f0f4f8a7fb03df33b`

The saved smoke JSON was produced before the reproduction-command fix. The batch runner now emits a shell-quoted command with the actual snapshot, DB, policy artifact, optional model flags, caches and roster inputs. The command below reconstructs the smoke configuration under the current checkout.

```bash
/root/legendarypicks/backend/venv/bin/python scripts/nfl_sequence/simulate_pregame_batch.py \
  --snapshot-file docs/research/slc-week8-2026/snapshots/2026_08_CAR_GB.json \
  --db /root/legendarypicks/backend/data/picks.dev.db \
  --games 1 --seed-start 1 \
  --playcall-artifact docs/research/SLC-PLAYCALL-ARTIFACT-v1.json \
  --playcall-team-outcomes --playcall-formation --playcall-coverage \
  --playcall-dirichlet-shares --playcall-qb-decisions --playcall-player-outcomes \
  --playcall-target-roles --playcall-decision --playcall-playbook \
  --playcall-point-splits --playcall-streak-splits --playcall-streak-league \
  --playcall-streak-file docs/research/SLC-STREAK-PREGAME-2026_08_CAR_GB-2026-10-29.json \
  --playcall-exact-yardline --progress-every 0 \
  --out /tmp/slc-all-layers-replay.json
```

With `--playcall-decision`, the row filter is enabled unless `--playcall-decision-unfiltered` is supplied. Keep the filter as a separate ablation. The 100-seed CAR–GB comparison attributed +6.39 ± 1.78 total points to the filter by itself; this uplift is not evidence of better player modeling.

## Week 8 10K command

The existing Week 8 directory contains multiple games. This command uses CAR–GB, the snapshot already used by the smoke. A 10K run describes the distribution for these frozen inputs; it does **not** calibrate the model. Run the three-arm and per-layer comparisons separately for calibration.

Before a large run, execute a 100-seed pilot, check the finished/valid/error counts and all roster/outcome traces, then measure runtime. Immediately before the 10K run, check `uptime` and `free -h`; use one process and do not start if available memory is below 1.5 GiB. Keep outputs in a new research directory, preserve blocked and failed seeds, and do not overwrite prior artifacts.

```bash
/root/legendarypicks/backend/venv/bin/python scripts/nfl_sequence/simulate_pregame_batch.py \
  --snapshot-file docs/research/slc-week8-2026/snapshots/2026_08_CAR_GB.json \
  --db /root/legendarypicks/backend/data/picks.dev.db \
  --games 10000 --seed-start 1 \
  --playcall-artifact docs/research/SLC-PLAYCALL-ARTIFACT-v1.json \
  --playcall-team-outcomes --playcall-formation --playcall-coverage \
  --playcall-dirichlet-shares --playcall-qb-decisions --playcall-player-outcomes \
  --playcall-target-roles --playcall-decision --playcall-playbook \
  --playcall-point-splits --playcall-streak-splits --playcall-streak-league \
  --playcall-streak-file docs/research/SLC-STREAK-PREGAME-2026_08_CAR_GB-2026-10-29.json \
  --playcall-exact-yardline --progress-every 100 \
  --out docs/research/slc-week8-2026/all-layers-10k/2026_08_CAR_GB.json
```

Use the same seed IDs and frozen inputs for pooled score-clock, team-conditioned, player-conditioned and all-layer arms. Report the decision-filter-on and decision-filter-off arms separately. Do not claim a layer improves from the full-stack result alone.

## Live Week 8 run configuration check

The resumed 7-job batch was launched with pooled and team-conditioned controls, plus a `full-player-stack` arm. The shell-pane resumer currently enables team outcomes, formation, coverage, Dirichlet shares, QB decisions and player-conditioned outcomes. It omits target-role priors, decision labels and filter, playbook priors, point splits, team and league streak splits, the current-streak input, and exact-yardline outcomes. The active batch therefore does not match the all-layer command above. Preserve its existing ledgers and logs; do not describe those outputs as the all-layer forecast. Hermes2 has been asked to preserve the running jobs and report the least disruptive path to the requested full-layer configuration.

## Calibration order

1. **Pace and game mechanics:** resolve the excess plays through clock stoppages, drives, possession changes and game duration. Recheck plays and possessions against the same historical cohort.
2. **Red-zone outcomes:** finish the matched exact-yardline comparison, then isolate yards, touchdowns, field goals, turnovers and fourth-down decisions on the same games and seeds.
3. **Conditional outcome layers:** compare team offense/defense, formation/personnel and coverage against pooled and team-conditioned baselines on chronological holdouts.
4. **Decision priors:** validate target-role, QB, decision labels and playbook separately. Tune the decision row filter independently because it changes outcome selection sharply.
5. **Player distributions:** retain the positive share-model log-score result, but correct zero rates and count quantiles and include new players, transfers and frozen-roster eligibility in the scored cohort.
6. **Full-game calibration:** after the preceding gates pass, evaluate score, win/tie, player-stat distributions and prediction scores on a held-out season with game-cluster uncertainty.

For every comparison, record the exact source cutoff, model version, artifact/input/code hashes, paired seed ledger, matched-game population and valid-game coverage. The current 2024 and 2025 historical replays lack row-level publication timestamps and remain exploratory rather than verified point-in-time backtests.

## Current local changes

This change set includes the corrected red-zone diagnostic and report, updated model/context documents, layer-calibration audit, engine manifest and runner wiring, and the completed paired exact-yardline comparison. The raw exact-yardline artifact remains on the faster host and is identified by its path and SHA-256 above. Coaching tendencies remain separate research and are not part of the executable SLC layer set.
