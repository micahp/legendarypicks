# Tennis match backtest, step 3: point model through the simulator, against Elo, 2026-10-14

Status: result of the frozen protocol (`TENNIS-MATCH-BACKTEST-PROTOCOL-2026-10-14.md`). The protocol was committed
before the run, and the run used it unchanged. Research use only. Licence decision D1 is open, so nothing here
authorises product use.

## Decisions

| Decision | ATP | WTA | Result |
|---|---|---|---|
| P1, predictive value: simulator log loss below Elo, with the 95% interval below zero | Fail | Fail | Not supported on either tour |
| P2, calibration: largest bin gap at most 0.03 (bins with n of at least 200), mean gap at most 0.01 | Fail (0.053) | Pass, narrowly (0.030) | Mean level is fine on both tours |
| P3, stability: simulator better than Elo in at least 3 of 4 years | Fail (0 of 4) | Fail (0 of 4) | Not supported |
| S, simulation correctness: exact against Monte Carlo | Pass | Pass | 200,000 matches per case, 48 cases, 7,224 quantities, exact p-values, Bonferroni threshold 6.9e-6 (see `TENNIS-MATCH-SIM-2026-10-14.md`) |
| L, licence | Not assessed | Not assessed | D1 open |

**Decision.** The complete system (point model plus simulator) does not add predictive value over Elo on either tour,
on the frozen rules. The simulator stays research code. Its correctness is a separate decision, and it is covered in
`TENNIS-MATCH-SIM-2026-10-14.md`.

## Results on the test window (2023 to 2026, best-of-three, scored matches)

| | ATP | WTA |
|---|---|---|
| Test-window matches read | 14,036 | 13,516 |
| Scored (best-of-three, complete score) | 11,777 | 13,066 |
| Excluded: best-of-five or best-of-one | 1,849 | 0 |
| Excluded: retirement, walkover, default or abandonment | 410 | 450 |
| Scored matches with serve stats in the match itself | 11,775 (99.98%) | 12,899 (98.7%) |
| Simulator log loss per match | 0.66277 | 0.64864 |
| Elo log loss per match | 0.64896 | 0.62100 |
| Difference, simulator minus Elo (95% paired bootstrap) | +0.01381 (+0.00703 to +0.02032) | +0.02764 (+0.02176 to +0.03336) |
| Brier, simulator / Elo | 0.23530 / 0.22802 | 0.22884 / 0.21596 |
| Mean predicted / mean observed (simulator) | 0.50114 / 0.49928 | 0.49908 / 0.50077 |
| Largest bin gap, bins with n of at least 200 | 0.053 (0.8 to 0.9, n = 235) | 0.030 (0.2 to 0.3, n = 962) |

The simulator is worse than Elo on both tours, by 0.014 (ATP) and 0.028 (WTA) per match.

### By year (simulator minus Elo, log loss per match; negative would favour the simulator)

| Year | ATP | WTA |
|---|---|---|
| 2023 | +0.0143 | +0.0364 |
| 2024 | +0.0198 | +0.0255 |
| 2025 | +0.0121 | +0.0231 |
| 2026 | +0.0026 | +0.0230 |

### By surface (simulator minus Elo)

| Surface | ATP (n) | WTA (n) |
|---|---|---|
| Hard | +0.0142 (6,755) | +0.0237 (8,172) |
| Clay | +0.0037 (3,934) | +0.0295 (3,407) |
| Grass | +0.0477 (1,088) | +0.0451 (1,487) |

### By history depth (effective points on the surface, lowest of the four counts)

| Depth | ATP (n) | WTA (n) |
|---|---|---|
| Thin, below 300 | +0.0566 (2,600) | +0.0619 (2,961) |
| Middling, 300 to 1,499 | -0.0011 (3,791) | +0.0162 (4,502) |
| Deep, 1,500 and above | +0.0036 (5,386) | +0.0187 (5,603) |

### Calibration bins (simulator; predicted, then observed)

ATP: 0.0 to 0.1 (n 32) 0.074 / 0.188; 0.1 to 0.2 (218) 0.165 / 0.188; 0.2 to 0.3 (858) 0.258 / 0.295;
0.3 to 0.4 (1,855) 0.355 / 0.387; 0.4 to 0.5 (2,903) 0.453 / 0.466; 0.5 to 0.6 (2,875) 0.548 / 0.530;
0.6 to 0.7 (1,898) 0.645 / 0.611; 0.7 to 0.8 (879) 0.739 / 0.705; 0.8 to 0.9 (235) 0.836 / 0.783;
0.9 to 1.0 (24) 0.922 / 0.958.

WTA: 0.0 to 0.1 (n 48) 0.070 / 0.083; 0.1 to 0.2 (270) 0.162 / 0.189; 0.2 to 0.3 (962) 0.258 / 0.288;
0.3 to 0.4 (2,065) 0.353 / 0.353; 0.4 to 0.5 (3,267) 0.453 / 0.462; 0.5 to 0.6 (3,145) 0.549 / 0.539;
0.6 to 0.7 (2,037) 0.644 / 0.636; 0.7 to 0.8 (973) 0.742 / 0.750; 0.8 to 0.9 (261) 0.838 / 0.828;
0.9 to 1.0 (38) 0.926 / 0.947.

