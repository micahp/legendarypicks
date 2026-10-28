# Game-winner comparison, 2021 to 2025, identical games (2026-10-27)

Status: research, read-only. No LP model, lock, or production table is changed. The 2026 season is not used. The
comparison covers the game-winner models the LP model card lists, plus our S0b, S1 and S2. The decision model is not
included, because it predicts decision mixes and the card says different targets are not ranked together. The v1+Elo
stack is not included, because its coefficients were not refitted in this run.

Script: `scripts/nfl_sequence/splits/game_winner_comparison.py`. Output: `results/game_winner_comparison.json` (scratchpad).

## Models

- **LP v1 points.** `nfl_backtest.backtest_season` with the frozen configuration from the model card (half-life 6, cap 14,
  sigma 13.295). Walk-forward.
- **LP v2 EPA.** `nfl_epa_backtest`, with half-life and lambda chosen on 2024 by its own grid and rule. The rule chose
  half-life 12 and lambda 450. Each season uses the previous season as its prior. Walk-forward.
- **Closing market.** De-vigged moneyline, stored with the v1 rows.
- **S0b, S1, S2 (ours).** Rebuilt with `s0_baseline.py` and `s1_s2_models.py`. Fit window 2010 to 2017. S1 uses the ridge
  settings chosen on 2018 to 2020.

## Common set

Regular-season games from 2021 to 2025 that meet the S0b eligibility rule, are not tied, have a market number, and have a
probability from every model. n = 1,037.

## Brier and log loss (lower is better)

| Window | n | Market | LP v1 | LP v2 EPA | S0b | S1 | S2 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2021 to 2025 | 1,037 | 0.2080 | 0.2230 | 0.2248 | 0.2259 | 0.2228 | 0.2236 |
| 2021 to 2023 (least examined) | 621 | 0.2132 | 0.2283 | 0.2269 | 0.2329 | 0.2284 | 0.2291 |
| 2024 (EPA setting chosen here) | 208 | 0.1831 | 0.2034 | 0.2116 | 0.2072 | 0.2015 | 0.2014 |
| 2025 (v1 and v2 second look) | 208 | 0.2173 | 0.2269 | 0.2318 | 0.2235 | 0.2275 | 0.2294 |

## Paired Brier differences (week-block 95% interval; negative favours the first model)

| Comparison | 2021 to 2025 | 2021 to 2023 | 2024 | 2025 |
|---|---|---|---|---|
| v1 minus market | +0.0151 [+0.0103, +0.0196] | +0.0152 [+0.0089, +0.0209] | +0.0203 [+0.0092, +0.0317] | +0.0096 [+0.0004, +0.0182] |
| LP v2 EPA minus market | +0.0169 [+0.0115, +0.0223] | +0.0137 [+0.0066, +0.0205] | +0.0286 [+0.0174, +0.0409] | +0.0145 [+0.0029, +0.0268] |
| S1 minus market | +0.0149 [+0.0098, +0.0197] | +0.0153 [+0.0081, +0.0219] | +0.0184 [+0.0061, +0.0299] | +0.0102 [+0.0008, +0.0185] |
| S0b minus market | +0.0179 [+0.0121, +0.0237] | +0.0197 [+0.0119, +0.0275] | +0.0241 [+0.0108, +0.0378] | +0.0062 [-0.0038, +0.0163] |
| S2 minus market | +0.0156 [+0.0101, +0.0209] | +0.0159 [+0.0084, +0.0232] | +0.0183 [+0.0058, +0.0304] | +0.0121 [+0.0022, +0.0210] |
| LP v2 EPA minus LP v1 | +0.0018 [-0.0029, +0.0068] | -0.0014 [-0.0057, +0.0029] | +0.0082 [-0.0040, +0.0207] | +0.0049 [-0.0079, +0.0184] |
| S1 minus LP v1 | -0.0002 [-0.0023, +0.0021] | +0.0001 [-0.0025, +0.0027] | -0.0019 [-0.0056, +0.0025] | +0.0006 [-0.0054, +0.0065] |
| S1 minus S0b | -0.0030 [-0.0066, +0.0005] | -0.0044 [-0.0092, -0.0000] | -0.0057 [-0.0141, +0.0029] | +0.0040 [-0.0035, +0.0123] |
| S2 minus S1 | +0.0008 [-0.0009, +0.0025] | +0.0007 [-0.0014, +0.0028] | -0.0001 [-0.0038, +0.0042] | +0.0019 [-0.0010, +0.0049] |

## Reading

1. **The closing market is the best model on every window.** Each model trails it by about 0.01 to 0.02 Brier. The
   intervals exclude zero everywhere except S0b in 2025.
2. **On the least examined window (2021 to 2023), S1, v1 and v2 EPA are within noise of each other.** S1 minus v1 is
   +0.0001 [-0.0025, +0.0027]. v2 EPA minus v1 is -0.0014 [-0.0057, +0.0029].
3. **v2 EPA does not beat v1 on any window.** The card's 2025 second look reads the same way. Over 2021 to 2025 the
   difference is +0.0018 [-0.0029, +0.0068].
4. **S1 beats S0b on 2021 to 2023** by 0.0044, with an interval that only just excludes zero. That is the one
   within-family improvement that looks real, and it is small.
5. **S2 adds nothing over S1** on any window. This matches the situational results in
   `NFL-S1-S2-RESULTS-2026-10-27.md`.

## Caveats

- 2024 is the window where v2 EPA's setting was chosen, and where the card says v1's configuration was selected. Treat
  2024 results as examined for those two models.
- 2025 was v1's holdout and is a second look for v2 EPA. Our S-models were not selected on 2025, but the market and v1 are
  examined there.
- The card reports v1 at 0.2288 on 255 games for 2025 and the market at 0.2137. This run uses the 208-game strict subset
  of 2025, so its numbers differ. The card's totals are not reproduced here.
- The v1+Elo stack is not in this table. Its 0.2197 on 2011 to 2023 (card) is a different window and cohort.
- Market is a de-vigged moneyline with no timestamp, so it is a closing-line proxy, not a pre-kickoff price.
