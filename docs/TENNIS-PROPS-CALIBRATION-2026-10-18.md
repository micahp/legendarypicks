# Tennis props: calibration of the direct Gamma-Poisson P0 and P1 on identical rows

- **Date:** 2026-10-18
- **Status:** Development evidence. Not prospective confirmation. No direct incumbent is selected in this report.
- **Track:** Track B, build-order item B1 (see [TENNIS-STATE-2026-10-18.md](TENNIS-STATE-2026-10-18.md)).
- **Code:** [`research/tennis/props/2026-10-18/gp_calibration.py`](../research/tennis/props/2026-10-18/gp_calibration.py).
  It runs the unchanged replay in `backend/tennis_props_rate_backtest.py` with two read-only hooks.
- **Outputs:** `research/tennis/props/2026-10-18/gp_calibration_{atp,wta}.json`.
- **Source data:** `backend/data/picks.dev.db`, opened read-only. Research-only under the CC BY-NC-SA source terms.

## Question

Which direct count forecast should be the ace and double-fault incumbent on each tour? The brief requires the frozen
variants to be compared on identical rows, with calibration finished, before one is chosen. This report does the first
part for the two Gamma-Poisson variants and records what blocks the rest.

## Rows and method

- **Rows:** completed best-of-three main-tour matches, 2015 to 2026, prior-only. Each player-match is one target row.
  Sides are randomized. Targets are aces and double faults. Both players must have valid serve inputs.
- **Models:** P0 Gamma-Poisson (per-match rate, shrunk to the tour) and P1 Gamma-Poisson (service-point exposure times
  the rate, with exposure variance moment-matched). Both come from the replay, unchanged.
- **Hooks:** one records, for each forecast distribution, the CDF at the observed count and the upper-tail probabilities at
  the replay's thresholds. The headline scores are the replay's own.
- **Randomized PIT:** U = F(y-1) + V (F(y) - F(y-1)), V uniform from a fixed seed. Calibrated forecasts give U uniform.
  Reported as decile shares, a Kolmogorov distance to uniform (KS), and tail shares below 0.05 and above 0.95.
- **Coverage:** the replay's central intervals at 50, 80 and 90%. These intervals are discrete, so they can over-cover
  when the count is small. Read them together with PIT.
- **Paired differences:** P1 minus P0 on the same rows. Negative favours P1. Intervals resample tournament events
  (`event_id`), 1,000 times. Seeds depend on the slice name.
- **Slices:** all rows; 2019 to 2026; each year; each surface; each history band from the replay (`cold` under 10, `mid`
  10 to 40, `deep` 40 and over); and quartiles of the predicted P1 mean. Quartiles use the forecast, not the outcome.
  Banding on the observed count would select on the outcome and was not used.

## Verification of the re-run

The re-run reproduces the replay's published totals exactly at four decimals (CRPS and negative log score):

| Target | Family | Re-run CRPS | Re-run NLL | Published (JSON) CRPS | Published NLL |
|---|---|---:|---:|---:|---:|
| ATP aces | P0 GP | 2.0505 | 2.7950 | 2.0505 | 2.7950 |
| ATP aces | P1 GP | 1.9934 | 2.6152 | 1.9934 | 2.6152 |
| ATP double faults | P0 GP | 1.1047 | 2.0422 | 1.1047 | 2.0422 |
| ATP double faults | P1 GP | 1.0955 | 2.0044 | 1.0955 | 2.0044 |
| WTA aces | P0 GP | 1.2221 | 2.1133 | 1.2221 | 2.1133 |
| WTA aces | P1 GP | 1.2005 | 2.0280 | 1.2005 | 2.0280 |
| WTA double faults | P0 GP | 1.3444 | 2.2682 | 1.3444 | 2.2682 |
| WTA double faults | P1 GP | 1.3308 | 2.2086 | 1.3308 | 2.2086 |

Rows: ATP 70,198 per target from 711 tournament events; WTA 77,274 aces and 77,256 double faults from 609 events.
The hooks did not change any score.

