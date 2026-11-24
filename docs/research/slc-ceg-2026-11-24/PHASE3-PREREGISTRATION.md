# SLC-CEG Phase 3 pre-registration: clock and timeouts

Written 2026-11-24, before any Phase 3 model is scored. Phase 2 results and pre-registration stay unchanged. Code:
`scripts/nfl_sequence/ceg_clock.py` (models, local scoring), `ceg_harness.py` (generated drives through
`e1_drive.simulate`).

## Rules, checked against the data before writing this (2025 play-by-play)

- Two-minute warning in Q2, Q4 and overtime: plays that start above 2:00 and end below it have their next snap at
  exactly 2:00 in 1,073 of 1,204 (Q2), 1,019 of 1,244 (Q4) and 22 of 23 (overtime) cases, against 34 and 40 in Q1 and
  Q3.
- Out of bounds stops the clock until the snap inside the last 2:00 of Q2 and the last 5:00 of Q4 and of overtime
  (median runoff 6 to 7 s), and restarts on the ready signal otherwise (median 33.5 to 36 s).
- Model D (`clock_d.py`) applies both rules to Q2 and Q4 only, not to overtime. CEG applies them to overtime as well.

## Components

| id | target | unit | arm B | arm C |
|---|---|---|---|---|
| oob | out of bounds | run, scramble, completion (no score, no turnover) | by event | event, then the Phase 2 situation hierarchy |
| live | live-play seconds (integer, no cap) | stopped-clock snap (below) | by event | event, yards bucket, out of bounds |
| dead | dead-ball seconds while the clock runs (0 to 60) | running-clock snap | one distribution | score state x time bucket x late quarter |
| timeout_first | none, offense, defense | dead-ball opportunity (below) | league, legal mask | time and quarter group, clock running, score state, timeouts left |
| timeout_more | none, offense, defense | opportunity that already had a timeout | league, legal mask | same hierarchy |

Live duration is identified only on snaps after which the clock stops at the whistle: incomplete passes, spikes,
touchdowns, turnovers, out of bounds inside the stop windows, and plays followed by a timeout before the next snap
(the timeout adds the seconds until it is called). For runs and completions that stay in bounds with a running clock,
live time is not observed. The model assumes it has the same distribution, given event, yards bucket and out of bounds,
as on the stopped snaps. This is the stated limit of identification from play-by-play. A sensitivity check reports the
live medians for runs from each source (late out of bounds, touchdowns, timeout-followed) separately.

Dead-ball seconds are not observed on any snap. Arm C recovers them by deconvolution: on running-clock snaps,
runoff = live + dead; with the live model fixed, the dead distribution in each cell is fitted by EM. Arm B fits one dead
distribution for all running-clock snaps the same way.

Censoring: a snap whose next snap is at exactly 2:00 after crossing it, or that ends the quarter, has its runoff
censored; it is scored as P(runoff >= the observed value).

A dead-ball opportunity is the interval after a scrimmage snap whose next snap is in the same quarter by the same
offense (no change of possession). The timeouts in it are read in order from the timeout rows. Timeouts in other
intervals (after scores, after changes of possession, before kickoffs) are counted and reported, not modelled.

Buckets: yards gained <= 0, 1-5, 6-10, 11-20, 21+; time bucket (quarter clock) > 300, 121-300, 61-120, 31-60, <= 30;
late quarter group Q2, Q4 or overtime against Q1 or Q3; score state from the offense: trailing 9+, trailing 1-8, tied,
leading 1-8, leading 9+.

## Selection, periods, metrics

- k from {1, 3, 10, 30, 100, 300} chosen on train 2022-2023, validate 2024; refit 2022-2024; score once on 2025;
  report 2026 weeks 1 to 11 as examined.
- Local metrics, per opportunity: log loss (censored where stated), with a 95% game-bootstrap interval for C minus B.
  For total runoff also the median absolute error of the predictive median.
- Benchmark: Model D refit on 2022-2024 from the Phase 1 tables with its own keys and fallbacks (`stop_class`,
  `qsr_bucket`, `MIN_KEY`, the quarter-end hazard), its pools smoothed by +0.5 per second so its log loss is finite.
  Scored on the same 2025 snaps for total runoff.
- Timeout aggregates: expected against observed timeouts per team-half, overall and in the last 2:00 of each half.

## Harness (generated events through the real interfaces)

`ceg_harness.py` runs `e1_drive.simulate` with a CEG provider (`generates_events = True`, a switch on this branch that
skips only the historical-cell lookup) and a CEG clock in the `clock=` slot (the `BoundaryClock.draw` interface). The
reducer, the quarter, halftime, regulation and overtime logic, and the drive validator are the existing ones. Punts use
an arm B league net-punt placeholder; field goals end the drive (Phase 4).

- Drive starts: 2,000 regular-season 2025 drives sampled from the Phase 1 tables (quarter, clock, field, score, timeouts
  at the first snap), seed 20261124. One generated drive per start, per arm.
- Arms: scrimmage B, C, and **BC-selective** (C for the six Phase 2 components where C beat B in 2025: intent, air
  yards, run yards, targeted outcome, dropback outcome, throwaway; B for YAC, scramble yards, sack yards, fumble, fumble
  lost). Clock: the CEG clock (arm C clock components) and Model D.
- Measures against the observed 2025 drives from the same starts: plays per drive, drive duration (game seconds),
  timeouts per drive, end reasons, plays per 60 game-clock seconds.
- BC-selective was chosen from the 2025 results, so its 2025 harness numbers are not a confirmation. Its aggregate
  check is the 2026 examined starts (weeks 1 to 11), run the same way.
- No harness number is used to select or tune anything.
