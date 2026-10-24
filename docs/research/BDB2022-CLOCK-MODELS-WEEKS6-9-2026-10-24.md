# Runoff model comparison on the 2022 matched plays, fit weeks 1–5, test weeks 6–9 (2026-10-24)

Script: `scripts/bdb/bdb2022_clock_models.py`. Output: `bdb2022-clock-models-weeks6-9-2026-10-24.json` (same folder).
Instrument: each test play is given K = 100 draws from each model, conditioned on that play's observed outcome. This
isolates timing from the play mix. It is not a full-game simulation of the engine.

## The three models

- **A, current engine rule.** The runoff pool keyed by (down, distance bucket, field bucket) and the outcome, with the
  engine's bucket cut-offs (copied from `e0_single_play.py` in the E2 worktree) and its floor of 50 plays per cell. The
  draw ignores the quarter clock and whether the play stopped the clock.
- **B, PBP-only conditional.** The runoff pool keyed by (outcome, stop class, end-of-half band). Stop class is the
  audit's exclusive class: incomplete pass or touchdown; out of bounds or timeout; none observed. The end-of-half band is
  the last two minutes of the second or fourth quarter, using the quarter clock. No tracking is used.
- **C, tracking-informed.** In-play time drawn from the tracking pool keyed by outcome, plus a residual drawn from the
  pool keyed by (outcome, stop class, band). The two parts are drawn independently.

Fit: the 9,225 matched plays of weeks 1–5. Test: the 6,540 matched plays of weeks 6–9, of which 5,881 are used (all three
models must draw; see the skip counts). The seed is fixed.

## Quarter end: does the draw reach the remaining quarter time?

The engine clamps the clock at zero when a draw exceeds the remaining quarter time. In the play-by-play, a play that ends a
quarter is followed by a marker row with no play type and the clock at the boundary (0, 900, 1800 or 2700 s, checked
across the weeks 1–9 rows). Its runoff therefore equals the remaining quarter time. The observed side counts plays whose
runoff reaches that time; the models count draws that reach it.

| | all test plays | last two minutes of the second or fourth quarter | otherwise |
| --- | ---: | ---: | ---: |
| observed (test plays) | 2.3% | 6.7% | — |
| A, current engine rule | 2.95% | 15.3% | 1.5% |
| B, PBP-only conditional | 2.1% | 6.7% | 1.5% |
| C, tracking-informed | 2.0% | 6.5% | 1.5% |

The current rule reaches the end of the half about twice as often as observed late in a half. B and C match the observed
share.

## Out-of-bounds plays (observed stop)

| plays | n | observed median | A | B | C |
| --- | ---: | ---: | ---: | ---: | ---: |
| last two minutes of the half | 78 | 5.0 s | 36.0 s | 5.0 s | 5.4 s |
| otherwise | 603 | 35.0 s | 37.0 s | 34.0 s | 33.5 s |

A runs the clock as if the play had no stop, so out-of-bounds plays late in a half are 36 s where the data show 5 s. B and
C reproduce both halves of the observed split.

## Per-outcome timing (median draw, observed median, and W1 distance in seconds)

| outcome | n | observed median | A median (W1) | B median (W1) | C median (W1) |
| --- | ---: | ---: | ---: | ---: | ---: |
| run | 2,449 | 38.0 | 38.0 (0.37) | 38.0 (0.28) | 37.9 (0.43) |
| pass complete | 1,979 | 36.0 | 36.0 (0.67) | 36.0 (0.53) | 36.1 (0.54) |
| pass incomplete | 1,005 | 5.0 | 5.0 (0.08) | 5.0 (0.05) | 4.7 (0.31) |
| sack | 178 | 40.0 | 40.0 (2.49) | 41.0 (0.69) | 41.0 (0.74) |
| interception | 30 | 8.5 | 9.0 (0.67) | 7.0 (1.14) | 7.7 (0.96) |
| touchdown | 182 | 5.5 | 5.0 (0.39) | 5.0 (0.21) | 5.2 (0.38) |
| other (kneels, spikes and similar) | 58 | 25.0 | 13.0 (5.56) | 19.0 (4.17) | 19.2 (4.00) |

The "other" class is a mix: its in-play median is 0.7 s, but its residual is about 21 s. It is the weakest row for every
model and needs splitting before it can be modelled.

## Drive duration (snap to snap, complete in-quarter drives, weeks 6–9)

| | n drives | median per drive (s) | mean absolute error per drive (s) |
| --- | ---: | ---: | ---: |
| observed | 54 | 112.5 | — |
| A | 54 | 117.1 | 23.0 |
| B | 54 | 109.5 | 18.3 |
| C | 54 | 112.4 | 19.3 |

Only 54 drives pass the filters (see `drive_skipped` in the JSON). With 54 drives the differences in mean absolute error
are within what sampling would produce, so this table does not separate the models. It is reported for completeness.

## What the comparison supports

- The gain over the current rule comes from conditioning on the stop class and the end-of-half band, not from tracking.
  B, which uses only play-by-play flags and the clock, matches the observed quarter-end share and the out-of-bounds split.
- Tracking adds the split of runoff into in-play time and residual (C). On the quarter-end and out-of-bounds tests C does
  no better than B, and its interception row is slightly worse. Tracking's value is in play duration; it does not
  change the clock outcome measured here.
- Turnovers need their own residual. Interception and fumble residuals are short (2.7 s and 3.1 s), so a residual keyed on
  the stop class alone misses them: the first run of C, keyed on stop class only, drew 39 s for interceptions where the
  data show 8.5 s. The residual is keyed on outcome as well in the table above.

## Limits

- Period boundaries: the observed quarter-end plays are followed by a play-by-play marker row with no play type, and the
  runoff to that marker is the remaining quarter time. The three models are not tested on legal transitions between
  quarters, because the rule text for them is not in the repository.
- Timeouts and penalty stoppages are unresolvable from these sources (see the audit report). Neither model includes them.
- The two-minute rule is observed in the data, not checked against the rulebook.
- Complete-game realism (game length, total clock) was not tested. That needs a full engine run with each model swapped in.
- The current rule here is a reproduction of the engine's cell key, not the engine itself. The E1 census figure (594 of
  7,016 plays clamped, 8.5%) comes from the engine's own run and is a different instrument.
- A is fitted on matched plays only, with the same weeks as B and C, so all three are compared on the same data. The
  engine draws from the full 2022–2025 pool.
- Thin conditioning pools are skipped and counted, not filled from other cells: 535 test plays for A, 148 for B and C.
