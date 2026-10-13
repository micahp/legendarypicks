# RESULTS: Elo, era variables and a year-by-year breakdown, 2026-10-13

Question from Micah: can anything we have discussed get frozen v1 below 0.220 Brier, and how did 538 score so low?
Everything runs on the existing harness (`nfl_feature_backtest.py`, rules and groups unchanged) and is read-only on the
dev DB. Each rule was committed before its run: `nfl_shotgun_feature.py` (2318c0c), `nfl_elo_replica.py` (3af4899,
394fc84), `nfl_era_scores.py` (bcb5268), `nfl_year_breakdown.py` (8c44b54). All on branch `feat/nfl-shotgun-feature`.

Reference, Brier on the harness's graded set (lower is better):

| | 2011-2023 (n 3,158) | 2024 (n 256) | 2025 (n 255) |
|---|---|---|---|
| Recalibrated v1 (B) | 0.2229 | 0.2223 | 0.2292 |
| Frozen v1 | 0.2231 | 0.2210 | 0.2288 |
| Closing market | 0.2104 | 0.2001 | 0.2137 |

## 1. Elo passes; nothing else owned by us does

| Feature stacked on v1 | 2011-2023 | F minus B, 95% interval | 2024 | 2025 | Keep rule |
|---|---|---|---|---|---|
| `elo_diff` (replica of 538 Elo) | **0.2197** | -0.0032 [-0.0050, -0.0014] | 0.2145 | 0.2255 | **met** |
| `elo_plus_epa` | 0.2196 | -0.0033 [-0.0054, -0.0012] | 0.2142 | 0.2256 | met (EPA adds ~0.0001 once Elo is in) |
| EPA by unit | 0.2210 | -0.0019 [-0.0037, -0.0001] | 0.2177 | 0.2275 | met, marginal |
| Market prior (market-derived, not ours) | 0.2174 | -0.0055 | 0.2146 | 0.2282 | met, not independent |
| Special teams | 0.2235 | +0.0006 | | | not kept |
| Venue, rest, wind | 0.2232 | +0.0003 | | | not kept |
| Pressure matchup | 0.2226 | -0.0002 [-0.0006, +0.0001] | | | not kept |
| Sack matchup | 0.2230 | +0.0001 | | | not kept |
| Share-weighted absence | 0.2229 | -0.0000 | | | not kept |

Keep rule: pooled 2011-2023 interval entirely below zero, and the 2024 and 2025 point differences not above zero.
`elo_diff` is the first own-data feature below 0.220 on 2011-2023.

## 2. How 538 got that score

538's NFL Elo, rebuilt from scores, reproduces the file exactly (E0): mean absolute difference 0.0002 Elo over 2,939
games 2010 to 2020, using the file's own neutral flag and the tie multiplier.

- p = 1 / (1 + 10^(-(elo1 - elo2 + 65 x not neutral) / 400)); difference from the file 0.00000, playoffs included.
- Post-game rating = pre + 20 x mult x (result - p), mult = ln(|margin| + 1) x 2.2 / (0.001 x winner edge + 2.2),
  winner edge includes the home 65. A tie uses the constant 1.525 (found in all 11 ties in the file).
- A new season starts at 2/3 x last rating + 1/3 x 1505.
- 538 kept relocated home games (Buffalo 2013 and 2014, SF 2020) as home games; our schedule marks them neutral.
  That flag alone accounted for the largest gaps.
- Nothing else is in the model: no QB, rest or travel term.

Extended through 2025 from our own scores, Elo alone scores 0.2208 (2011-2023), 0.2148 (2024), 0.2279 (2025).

One-at-a-time changes from 538's constants, Brier on 2011-2023 (538 constants 0.2208):

| Change | Brier | vs 538 constants |
|---|---|---|
| margin multiplier off | 0.2271 | +0.0064 |
| carryover 0 (start each season from the mean) | 0.2260 | +0.0052 |
| K 40 | 0.2253 | +0.0045 |
| home field 95 | 0.2244 | +0.0036 |
| home field 0 | 0.2237 | +0.0029 |
| K 10 | 0.2235 | +0.0028 |
| K 30 | 0.2221 | +0.0014 |
| carryover 1/6 | 0.2224 | +0.0016 |
| carryover 1/2 | 0.2206 | -0.0002 |
| home field 35 | 0.2202 | -0.0006 |

The margin damping and the long memory between seasons carry most of it. 538's home value of 65 is a little high.
Walk-forward tuning (E4: 160 configurations, each season chooses from earlier seasons only) scores 0.2209 pooled
over 2013 to 2025 against 0.2219 for the fixed 538 constants (difference -0.0009). It picks carryover 0.5 in 12 of 13
seasons, K 20 to 25, home field 35 to 50.

## 3. Era variables: none helps

Shotgun era (league shotgun share of plays, same season before the game; 28.8% in 2010, 55.1% in 2023, 50.3% in 2025):

| Test | 2011-2023 Brier | F minus B | Verdict |
|---|---|---|---|
| `era_shift` (level and slope) | 0.2279 | +0.0050 [+0.0027, +0.0074] | worse |
| `era_sigma` | 0.2228 | -0.0001 [-0.0003, +0.0001] | no effect |
| `era_all` | 0.2284 | +0.0055 [+0.0030, +0.0080] | worse |
| EPA by unit + era | 0.2243 | +0.0014 [-0.0014, +0.0042] | era erased EPA's gain |
| everything stacked (exploratory) | 0.2247 | +0.0019 [-0.0013, +0.0049] | worse |

Era from scores, history back to 1920 (windows 3, 5 and 25 seasons, no break year chosen):