## Results: all rows, identical rows for both models

NLL is the replay's negative log score (lower is better). Coverage is the observed share inside the central interval
(nominal 50, 80, 90). KS is the distance to uniform of the randomized PIT (lower is better; 0.02 is nearly flat for this n).

| Tour, target (n rows, events) | Model | CRPS | NLL | Coverage 50/80/90 | PIT KS | PIT tails below 0.05 / above 0.95 |
|---|---|---:|---:|---|---:|---|
| ATP aces (70,198; 711) | P0 GP | 2.0505 | 2.7950 | 44.3 / 68.5 / 79.3 | 0.132 | 14.7 / 12.6 |
| ATP aces | P1 GP | **1.9934** | **2.6152** | 50.5 / 76.3 / 86.7 | **0.080** | 10.1 / 9.0 |
| ATP double faults (70,198; 711) | P0 GP | 1.1047 | 2.0422 | 59.5 / 83.0 / 92.0 | 0.058 | 8.0 / 8.1 |
| ATP double faults | P1 GP | **1.0955** | **2.0044** | 63.6 / 87.8 / 95.1 | **0.021** | 5.9 / 6.0 |
| WTA aces (77,274; 609) | P0 GP | 1.2221 | 2.1133 | 56.1 / 80.9 / 89.7 | 0.113 | 10.4 / 9.8 |
| WTA aces | P1 GP | **1.2005** | **2.0280** | 60.6 / 85.9 / 92.7 | **0.078** | 8.0 / 7.9 |
| WTA double faults (77,256; 609) | P0 GP | 1.3444 | 2.2682 | 56.3 / 79.7 / 88.8 | 0.067 | 9.0 / 8.7 |
| WTA double faults | P1 GP | **1.3308** | **2.2086** | 62.7 / 86.3 / 94.1 | **0.013** | 5.7 / 5.6 |

### Paired P1 minus P0 (identical rows, event-clustered 95% interval)

| Tour, target | CRPS difference | Interval | NLL difference | Interval |
|---|---:|---|---:|---|
| ATP aces | −0.0571 | −0.0595 to −0.0548 | −0.1798 | −0.1874 to −0.1726 |
| ATP double faults | −0.0092 | −0.0101 to −0.0084 | −0.0378 | −0.0405 to −0.0353 |
| WTA aces | −0.0216 | −0.0228 to −0.0205 | −0.0853 | −0.0901 to −0.0812 |
| WTA double faults | −0.0137 | −0.0149 to −0.0122 | −0.0595 | −0.0696 to −0.0522 |

Across the 23 slices per cell (window, years, surfaces, history bands, forecast quartiles), the CRPS interval is entirely
below zero in 23 of 23 for each of the four cells, and the NLL interval is entirely below zero in 23 of 23. P1's PIT KS is
lower than P0's in 23 of 23. The slices overlap, so these counts describe consistency and are not independent tests.

The 2019 to 2026 window, the window the E2 family covers, gives the same direction: paired CRPS differences are
−0.0571 (ATP aces, n = 46,216, 451 events), −0.0097 (ATP double faults), −0.0222 (WTA aces, n = 51,026, 382 events) and
−0.0137 (WTA double faults, n = 51,020).

### Forecast-size quartiles (P1 predicted mean)

P1 minus P0 CRPS, with P1's KS. Quartile edges are from the predicted P1 mean within each target.

| Tour, target (edges) | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|
| ATP aces (3.96, 5.05, 6.51) | −0.035, KS 0.113 | −0.046, KS 0.100 | −0.055, KS 0.081 | −0.093, KS 0.072 |
| ATP double faults (2.24, 2.67, 3.09) | −0.006, KS 0.033 | −0.007, KS 0.027 | −0.009, KS 0.019 | −0.015, KS 0.019 |
| WTA aces (1.81, 2.45, 3.28) | −0.014, KS 0.116 | −0.017, KS 0.093 | −0.021, KS 0.078 | −0.035, KS 0.054 |
| WTA double faults (2.98, 3.65, 4.35) | −0.010, KS 0.041 | −0.009, KS 0.023 | −0.014, KS 0.013 | −0.021, KS 0.016 |

