# SLC v1 model card (research, 2026-10-29)

**Model id:** `slc_v1_incomplete` (the engine's `MODEL_ID`; outputs carry the `_incomplete` label).
**Status:** research only. Not adopted, not deployed, not a forecast of record. The Week 8 2026 lock exists as a frozen artifact and
has no graded outcome yet.
**Scope:** NFL regular-season game simulation: play calling, outcomes, scoring and clock, from a pregame snapshot.

## What is connected

Each item is on by default unless marked as a flag.

| component | where | default |
|---|---|---|
| Score-clock play-call artifact (dropback versus run versus kick, by situation) | `slc_playcall.py`, `SLC-PLAYCALL-ARTIFACT-v1.json` | on |
| Trick throws (non-QB passer) and QB catches, at measured rates | `pre_event.py` (`TRICK_PASSER_RATE`, `QB_RECEIVER_RATE`) | on |
| Formation and personnel, with formation-conditioned outcomes | `formation_layer.py` | flag `--playcall-formation` |
| Team outcome splits | `team_tendency.py` | flag `--playcall-team-outcomes` |
| Team score-state splits | `point_splits.py` | flag `--playcall-point-splits` |
| Team and league win-loss streak splits (individual buckets, W5+ to L5+) | `streak_splits.py` | flags `--playcall-streak-splits`, `--playcall-streak-league` |
| Defensive coverage on dropbacks | `defense_layer.py` | flag `--playcall-coverage` |
| Exact yard line inside the 20 | `slc_playcall.py` | flag `--playcall-exact-yardline` |
| Player target and carry shares (observed prior-season shares) | `player_shares.py` | flag `--playcall-player-shares` |
| Per-game Dirichlet target and carry shares | `share_distributions.py` | flag `--playcall-dirichlet-shares` (implies player shares; off by default) |
| Decision model category A (target role), prior by situation | `target_roles.py` | flag `--playcall-target-roles` |
| Decision model categories A to N as labels, with the lifts and row filter | `decision_layer.py` | flag `--playcall-decision` (filter on by default) |
| Team and league win-loss record for display | `wl_streak.py` | display only, not a model input |

## What is not connected

- **Playbook layer.** The team playbook files (Gridiron Physics, 2025 season, 76 team-season files) are not an input. The
  categories they describe are the decision model's categories, and those are connected through the decision layer. The playbook
  files are not yet used as a separate cross-check.
- **External player-count distributions.** SLC has a separate per-game Dirichlet-multinomial share layer, fitted on prior-season
  nfl_pbp counts and drawn once per team and role. It is behind --playcall-dirichlet-shares and off by default. The external
  target-count Monte Carlo and zero-truncated negative-binomial carry-count models remain unported. The held-out check is in
  SLC-PLAYER-SHARE-VALIDATION-2026-10-29.md.
- **QB opportunity model.** A validation target only. It is a team-attempts decomposition (plays per game times pass propensity
  times QB share) from another branch. It is not an input to SLC.
- **Red-zone yardage.** The replay still gains about three yards fewer than actual on red-zone passes and two fewer on red-zone runs
  (`SLC-YARDS-REPLAY-2024-2026-10-29.md`). The exact yard-line draw closed about 30 percent of the trip gap earlier.
- **Out of v1 by design:** coaching, and physical movement.

## Evidence

Paired against score-clock SLC, same seeds, valid games only, CAR-GB Week 8 snapshot. Real regular-season totals were 45.8 (2024)
and 46.0 (2025).

| arm | seeds | margin diff | total diff |
|---|---:|---:|---:|
| coverage | 300 | +0.74 ± 0.97 | +1.26 ± 0.98 |
| streak, team (individual buckets) | 100 | -0.49 ± 0.72 | -0.49 ± 0.86 |
| streak, league (individual buckets) | 100 | +1.73 ± 1.60 | +2.15 ± 1.68 |
| decision labels, lifts only (vs player shares) | 100 | -3.24 ± 1.58 | +3.68 ± 1.63 |
| decision labels, lifts and row filter (vs player shares) | 100 | +3.25 ± 1.71 | +10.36 ± 1.68 |

Score-clock SLC itself totals about 40 points a game on this snapshot, under the real league total by about six. The lifts-and-filter
arm totals about 50, over by about four. The filter accounts for about +6.4 points of that uplift, from a selection effect. See
`SLC-DECISION-LAYER-UPLIFT-2026-10-29.md`. No arm here is a calibration to the real league total.

Player-share validation fits 2024 and scores 2025 on returning players with same-team history. The Dirichlet-multinomial improves
held-out log score by +4.30 per team-game for target counts and +5.54 for carry counts under the reported team-game bootstrap. It moves variance and zero
rates toward the observed values, while remaining underdispersed. On the same-source CAR-GB check, the fixed-share and Dirichlet
arms had identical team scores on all 99 paired valid seeds. The 2024 formation replay uses 229 of 256 eligible games and does not
establish a scoring change. See the two result reports for cohort rules and limitations.

## Holdout

2026 is the sealed holdout. No 2026 game outcome was used to fit, tune, or select any component. The decision prior is built from
the prior season only (2025 for a 2026 forecast). The Week 8 lock (`ad7e26d9`) was frozen before its games.

## Known issues

1. The row filter over-samples a subset of labelled rows, and the filtered layer totals about four points above the real league total.
2. Red-zone yardage remains short (see above).
3. Most evidence is one snapshot (CAR-GB) at 100 seeds. Margins carry about ±1.6 standard error per arm, so margin differences of
   this size are not team effects.
4. Some earlier arms ran on older code. Score-clock was rerun on current code (`score_clock_v2`) and matched the earlier totals exactly.
5. Pass length is taken from the nflverse play-by-play snapshot dated 2026-10-27, read only for seasons before the cutoff.
6. The 2024 scoring replay has only 89.5 percent game coverage, with missing snapshots concentrated in CIN.

## Intended use and limits

Research on play-calling and scoring structure. Not for betting, pricing, or public forecasts. It should not be presented as a
calibrated model of NFL games until the points, red-zone and row-filter issues above are resolved and the layers are tested on more
snapshots.

## Reproduce

`python3 scripts/nfl_sequence/simulate_pregame_batch.py --snapshot-file docs/research/slc-week8-2026/snapshots/2026_08_CAR_GB.json --playcall-artifact docs/research/SLC-PLAYCALL-ARTIFACT-v1.json --playcall-player-shares --playcall-decision --games 100 --seed-start 1 --out <json>`

Tests: `python3 -m unittest test_decision_layer test_participant_invariants test_pre_event test_slc_playcall test_player_shares test_streak_splits` (in `scripts/nfl_sequence`).
