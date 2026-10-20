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

Final run: `run_counts_eval.py`, both tours in one process (about 7 minutes). It is deterministic: a rerun
reproduces every number in `summary.json` (checked against the first complete run, where only file names and the
leakage-check keys changed). The six winning-variant predictions reproduce their published CRPS and log scores to six
decimals when recomputed from the frozen pmfs alone.

### Verdicts

| Cell | n (matches) | Winner (clear over reference, lowest CRPS) | Runner-up | Winner minus runner-up CRPS [95% CI] | Years negative | Calibration gates | Verdict |
|---|---|---|---|---|---|---|---|
| ATP aces | 23,546 (11,773) | p1_gamma_poisson | p0_gamma_poisson | -0.0549 [-0.0596, -0.0508] | 4/4 | 7 of 7 fail | INCONCLUSIVE |
| ATP double faults | 23,546 (11,773) | p1_gamma_poisson | p0_gamma_poisson | -0.0094 [-0.0107, -0.0082] | 4/4 | 3 fail (KS, low tail, threshold) | INCONCLUSIVE |
| ATP total games | 11,766 (11,766) | direct_surface_competitive | direct_surface | -0.0061 [-0.0101, -0.0019] | 3/4 | 1 fails (KS 0.0232) | INCONCLUSIVE |
| WTA aces | 25,802 (12,901) | p1_gamma_poisson | p0_gamma_poisson | -0.0219 [-0.0246, -0.0198] | 4/4 | 6 fail (KS, tails, p95, p99, threshold) | INCONCLUSIVE |
| WTA double faults | 25,802 (12,901) | p1_gamma_poisson | p0_gamma_poisson | -0.0124 [-0.0147, -0.0102] | 4/4 | all pass | ADOPT_CANDIDATE |
| WTA total games | 13,062 (13,062) | direct_surface_competitive | direct_surface | -0.0169 [-0.0234, -0.0101] | 4/4 | all pass | ADOPT_CANDIDATE |

Against the reference, every count candidate beats C0 with an interval below zero in 4 of 4 years, so the count
reference is clearly beaten in all four count cells. Direct surface plus competitiveness beats direct format on total
games: ATP -0.0068 [-0.0127, -0.0005] (3 of 4 years), WTA -0.0181 [-0.0249, -0.0111] (4 of 4). Match-clustered
intervals agree with every sign above.

Answer to the brief's question, per cell:

- **ATP aces, ATP double faults, WTA aces: no incumbent adopted.** The best-scoring candidate is P1 Gamma-Poisson in
  each cell, and it beats its runner-up clearly, but it fails calibration. Under the declared rule the incumbent is not
  established. No incumbent is established for those cells, so nothing here supports changing a count model in production.
- **WTA double faults: P1 Gamma-Poisson is an ADOPT_CANDIDATE** on development evidence. It passes every gate.
- **Total games: direct surface plus competitiveness is the winner on both tours.** WTA is an ADOPT_CANDIDATE. ATP is
  INCONCLUSIVE on one marginal calibration miss (below). The simulator loses to every direct candidate on both tours.

Cell notes:

- **ATP aces (INCONCLUSIVE).** The winner has the lowest CRPS and log score. It is too narrow and off-centre: PIT KS
  0.077, both PIT tails near 10% against a nominal 5%, 8.0% of counts above its predicted 95th percentile (nominal 5%)
  and 3.1% above its 99th (nominal 1%), and 80 and 90% coverage of 75.6% and 86.5%. It predicts 54.8% over 4.5 against
  51.7% observed. This is the same direction the 2015 to 2026 calibration report found.
- **ATP double faults (INCONCLUSIVE).** Close to calibrated but not within the rule: PIT KS 0.029 against 0.02, a lower
  PIT tail of 6.03% against a 4 to 6% band, and an over-1.5 gap of -2.6 pp against a 2 pp limit.
- **ATP total games (INCONCLUSIVE).** Calibration fails on one gate only: PIT KS 0.0232 against 0.02. That is a marginal
  miss. The direct-format reference is also at 0.0212, and the threshold gaps are within 2 pp. The tolerance was not
  changed after the run. A decision on whether this miss matters needs a new pre-registration, not a looser number.
