# Tennis direct incumbents: aces, double faults and total games (Track B)

- **Date:** 2026-10-20. **Branch:** `research/tennis-counts-2026-10-20` (from `feat/tennis-track-b-2026-10-18` @ `692b1901`).
- **Status:** Development evidence. Not prospective confirmation (CP4 open). No production code touched; nothing merged to `dev`.
- **Entry point:** `run_counts_eval.py` (this directory). It reproduces every number below. Generated tables: `TABLES.md`.
  Per-cell numbers and paired intervals: `summary.json`. Per-match frozen predictions for the lowest-CRPS candidate in each cell:
  `predictions/`.
- **Reproduce:**
  `python3 -I research/tennis/counts-2026-10-20/run_counts_eval.py --db /root/legendarypicks/backend/data/picks.dev.db`
  (the database is gitignored and lives in the main checkout; it is opened read-only).

## Pre-registration (written and committed before the first run)

### Question

For each cell (aces, double faults, total games; ATP and WTA), which frozen candidate is the direct incumbent? Each cell
is selected independently, as the brief requires. The rolling protocol of 2026-10-18 pooled both tours; this run applies
the same rule per cell.

### Candidates (frozen; no new family)

| Cell | Reference | Candidates |
|---|---|---|
| Aces, double faults | C0: prior calendar-year tour and surface mean per player-match, Poisson | P0 Poisson, P0 Gamma-Poisson, P1 Poisson, P1 Gamma-Poisson (`backend/tennis_props_rate_backtest.py`, unchanged) |
| Total games | Direct format histogram (`direct_format`) | Direct format plus surface; direct format plus surface plus competitiveness; point simulator (`backend/tennis_total_games_backtest.py`, unchanged, histogram start 2000 as in the rolling protocol) |

No candidate is refitted. Every forecast uses only matches dated before its event-start date.

### Populations

- **Counts:** completed best-of-three main-tour matches, as defined by the replay (`TOUR_FILTER`, surface recorded, valid
  serve counts). Each match gives two player-match targets, with randomized sides (seed 20261016 in the replay).
- **Total games:** completed best-of-three main-tour matches with a parseable score. Grand Slam best-of-three matches from
  2022 use the 10-point final-set tiebreak; a match tiebreak in brackets adds no games.
- **Retirements and walkovers:** any score containing `RET`, `W/O`, `DEF` or `ABD` is excluded from scoring and from state
  in both replays. This is the handling already stated in the existing research, and it is kept.
- **Stat coverage (checked against the replay's filter, 2026-10-20):** serve counts are present for 100% of complete
  best-of-three main-tour matches in ATP 2023 to 2026, and for 99.7% to 99.9% in WTA 2023 to 2025. WTA 2026 is 91.6%
  (1,610 of 1,758). Matches without serve counts are excluded from the count cells, and that exclusion is the only
  population difference from the total-games cells. The low coverage elsewhere in the database comes from Challenger and
  ITF rows, which the replay also excludes.

### Window

- **Fit (state only, not scored):** 2000-01-01 to 2022-12-31.
- **Scored window:** 2023-01-01 to the last scoreable date (counts: 2026-05-17; total games: ATP 2026-05-17, WTA 2026-05-25).

### Book-style lines (rule fixed before the run)

Lines are set from the fit period only, never from the window. Let `m` be the fit-period mean outcome of the cell.
Centre `c = floor(m) + 0.5`, and the lines are `c - 1`, `c`, `c + 1`. A line `L` means over `L` = count of at least
`floor(L) + 1`.

### Scores (per cell, per model)

CRPS (primary) and log score, from the replay's own functions. Central 50, 80 and 90% coverage. Randomized PIT, with the
same uniform draw shared by all models on a row: decile shares, Kolmogorov distance (KS), and shares below 0.05 and above
0.95. Share of observed counts above the predicted 95th and 99th percentile (nominal at most 5% and 1%). Predicted and
observed probability of over each line, with the gap, and Brier at each line. Paired differences against the reference
and against the runner-up, with a cluster bootstrap (1,000 resamples, seed 20261020). The verdict uses tournament
clusters, which are the more conservative choice; match clusters are reported as a sensitivity.

### Calibration gates (a candidate passes only if all hold)

| Gate | Rule |
|---|---|
| PIT uniformity | KS ≤ 0.02 |
| PIT tails | share below 0.05 and share above 0.95 each in [0.04, 0.06] |
| Coverage | observed 50, 80 and 90% coverage each ≥ nominal − 0.02 (over-coverage is allowed: the intervals are discrete) |
| Upper tail | share above predicted p95 ≤ 0.06; share above predicted p99 ≤ 0.015 |
| Threshold reliability | at each line, |observed − predicted| ≤ 0.02 |

### Selection and verdict (rule fixed before the run)

Let `R` be the reference, `W` the lowest pooled-CRPS candidate that clearly beats `R`, and `U` the lowest pooled-CRPS
candidate other than `W`.

- **Clearly beats** `R`: event-clustered 95% interval for the CRPS difference entirely below zero, and negative in at least
  3 of the 4 window years (9-of-12 years in the rolling protocol, scaled to four years).
- **Verdict:**
  - `NOT_ADOPTED`: no candidate clearly beats `R`. The reference stays.
  - `ADOPT_CANDIDATE`: `W` clearly beats `U` by the same test, and `W` passes every calibration gate.
  - `INCONCLUSIVE`: `W` beats `R` clearly, but either it does not clearly beat `U`, or it fails a calibration gate.
    The incumbent is not established for that cell.
  - `INSUFFICIENT_DATA`: window rows below 5,000, matches below 2,000, or any window year with no rows. Not expected here.

"Lowest CRPS overall" is also reported for each cell. It sets which candidate's per-match predictions are written to
`predictions/`.

### Verification anchors (the run stops on mismatch)

- Count CRPS per year and model (2023 to 2026) equals `research/tennis/rolling/2026-10-18/rolling_summary.json` within 1e-6.
- Total-games CRPS per year and model equals the same file.
- Simulator pooled CRPS equals `research/tennis/total-games/2026-10-16/{atp,wta}.json` to four decimals (3.5327 ATP,
  3.5572 WTA on the earlier run's window).

### Leakage checks

- The replay sets a count distribution's support cap from the observed count when the observed count is larger than the
  forecast's cap, which would let the outcome shape the distribution. The script counts rows where the observed count is
  above the forecast mean plus 12 standard deviations plus 30, and reports them per model. Expected: zero.

## Limits stated before the run

- **No untouched window exists.** The 2023 to 2026 window was scored in the 2015 to 2026 development replays (rolling
  validation and calibration, 2026-10-18) and in the total-games backtest (2026-10-16). The calibration report states that
  the P1 variant was added after earlier outcomes were inspected (`docs/TENNIS-PROPS-CALIBRATION-2026-10-18.md`, Limits). Post-window rows in the database are either
  without serve counts (so excluded from counts) or were already scored on 2026-10-16 (WTA total games to 2026-05-25).
  Any verdict here is development evidence.
- Prospective ace and double-fault distributions were not stored by the locks (BRIEF, checkpoint CP4). Prospective
  scoring of these targets is not possible yet.
- Sackmann records are CC BY-NC-SA and research-only. Recorded here, not resolved.
- The simulator fails the service-point exposure gate. It is a total-games candidate only, and this run does not depend on
  it for the count cells.

## Results

_To be filled from the run._
