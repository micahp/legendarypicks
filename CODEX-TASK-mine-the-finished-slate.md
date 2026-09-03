# CODEX TASK: mine the finished slate for insights

## What this is

Every night a slate finishes and we settle props against it. Nobody reads the
result. `prop_results` is the largest honest record we own of what actually
happened versus what a book priced, and we have never asked it a question.

This task builds one script that asks. It is a READ-ONLY analysis pass. It
writes a report. It does not write to the database, does not touch the serving
path, and does not change any ingest.

## Scope lock

Create exactly one new file:

- `backend/mine_slate.py`
- `backend/test_mine_slate.py`

Do NOT edit anything else. Specifically forbidden:

- any file under `backend/routers/`
- `backend/_core.py`, `backend/news_classifier.py`, or any existing ingest script
- any shared helper module (write what you need inside `mine_slate.py`)
- any systemd unit, any file under `scripts/`
- any frontend file

If you believe a shared helper must change, stop and write the reason in your
report instead of changing it.

## The data

Read-only, via `LP_DB_PATH` (default `backend/data/picks.db`; the dev DB is
`backend/data/picks.dev.db`). Run every query against BOTH databases and report
both. They disagree, and the disagreement is itself a finding.

```
prop_games(id, league, date, home, away, espn_event_id,
           final_home, final_away, start_time, cancelled_at, cancel_reason, cancel_source)
props(id, game_id -> prop_games.id, player_id -> players.id,
      market, line, side, source, captured_at, odds, odds_captured_at)
prop_results(prop_id -> props.id, actual_value, hit, settled_at)
players(...)              -- the identity spine; join on players.id, never on name
prop_odds_snapshots(...)  -- line movement, if it carries the slate
```

Target slate = the most recent `prop_games.date` where every non-cancelled game
has `final_home IS NOT NULL`. Compute it; do not hardcode it. As of
2026-09-03 that resolves to **2026-09-02** (15 MLB games, 14 final, plus 2
`lcup`). Accept `--date YYYY-MM-DD` to override.

## Measured starting conditions (verify these before you trust anything)

Run against prod (`backend/data/picks.db`) on 2026-09-03:

- MLB 2026-09-02: 1,361 props, ~1,161 carry a `prop_results` row.
- `lcup` 2026-09-02: `first_goal_scorer` 94 props / 32 settled;
  `goals` 94 props / **0 settled**.
- `ufc` 2026-09-02: 37 props, **0 settled**.
- `player_game_logs` has **zero rows** with `game_date LIKE '2026-09-02%'`.

Those last three are gaps, not zeroes. A settled-rate of 0 means the settler
never ran for that market, not that nothing hit. Any aggregate you compute
must state its denominator and must exclude unsettled rows from a hit rate
rather than counting them as misses. A market with no settlement is reported
as UNSETTLED, never as 0%.

## What to produce

`backend/mine_slate.py --date YYYY-MM-DD [--db PATH] [--json]` prints a report
with these sections. Each finding must carry the row count behind it and the
SQL that produced it, so it can be re-run and falsified.

1. **Coverage.** Per league and market: props offered, props settled, settled
   rate. Name every market with a settled rate under 100% and say whether the
   shortfall is unsettled or genuinely absent. This section is the gate: if
   coverage is bad, every number below it is suspect and the report must say so
   at the top, not in a footnote.

2. **Where the line was wrong.** Per `(league, market, line)`: over/under hit
   rate against the posted line, with counts. A market where the line is
   systematically beaten is the whole point of the exercise. Report only
   buckets with n >= 20 and give the exact n; a 3-for-4 is noise and must not
   appear as a percentage.

3. **Distance from the line.** For each market, the distribution of
   `actual_value - line`. The mean matters less than the shape: a market that
   misses by 0.2 is priced; one that misses by 2.0 is not. Report median and
   the 10th/90th percentile, not just the mean.

4. **Repeat offenders.** Players (joined via `players.id`, never by name) whose
   props settled the same direction 4+ times on this slate or across the last
   7 slates. State the window explicitly on every such claim.

5. **Odds vs. outcome.** Where `props.odds` is present, bucket by implied
   probability and compare to realized hit rate. Say how many rows carry odds
   at all. If most do not, this section reports "insufficient odds coverage"
   and stops.

6. **What the slate cannot tell us.** An explicit list: every market that went
   unsettled, every game with a NULL final, every prop whose `player_id` is
   NULL. This section is mandatory and must never be empty when the gaps above
   still exist.

## Rules

- Every number is a claim about the query that produced it. Print the SQL.
- A missing row is `unknown`, never `0` and never a miss.
- Never join players by name. `player_id` or nothing.
- No model calls. No network. This is SQL and arithmetic.
- `python3 -m pytest backend/test_mine_slate.py` must pass. Test the
  denominators specifically: an unsettled market must not be able to produce a
  hit rate, and a bucket under n=20 must not be able to produce a percentage.
  Build the fixtures in a temp DB; do not read the real databases in tests.

## Report back

A short summary naming: the slate you analysed, the three most interesting
findings with their n, and every check that came back inconclusive because the
data was not there. If the honest answer is "this slate is too thin to
conclude anything", that is the correct answer and I want it stated plainly.
