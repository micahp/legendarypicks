# Three clock models, compared on the same plays (2026-10-24)

Script: `scripts/nfl_sequence/clock_compare.py`. Output: `three-model-clock-comparison-2026-10-24.json`. Inputs (pinned, copied from
the audit branch at `4e18cb9f`): `inputs/e3-clock-decomposition-2026-10-24.csv` (sha `11f8dc2b…`) and
`inputs/nflverse-2022-w1-9-flags.csv` (sha `00f38a10…`). The run is seeded (`20261025`), 100 draws per play, fit on 2022 weeks 1–5,
tested on 2022 weeks 6–9.

**Status.** This is a diagnostic. Weeks 6–9 were examined in earlier work, so these results do not test a holdout. No model is
adopted or rejected on this comparison alone, and E2 is not promoted by it.

## The three models

- **A, current sampled runoff.** The E2 rule: the runoff is drawn from the pool keyed by the cell (down, distance bucket, field
  bucket, using the engine's cut-offs) and the outcome. The pool includes quarter-end runoffs, censored at the boundary, as E1's pool
  does. The draw does not read the quarter clock.
- **B, PBP-conditional.** The runoff is drawn from the pool keyed by outcome, stoppage context and late half. Stoppage context comes
  from the flags. Quarter-end runoffs are excluded. No tracking is used.
- **C, tracking-informed.** In-play time is drawn from the tracking pool keyed by outcome; a residual is drawn from the pool keyed by
  outcome, stoppage context and late half; the two are independent.

Features were checked against the audit: the LP-derived outcome, stoppage context and late-half flag agree with the audit on all
15,768 verified plays.

Plays: 9,379 test plays. 6,032 are drawn by all three models. Refusals (a model could not draw a modelled play, and the observed
runoff was used instead, for that model only): A 506, B 170, C 240.

## T1 play timing (runoff, seconds)

Distance is the 1-Wasserstein distance between a model's draws and the observed runoff (lower is better). Medians are the draws and
the observed value.

| outcome | n | observed median | A (W1) | B (W1) | C (W1) |
| --- | ---: | ---: | ---: | ---: | ---: |
| run | 2,560 | 38.0 | 0.52 | **0.25** | 0.41 |
| pass complete | 2,008 | 36.0 | **0.29** | **0.29** | 0.44 |
| pass incomplete | 1,051 | 5.0 | 0.08 | **0.06** | 0.31 |
| sack | 185 | 40.0 | 3.35 | **0.94** | 0.76 |
| interception | 36 | 9.0 | **0.81** | 1.20 | 1.06 |
| touchdown | 192 | 6.0 | 0.31 | **0.23** | 0.38 |

C's in-play time, against the tracking in-play time on the verified test plays, is close on every outcome with at least ten plays
(W1 0.02 to 0.16 for run, pass complete, pass incomplete, sack, interception, touchdown; 0.83 for fumble on 37 plays).

**Reading.** A is worst on sacks (3.35 s against 0.94 for B), and B is best or tied on most outcomes. C is worse than B on pass
complete, pass incomplete and touchdown. The tracking split reproduces its own in-play time, but adding it does not improve the
total runoff.

## T2 end-of-quarter (late-half plays, 609)

| model | share of draws reaching the remaining quarter time |
| --- | ---: |
| observed (the next play is the quarter-end marker) | **2.46%** |
| A | 14.32% |
| B | 4.73% |
| C | 4.52% |

A reaches the boundary about six times as often as observed. B and C are close to the observed share.

## T3 drive duration (complete in-quarter drives, 1,007)

Observed median 128.0 s per drive. Mean absolute error per drive, against the observed sum of runoffs (all plays but the last):

| model | median (s) | mean absolute error (s) |
| --- | ---: | ---: |
| A | 135.9 | 29.7 |
| B | 128.9 | **20.0** |
| C | **128.2** | 20.1 |

B and C are close, and both are better than A. Skipped: 111 drives crossing a quarter, 71 with fewer than three plays, 5 with an
unresolved or censored runoff.

## T4 complete-game realism (clock consumed per quarter against the observed quarter)

Each quarter's error is the model's clock consumed minus the observed clock consumed (the quarter's 900 s, from the play-by-play), by
replicate. The overshoot share is the share of replicates where the model would reach the boundary before the observed last play. 218
quarters; 51 games with four quarters.

| model | median error (s) | mean absolute error (s) | overshoot share | game total, median of per-game medians (s) |
| --- | ---: | ---: | ---: | ---: |
| A | −7.8 | 79.9 | 48.0% | 20.0 |
| B | **+1.8** | **56.3** | 49.2% | 25.0 |
| C | +0.8 | 56.6 | 50.7% | 26.9 |

Across games, the spread of each game's replicate totals is wide: the 10th to 90th percentile of per-game medians runs from about −160 s
to +290 s for A, −130 s to +310 s for B, and −140 s to +320 s for C. The medians are near zero, and the spread is minutes.

## Regressions and limits

- **A regresses on every quarter-level test** against B and C: its end-of-quarter share (T2) is about three times theirs, its quarter
  error is larger (T4), and its sack timing is worse (T1).
- **C regresses against B on runoff timing** for run, pass complete, pass incomplete and touchdown (T1); it is better only on sacks.
  It does not improve the clock totals (T3, T4). The tracking split is accurate for in-play time and does not carry the clock error.
- **No model is calibrated at the quarter level.** The median error is near zero for B and C, and the mean absolute error is 56 to 57
  seconds per quarter. A model that draws each play independently cannot reproduce 900 seconds per quarter. The spread is structural,
  not a tuning gap.
- **Not covered:** timeouts, penalty clock stops, and the two-minute warning are not modelled (the audit labels them unresolvable). The
  kickoff clock is not in these replays. The replays are fixed-outcome: no game was generated freely.

## What this supports

For a clock subsystem, B (stoppage and late-half conditioning, from PBP) is the best of the three on this data, and tracking adds
accuracy to in-play time without improving the game clock. The quarter-level spread shows that conditioning does not fix the clock.
That is the case for an event-driven clock subsystem rather than a repair of the sampled runoff: the boundary and the stoppages have to
be generated as events, not inherited as independent draws. That design is not built here.
