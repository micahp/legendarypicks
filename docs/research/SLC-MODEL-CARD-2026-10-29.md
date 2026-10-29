# SLC v1 model card (research, 2026-10-29)

**Model id:** `slc_v1_incomplete` (the engine's `MODEL_ID`; outputs carry the `_incomplete` label).
Optional research IDs: `slc_v1_qb_decisions_research`, `slc_v1_player_outcomes_research`, and
`slc_v1_qb_decisions_player_outcomes_research`.
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
| Team playbook priors for pass depth, pass location and run gap | `playbook_prior.py` | flag `--playcall-playbook` (requires decision layer; off by default) |
| Decision model category A (target role), prior by situation | `target_roles.py` | flag `--playcall-target-roles` |
| Decision model categories A to N as labels, with the lifts and row filter | `decision_layer.py` | flag `--playcall-decision` (filter on by default) |
| QB action and target-role decisions, keyed by QB, team and situation | `qb_decisions.py`, `pre_event.py`, `slc_playcall.py` | `--playcall-qb-decisions` or `--qb-decisions`; off |
| Player-conditioned event and result distributions for the selected passer, receiver and rusher | `player_outcomes.py`, `slc_playcall.py`, `game_stats.py` | `--playcall-player-outcomes` or `--player-outcomes`; off |
| Team and league win-loss record for display | `wl_streak.py` | display only, not a model input |

## What is not connected

- **External player-count distributions.** SLC has a separate per-game Dirichlet-multinomial share layer, fitted on prior-season
  nfl_pbp counts and drawn once per team and role. It is behind --playcall-dirichlet-shares and off by default. The external
  target-count Monte Carlo and zero-truncated negative-binomial carry-count models remain unported. The held-out check is in
  SLC-PLAYER-SHARE-VALIDATION-2026-10-29.md.
- **External QB opportunity model.** A validation target only. It is a team-attempts decomposition (plays per game times pass
  propensity times QB share) from another branch. It is not an input to SLC. The in-play QB decision slice is separate and limited
  to scramble propensity and target-role selection.
- **Full player-conditioned sequence.** The first QB decision and player event/result distributions are wired into the single-game
  and batch runners, but remain experimental and off by default. The QB model does not cover progressions, throwaways, pressure
  response or defensive adaptation. The outcome model uses marginal player distributions with clipped likelihood ratios; the joint
  passer-receiver model and full-game calibration remain open.
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

Player-share validation fits 2024 and scores 2025 on returning players with same-team history (506 receiver and 332 carry player-team
units). The Dirichlet-multinomial improves held-out log score by +4.30 per team-game for target counts and +5.54 for carry counts,
with uncertainty resampled by NFL game. Predicted variance and zero rates move closer to observed values, but lower and median count
quantiles remain too low. On the same-source CAR-GB check, per-player target and carry counts
changed on all 99 paired valid seeds while team scores stayed identical. The matched playbook input changed mean total points by
-0.86 (SE 1.76) and home margin by -0.47 (SE 1.80) across 98 paired seeds; this single-matchup result does not establish a scoring
effect. The 2024 formation replay uses 229 of 256 eligible games and does not establish a scoring change. See the result reports for
cohort rules and limits.

The QB/player-outcome score report fits 2022-2024 and scores 2025, with paired uncertainty resampled by NFL game. Receiver event and
completion-result distributions improve log loss by +0.00746 and +0.02066 per event; both 95 percent game-bootstrap intervals are
above zero. QB scramble/pass action has a small negative score difference whose interval includes zero. The QB-specific target-role
distribution is worse by -0.00734 log loss per target (95 percent interval -0.00889 to -0.00572). QB completion-result log loss is
worse by -0.00448 (95 percent interval -0.00707 to -0.00200). Rusher event and result score changes are small and uncertain. These
are marginal source-row scores, not full-game calibration. See `SLC-QB-PLAYER-OUTCOME-VALIDATION-2026-10-29.md`.

## Holdout

2026 is the sealed holdout. No 2026 game outcome was used to fit, tune, or select any component. The decision prior is built from
the prior season only (2025 for a 2026 forecast). The Week 8 lock (`ad7e26d9`) was frozen before its games.

## Known issues

1. The row filter over-samples a subset of labelled rows, and the filtered layer totals about four points above the real league total.
2. Red-zone yardage remains short (see above).
3. Simulated scrimmage plays run about 9 to 11 percent above 2025; the excess appears in the clock and drive model. This remains
   uninvestigated.
4. The share model's lower and median count quantiles remain too low on the 2025 holdout, and the full frozen-roster population was not scored.
5. The player-conditioned adapter improves receiver event and receiving-yard scores on the 2025 holdout, but QB target-role and
   completion-yard scores regress, while rusher scores show no clear gain. The player-conditioned layer has not cleared calibration
   gates and remains off by default.
6. Most evidence is one snapshot (CAR-GB) at 100 seeds. Margins carry about ±1.6 standard error per arm, so margin differences of
   this size are not team effects.
7. Some earlier arms ran on older code. Score-clock was rerun on current code (`score_clock_v2`) and matched the earlier totals exactly.
8. Pass length is taken from the nflverse play-by-play snapshot dated 2026-10-27, read only for seasons before the cutoff.
9. The 2024 scoring replay has only 89.5 percent game coverage, with missing snapshots concentrated in CIN.

## Intended use and limits

Research on play-calling and scoring structure. Not for betting, pricing, or public forecasts. It should not be presented as a
calibrated model of NFL games until the points, red-zone and row-filter issues above are resolved and the layers are tested on more
snapshots.

## Reproduce

`python3 scripts/nfl_sequence/simulate_pregame_batch.py --snapshot-file docs/research/slc-week8-2026/snapshots/2026_08_CAR_GB.json --playcall-artifact docs/research/SLC-PLAYCALL-ARTIFACT-v1.json --playcall-player-shares --playcall-decision --games 100 --seed-start 1 --out <json>`

`python3 scripts/nfl_sequence/validate_qb_player_outcomes.py --out-json docs/research/SLC-QB-PLAYER-OUTCOME-VALIDATION-2026-10-29.json --out-md docs/research/SLC-QB-PLAYER-OUTCOME-VALIDATION-2026-10-29.md`

Tests: `python3 -m unittest test_decision_layer test_participant_invariants test_pre_event test_slc_playcall test_player_shares test_streak_splits` (in `scripts/nfl_sequence`).
