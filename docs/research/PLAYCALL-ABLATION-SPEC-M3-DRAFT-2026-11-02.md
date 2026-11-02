# WP1 ablation spec, M3 (DRAFT, 2026-11-02)

Status: draft for owner approval. No run has started. Parameters marked OPEN are not assumed; they wait for the owner
(see the open list in `PLAYCALL-DESIGN-NOTE-M1-2026-11-02.md`, section 5).

## 0. Decisions received (owner, 2026-11-02)

- The source write-up is not canonical. Canonical numbers are the ones computed from the named source files in this
  repo (see `docs/research/playcall-baseline-2022-2025/README.md`).
- 2026 may be opened for verification. SLC v1 simulations do not use 2026 data. Any 2026 access is still logged in
  `HOLDOUT-EXPOSURE-RECORD-2026.md` before the value is used.
- Future simulations will use current-season play-by-play, target share, playbook and workload data. That is a
  later change and is out of scope here.
- Still OPEN: the 2025 status (known validation fold or test), the fit and test split, the advance thresholds, and Q1.

## 1. Question

Does the team opportunity structure (plays, runs, dropbacks, drives, plays per drive) come mainly from pace and drive
volume, or from the run/pass choice? WP1 answers this before any player workload is changed.

## 2. Data (pre-2026 only, until D1 is answered)

- Historical play-by-play: `/root/gridiron-playbooks-research/data/raw/pbp_{2022,2023,2024,2025}.csv.gz`.
- Historical participation: `pbp_participation_{2022..2025}.csv`, including `offense_personnel`.
- Baseline definitions: `docs/research/playcall-baseline-2022-2025/README.md`.
- 2026 files are not read by this spec unless the verification step in section 10 is requested.

## 3. Arms (one mechanism changes per arm, all on the same frozen inputs and seeds)

- A0 (control): current score-clock play-call model, frozen. Source: `scripts/nfl_sequence/slc_config.py`,
  `decision_layer.py`.
- A1: drive and possession volume only. The run/pass choice is held at the control; drive count and plays per drive
  change. Fit on the fit split only.
- A2: run/pass choice only, conditioned on down, distance, field position, score, and clock, fit on the fit split
  only. Drive volume is held at the control.
- A3 (optional, decide after A1 and A2): both mechanisms together, to test interaction.

Arms A1 and A2 are alternatives that need a fit. Their functional form is OPEN (not specified in the write-up).
Propose one form per arm before any fit.

## 4. Folds

- Fit: OPEN (D2). The write-up proposes 2022-2024.
- Test: OPEN (D1, D2). The write-up proposes 2025, but the holdout record says 2025 was already examined, so 2025 is
  at most a known validation fold. Until D1 is answered, no fold is labelled a test set.
- 2026: sealed. Not used.

## 5. Metrics (per arm, per held-out season)

- Held-out play-call log loss (run versus dropback, and the categories that the arm changes).
- Team-game counts: runs, dropbacks, drives, plays per drive, third and fourth down decisions, clock behavior, scoring.
- Bias: arm minus observed, per team-season, against the same season's observed counts from the baseline table.

## 6. Advance rule

An arm advances only if all three hold:

1. Held-out play-call log loss improves over A0.
2. Team opportunity bias drops on the counts the arm targets.
3. No other opportunity category worsens.

The numeric size of "improves" and "drops" is OPEN (D3). Until D3 is answered, no arm can be advanced, by definition.

## 7. Checks before any run

- Determinism: same seed, same output.
- Accounting: team totals equal the sum of player lines (for player-level outputs in later work).
- Matched inputs: every arm uses the same game list and seeds.

## 8. Not in this spec

- Player allocation (WP2), personnel eligibility (WP3), defensive labels (WP4), fatigue, injuries, coaching.
- Any default change.

## 9. Approval needed from the owner

D1, D2, D3, and Q1 (playbook prior state, needed if any arm touches the D, E or C labels). Once those are answered,
this draft becomes M3.

## 10. Optional verification of the write-up's 2026 observed numbers (not started)

Permitted by the owner (section 0). Steps, if requested: log the access in the holdout record first; then compare the
write-up's observed figures (Dallas 22.86, Wilson 23.3%, Williams 15.71 and 68.7%) with the same definitions used in the
baseline. Report the result as a verification, not as a fit or a test.