Each quartile holds about 17,500 rows (ATP) or 19,300 (WTA).

## Reading the calibration

- **P1 is better calibrated than P0 in every cell and slice.** The gain is largest where P0 is most wrong: ATP aces,
  where P0's PIT is U-shaped (its lowest decile holds 22% of outcomes).
- **ATP double faults (P1): calibrated.** PIT tails are 5.9% and 6.0% (nominal 5%). Threshold gaps are small: at 1 or more,
  predicted 89.2% and observed 87.4%; at 4 or more, 29.6% against 29.7%. Coverage is above nominal (63.6% at 50%), which is
  consistent with the discrete intervals over-covering when counts are small, but the PIT is the sharper test.
- **WTA double faults (P1): calibrated.** PIT tails 5.7% and 5.6%. Largest gap: at 2 or more, predicted 80.5% and observed
  79.1%.
- **ATP aces (P1): too narrow and off-centre.** PIT tails are 10.1% and 9.0%, and 80 and 90% coverage fall short
  (76.3% and 86.7%). Threshold gaps: at 4 or more, predicted 66.4% against observed 60.1%; at 10 or more, predicted 12.4%
  against 16.0%. The upper tail is under-predicted and the middle is over-predicted.
- **WTA aces (P1): thin upper tail.** PIT tails are 8.0% and 7.9%. At 10 or more, predicted 1.35% against observed 2.77%;
  at 8 or more, 3.8% against 6.1%. The upper tail is about half what is observed.
- **Remaining P1 gaps are not corrected by the PIT.** The discrete coverage intervals over-cover, so their sizes should not
  be used to choose between models.

## E2 family: what can and cannot be compared now

The E2 family (P0 negative binomial, P1 negative binomial, X_thin and X_bbin) appears only as aggregates in
`research/tennis/props/2026-10-14/e2-count-mixtures.json`. Its evaluation covers 2019 to 2026 with 53,284 ATP sides and
51,018 WTA sides per target. The GP replay covers 46,216 ATP and 51,026 WTA rows in 2019 to 2026, so the samples differ.
The E2 row-level predictions were not saved, and its code is uncommitted or on another branch (see the state audit,
defects D5 and D6). Results therefore cannot be paired row by row yet.

The E2 file does report PIT decile shares. Both families report these, so they can be placed side by side. The E2 PIT
definition is not in dev and may not be randomized, so this comparison is a signal for the next step, not a result.

| Target | Model | Decile shares of PIT (lowest to highest decile) |
|---|---|---|
| ATP aces | GP P1 | 0.170, 0.110, 0.095, 0.084, 0.080, 0.077, 0.078, 0.078, 0.087, 0.142 |
| ATP aces | E2 P0 NB | 0.094, 0.098, 0.099, 0.097, 0.099, 0.102, 0.102, 0.099, 0.104, 0.105 |
| ATP aces | E2 X_bbin | 0.089, 0.093, 0.097, 0.098, 0.101, 0.103, 0.108, 0.106, 0.109, 0.097 |
| WTA aces | GP P1 | 0.153, 0.122, 0.103, 0.093, 0.086, 0.080, 0.077, 0.080, 0.083, 0.125 |
| WTA aces | E2 P0 NB | 0.099, 0.103, 0.102, 0.105, 0.099, 0.098, 0.098, 0.102, 0.097, 0.096 |
| ATP double faults | GP P1 | 0.116, 0.105, 0.098, 0.098, 0.096, 0.094, 0.093, 0.094, 0.098, 0.109 |
| ATP double faults | E2 P0 NB | 0.102, 0.104, 0.104, 0.101, 0.102, 0.101, 0.101, 0.098, 0.095, 0.094 |
| WTA double faults | GP P1 | 0.109, 0.103, 0.101, 0.099, 0.099, 0.100, 0.096, 0.096, 0.093, 0.105 |
| WTA double faults | E2 P0 NB | 0.102, 0.101, 0.102, 0.104, 0.105, 0.104, 0.100, 0.097, 0.093, 0.092 |

