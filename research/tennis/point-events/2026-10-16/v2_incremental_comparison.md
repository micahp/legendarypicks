# Elo-informed simulator V2: matched incremental comparison

- **Run date:** 2026-10-16
- **Status:** Historical development evidence; V2 remains a research challenger
- **Test period:** 2022–2024
- **Validation period:** 2021
- **Primary question:** Do point-model features add winner information beyond calibrated Elo, and does V2 improve total-games forecasts over the direct historical distribution?

## Sample and comparison design

All winner and total-games methods were scored on the same 2,749 verified, completed best-of-three matches: 1,272 ATP and 1,477 WTA. The point histories were verified against tour, year, tournament and both player identities; the sample has 2,041 Match Charting Project and 708 Grand Slam Archive histories. The US Open and Kalshi captures are from 2026 and do not overlap this 2022–2024 test. The matches span 300 tournament clusters (167 ATP, 133 WTA); uncertainty intervals resample tournament clusters, not individual points.

The 2021 validation set has 623 verified matches. Each winner forecast was calibrated on that set using a side-symmetric logistic fit. The no-simulation challenger is a logistic model combining Elo log-odds with the difference between the two players' direct point-model log-odds. A sensitivity version uses the Elo-informed point features. The direct total-games model is the prior-only format, surface and competitiveness distribution from the existing walk-forward backtest.

## Match-winner Brier

Lower is better.

| Tour | Matches | Calibrated Elo | Elo + raw point features | Elo + Elo-informed point features | Elo-informed V2 |
|---|---:|---:|---:|---:|---:|
| ATP | 1,272 | 0.21287 | 0.21257 | 0.21224 | **0.20960** |
| WTA | 1,477 | **0.20178** | 0.20437 | 0.20372 | 0.20205 |
| Combined | 2,749 | 0.20691 | 0.20816 | 0.20766 | **0.20554** |

The pooled V2-minus-Elo Brier difference is **−0.00137** (95% tournament-cluster bootstrap interval **−0.00393 to +0.00108**). The improvement over Elo is not established on the pooled sample. The ATP-only difference is −0.00327 (interval −0.00654 to −0.00009); WTA is +0.00027 (−0.00379 to +0.00381). The ATP-only result is exploratory, has already been inspected in the prior V2 analysis, and does not establish an advantage across tours.

The non-simulation point-feature models did not improve on Elo: raw point features changed pooled Brier by +0.00125 (95% interval −0.00058 to +0.00280); Elo-informed point features changed it by +0.00075 (−0.00085 to +0.00213). On this test set, V2's promising winner result is not reproduced by simply adding a linear point-feature signal to Elo.

## Total-games distribution

The direct format, surface and competitiveness distribution is better than V2 on this exact sample.

| Tour | Matches | Observed mean games | V2 mean | Direct mean | V2 CRPS | Direct CRPS | V2 − direct CRPS (95% tournament-cluster interval) |
|---|---:|---:|---:|---:|---:|---:|---:|
| ATP | 1,272 | 22.855 | 23.520 | 23.166 | 3.567 | **3.393** | +0.173 (+0.094 to +0.253) |
| WTA | 1,477 | 21.531 | 22.510 | 21.763 | 3.347 | **3.222** | +0.126 (+0.056 to +0.203) |
| Combined | 2,749 | 22.143 | 22.977 | 22.412 | 3.449 | **3.301** | +0.148 (+0.096 to +0.204) |

The same ranking holds for every reported total-games threshold Brier score:

| Over threshold | V2 Brier | Direct-distribution Brier |
|---:|---:|---:|
| 18.5 | 0.23448 | **0.22185** |
| 20.5 | 0.26319 | **0.24814** |
| 22.5 | 0.24820 | **0.23350** |
| 24.5 | 0.22549 | **0.21389** |
| 26.5 | 0.19326 | **0.18482** |

Thus V2 improves total-games CRPS against the original simulator, but it does not beat the direct historical baseline on the verified match population. The direct model also reduces the remaining mean overprediction from +0.83 games to +0.27.

## Reading the result

V2 is a substantial improvement over the original point simulator on match-winner Brier, but its pooled advantage over calibrated Elo is uncertain. Adding point features to Elo without simulation did not show incremental winner value. For total games, the direct distribution remains the stronger reference, on CRPS and all five threshold Brier scores.

Keep calibrated Elo as the winner reference and the direct historical distribution as the total-games reference. Keep V2 frozen as a research challenger while prospective records accumulate; this run does not support promoting it as the winner or total-games incumbent.

## Prospective ledger

The isolated ledger implementation is [`backend/tennis_v2_research_ledger.py`](../../../../backend/tennis_v2_research_ledger.py). It stores immutable pre-match forecasts, full total-games distributions, calibration/version metadata and separate grades in `backend/data/tennis_v2_research.sqlite3`, which is ignored by Git. It records calibrated Elo, Elo plus point features, V2, and the direct total-games comparator. The point-history inputs are frozen through 2024 to match the historical experiment; Elo and direct-game histories update through the forecast date. No sportsbook odds are used. To capture newly scheduled matches and grade finals, run `python3 backend/tennis_v2_research_ledger.py --db backend/data/picks.dev.db --days 3`.

The first run locked four matches at **2026-10-16 22:04 UTC**, before their scheduled starts, with all player identities resolved. Probabilities are for the first listed player; expected-games entries show direct / V2 distributions.

| Scheduled start UTC | Match | Calibrated Elo | Elo + point features | V2 | Expected games: direct / V2 |
|---|---|---:|---:|---:|---:|
| Oct 17 08:30 | Alexander Zverev–Alejandro Davidovich Fokina | 0.7523 | 0.7648 | 0.7801 | 22.38 / 21.32 |
| Oct 17 09:00 | Sonay Kartal–Jelena Ostapenko | 0.5007 | 0.4983 | 0.4875 | 23.00 / 24.44 |
| Oct 17 10:30 | Iga Swiatek–Maja Chwalinska | 0.7676 | 0.7879 | 0.8770 | 22.38 / 18.05 |
| Oct 17 11:00 | Rafael Jodar–Daniil Medvedev | 0.4228 | 0.4009 | 0.3297 | 22.82 / 23.57 |

These are the initial prospective locks, not enough outcomes to grade a model. The ledger is implemented but is not yet connected to a recurring job; subsequent captures and grading require running the command above.

Historical source attribution and terms are recorded once in the [tennis data document](../../../../docs/TENNIS-DATA-2026-10-13.md).

## Reproduction and source artifacts

- Aggregate matched scores and tournament-cluster intervals: [`v2_incremental_comparison.json`](v2_incremental_comparison.json)
- Direct historical distribution method: [`backend/tennis_total_games_backtest.py`](../../../../backend/tennis_total_games_backtest.py)
- Point archive crosswalk and feature definitions: [`analyze_archives.py`](analyze_archives.py)
- Original point-event model diagnostics: [`findings.md`](findings.md)
