# Results: the benchmark ladder and the season-start (carryover) sweep, 2026-10-12

Code: `backend/nfl_ladder.py` (pre-registered in its docstring before any run). Read-only on the dev DB.
North star stage 1: [STRATEGY-forecasting-north-star-2026-10-10.md](STRATEGY-forecasting-north-star-2026-10-10.md).

## Ladder: identical games, 2011 to 2020

Brier on the 2,386 REG games v1 grades that have a moneyline and a 538 Elo row (7 of 2,393 did not
join). v1 makes no week 1 forecast, so week 1 games are outside these rows. Lower is better.

| Rung | All | Wk 2-4 | Wk 5-8 | Wk 9+ |
|---|---|---|---|---|
| Coin flip | .2500 | .2500 | .2500 | .2500 |
| Home field | .2460 | .2445 | .2446 | .2472 |
| 538 Elo | .2183 | .2240 | .2149 | .2178 |
| v1 | .2202 | .2391 | .2156 | .2157 |
| v1 recalibrated (B) | .2204 | .2360 | .2160 | .2168 |
| Market | .2097 | .2231 | .2041 | .2073 |

v1 minus Elo (paired bootstrap, 5,000):

| Group | v1 - Elo | Reading |
|---|---|---|
| All | +0.0019 [-0.0017, +0.0054] | tie |
| Wk 2-4 | +0.0151 [+0.0046, +0.0256] | v1 worse |
| Wk 5-8 | +0.0007 [-0.0073, +0.0089] | tie |
| Wk 9+ | -0.0021 [-0.0061, +0.0017] | tie |

- v1 beats home field by about 0.028 (home - Elo is +0.0277 [+0.0217, +0.0336]).
- Elo trails the market by only +0.0009 [-0.0073, +0.0089] in weeks 2 to 4; v1 trails it by about 0.016.
- 538 fit its constants on this history and backfilled it with its later method, so Elo is a flattering
  bar. v1 is ranked against it here, not claimed to beat it.

## Carryover sweep

v1 pulls last season's final ratings toward zero by `shrink` and gives that prior `prior_games`
pseudo-games of weight. The current v1 is shrink 1/3, prior_games 4. 12 configurations, other
parameters as frozen. Brier of B (the recalibrated stack, no feature columns):

| shrink | prior_games | 2011-2023 | 2024 | 2025 | Wk 2-4 (2011-2023) |
|---|---|---|---|---|---|
| 0.200 | 2 | .2244 | .2238 | .2297 | .2424 |
| 0.200 | 4 | .2225 | .2222 | .2291 | .2378 |
| 0.200 | 8 | .2209 | .2215 | .2293 | .2333 |
| 0.333 | 2 | .2247 | .2238 | .2300 | .2435 |
| 0.333 | 4 (current) | .2229 | .2223 | .2292 | .2391 |
| 0.333 | 8 | .2213 | .2215 | .2293 | .2348 |
| 0.500 | 2 | .2252 | .2240 | .2304 | .2450 |
| 0.500 | 4 | .2235 | .2225 | .2295 | .2411 |
| 0.500 | 8 | .2220 | .2216 | .2293 | .2371 |
| 0.667 | 2 | .2257 | .2242 | .2308 | .2468 |
| 0.667 | 4 | .2242 | .2229 | .2299 | .2434 |
| 0.667 | 8 | .2229 | .2220 | .2295 | .2399 |

Selected (lowest pooled 2011-2023): shrink 0.200, prior_games 8. Against the current config:

| Group | Selected - current |
|---|---|
| 2011-2023 | -0.0020 [-0.0027, -0.0013] |
| 2024 | -0.0008 [-0.0032, +0.0017] |
| 2025 | +0.0001 [-0.0023, +0.0025] |
| Wk 2-4, 2011-2023 | -0.0058 [-0.0080, -0.0037] |

## Verdict

**Not adopted under the pre-registered rule.** The rule needs the pooled interval entirely below zero
(met) and the 2024 and 2025 point differences not above zero. 2025 is +0.0001, above zero by that
amount. The check was not loosened.

