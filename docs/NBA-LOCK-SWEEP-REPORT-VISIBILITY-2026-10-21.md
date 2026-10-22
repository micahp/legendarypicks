# NBA lock sweep report visibility

Branch: `research/nba-lock-sweep-report-visibility-2026-10-21`, based on
`e3157697b3b15fd2588705fbe7fa5a8903dc8c54`.

## Design

Chosen: optional schedule metadata input to `export_payload`, with the API router
attaching the guarded dev picks database read-only. `nba_model_store.py:604-620`
shows that report games came from locks and future previews while missed events
were only counted; the event table does not store teams or scheduled tip time
(`backend/nba_model_store.py:116-123`). The router previously opened only the
model database before calling the exporter (`backend/routers/nba_model.py:78-82`).
Schedule data supplies the missing metadata without changing the event schema.

The dev API listener on port 8096 ran in the backend process with `LP_DB_PATH`
present. Its value was checked without printing it: its basename is
`picks.dev.db`, and the file is readable. The API process had no
`NBA_MODEL_DB_PATH`, so it uses the model store's default dev database. The
same `require_dev_picks_db` guard used by the runtime validates and resolves the
picks path (`backend/nba_model_runtime.py:28-41`). This is why the API can
attach the schedule source in this deployment; option (c) is unnecessary.

Option (b), adding schedule fields to `nba_model_lock_events`, was rejected. It
would denormalize schedule data into the ledger and require a schema change;
the existing dev schedule is reachable, and the report can join its metadata
at read time. No lock-event schema was changed.

The router passes only season-2027 REG/CUP schedule rows from `nba.com` to the
exporter and opens the attached database with `mode=ro`
(`backend/routers/nba_model.py:42-60`). Missing or unreadable schedule data
falls back to the prior report payload. Event-only missed games are emitted
with their schedule metadata, `status: "missed"`, and an empty `models` map
(`backend/nba_model_store.py:658-671`).

## Failing-first regression

At parent `e3157697`, the new temporary-database regression ran the sweep for a
previewed game and a game with no preview, then failed because the previewed
missed game was absent from `games`:

```text
E       AssertionError: previewed missed game 0022600001 is absent
1 failed in 0.29s
```

After the exporter and router changes, the focused lock-sweep and API regressions
passed: `8 passed`. The tests assert both missed games' status, empty model map,
tip and team metadata, per-model missed counts, the API's read-only schedule
attachment, and fallback when the schedule table is unavailable.

## Scratch-copy sweep

Both dev databases were copied with SQLite's backup API into scratch files; all
sweep writes targeted only those copies. Sweep time: `2026-10-22T03:26:20Z`.
The scratch picks copy contained 1,207 season-2027 REG/CUP
`nba.com` schedule rows.

| Measure | Before | After first sweep | After second sweep |
|---|---:|---:|---:|
| Missed lock-event rows | 9 | 42 | 42 |
| Newly inserted event rows | — | 33 | 0 |
| Sweep `missed_window_games` | — | 14 | 14 |
| Sweep `missed_lock_events` | — | 33 | 0 |
| Report games with `status=preview` | 22 | 22 | 22 |
| Report games with `status=missed` | 3 | 14 | 14 |
| `records[model].missed`, G1/G2/G3 | 3 each | 14 each | 14 each |
| Lock rows | 0 | 0 | 0 |
| Grade rows | 0 | 0 | 0 |

The lock and grade row-set digests remained the SHA-256 of an empty row set
(`4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`) at all
three snapshots. Thus the sweep added no lock or grade rows and changed none.

The first-run payload SHA-256 was
`f201222fa2da049b88393b237cdc9cda39bdecf154f49ea1ba9064ab3a194b65`; the
second-run payload had the same SHA-256 and was byte-identical. The pre-sweep
payload digest was `f8b95fc845f870d989a18c8fad0072f3894c299ac24365e108c7593dda30161d`.

## Real dev database integrity

SHA-256 values were computed on the actual dev database files before and after
the scratch work. Both pairs match:

| File | Before | After |
|---|---|---|
| `picks.dev.db` (3,173,289,984 bytes) | `df7788c53e90d1aa1227d02e88b62bc7b8a808d98f97ce42ff5e8bea17984ae9` | `df7788c53e90d1aa1227d02e88b62bc7b8a808d98f97ce42ff5e8bea17984ae9` |
| `nba-model.dev.sqlite3` (2,793,472 bytes) | `0e5636a7cf57b45b466884228990e2d6feb499f39cd6b1a59f1ffff7ff663fc7` | `0e5636a7cf57b45b466884228990e2d6feb499f39cd6b1a59f1ffff7ff663fc7` |

No live database, timer, promotion gate, model version, coefficient, or lock-event
schema was changed. No service was restarted and nothing was merged or deployed.
