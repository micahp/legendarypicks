# RESULTS: NFL features against the market, 2026-10-11

Plan: [PLAN-nfl-features-2026-10-11.md](PLAN-nfl-features-2026-10-11.md). Harness and every rule:
`backend/nfl_feature_backtest.py` (shared rules committed in `5c56c7c`, each feature's rule
committed before its run). Read-only on the dev DB; nothing recorded, nothing ingested, no locks.

Reproduce: `cd backend && LP_DB_PATH=<dev db> venv/bin/python nfl_feature_backtest.py --feature <name>`

## Verdict

**The market bar is not reached.** No feature, alone or combined, brings Brier level with the
de-vigged moneyline in any group. The best (the market-implied prior) halves the 2011-2023 gap,
from +0.0125 to +0.0070, and that feature is itself built from closing spreads, so it is not an
independent forecast. Our own-data features close little: EPA by unit closes 0.0019 of 0.0125.
Special teams, venue (rest, wind) and week-dependent sigma close nothing.

## Method in one paragraph

Stack on frozen v1: for season S, OLS of home margin on [1, v1 margin, feature columns] fitted on
seasons 2010 to S-1; sigma from that fit's residuals. Baseline B is the same stack without
features, so recalibration is never credited to a feature (B vs frozen v1, 2011-2023: Brier 0.2229
vs 0.2231). Keep rule: pooled 2011-2023 interval of Brier(F) - Brier(B) entirely below zero, and the
2024 and 2025 point differences not above zero. 2010 is training only. 5,000 paired resamples.

## Results (F minus B; F minus market; 95% intervals)

Market Brier: 0.2104 (2011-2023, n 3,158), 0.2001 (2024, n 256), 0.2137 (2025, n 255).
B minus market: +0.0125 [+0.0095, +0.0157], +0.0222 [+0.0096, +0.0349], +0.0155 [+0.0043, +0.0268].

| Feature | Group | Brier F-B | Brier F-market | Margin MAE F-B (spread MAE) | Kept |
|---|---|---|---|---|---|
| market_prior | 2011-2023 | -0.0055 [-0.0078, -0.0032] | +0.0070 [+0.0042, +0.0098] | -0.218 [-0.308, -0.129] (10.088) | yes, market-derived |
| | 2024 | -0.0076 [-0.0154, +0.0002] | +0.0145 [+0.0042, +0.0248] | -0.251 [-0.540, +0.029] (9.648) | |
| | 2025 | -0.0010 [-0.0087, +0.0069] | +0.0145 [+0.0046, +0.0242] | -0.135 [-0.421, +0.152] (9.971) | |
| epa_units | 2011-2023 | -0.0019 [-0.0037, -0.0001] | +0.0106 [+0.0078, +0.0135] | -0.052 [-0.125, +0.021] | yes, marginal |
| | 2024 | -0.0046 [-0.0101, +0.0008] | +0.0176 [+0.0066, +0.0287] | -0.165 [-0.366, +0.030] | |
| | 2025 | -0.0018 [-0.0073, +0.0037] | +0.0138 [+0.0034, +0.0241] | -0.058 [-0.264, +0.149] | |
| rating_uncertainty | 2011-2023 | +0.0000 [-0.0001, +0.0001] | +0.0125 [+0.0095, +0.0157] | 0 by construction | no |
| | 2024 | -0.0002 [-0.0004, +0.0000] | +0.0220 | | |
| | 2025 | +0.0000 [-0.0002, +0.0002] | +0.0155 | | |
| special_teams | 2011-2023 | +0.0006 [-0.0001, +0.0014] | +0.0131 [+0.0100, +0.0163] | +0.012 [-0.017, +0.042] | no |
| | 2024 | +0.0008 [+0.0001, +0.0014] | +0.0229 | +0.020 | |
| | 2025 | -0.0003 [-0.0008, +0.0001] | +0.0152 | -0.010 | |
| venue_conditions | 2011-2023 | +0.0003 [-0.0004, +0.0009] | +0.0128 [+0.0096, +0.0160] | +0.009 [-0.022, +0.038] | no |
| | 2024 | +0.0000 [-0.0010, +0.0010] | +0.0222 | +0.007 | |
| | 2025 | +0.0000 [-0.0009, +0.0011] | +0.0156 | -0.012 | |
| kept_combined | 2011-2023 | -0.0053 [-0.0078, -0.0029] | +0.0072 [+0.0044, +0.0100] | -0.200 [-0.295, -0.105] | adds nothing over market_prior alone |
| | 2024 | -0.0080 [-0.0159, +0.0001] | +0.0142 [+0.0039, +0.0243] | -0.256 [-0.545, +0.024] | |
| | 2025 | -0.0011 [-0.0091, +0.0069] | +0.0144 [+0.0044, +0.0242] | -0.125 [-0.414, +0.171] | |

## Reading

- "Kept" means only that the pre-registered rule was met. Neither kept feature has an interval
  excluding zero in 2024 or 2025 alone; they agree in sign only.
- epa_units uses v2's frozen 12 / 450, chosen on 2024 (A9). Its 2024 row is therefore not clean
  confirmation, and 2025 is a second look.
- Even a rating fitted on the market's own earlier spreads leaves +0.0070. The remaining gap is
  information in the current game's line that week-old ratings lack: most plausibly who plays
  (QB and injuries, Spec B), which no feature here carries. That is a hypothesis, not measured.
- Rating uncertainty was tested only as game-level sigma by week. The season-simulation version
  has no market comparator (no futures prices stored) and was not tested.
- Weather: no data was missing beyond nflverse's own gaps (outdoor games without wind: 2021 11,
  2022 91, 2023 41, the same in the raw games file). Wind is the game-time reading.
- 2026 weeks 1-5 (about 65 games) were not used as a live check.