| Test | 2011-2023 Brier | F minus B |
|---|---|---|
| `hfa_drift` | 0.2232 | +0.0003 [-0.0002, +0.0007] |
| `scoring_scale` | 0.2228 | -0.0001 [-0.0008, +0.0007] |
| `spread_sigma` | 0.2227 | -0.0002 [-0.0006, +0.0001] |
| all three | 0.2233 | +0.0004 [-0.0007, +0.0016] |

Limit: an era variable is constant within a season, so the stack learns from 13 to 15 distinct values.
Play-by-play (and so the shotgun flag) starts in 2010; the shotgun was introduced in 1960 (date supplied by Micah, not
checked) and the earlier ramp is not in our data.

## 4. Year by year

| Year | n | home win % | mean total | Elo | v1 | v1 + Elo | market | v1 - Elo |
|---|---|---|---|---|---|---|---|---|
| 2011 | 240 | 56.2 | 44.2 | 0.2109 | 0.2055 | 0.2100 | 0.2021 | -0.0054 |
| 2012 | 239 | 57.3 | 45.2 | 0.2172 | 0.2150 | 0.2148 | 0.2074 | -0.0022 |
| 2013 | 239 | 60.3 | 46.8 | 0.2144 | 0.2114 | 0.2134 | 0.2037 | -0.0030 |
| 2014 | 239 | 56.5 | 45.1 | 0.2067 | 0.2170 | 0.2091 | 0.2070 | +0.0103 |
| 2015 | 240 | 53.3 | 45.6 | 0.2283 | 0.2297 | 0.2264 | 0.2320 | +0.0013 |
| 2016 | 238 | 58.8 | 45.7 | 0.2213 | 0.2293 | 0.2223 | 0.2190 | +0.0080 |
| 2017 | 240 | 57.1 | 43.6 | 0.2165 | 0.2207 | 0.2158 | 0.1990 | +0.0042 |
| 2018 | 239 | 60.7 | 46.6 | 0.2204 | 0.2265 | 0.2200 | 0.2094 | +0.0061 |
| 2019 | 240 | 51.7 | 45.4 | 0.2252 | 0.2242 | 0.2221 | 0.2147 | -0.0010 |
| 2020 | 239 | 49.8 | 49.7 | 0.2177 | 0.2194 | 0.2163 | 0.2002 | +0.0017 |
| 2021 | 255 | 51.8 | 45.9 | 0.2329 | 0.2356 | 0.2290 | 0.2144 | +0.0026 |
| 2022 | 254 | 57.1 | 43.9 | 0.2248 | 0.2292 | 0.2242 | 0.2085 | +0.0044 |
| 2023 | 256 | 56.6 | 43.7 | 0.2317 | 0.2353 | 0.2305 | 0.2173 | +0.0036 |
| 2024 | 256 | 52.3 | 45.8 | 0.2148 | 0.2210 | 0.2145 | 0.2001 | +0.0062 |
| 2025 | 255 | 53.7 | 46.2 | 0.2279 | 0.2288 | 0.2255 | 0.2137 | +0.0009 |

2020 was not a year in which 538 stood out against v1 (+0.0017). It stood out for the market (0.2002) and for the home
advantage, which was gone: mean home margin by year 2011 +3.3, 2014 +2.5, 2019 -0.0, 2020 -0.1, 2021 +1.9, 2023 +3.1,
2025 +1.9. The seasons where Elo beat v1 most (rule fixed in advance): 2014, 2016, 2024, 2018; least: 2011, 2013, 2012.

Pre-registered hypotheses against the tables (descriptive; no intervals computed, single-season buckets hold 45 to 75
games):
- **H1 early season: supported.** Pooled 2011-2025, v1 minus Elo by week: weeks 2-4 +0.0170 (n 706), weeks 5-9 +0.0019,
  weeks 10-14 -0.0029, week 15 on -0.0019. Elo is better early and v1 is better after week 10. In the four best years the
  weeks 2-4 gap is +0.0359 (2014), +0.0260 (2016), +0.0221 (2024), +0.0287 (2018). In 2011, the lockout year, v1 was
  better in weeks 2-4 (-0.0158); the cause is not tested.
- **H2 big favourites: not supported.** v1 minus Elo by market spread: under 3 +0.0026, 3 to 6.5 +0.0014, over 6.5
  +0.0039. Elo is ahead in all three and the gap barely changes with spread.
- **H3 home field in odd years: mixed.** Home advantage was about zero in both 2019 and 2020. v1 was ahead in 2019
  (-0.0010), Elo in 2020 (+0.0017).

Calibration, all 2011-2025 (predicted home win probability against realised): Elo is too generous to the home team in
the middle (45 to 55%: predicted 0.503, realised 0.447; 55 to 70%: 0.625 against 0.588; 70% and up: 0.788 against
0.765). v1 is close (0.499 against 0.513; 0.621 against 0.631; 0.775 against 0.777). Elo's flat 65 home value is too
high for these seasons, consistent with 35 to 50 doing better in the ablation and the walk-forward.

## What is not shown

- Constants of the Elo rung were chosen by 538 with this history in view (flattering); the walk-forward result is
  the out-of-sample check and differs by 0.0009.
- For 2021 and later the replica uses our schedule's neutral flag, so a few relocated games (for example Buffalo in
  Detroit, 2022) are treated as neutral where 538's rule would have kept them as home games.
- `stacked_all` is exploratory and was never a keep test.
- Year-level numbers are descriptive. The week-bucket pattern was found after looking at the same seasons the
  hold-out groups use, so a follow-up that uses it (a week-dependent Elo weight) needs its own pre-registration and
  cannot treat 2024 and 2025 as untouched.
