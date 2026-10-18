# NFL prop baseline: the live Marcel-lite P(over), graded

Measured 2026-10-16 on `picks.dev.db` (read-only), on `scratch/spec-b-rebase`. This is the number the v2
engine has to beat before it can replace the live player-projection route. Until now the live route had
never been graded.

Script: `backend/grade_nfl_prop_baseline.py` (read-only, prints; writes a CSV only if asked). It imports
the item set from `grade_nfl_prop_probabilities.collect`, so the props, the sportsbook source list, the
devig, the weeks, the position and lead-passer filters and the box-score outcome are the same code as the
v2 grade. Only the projection differs.

## What is being graded

The live route is `GET /api/projections/player/{id}` -> `backend/routers/players/projections.py` ->
`backend/analytics/projections.py`. Its P(over) is `prob_over(vals, line)`: the share of the player's own
2026 regular-season games in which the stat beat the line, with no shrinkage and no fitted distribution.
Its point projection is `project_stat`, a recency-weighted mean (0.5 last five, 0.3 last ten, 0.2 season).

Two readings are reported:

- **walk-forward**: only the player's games before the target week enter the series, and `project_stat`'s
  own `min_games=3` gate applies. This is what the route would have served before kickoff, and it is the
  comparison the walk-forward v2 numbers are against.
- **as-served**: the route replayed today, over every 2026 log in the season, including the target game.
  Reported only to size the look-ahead. It is not a forecast.

## Population

2026 NFL props from sportsbook sources only (bovada and six rotowire sportsbook feeds), weeks 2 to 5 with
a final score, one item per (nflverse game, player, market, book, line).

Excluded: 8,671 items outside those weeks, 5,249 where the player has no box-score line, 178 with no v2
projection, 163 passing props on a quarterback who did not lead his team in attempts, 1 whole-number line,
2 with one side only. On 15 graded items the box-score outcome disagrees with the book's own settlement
(`prop_results.hit`); the v2 grade has 38. Not investigated.

## Result: the live route serves nothing before week 4

`project_stat` returns `None` below three games, so the route returns no projection at all for a player
with fewer than three prior games. Of the 33,519 items the v2 engine grades, **19,088 (57%) have no live
number to compare against**: every week 2 and week 3 item, plus week 4 and 5 items for players who had not
played three games.

The walk-forward baseline is therefore measured on weeks 4 and 5 only: **14,431 items on 354
player-games** (week 4: 7,411 items, 169 player-games; week 5: 7,020 items, 185 player-games).

| Group | Items | Player-games | Brier live | Brier market | Over rate |
|---|---:|---:|---:|---:|---:|
| all | 14,431 | 354 | 0.3082 | 0.2463 | 0.496 |
| receiving yards | 8,217 | 304 | 0.3068 | 0.2479 | 0.471 |
| receptions | 2,358 | 304 | 0.3084 | 0.2422 | 0.502 |
| passing yards | 2,883 | 50 | 0.3148 | 0.2444 | 0.550 |
| pass attempts | 356 | 50 | 0.3228 | 0.2495 | 0.520 |
| pass completions | 304 | 50 | 0.2954 | 0.2493 | 0.559 |
| passing TDs | 313 | 50 | 0.2772 | 0.2436 | 0.521 |

A constant 0.5 scores 0.2500 on these items. The live P(over) scores **0.3082, which is worse than a coin
flip** by 0.058 (clustered 95% interval 0.034 to 0.082, clustered by player-game). The calibration table
says why: a hit rate of 0 over three games is emitted as a probability of 0.000 and the overs then land
50.5% of the time, and a hit rate of 1.0 is emitted as 1.000 against an observed 0.549.

Calibration, all items (live P(over) bin: n, mean predicted, observed over rate): 0.0-0.1: 1,320, 0.000,
0.505; 0.2-0.3: 1,518, 0.250, 0.381; 0.3-0.4: 2,949, 0.333, 0.474; 0.5-0.6: 2,243, 0.500, 0.492;
0.6-0.7: 3,329, 0.667, 0.531; 0.7-0.8: 1,568, 0.750, 0.522; 0.9-1.0: 1,504, 1.000, 0.549.

