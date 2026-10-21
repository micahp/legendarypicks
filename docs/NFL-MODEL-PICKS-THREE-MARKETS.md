# NFL Model Picks: Winner, Spread, Total

**Status:** Feature branch `fix/nfl-three-market-model-picks-2026-10-20`; do not treat as deployed until tests and merge are verified.

Every NFL game-model version makes up to three **model picks**, without a separate lean or
qualifying-wager policy. A pick is a model output, not a claim of positive expected return.

| Market | Frozen inputs | Selection | Grade |
|---|---|---|---|
| Winner (ML side) | `p_home_win` | home if > 0.5, away if < 0.5; otherwise `no_pick` | W/L; `tie` for tied game |
| Spread (ATS) | `proj_margin`, frozen `spread_line` | home if margin > line, away if < line; equal `no_pick`, missing `no_line` | W/L/P |
| Total (O/U) | `proj_total`, frozen `total_line` | over if projected > line, under if < line; equal `no_pick`, missing `no_line` | W/L/P |

Comparisons use a numeric tolerance of `1e-9`; **positive spreads mean expected home margin**,
not the more common sportsbook notation. `nfl_metrics.py` owns the three selections and winner/
total grading. The existing `grade_nfl_locks.py` owns the final-score quality checks and
append-only `projection_grades` row (including persisted ATS). The API computes winner and
total grades from that recorded final score and the original lock, **never from a subsequently
updated schedule score or market line**. It does so only after a `projection_grades` row exists.

### Existing lock storage, no new schema

`game_projections` captures immutable `p_home_win`, `proj_margin`, `proj_total`,
`locked_at`, `model_version`, and either a snapshot id into `nfl_line_snapshots` or
legacy `market_spread`/`market_total` columns. Both the API and grader use
`COALESCE(snapshot line, locked row line)`, by market. Previews and later unlocked runs
never alter the official lock or its record. Already-graded historical rows are not rewritten.

API: `/api/nfl/model/locks` adds `lock.picks = {winner, spread, total}` and
`lock.grade.total` alongside existing `lock.grade.su` (winner) and `lock.grade.ats`
(spread). `lock.pick` remains a backwards-compatible alias for the spread pick.
Season records are `su`, `ats`, `total`, isolated by model version.

### Verification before merging

```sh
cd backend
venv/bin/python -m unittest test_nfl_metrics test_grade_nfl_locks test_nfl_model_api test_home_featured
cd ..
npx jest components/Leagues/NflModelTab.test.tsx --runInBand
npx tsc --noEmit
```

Also perform a read-only smoke check of one graded and one upcoming game on the real dev DB:
verify `picks.winner/spread/total`, immutable line source, the grade for all three,
and one model version's `su/ats/total` season records. Do not write production data.