- **WTA aces (INCONCLUSIVE).** Upper and lower tails are too thin: 6.2% above the predicted 95th percentile (limit
  6.0%), 2.3% above the 99th (limit 1.5%), PIT tails 7.8% each, and over 1.5 predicted 64.1% against 57.4% observed. The
  2015 to 2026 calibration report found the same thin WTA ace upper tail.
- **WTA double faults (ADOPT_CANDIDATE).** PIT KS 0.0147, PIT tails 5.5% and 5.4%, coverage 63.2/86.7/94.4 (over-covers
  at 90, which the discrete intervals allow), 4.0% above p95 and 0.87% above p99, and threshold gaps of -1.3, -1.0 and
  -0.8 pp. Development evidence only: see the limits.
- **WTA total games (ADOPT_CANDIDATE).** PIT KS 0.0088, coverage 57.1/85.1/92.8, 4.4% above p95 and 0.87% above p99,
  threshold gaps of +0.8, +0.5 and +0.4 pp.
- **Simulator (not a candidate for any cell).** Total-games CRPS +0.166 ATP and +0.311 WTA over direct format, with 0 of
  4 years better. It overstates totals: over 22.5 it predicts 59.2% against 45.8% observed (ATP). The reproduced pooled
  values are 3.5327 ATP and 3.5572 WTA, matching the 2026-10-16 run.

### Population (per cell)

- Completed best-of-three main-tour matches (replay `TOUR_FILTER`). Scored window 2023-01-01 to 2026-05-17 (counts; WTA
  total games to 2026-05-25). Retirements, walkovers, defaults and abandonments are excluded from scoring and from state.
  For context, the 2026-10-16 total-games run excluded 412 ATP and 450 WTA incomplete or walkover matches over 2023 to
  2026 under the same rule. This run did not count the count-population exclusions separately.
- Serve counts (the count-cell population) are present for 100% of ATP and 99.7% to 99.9% of WTA complete best-of-three
  main-tour matches in 2023 to 2025. WTA 2026 is 91.6%. Matches without serve counts are excluded from the count cells
  only.
- Surfaces and history bands, by cell:

| Cell | Clay / Grass / Hard | Thin / middling / deep history (points) |
|---|---|---|
| ATP aces, double faults | 7,862 / 2,176 / 13,508 player-match targets | 2,654 / 5,739 / 15,153 |
| ATP total games | 3,933 / 1,079 / 6,754 matches | 2,594 / 3,786 / 5,386 |
| WTA aces, double faults | 6,568 / 2,974 / 16,260 player-match targets | 2,737 / 5,234 / 17,831 |
| WTA total games | 3,404 / 1,487 / 8,171 matches | 2,960 / 4,501 / 5,601 |

  Bands for counts are the replay's (`cold_lt10`, `mid_10_40`, `deep_ge40`, by the player's prior matches). Bands for
  total games are the replay's effective serve-point history (`thin_under_300`, `middling_300_to_1499`, `deep_1500_plus`).
- Fit: state from 2000-01-01 onward in both replays. Book-line means use the scored-replay rows before 2023: 2014 to
  2022 for counts (the replay yields rows from 2014), 2000 to 2022 for total games.
- Lines (fit means ATP aces 5.41, ATP double faults 2.80, ATP total games 22.85, WTA aces 2.62, WTA double faults 3.74,
  WTA total games 21.36): ATP aces 4.5/5.5/6.5; ATP double faults 1.5/2.5/3.5; ATP total games 21.5/22.5/23.5; WTA aces
  1.5/2.5/3.5; WTA double faults 2.5/3.5/4.5; WTA total games 20.5/21.5/22.5. These are rule-based, not market lines.

### Frozen predictions