With three or four prior games the hit rate can only be 0, 1/4, 1/3, 1/2, 2/3, 3/4 or 1, so the estimate is
not a probability at all. That is the live behaviour, not an artifact of the harness.

## The paired comparison against v2

Both systems are run on the current DB and joined item by item, so the comparison is on identical games,
players, markets, books, lines and outcomes.

| | Items | Player-games | Live Marcel-lite | v2 | Market |
|---|---:|---:|---:|---:|---:|
| all | 14,431 | 354 | 0.3082 | 0.2706 | 0.2463 |
| receiving yards | 8,217 | 304 | 0.3068 | 0.2637 | 0.2479 |
| receptions | 2,358 | 304 | 0.3084 | 0.2809 | 0.2422 |
| passing yards | 2,883 | 50 | 0.3148 | 0.2862 | 0.2444 |
| pass attempts | 356 | 50 | 0.3228 | 0.2606 | 0.2495 |
| pass completions | 304 | 50 | 0.2954 | 0.2796 | 0.2493 |
| passing TDs | 313 | 50 | 0.2772 | 0.2325 | 0.2436 |

Paired per-item Brier differences, clustered by player-game (items are alternate lines on the same
player-game, so the item-level interval is optimistic; both are given):

| Comparison | Difference | Item-level 95% | Clustered 95% (354 clusters) |
|---|---:|---:|---:|
| v2 minus live | -0.0376 | +/- 0.0049 | +/- 0.0282 |
| market minus v2 | -0.0243 | | +/- 0.0152 |
| market minus live | -0.0619 | | +/- 0.0240 |

Every interval excludes zero. Read plainly:

1. **v2 improves on the live route.** 0.2706 against 0.3082 on the same 14,431 items, an improvement of
   0.0376 Brier with the clustered interval excluding zero. This is the first paired evidence that v2 is
   better than what the site serves, and it is worth 0.0376 against a baseline that is itself worse than a
   coin flip.
2. **v2 still loses to the market**, by 0.0243, and that interval also excludes zero. Replacing the live
   route is a real improvement and does not by itself make the prop probabilities good.
3. **Pass completions is the one market where v2 is not clearly ahead** (-0.0158, item-level interval
   touches zero).

On the v2 engine's full population (33,519 items, 920 player-games) the current DB gives Brier 0.2747
against the market's 0.2460. The 2026-10-12 results doc records 0.2746 against 0.2458 on 32,810 items and
902 player-games; the difference is the DB growing since that run, not a change in the engine.

## The look-ahead in the number the page shows today

Replaying the route exactly as it is served (every 2026 log in the season, the target game included) gives
Brier **0.1911 against the market's 0.2463**, which would read as beating the books. It does not: the
target game is inside its own hit rate. This is the same number the props page renders for a past game, so
a served P(over) read after the fact is not evidence about the model.

## Caveats

- One season, weeks 4 and 5 only, one DB read. The walk-forward number is recomputed now, not captured
  before kickoff; the first genuinely prospective test is the week 6 job plus a pre-kickoff capture.
- 304 items (2.1%) have a different denominator in the two builds: a game whose blob omits the stat key is
  skipped by the live route but read as 0.0 by the branch `History.Row`. Every market key appears in the
  2026 logs, so no item is lost to a missing key.
- The live route's served P(over) has no minimum-sample display; the props page shows it beside a line
  without saying it rests on three games.

## Reproducing

```bash
cd backend
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db python3 grade_nfl_prop_probabilities.py \
  --season 2026 --csv /tmp/v2_items.csv
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db python3 grade_nfl_prop_baseline.py \
  --season 2026 --csv /tmp/base_items.csv --v2-csv /tmp/v2_items.csv
```