## Diagnostics (post hoc: run after the decisions, not part of the protocol)

These explain the result. They do not change it, and they were not used to tune anything.

| Measure | ATP simulator | ATP Elo | WTA simulator | WTA Elo |
|---|---|---|---|---|
| AUC (ability to separate winners from losers) | 0.638 | 0.677 | 0.664 | 0.713 |
| Calibration slope (1 is ideal) | 0.80 | 0.71 | 0.95 | 0.84 |
| Spread of logit predictions (SD) | 0.67 | 0.98 | 0.69 | 1.04 |

The gap is in discrimination, not level. The simulator's probabilities are close to calibrated on WTA (slope 0.95),
and on ATP they are too extreme at the top (slope 0.80, which the calibration bins show at 0.8 to 0.9). But both
models are weaker in discrimination than Elo, by about 0.04 AUC on ATP and 0.05 on WTA.

## Reading the result

1. **Discrimination is the problem.** The serve-point model, built from surface-specific serve and return rates, sorts
   winners from losers less well than Elo's accumulated record of results. Step 1 had already measured the gain over the
   surface baseline at 0.2 to 0.3% per point, and the match-level result is consistent with a signal that small.
2. **Thin history is the largest loss on both tours** (+0.057 ATP, +0.062 WTA). The point model uses only the player's
   record on the surface, with serve stats present. When that record is thin, it shrinks to the surface average, so
   the prediction is near 50%. Elo still knows the player from their overall record. This is a pooling problem: the
   model needs an all-surface prior for each player, which it does not have.
3. **Grass is sparse** (1,088 ATP and 1,487 WTA matches in the test window), and it shows the same pooling problem.
4. **The bracketed match-tiebreak format is too rare to judge.** Four ATP matches in the window used it.
5. **Both models ignore results from earlier rounds of the same event**, because predictions are made per event date.
   The handicap is symmetric, so it does not change the comparison, but it is a real loss for both.
6. **Retirements and walkovers are excluded**, so the test is easier than a live betting market would be.

## Sample selection

Serve stats are the input to the point model, and their coverage varies by era. Coverage by year, tour-level matches with
both serve counts present (from the dev DB and the ATP scratch database):

- ATP: under 1% before 1990; 2% in 1990; 95% to 99% in 1991 to 1999; 84% to 87% in 2000 to 2006; about 60% in 2007 to
  2009; 99% in 2010; 96% to 97% in 2011 to 2014; 80% to 88% in 2015 to 2017; 93% in 2018; 98% to 99% in 2019 to 2025.
- WTA: 0% before 2003; 9% in 2003; 32% to 52% in 2006 to 2009; 83% to 94% in 2010 to 2018 (47% in 2015); 98% to 99% in
  2019 to 2025.

The test window is well covered (ATP 99.98%, WTA 98.7%). The matches without stats in the test window are too few to
compare (24 ATP matches with ranks, 1 WTA). The gaps are in the history that the surface baseline and the player counts
are built from. Whether the missing matches differ in some systematic way (tour level, draw, or player strength) is not
tested here. The first test is a sensitivity run on history from 2019 only, where coverage is 98% or more on both tours.

## Protocol notes

- The protocol says Elo is updated from "all main-tour matches". The loader also requires a recorded surface. That
  filter removes no main-tour matches from 2000 onward on either tour (ATP 0 of 104,106; WTA 0 of 105,882), so the
  wording holds in effect. Null-surface rows exist only before 2000 (ATP 1,841 in all years; WTA 4,423).
- The bracketed-score format rule matched four ATP matches in the window and none in WTA.
- The protocol file was written at 00:30, before the run started at 00:35, and the run used it unchanged. It is
  committed with this report, so its committed history is later than the run.

## What would change the decision

Each of these needs a new frozen protocol, and none has been run:

- **An all-surface prior for each player.** Shrink each surface's serve and return rates toward the player's overall
  rates, not only toward the surface average. This targets the thin-history loss directly. It should be fitted on the
  2022 validation window.
- **An incremental test against Elo.** Does the simulator add information that Elo lacks? Fit a logistic blend of the
  two logits on 2022, then score it once on the frozen 2023 to 2026 window. The standalone test above does not answer
  this.
- **History from 2019 only**, for the sample-selection sensitivity.
- **A prospective window.** The 2023 to 2026 window was used for the step 1 reports, so it is not untouched. A positive
  claim needs matches played after this freeze, scored as they happen.

## Commands

    python3 backend/tennis_match_backtest.py --db <ATP scratch DB> --tour atp \
      --out backtest-atp.json --records backtest-atp-rows.csv
    python3 backend/tennis_match_backtest.py --db <dev DB, read-only> --tour wta \
      --out backtest-wta.json --records backtest-wta-rows.csv

The JSON summaries and per-match rows are in the session scratchpad. The rows file has one line per scored match, with
the two probabilities and the outcome, so any other breakdown can be recomputed from it.