`predictions/` holds one gzipped CSV per cell for the lowest-pooled-CRPS candidate, which is the verdict winner in every
cell: one row per scored row, with the observed count, the predicted mean and the full pmf from `support_start`
(probabilities below 1e-12 at each end trimmed; the trimmed mass is below 2e-12). Files: `atp_aces_p1_gamma_poisson`,
`atp_double_faults_p1_gamma_poisson`, `atp_games_direct_surface_competitive`, `wta_aces_p1_gamma_poisson`,
`wta_double_faults_p1_gamma_poisson`, `wta_games_direct_surface_competitive` (`.csv.gz`, 14 MB in total). Decompress with
`gzip -dk`. Recomputing CRPS (energy form, E|X-X'| from the CDF) and log score from the pmf reproduces the published
values to six decimals for all six files.

### Scoring tables (generated by `run_counts_eval.py`; copied from `TABLES.md`)


Produced by `run_counts_eval.py` from `summary.json`. Differences are candidate minus reference.
CI is the 95% cluster bootstrap (tournament clusters; match clusters in the JSON as sensitivity).

### ATP aces

n = 23546 player-match targets (11773 matches); years {'2023': 6894, '2024': 7140, '2025': 6380, '2026': 3132}; lines [4.5, 5.5, 6.5].

| model | CRPS | dCRPS vs ref [95% CI] | log score | dlog [95% CI] | cov 50/80/90 | PIT KS | PIT <0.05 / >0.95 | >p95 / >p99 | calibrated |
|---|---:|---|---:|---|---|---:|---|---|---|
| C0 | 2.37552 | (ref) | 3.14010 | (ref) | 41.2/63.9/72.3 | 0.1554 | 17.6 / 15.7 | 14.3 / 7.64 | no |
| p0_poisson | 2.09232 | -0.28320 [-0.32596, -0.23651] | 2.84838 | -0.29172 [-0.33176, -0.25047] | 43.3/67.4/78.0 | 0.1323 | 15.0 / 13.4 | 11.5 / 5.89 | no |
| p0_gamma_poisson | 2.08776 | -0.28776 [-0.33021, -0.24093] | 2.82893 | -0.31117 [-0.35096, -0.26991] | 43.7/68.1/78.4 | 0.1287 | 14.6 / 13.1 | 11.3 / 5.67 | no |
| p1_poisson | 2.08967 | -0.28585 [-0.32732, -0.23889] | 2.84601 | -0.29409 [-0.33412, -0.25232] | 43.5/67.4/78.1 | 0.1298 | 14.8 / 13.3 | 11.6 / 5.89 | no |
| p1_gamma_poisson | 2.03281 | -0.34271 [-0.38197, -0.29946] | 2.64633 | -0.49377 [-0.53293, -0.45141] | 49.8/75.6/86.5 | 0.0769 | 10.0 / 9.5 | 8.0 / 3.06 | no |

Threshold reliability at the book-style lines (predicted vs observed P(over), Brier):

| model | over 4.5 | over 5.5 | over 6.5 |
|---|---|---|---|
| C0 | 60.3 vs 51.7, B 0.2457 | 45.4 vs 42.1, B 0.2352 | 31.9 vs 34.2, B 0.2151 |
| p0_poisson | 58.2 vs 51.7, B 0.2112 | 44.6 vs 42.1, B 0.2033 | 32.7 vs 34.2, B 0.1879 |
| p0_gamma_poisson | 58.1 vs 51.7, B 0.2107 | 44.6 vs 42.1, B 0.2031 | 32.8 vs 34.2, B 0.1878 |
| p1_poisson | 57.9 vs 51.7, B 0.2110 | 44.4 vs 42.1, B 0.2035 | 32.6 vs 34.2, B 0.1882 |
| p1_gamma_poisson | 54.8 vs 51.7, B 0.2063 | 42.8 vs 42.1, B 0.2006 | 32.6 vs 34.2, B 0.1858 |

CRPS by year: C0 2023 2.3192, 2024 2.4085, 2025 2.3906, 2026 2.3936; p0_poisson 2023 2.0134, 2024 2.1008, 2025 2.1138, 2026 2.2029; p0_gamma_poisson 2023 2.0087, 2024 2.0964, 2025 2.1093, 2026 2.1982; p1_poisson 2023 2.0105, 2024 2.0971, 2025 2.1134, 2026 2.1988; p1_gamma_poisson 2023 1.9573, 2024 2.0429, 2025 2.0559, 2026 2.1289

**Decision:** INCONCLUSIVE; winner (clear over reference, lowest CRPS) p1_gamma_poisson; runner-up p0_gamma_poisson; calibrated False; lowest pooled CRPS overall p1_gamma_poisson.

### ATP double_faults

n = 23546 player-match targets (11773 matches); years {'2023': 6894, '2024': 7140, '2025': 6380, '2026': 3132}; lines [1.5, 2.5, 3.5].

| model | CRPS | dCRPS vs ref [95% CI] | log score | dlog [95% CI] | cov 50/80/90 | PIT KS | PIT <0.05 / >0.95 | >p95 / >p99 | calibrated |
|---|---:|---|---:|---|---|---:|---|---|---|
| C0 | 1.15316 | (ref) | 2.11434 | (ref) | 64.1/76.4/92.1 | 0.0888 | 9.8 / 9.0 | 7.2 / 2.89 | no |
| p0_poisson | 1.06913 | -0.08403 [-0.09170, -0.07559] | 2.00782 | -0.10652 [-0.11651, -0.09587] | 59.7/83.8/92.3 | 0.0677 | 8.4 / 7.9 | 5.8 / 2.18 | no |
| p0_gamma_poisson | 1.06786 | -0.08530 [-0.09299, -0.07684] | 2.00158 | -0.11275 [-0.12283, -0.10204] | 60.3/84.3/92.6 | 0.0640 | 8.2 / 7.6 | 5.7 / 2.04 | no |
| p1_poisson | 1.06902 | -0.08415 [-0.09155, -0.07571] | 2.00775 | -0.10659 [-0.11661, -0.09593] | 59.9/83.7/92.3 | 0.0676 | 8.3 / 7.8 | 5.8 / 2.19 | no |
| p1_gamma_poisson | 1.05849 | -0.09467 [-0.10208, -0.08635] | 1.96644 | -0.14790 [-0.15966, -0.13529] | 64.0/88.7/95.5 | 0.0289 | 6.0 / 5.6 | 4.2 / 1.13 | no |

Threshold reliability at the book-style lines (predicted vs observed P(over), Brier):

| model | over 1.5 | over 2.5 | over 3.5 |
|---|---|---|---|
| C0 | 74.0 vs 65.0, B 0.2355 | 49.2 vs 43.3, B 0.2490 | 27.4 vs 27.0, B 0.1971 |
| p0_poisson | 71.5 vs 65.0, B 0.2188 | 47.7 vs 43.3, B 0.2297 | 27.7 vs 27.0, B 0.1816 |
| p0_gamma_poisson | 71.1 vs 65.0, B 0.2184 | 47.5 vs 43.3, B 0.2295 | 27.7 vs 27.0, B 0.1816 |
| p1_poisson | 71.4 vs 65.0, B 0.2187 | 47.6 vs 43.3, B 0.2297 | 27.6 vs 27.0, B 0.1816 |
| p1_gamma_poisson | 67.6 vs 65.0, B 0.2152 | 45.6 vs 43.3, B 0.2280 | 28.0 vs 27.0, B 0.1813 |

CRPS by year: C0 2023 1.1651, 2024 1.1534, 2025 1.1839, 2026 1.0639; p0_poisson 2023 1.0764, 2024 1.0603, 2025 1.1114, 2026 0.9870; p0_gamma_poisson 2023 1.0750, 2024 1.0591, 2025 1.1103, 2026 0.9857; p1_poisson 2023 1.0759, 2024 1.0610, 2025 1.1117, 2026 0.9853; p1_gamma_poisson 2023 1.0658, 2024 1.0501, 2025 1.1010, 2026 0.9747

**Decision:** INCONCLUSIVE; winner (clear over reference, lowest CRPS) p1_gamma_poisson; runner-up p0_gamma_poisson; calibrated False; lowest pooled CRPS overall p1_gamma_poisson.

### ATP games

n = 11766 matches (11766 matches); years {'2023': 3448, '2024': 3561, '2025': 3191, '2026': 1566}; lines [21.5, 22.5, 23.5].

| model | CRPS | dCRPS vs ref [95% CI] | log score | dlog [95% CI] | cov 50/80/90 | PIT KS | PIT <0.05 / >0.95 | >p95 / >p99 | calibrated |
|---|---:|---|---:|---|---|---:|---|---|---|
| direct_format | 3.36637 | (ref) | 3.05601 | (ref) | 59.1/86.3/93.3 | 0.0212 | 4.0 / 5.3 | 4.7 / 0.96 | no |
| direct_surface | 3.36563 | -0.00074 [-0.00471, +0.00315] | 3.05949 | +0.00348 [-0.00090, +0.00876] | 57.9/85.7/93.0 | 0.0224 | 3.9 / 5.5 | 4.9 / 0.95 | no |
| direct_surface_competitive | 3.35956 | -0.00681 [-0.01267, -0.00054] | 3.06563 | +0.00962 [+0.00176, +0.01942] | 56.1/84.7/92.8 | 0.0232 | 4.0 / 5.5 | 4.6 / 0.88 | no |
| simulator | 3.53266 | +0.16628 [+0.13622, +0.19650] | 3.10589 | +0.04988 [+0.03792, +0.06164] | 51.7/79.0/89.1 | 0.1358 | 11.9 / 3.2 | 2.2 / 0.38 | no |

Threshold reliability at the book-style lines (predicted vs observed P(over), Brier):

| model | over 21.5 | over 22.5 | over 23.5 |
|---|---|---|---|
| direct_format | 52.1 vs 54.0, B 0.2488 | 44.6 vs 45.8, B 0.2485 | 38.9 vs 40.1, B 0.2404 |
| direct_surface | 52.0 vs 54.0, B 0.2487 | 44.5 vs 45.8, B 0.2486 | 38.8 vs 40.1, B 0.2406 |
| direct_surface_competitive | 52.0 vs 54.0, B 0.2478 | 44.5 vs 45.8, B 0.2479 | 38.9 vs 40.1, B 0.2400 |
| simulator | 67.3 vs 54.0, B 0.2632 | 59.2 vs 45.8, B 0.2643 | 52.7 vs 40.1, B 0.2552 |

CRPS by year: direct_format 2023 3.3912, 2024 3.3250, 2025 3.3562, 2026 3.4265; direct_surface 2023 3.3946, 2024 3.3241, 2025 3.3517, 2026 3.4245; direct_surface_competitive 2023 3.3872, 2024 3.3157, 2025 3.3441, 2026 3.4297; simulator 2023 3.5354, 2024 3.5126, 2025 3.5171, 2026 3.6037

**Decision:** INCONCLUSIVE; winner (clear over reference, lowest CRPS) direct_surface_competitive; runner-up direct_surface; calibrated False; lowest pooled CRPS overall direct_surface_competitive.

### WTA aces

n = 25802 player-match targets (12901 matches); years {'2023': 7558, '2024': 7762, '2025': 7262, '2026': 3220}; lines [1.5, 2.5, 3.5].

| model | CRPS | dCRPS vs ref [95% CI] | log score | dlog [95% CI] | cov 50/80/90 | PIT KS | PIT <0.05 / >0.95 | >p95 / >p99 | calibrated |
|---|---:|---|---:|---|---|---:|---|---|---|
| C0 | 1.45075 | (ref) | 2.42899 | (ref) | 42.3/71.3/87.6 | 0.1553 | 14.7 / 13.0 | 10.6 / 6.17 | no |
| p0_poisson | 1.22969 | -0.22106 [-0.24413, -0.19689] | 2.13225 | -0.29674 [-0.32520, -0.26948] | 56.3/80.0/89.2 | 0.1140 | 10.8 / 10.0 | 8.0 / 3.74 | no |
| p0_gamma_poisson | 1.22703 | -0.22372 [-0.24662, -0.19977] | 2.12019 | -0.30880 [-0.33732, -0.28143] | 56.7/80.7/89.4 | 0.1108 | 10.4 / 9.8 | 7.8 / 3.65 | no |
| p1_poisson | 1.22856 | -0.22220 [-0.24574, -0.19771] | 2.13100 | -0.29799 [-0.32643, -0.27034] | 56.5/80.0/89.1 | 0.1118 | 10.7 / 10.1 | 8.0 / 3.74 | no |
| p1_gamma_poisson | 1.20510 | -0.24565 [-0.26767, -0.22294] | 2.03449 | -0.39451 [-0.42351, -0.36671] | 60.9/85.9/92.6 | 0.0733 | 7.8 / 7.8 | 6.2 / 2.25 | no |

Threshold reliability at the book-style lines (predicted vs observed P(over), Brier):

| model | over 1.5 | over 2.5 | over 3.5 |
|---|---|---|---|
| C0 | 72.3 vs 57.4, B 0.2634 | 48.0 vs 41.0, B 0.2434 | 27.1 vs 28.6, B 0.2013 |
| p0_poisson | 67.8 vs 57.4, B 0.2132 | 46.3 vs 41.0, B 0.2023 | 28.9 vs 28.6, B 0.1689 |
| p0_gamma_poisson | 67.5 vs 57.4, B 0.2121 | 46.2 vs 41.0, B 0.2020 | 29.0 vs 28.6, B 0.1690 |
| p1_poisson | 67.5 vs 57.4, B 0.2127 | 46.1 vs 41.0, B 0.2025 | 28.9 vs 28.6, B 0.1692 |
| p1_gamma_poisson | 64.1 vs 57.4, B 0.2060 | 44.1 vs 41.0, B 0.1992 | 28.6 vs 28.6, B 0.1679 |

CRPS by year: C0 2023 1.4480, 2024 1.4419, 2025 1.4648, 2026 1.4469; p0_poisson 2023 1.1968, 2024 1.2131, 2025 1.2733, 2026 1.2487; p0_gamma_poisson 2023 1.1939, 2024 1.2106, 2025 1.2706, 2026 1.2462; p1_poisson 2023 1.1952, 2024 1.2118, 2025 1.2725, 2026 1.2481; p1_gamma_poisson 2023 1.1700, 2024 1.1906, 2025 1.2487, 2026 1.2243

**Decision:** INCONCLUSIVE; winner (clear over reference, lowest CRPS) p1_gamma_poisson; runner-up p0_gamma_poisson; calibrated False; lowest pooled CRPS overall p1_gamma_poisson.

### WTA double_faults

n = 25802 player-match targets (12901 matches); years {'2023': 7558, '2024': 7762, '2025': 7262, '2026': 3220}; lines [2.5, 3.5, 4.5].

| model | CRPS | dCRPS vs ref [95% CI] | log score | dlog [95% CI] | cov 50/80/90 | PIT KS | PIT <0.05 / >0.95 | >p95 / >p99 | calibrated |
|---|---:|---|---:|---|---|---:|---|---|---|
| C0 | 1.48092 | (ref) | 2.41592 | (ref) | 57.6/78.0/83.9 | 0.1023 | 11.3 / 10.5 | 9.0 / 3.72 | no |
| p0_poisson | 1.33162 | -0.14930 [-0.15884, -0.13951] | 2.25551 | -0.16041 [-0.17053, -0.15038] | 56.6/79.4/88.8 | 0.0718 | 9.2 / 8.9 | 6.9 / 2.59 | no |
| p0_gamma_poisson | 1.32996 | -0.15096 [-0.16042, -0.14123] | 2.24895 | -0.16697 [-0.17721, -0.15733] | 57.0/79.8/89.2 | 0.0684 | 9.0 / 8.6 | 6.6 / 2.47 | no |
| p1_poisson | 1.33469 | -0.14624 [-0.15531, -0.13681] | 2.25837 | -0.15754 [-0.16746, -0.14765] | 56.5/79.2/88.7 | 0.0727 | 9.2 / 8.9 | 6.9 / 2.61 | no |
| p1_gamma_poisson | 1.31752 | -0.16340 [-0.17198, -0.15473] | 2.19704 | -0.21888 [-0.23153, -0.20615] | 63.2/86.7/94.4 | 0.0147 | 5.5 / 5.4 | 4.0 / 0.87 | yes |

Threshold reliability at the book-style lines (predicted vs observed P(over), Brier):

| model | over 2.5 | over 3.5 | over 4.5 |
|---|---|---|---|
| C0 | 71.7 vs 61.7, B 0.2465 | 50.9 vs 45.2, B 0.2517 | 31.6 vs 31.2, B 0.2152 |
| p0_poisson | 68.3 vs 61.7, B 0.2167 | 49.1 vs 45.2, B 0.2211 | 32.1 vs 31.2, B 0.1913 |
| p0_gamma_poisson | 68.0 vs 61.7, B 0.2163 | 49.0 vs 45.2, B 0.2209 | 32.1 vs 31.2, B 0.1913 |
| p1_poisson | 68.2 vs 61.7, B 0.2172 | 49.1 vs 45.2, B 0.2218 | 32.0 vs 31.2, B 0.1920 |
| p1_gamma_poisson | 63.0 vs 61.7, B 0.2133 | 46.1 vs 45.2, B 0.2201 | 32.0 vs 31.2, B 0.1913 |

CRPS by year: C0 2023 1.4677, 2024 1.5123, 2025 1.4848, 2026 1.4274; p0_poisson 2023 1.3118, 2024 1.3516, 2025 1.3585, 2026 1.2693; p0_gamma_poisson 2023 1.3101, 2024 1.3498, 2025 1.3570, 2026 1.2677; p1_poisson 2023 1.3141, 2024 1.3545, 2025 1.3625, 2026 1.2726; p1_gamma_poisson 2023 1.2963, 2024 1.3359, 2025 1.3477, 2026 1.2551

**Decision:** ADOPT_CANDIDATE; winner (clear over reference, lowest CRPS) p1_gamma_poisson; runner-up p0_gamma_poisson; calibrated True; lowest pooled CRPS overall p1_gamma_poisson.

### WTA games

n = 13062 matches (13062 matches); years {'2023': 3781, '2024': 3892, '2025': 3631, '2026': 1758}; lines [20.5, 21.5, 22.5].

| model | CRPS | dCRPS vs ref [95% CI] | log score | dlog [95% CI] | cov 50/80/90 | PIT KS | PIT <0.05 / >0.95 | >p95 / >p99 | calibrated |
|---|---:|---|---:|---|---|---:|---|---|---|
| direct_format | 3.24659 | (ref) | 3.03204 | (ref) | 57.2/85.1/93.6 | 0.0089 | 4.4 / 5.1 | 4.5 / 0.87 | yes |
| direct_surface | 3.24539 | -0.00120 [-0.00338, +0.00080] | 3.03743 | +0.00539 [+0.00188, +0.00891] | 56.4/84.8/93.6 | 0.0094 | 4.4 / 5.2 | 4.3 / 0.82 | yes |
| direct_surface_competitive | 3.22852 | -0.01806 [-0.02492, -0.01105] | 3.04719 | +0.01515 [+0.00686, +0.02413] | 57.1/85.1/92.8 | 0.0088 | 4.5 / 5.1 | 4.4 / 0.87 | yes |
| simulator | 3.55718 | +0.31059 [+0.28488, +0.34064] | 3.14471 | +0.11267 [+0.10282, +0.12347] | 48.6/76.8/86.9 | 0.1803 | 14.8 / 2.7 | 2.1 / 0.45 | no |

Threshold reliability at the book-style lines (predicted vs observed P(over), Brier):

| model | over 20.5 | over 21.5 | over 22.5 |
|---|---|---|---|
| direct_format | 47.5 vs 48.3, B 0.2499 | 42.8 vs 43.3, B 0.2456 | 37.5 vs 37.9, B 0.2353 |
| direct_surface | 47.6 vs 48.3, B 0.2499 | 42.8 vs 43.3, B 0.2456 | 37.5 vs 37.9, B 0.2354 |
| direct_surface_competitive | 47.6 vs 48.3, B 0.2481 | 42.8 vs 43.3, B 0.2441 | 37.5 vs 37.9, B 0.2340 |
| simulator | 65.9 vs 48.3, B 0.2789 | 60.9 vs 43.3, B 0.2748 | 54.2 vs 37.9, B 0.2611 |

CRPS by year: direct_format 2023 3.2810, 2024 3.2550, 2025 3.2408, 2026 3.1660; direct_surface 2023 3.2816, 2024 3.2537, 2025 3.2373, 2026 3.1658; direct_surface_competitive 2023 3.2633, 2024 3.2365, 2025 3.2239, 2026 3.1456; simulator 2023 3.5968, 2024 3.5768, 2025 3.5321, 2026 3.4801

**Decision:** ADOPT_CANDIDATE; winner (clear over reference, lowest CRPS) direct_surface_competitive; runner-up direct_surface; calibrated True; lowest pooled CRPS overall direct_surface_competitive.


### Deviations from the pre-registration (all disclosed)

1. **Two crashed runs, no output.** The first two runs stopped with a `ZeroDivisionError` before writing anything. The
   causes were in my code: C0 was computed for 2014, which has no prior year (the rolling pipeline starts C0 in 2015),
   and the prior-year buckets were updated under the wrong year key. Both are fixed. No score was produced by a crashed
   run. The fixed run reproduces the rolling pipeline's per-year CRPS for every count and total-games model to 1e-6.
2. **Leakage check scope.** The first complete run counted cap-driven rows over all rows, including the pre-2023 fit
   rows: 3 to 4 flags per model, all WTA, all outside the scored window. The final run counts only scored rows. It
   reports zero flags for every model on both tours. The pre-registered expectation of zero holds for scored rows.
3. **Predictions gzipped.** The pre-registration says CSV or JSONL. The predictions are gzipped CSV because the plain
   files were 69 MB. The contents are identical and reconstruct the published scores.
4. **Count line means use 2014 to 2022.** The pre-registration says fit period 2000 to 2022. The count replay yields
   rows from 2014, so the count book-line means use 2014 to 2022 rows (state still starts in 2000).
5. **Per-cell selection.** The brief asks for one selection per cell. The rolling protocol pooled both tours. This run
   applies the same rule per cell, as the brief requires.

### Next gate

- **Calibration repair for ATP aces, ATP double faults, WTA aces (and the ATP total-games miss).** One change at a time,
  with the hypothesis written before the run, on the same rolling-origin table. For the ace cells the target is dispersion
  and the upper tail. For double faults it is the lower PIT tail and the over-1.5 threshold. For total games it is the
  KS miss. Any change needs its own pre-registration.
- **Prospective confirmation (CP4) for the two ADOPT_CANDIDATEs.** Freeze full count and games distributions before play
  (the current lock table stores none), grade them against official results, and report coverage on the 100, 250, 500
  and 1,000-match windows the brief names. These are development results until that exists.
- **Production (CP5) is Micah's decision.** Nothing here changes a lock writer, a live version or `dev`.

### Limits

- **No untouched window.** The 2023 to 2026 window was scored in the 2015 to 2026 development replays (rolling
  validation and calibration, 2026-10-18) and in the total-games backtest (2026-10-16). The P1 Gamma-Poisson design
  was added after earlier outcomes had been inspected (`docs/TENNIS-PROPS-CALIBRATION-2026-10-18.md`, Limits). Every
  verdict here is development evidence, and the ADOPT_CANDIDATEs are not confirmation.
- **Calibration tolerances were fixed before the run, and the verdicts depend on them.** The ATP total-games miss is
  0.0032 above the KS tolerance. WTA double faults passes its gates with margins of about 0.5 pp on the PIT tails and
  at least 0.7 pp on the threshold gaps; KS is 0.0147 against 0.02. The margins are real but small.
- The verdicts cover 2023 to 2026 data, with 2026 partial (about 1,570 to 1,760 matches per tour in 2026).
- Sackmann records are CC BY-NC-SA and research-only. Recorded here, not resolved.
- The simulator fails the service-point exposure gate. It was used only as a total-games candidate, and the count cells
  do not depend on it.
- No sportsbook price, stake or betting claim is made. The lines are rule-based.
