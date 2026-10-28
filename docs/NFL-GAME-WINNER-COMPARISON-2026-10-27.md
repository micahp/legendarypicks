# Game-winner comparison, 2021 to 2025, identical games (2026-10-27)

Status: research, read-only. No LP model, lock, or production table is changed. The 2026 season is not used. The
comparison covers the three game-winner models in the LP model card (v1 points, v2 EPA, v1 plus Elo stack), plus our S0b,
S1 and S2, and the closing market. The decision model is not included, because it predicts decision mixes and the card says
different targets are not ranked together.

Script: `scripts/nfl_sequence/splits/game_winner_comparison.py`. Output: `results/game_winner_comparison.json` (scratchpad,
not committed).

## Models

- **LP v1 points.** `nfl_backtest.backtest_season` with the frozen configuration from the model card (half-life 6, cap 14,
  sigma 13.295). Walk-forward. Its parameters were selected on 2024, so its 2021 to 2024 numbers carry hindsight (section
  "Selection chronology" below).
- **LP v2 EPA, as the card reports it.** `nfl_epa_backtest`, with half-life 12 and lambda 450 for every season, the setting
  chosen on 2024. This setting uses 2024 results for 2021 to 2024, so it carries hindsight.
- **LP v2 EPA, strict.** The same grid and rule, but for each season the setting is chosen on the season before it only:
  2021 uses (6, 450) chosen on 2020; 2022 and 2023 use (6, 450) chosen on 2021 and 2022; 2024 uses (12, 450) chosen on
  2023; 2025 uses (12, 150) chosen on 2024. Each season uses the previous season as its prior. This is the forward-selected
  EPA result.
- **v1 plus Elo stack.** Built as `lock_nfl_elo.py` defines it: margin = b0 + b1 times the v1 projected margin + b2 times
  the pre-game Elo gap (with home advantage unless neutral). OLS on every earlier season's v1 walk-forward rows, expanding
  each season. Win probability = Phi(margin / residual sd). Elo is the replica in `nfl_elo_replica.py`, read as each game's
  pre-game rating. Its Elo input uses 538's published constants.
- **Closing market.** De-vigged moneyline, stored with the v1 rows.
- **S0b, S1, S2 (ours).** Rebuilt with `s0_baseline.py` and `s1_s2_models.py`. Fit window 2010 to 2017. S1's ridge settings
  were chosen on 2018 to 2020. Every S-model setting is forward-selected for 2021 to 2025.

## Common set

Regular-season games from 2021 to 2025 that meet the S0b eligibility rule, are not tied, have a market number, and have a
probability from every model. n = 1,037.

## Brier and log loss (lower is better)

| Window | n | Market | LP v1 | LP v2 EPA | LP v2 EPA (strict) | v1+Elo stack | S0b | S1 | S2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2021 to 2025 | 1,037 | 0.2080 | 0.2230 | 0.2248 | 0.2247 | 0.2214 | 0.2259 | 0.2228 | 0.2236 |
| 2021 to 2023 (least examined) | 621 | 0.2132 | 0.2283 | 0.2269 | 0.2274 | 0.2258 | 0.2329 | 0.2284 | 0.2291 |
| 2024 | 208 | 0.1831 | 0.2034 | 0.2116 | 0.2116 | 0.2010 | 0.2072 | 0.2015 | 0.2014 |
| 2025 (v1 and v2 second look) | 208 | 0.2173 | 0.2269 | 0.2318 | 0.2297 | 0.2288 | 0.2235 | 0.2275 | 0.2294 |

Log loss, 2021 to 2025: market 0.6027, v1 0.6379, EPA 0.6412, EPA strict 0.6409, stack 0.6335, S0b 0.6431, S1 0.6373,
S2 0.6390.

## Paired Brier differences (week-block 95% interval; negative favours the first model)

