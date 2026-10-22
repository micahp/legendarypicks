# NBA missed-lock sweep patch

## Change

`lock_due_forecasts` now attaches the dev `picks.dev.db` read-only after validating it with the
existing `LP_DB_PATH` guard. The schedule recorder considers only season 2027 `REG`/`CUP` rows from
`nba.com` whose `start_utc <= now`, then inserts one `missed_t90_window` event per model without a
lock. `INSERT OR IGNORE` keeps repeats idempotent. When no picks path is configured, or SQLite
cannot attach it, the existing preview-based recorder remains the fallback. No schema, model,
promotion gate, environment variable, or timer changed.

The runtime adds the inserted per-model event count to `missed_events_recorded` and
`missed_window_games`; one zero-preview game therefore reports 3. Existing pre-tip lock-window
misses from `lock_forecasts` remain included in that latter counter.

The sweep runs at/after tip, rather than at T−88. The season payload labels any game with a
`missed_t90_window` event as `missed` at [nba_model_store.py:660](../backend/nba_model_store.py:660).
Writing the event at T−88 would expose that final missed state roughly 88 minutes before tip and
change current report/UI semantics. Waiting for `start_utc <= now` preserves them.

## A/B evidence

The pre-patch scratch A/B isolated the cause: no preview rows gave `record_missed_windows=0` and
events 9→9; three preview rows gave 3 and events 9→12. The preview path was active, but could not
observe a game with no preview rows.

The new tempfile-only regression test was run with the venv interpreter against unpatched
`04a421cf` and failed:

```text
FFFF
3 failed with TypeError: lock_due_forecasts() got an unexpected keyword argument 'lp_db_path'
1 failed with AssertionError: assert 0 == 3
4 failed in 0.60s
```

With this patch, the same test passes:

```text
....                                                                     [100%]
4 passed in 0.62s
```

The tests cover a zero-preview game at tip, partial and complete lock sets, repeated calls, the
season/type/source/tip filters, and the preview-based fallback.