What the sweep does show:
- Brier improves steadily as shrink falls and prior_games rises. In the 2011-2023 column it moves the
  same way along both axes in every row and column of the grid. Keeping more of last season's rating
  and trusting it more beats the current setting.
- The selected config sits at the corner of the grid (lowest shrink, highest prior_games), so the grid
  does not bracket the optimum. The true best may be further out.
- The gain is concentrated in weeks 2 to 4: -0.0058 pooled, against -0.0020 overall.
- 2024 is flat to slightly better and 2025 is flat. The pooled interval is optimistic: the config was
  chosen on those games, from 12.

## Caveats

1. The selected config's 2011-2023 interval was chosen on those games and is optimistic. 2024 is the
   honest check, and its interval includes zero.
2. Even the best weeks 2 to 4 value here (.2333) is above Elo's .2240 and the market's .2231, but those
   are on different game sets (2011-2023 vs 2011-2020) and are not a comparison.
3. 2025 was v1's holdout and has now been looked at for every config. It is a second look only.
4. No unit tests were added for `nfl_ladder.py`; the two runs are the check.

## Second grid (pre-registered after the first)

shrink {0.0, 0.1, 0.2} x prior_games {8, 16, 32}, same selection and rule, current config run as a
reference outside the selection set. The first launch of this grid crashed at the comparison step
(the current config was not in the grid) after all 9 runs, and its output was never read. The code was
fixed to run the reference separately; the grid and the rule did not change.

| shrink | prior_games | 2011-2023 | 2024 | 2025 | Wk 2-4 (2011-2023) |
|---|---|---|---|---|---|
| 0.000 | 8 | .2206 | .2218 | .2295 | .2316 |
| 0.000 | 16 | .2202 | .2236 | .2315 | .2285 |
| 0.000 | 32 | .2214 | .2275 | .2348 | .2283 |
| 0.100 | 8 | .2207 | .2217 | .2294 | .2323 |
| 0.100 | 16 | .2203 | .2232 | .2312 | .2293 |
| 0.100 | 32 | .2214 | .2269 | .2345 | .2292 |
| 0.200 | 8 | .2209 | .2215 | .2293 | .2333 |
| 0.200 | 16 | .2204 | .2228 | .2309 | .2303 |
| 0.200 | 32 | .2215 | .2264 | .2342 | .2303 |
| 0.333 | 4 (reference) | .2229 | .2223 | .2292 | .2391 |

Selected (lowest pooled 2011-2023): shrink 0.000, prior_games 16. Against the current config:

| Group | Selected - current |
|---|---|
| 2011-2023 | -0.0027 [-0.0042, -0.0011] |
| 2024 | +0.0013 [-0.0042, +0.0067] |
| 2025 | +0.0023 [-0.0029, +0.0073] |
| Wk 2-4, 2011-2023 | -0.0106 [-0.0151, -0.0061] |

**Not adopted.** The pooled interval is below zero, but both holdout seasons are above zero.

What the two grids show together:
- On 2011-2023, more weight on last season's ratings keeps helping until prior_games 16, then turns
  (prior_games 32 is worse than 16 at every shrink).
- On 2024 and 2025 the direction is the opposite: Brier gets worse as prior_games rises from 8 to 32 at
  every shrink. The recent seasons are best near prior_games 4 to 8.
- So the setting that wins on the 2011-2023 pool is not the one that holds up on the last two seasons.
  It could be a change in how much rosters turn over, or chance (about 256 games per holdout season, with
  intervals that include zero), or a fit to the older seasons. These runs cannot tell them apart.
- The early-weeks gain (weeks 2-4) is large in-sample and is the only part that is consistent across
  every setting that carries more of last year's ratings.

No setting in either grid meets the rule. v1 keeps shrink 1/3 and prior_games 4.

## Next

1. Leave v1's carryover unchanged for the 2026 locks.
2. Ask what differs about recent offseasons before any further grid: a third grid would only be fit to
   the same 13 seasons again, and 2024 and 2025 have now each been looked at twice.
3. The independent preseason prior (last season's EPA by unit regressed, QB change, returning starters)
   is the other route to the weeks 2-4 gap that does not depend on this one setting.