| Comparison | 2021 to 2025 | 2021 to 2023 | 2024 | 2025 |
|---|---|---|---|---|
| v1 minus market | +0.0151 [+0.0103, +0.0196] | +0.0152 [+0.0089, +0.0209] | +0.0203 [+0.0092, +0.0317] | +0.0096 [+0.0004, +0.0182] |
| LP v2 EPA (as reported) minus market | +0.0169 [+0.0115, +0.0223] | +0.0137 [+0.0066, +0.0205] | +0.0286 [+0.0174, +0.0409] | +0.0145 [+0.0029, +0.0268] |
| LP v2 EPA (strict) minus market | +0.0167 [+0.0114, +0.0221] | +0.0142 [+0.0072, +0.0210] | +0.0286 [+0.0174, +0.0409] | +0.0124 [+0.0024, +0.0224] |
| v1+Elo stack minus market | +0.0135 [+0.0087, +0.0182] | +0.0126 [+0.0066, +0.0183] | +0.0180 [+0.0059, +0.0327] | +0.0115 [+0.0036, +0.0192] |
| S1 minus market | +0.0149 [+0.0098, +0.0197] | +0.0153 [+0.0081, +0.0219] | +0.0184 [+0.0061, +0.0299] | +0.0102 [+0.0008, +0.0185] |
| S0b minus market | +0.0179 [+0.0121, +0.0237] | +0.0197 [+0.0119, +0.0275] | +0.0241 [+0.0108, +0.0378] | +0.0062 [-0.0038, +0.0163] |
| S2 minus market | +0.0156 [+0.0101, +0.0209] | +0.0159 [+0.0084, +0.0232] | +0.0183 [+0.0058, +0.0304] | +0.0121 [+0.0022, +0.0210] |
| LP v2 EPA (as reported) minus LP v1 | +0.0018 [-0.0029, +0.0068] | -0.0014 [-0.0057, +0.0029] | +0.0082 [-0.0040, +0.0207] | +0.0049 [-0.0079, +0.0184] |
| LP v2 EPA (strict) minus LP v1 | +0.0017 [-0.0026, +0.0061] | -0.0009 [-0.0051, +0.0034] | +0.0082 [-0.0040, +0.0207] | +0.0028 [-0.0080, +0.0137] |
| v1+Elo stack minus LP v1 | -0.0016 [-0.0047, +0.0014] | -0.0025 [-0.0063, +0.0010] | -0.0024 [-0.0096, +0.0052] | +0.0019 [-0.0054, +0.0098] |
| v1+Elo stack minus LP v2 EPA (as reported) | -0.0034 [-0.0069, -0.0000] | -0.0011 [-0.0047, +0.0024] | -0.0106 [-0.0192, -0.0016] | -0.0030 [-0.0117, +0.0066] |
| v1+Elo stack minus S1 | -0.0014 [-0.0049, +0.0020] | -0.0027 [-0.0077, +0.0021] | -0.0005 [-0.0075, +0.0072] | +0.0013 [-0.0050, +0.0082] |
| S1 minus LP v1 | -0.0002 [-0.0023, +0.0021] | +0.0001 [-0.0025, +0.0027] | -0.0019 [-0.0056, +0.0025] | +0.0006 [-0.0054, +0.0065] |
| S1 minus S0b | -0.0030 [-0.0066, +0.0005] | -0.0044 [-0.0092, -0.0000] | -0.0057 [-0.0141, +0.0029] | +0.0040 [-0.0035, +0.0123] |
| S2 minus S1 | +0.0008 [-0.0009, +0.0025] | +0.0007 [-0.0014, +0.0028] | -0.0001 [-0.0038, +0.0042] | +0.0019 [-0.0010, +0.0049] |

## Early season, strict: weeks 2 to 4 of 2021 to 2025

Every game in weeks 2 to 4 of 2021 to 2025 with a market number and all five probabilities (n = 239). S1's settings were chosen
on 2018 to 2020, so S1 is forward here. LP v1 carries hindsight (its parameters were selected on 2024). Strict EPA is forward.

| Model | Brier | Log loss |
|---|---:|---:|
| Closing market | 0.2231 | 0.6353 |
| LP v2 EPA (strict) | 0.2369 | 0.6658 |
| v1+Elo stack | 0.2391 | 0.6706 |
| S1 (ours) | 0.2488 | 0.6927 |
| LP v1 points | 0.2597 | 0.7177 |

Paired differences: S1 minus LP v1 -0.0109 [-0.0190, -0.0031]; strict EPA minus LP v1 -0.0228 [-0.0341, -0.0105]; S1 minus
closing market +0.0257 [+0.0138, +0.0360]. The interval for S1 minus strict EPA on this set was not computed.

## Reading

1. **The closing market is the best model on every window.** Each model trails it by about 0.01 to 0.03 Brier.
2. **Over 2021 to 2025, the forward-selected EPA (strict) ties v1, and the stack is the nominal leader.** The stack beats v1
   by 0.0016 and EPA by 0.0034, but neither interval excludes zero except the stack against EPA as reported.
3. **S1 ties v1 on the full window and on 2021 to 2023.** Both are forward-selected for S1; v1 carries hindsight.
4. **Early season, the picture changes.** In weeks 2 to 4 of 2021 to 2025, S1 beats v1 by 0.0109 with an interval that
   excludes zero. But the forward-selected EPA beats both, and it is the best non-market model there (0.2369 against S1's
   0.2488). That gap is the most important open question in this comparison, and its interval is still to be computed.
5. **S2 adds nothing over S1** on any window. This matches the situational results in `NFL-S1-S2-RESULTS-2026-10-27.md`.

## Selection chronology

- Forward-selected for every season: S0b, S1, S2 (their settings were chosen on 2010 to 2020 data, not on the season
  scored), the strict EPA rows, and the stack (fitted on earlier seasons only).
- Not forward-selected: LP v1 (its parameters were selected on 2024, so its 2021 to 2024 rows carry hindsight), and LP v2
  EPA as reported (its setting was selected on 2024, so its 2021 to 2024 rows carry hindsight). The 2025 row is forward for
  both only in the sense that 2025 was not used to choose them, but 2025 was the card's second look.
- The strict EPA rows are the only forward-selected version of the EPA model in this table.

## Caveats

- The stack's Elo input uses 538's published constants, which 538 fitted on this same history.
- The card reports v1 at 0.2288 on 255 games for 2025 and the market at 0.2137. This run uses the 208-game strict subset of
  2025, so its numbers differ.
- The card's stack result (0.2197 on 3,158 games, 2011 to 2023) is a different window and cohort from this table.
- The market is a de-vigged moneyline with no timestamp, so it is a closing-line proxy, not a pre-kickoff price.
- The weeks 2 to 4 table has 239 games. Intervals there are wide.
