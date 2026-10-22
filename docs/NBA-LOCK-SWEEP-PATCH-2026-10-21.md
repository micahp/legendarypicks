# NBA missed-lock sweep patch

## Change

`lock_due_forecasts` now attaches the dev `picks.dev.db` read-only after validating it with the
existing `LP_DB_PATH` guard. The schedule recorder considers only season 2027 `REG`/`CUP` rows from
`nba.com` whose `start_utc <= now`, then inserts one `missed_t90_window` event per model without a
lock. `INSERT OR IGNORE` keeps repeats idempotent. When no picks path is configured, or SQLite
cannot attach it, the existing preview-based recorder remains the fallback. No schema, model,
promotion gate, environment variable, or timer changed.

`missed_window_games` counts distinct games, while `missed_lock_events` counts newly inserted
game/model rows. A one-game sweep with three missing models reports `missed_window_games=1` and
`missed_lock_events=3`; another run still counts the game but reports zero newly inserted events.
The runtime combines distinct-game counts from the pre-tip lock report and the tipped-game
recorder. It reports inserted event rows separately; event-row counts never feed the game counter.
A previewed game already past T−88 but not yet at tip reports one missed game and zero events.

The sweep runs at/after tip, rather than at T−88. The season payload labels any game with a
`missed_t90_window` event as `missed` at [nba_model_store.py:665](../backend/nba_model_store.py:665).
Writing the event at T−88 would expose that final missed state roughly 88 minutes before tip and
change current report/UI semantics. Waiting for `start_utc <= now` preserves them.

## A/B evidence

The pre-patch scratch A/B isolated the cause: no preview rows gave `record_missed_windows=0` and
events 9→9; three preview rows gave 3 and events 9→12. The preview path was active, but could not
observe a game with no preview rows.

The updated tempfile-only regression test was run with the venv interpreter against unpatched
parent `979a5434` and failed:

```text
FFFF
3 failed with TypeError: lock_due_forecasts() got an unexpected keyword argument 'lp_db_path'
1 failed with AssertionError: assert 0 == 1
4 failed in 0.68s
```

With this patch, the same test passes:

```text
....                                                                     [100%]
4 passed in 0.57s
```

The tests cover a zero-preview game at tip, partial and complete lock sets, repeated calls, the
season/type/source/tip filters, the preview-based fallback, and preview rows already past T−88
before tipoff.

## First-run backfill measurement

Read-only query of `/root/legendarypicks/backend/data/picks.dev.db` and
`/root/legendarypicks/backend/data/nba-model.dev.sqlite3` at `2026-10-22T03:05:26Z` found 14 tipped
season-2027 `REG`/`CUP` nba.com games without locks (42 missing game/model pairs). Nine matching
events already existed, so the first schedule sweep would add 33 rows; the model DB had 9 lock
events total at measurement time.

Mass backfilling these 14 season-to-date misses is acceptable for the season report: each game
lacked an immutable lock, and the report's `missed` status should expose that gap. No activation
watermark is added. If a prospective-only view is later required, an explicit activation timestamp
can be proposed as a separate option; it is not part of the default sweep here.
