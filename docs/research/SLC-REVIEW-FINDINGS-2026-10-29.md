# SLC findings for review (2026-10-29)

Status: **findings only, for review. No defaults changed and no code acted on.** Each finding lists what was measured, on how many
seeds, and what is still unknown. Nothing here is a validated result. Snapshot 2026_08_CAR_GB throughout, 2026 not read.

## 1. The row filter is not the source of the uplift it appears to be, and it changes outcomes by bucket

Measured with the filter on and off, same seeds (20 seeds, the decision layer with player shares).

- Sources: both arms draw every sampled row from the charted seasons (2022 to 2025). The season restriction is not the cause.
- Event mix: nearly identical in both arms (runs about 43 percent of plays, completions about 35 percent, sacks about 1.5 percent).
  The filter does not change which event happens.
- Outcomes within event and yard-line bucket (`scripts/nfl_sequence/diagnose_row_filter_outcomes.py`):

| event and yard-line bucket | plays on / off | touchdown rate on / off | mean yards on / off |
|---|---|---|---|
| completion, own 1-9 | 55 / 51 | 0.44 / 0.37 | 3.6 / 4.3 |
| completion, 10-19 | 72 / 65 | 0.18 / 0.14 | 8.0 / 8.2 |
| completion, 20-49 | 283 / 314 | 0.074 / 0.032 | 12.4 / 10.1 |
| completion, 50+ | 541 / 505 | 0.007 / 0.008 | 12.8 / 11.8 |
| run, 1-9 | 108 / 123 | 0.32 / 0.24 | 2.0 / 1.3 |
| run, 10-19 | 103 / 90 | 0.03 / 0.06 | 3.4 / 4.4 |
| run, 20-49 | 347 / 370 | 0.014 / 0.000 | 4.9 / 3.8 |
| run, 50+ | 617 / 589 | 0.003 / 0.002 | 4.7 / 4.4 |

- Reading: with the filter on, completions in the 20-49 zone are longer and touchdown more often, and short runs score more. The
  sampled rows are drawn from label-matched subsets, and those subsets appear to carry higher-yield outcomes.
- Hypothesis, not tested: the label categories that drive this (for example pass length, pass location, or run gap) select rows
  whose yards differ from the cell. The test would be to filter on one category at a time and see which one moves the table.
- Caveat: 20 seeds, so cells with fewer than about 50 plays are noisy.

## 2. Simulated pace and dropbacks run about 9 to 11 percent above 2025

Measured against the 2025 regular season (`nfl_pbp`, both teams, per game):

| quantity | actual 2025 | simulated (decision_v3, 100 games) |
|---|---:|---:|
| scrimmage plays | 121.1 | 135.0 |
| runs | 52.2 | 59.9 |
| dropbacks (including sacks) | 68.9 | 75.1 |
| pass share | 0.569 | 0.556 |
| dropbacks thrown by a QB | 0.998 | QB1 by construction, trick throws rare |

- Reading: the excess is in total plays, not in the pass mix. The gap exists before the decision layer: score-clock SLC runs
  131.8 scrimmage plays a game on the same snapshot.
- This is a question for the clock and drive model (possessions, clock stoppage, kick and punt rates), which is not in this review's
  scope. It is also a check on the QB-opportunity validation target: simulated attempts are not yet consistent with 2025.
- Not acted on.

## 3. The playbook files and the decision labels agree on all 96 team-category pairs

`scripts/nfl_sequence/playbook_crosscheck.py`, 2025 season, 32 teams, categories pass depth, pass location and run gap:

- Before mapping team codes: 60 of 96 pairs agreed. The two failures were a key mismatch, not a data disagreement. The playbook files
  use `LA` and `WAS`, while the database and nflverse use `LAR` and `WSH`.
- After mapping those two codes: 96 of 96 agree. Run gap is compared on the playbook's own definition (every run with a gap). The
  decision label C is restricted to backs and fullbacks, a definition difference, not an error.
- Coverage of the playbook's categories by the decision layer: pass depth (D), pass location (E), run gap (C), formation (through the
  formation layer), motion (H), play action (G), backfield (L), box (M), pass rushers (N), blitz (I). Not covered: no-huddle, route,
  red zone and goal line, and air yards as a continuous quantity.
- Open for review: whether the playbook files should be a separate input. Adding them alongside the decision prior would count the same
  plays twice, so the current design uses the decision prior as the carrier. That is a decision for review.

## 4. Still open

- Receiver and carry Monte Carlo distributions are not ported. Only the observed-share adapter is in the engine.
- The red-zone yardage gap (see `SLC-YARDS-REPLAY-2024-2026-10-29.md`) is unchanged.
- The row-filter default is left on, and I have not changed it. Findings 1 and the uplift note (`SLC-DECISION-LAYER-UPLIFT-2026-10-29.md`)
  bear on it, and that call is for review.