On aces, the E2 variants are much closer to uniform than GP P1. On double faults the two are similar. Because the samples
differ, this does not show that E2 is better. It shows that the matched comparison is the next gate.

The E2 log scores (mean log probability, higher is better, opposite sign to the NLL above) favour P1 over P0 on ATP aces and
ATP double faults. On WTA, P0 NB is better on aces and the WTA double-fault point estimate is also in P0's favour. These are
the earlier results and are not on the GP rows.

## Decision

**No direct incumbent is selected on either tour.** The brief requires a comparison of the frozen variants on identical
rows, with calibration finished, before one is chosen. Two things block that:

1. The E2 family has no row-level predictions on the GP rows, so the frozen variants cannot be compared on identical
   rows. The E2 result on WTA (P0 ahead on aces) and the GP result (P1 ahead on WTA aces) cannot yet be reconciled.
2. Neither P0 nor P1 is well calibrated for ATP aces, and P1 is too thin in the WTA ace upper tail. The P0 comparator is
   weak for aces (D8 in the state audit), so the size of P1's gain over P0 is not an estimate of the value of exposure.

For the working record only: P1 Gamma-Poisson has the lowest CRPS of the four replay candidates (P0 and P1, Poisson and
Gamma-Poisson) in all four cells, checked against the October 16 CSV, and it is the better calibrated of the two
Gamma-Poisson models in every cell. It is not a selected incumbent.

## Next steps, in order

1. Commit or review the E2 count-mixture generator (`/root/lp-tennis-props/backend/tennis_props_count_mixtures.py`) and the
   E2 replay it reads. Regenerate E2 row-level predictions for 2019 to 2026 into `research/tennis/props/` with a manifest.
2. Score every frozen variant (P0 GP, P1 GP, P0 NB, P1 NB, X_thin, X_bbin) on the intersection of rows, matched by tour,
   tournament, date, match and player. Report the intersection size. Use the same PIT code for all families.
3. Compare threshold reliability and randomized PIT by tour, surface, year, history band and forecast quartile, with
   event-clustered intervals.
4. Diagnose ATP ace under-dispersion and the WTA ace upper tail. Test one change at a time, with the hypothesis stated
   before the run (the brief's rule).
5. Choose one incumbent per tour only after steps 1 to 4. Keep the choice provisional until prospective grading exists.
6. Correct the "frozen simulator" description of E2 in `docs/TENNIS-PROPS-BASELINES-2026-10-14.md` and
   `docs/RESEARCH-tennis-player-projections-2026-10-14.md` (defect D5).

## Limits

- Development evidence. The 2015 to 2026 replay has been used in model design, and the P1 variant was added after earlier
  outcomes were inspected (stated in the baselines document). Nothing here is confirmation.
- The row-level CSV that the replay writes is about 150 MB per tour and was never committed. The JSON summaries are kept
  under `research/tennis/props/2026-10-16/`. To regenerate the CSVs, run `backend/tennis_props_rate_backtest.py` once per
  tour with `--db backend/data/picks.dev.db`.
- Coverage uses discrete intervals and is not a continuous check. PIT is the calibration test used for the decision above.
- No sportsbook line, no stake, and no betting claim is made.

## Reproduce

```bash
python3 -I research/tennis/props/2026-10-18/gp_calibration.py --db backend/data/picks.dev.db --tour atp \
  --out research/tennis/props/2026-10-18/gp_calibration_atp.json
python3 -I research/tennis/props/2026-10-18/gp_calibration.py --db backend/data/picks.dev.db --tour wta \
  --out research/tennis/props/2026-10-18/gp_calibration_wta.json
```

Each run takes about 1.5 to 2 minutes and holds a few hundred megabytes in memory.
