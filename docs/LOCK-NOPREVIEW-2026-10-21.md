# NBA no-preview lock observability — 2026-10-21

**Location:** worktree `/root/lp-nba-lock-preflight`, branch `research/nba-lock-nopreview-2026-10-21`, based on `9536ad3b840ea264ec02140e1acac90707903a94`. This report audits read-only code at dev HEAD `04a421cfb2b17c2e5c64518da04ecf257f122bc6`.

## Code path: a schedule-only game disappears

The lock runtime takes its candidate set only from `nba_model_previews` (`backend/nba_model_runtime.py:376-392`):

```python
rows = model.execute(
    "SELECT * FROM nba_model_previews WHERE scheduled_start_utc>? "
    "AND scheduled_start_utc<=? ORDER BY scheduled_start_utc,game_id,model",
    (iso_utc(now), iso_utc(now + dt.timedelta(minutes=92))),
).fetchall()
items = [{
    "game_id": row["game_id"], "model": row["model"], "season": row["season"],
    "scheduled_start_utc": row["scheduled_start_utc"],
    "home_team": row["home_team"], "away_team": row["away_team"],
    "model_version": row["model_version"], "forecast": json.loads(row["forecast_json"]),
    "feature_snapshot": json.loads(row["feature_snapshot_json"]),
    "source_hash": row["source_hash"], "previewed_at_utc": row["previewed_at_utc"],
} for row in rows]
report = upsert_lock_calls(model, items, now)
missed = record_missed_windows(model, now)
report["missed_events_recorded"] = missed
```

`lock_forecasts` groups and iterates only the rows passed by that runtime (`backend/nba_model_store.py:417-424`):

```python
by_game: dict[str, list[dict[str, Any]]] = {}
for row in rows:
    by_game.setdefault(str(row["game_id"]), []).append(row)
con.execute("BEGIN")
try:
    for game_id, game_rows in by_game.items():
        if {row["model"] for row in game_rows} != set(MODEL_IDS) or len(game_rows) != len(MODEL_IDS):
            raise NBAModelStoreError(f"{game_id}: lock feed must contain exactly G1/G2/G3")
```

The missed-window recorder also selects and iterates only preview rows (`backend/nba_model_store.py:470-486`):

```python
locked = {(r[0], r[1]) for r in con.execute("SELECT game_id,model FROM nba_model_locks")}
missed = 0
con.execute("BEGIN")
try:
    rows = con.execute("SELECT * FROM nba_model_previews").fetchall()
    for row in rows:
        key = (row["game_id"], row["model"])
        if key in locked or now < parse_time(row["scheduled_start_utc"]):
            continue
        cursor = con.execute(
            "INSERT OR IGNORE INTO nba_model_lock_events(game_id,model,season,event_type,"
            "recorded_at_utc) VALUES(?,?,?,'missed_t90_window',?)",
            (row["game_id"], row["model"], row["season"], iso_utc(now)),
        )
        missed += cursor.rowcount
```

Both graders are row-driven too. The locked grader selects locks (`backend/nba_model_store.py:515-516`):

```python
locks = con.execute("SELECT * FROM nba_model_locks ORDER BY game_id,model").fetchall()
for lock in locks:
```

The unlocked-preview grader selects stored previews with no matching lock (`backend/nba_model_store.py:573-577`):

```python
rows = con.execute(
    "SELECT p.* FROM nba_model_previews p LEFT JOIN nba_model_locks l USING(game_id,model) "
    "WHERE l.game_id IS NULL ORDER BY p.game_id,p.model"
).fetchall()
for row in rows:
```

Consequently a schedule row with no preview yields no lock input, no iteration in either missed-window loop, and no row for either grader. It does not increment `missed_window_games` or write an event at tipoff. The prior SAC@LAC case had previews eventually, so it reached the preview-based late-event path; the zero-preview case does not.

## Scratch-copy reproduction

Both live databases were opened with SQLite `mode=ro` and backed up to a temporary directory. A synthetic season-2027 REG schedule row was added only to the scratch `picks.dev.db`. No model preview was added for it. I called the existing `lock_due_forecasts` runtime against the scratch model DB at a time after its T−88 and before its tip. The copied model DB retained its 75 real preview rows and 9 existing lock events; the synthetic game had none.

Actual command:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import datetime as dt
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
live_dir = Path('/root/legendarypicks/backend/data')
scratch = Path(tempfile.mkdtemp(prefix='nba-lock-nopreview-20261021-'))
picks_copy = scratch / 'picks.dev.db'
model_copy = scratch / 'nba-model.dev.sqlite3'
for source, target in ((live_dir / 'picks.dev.db', picks_copy),
                       (live_dir / 'nba-model.dev.sqlite3', model_copy)):
    src = sqlite3.connect(f'file:{source}?mode=ro', uri=True)
    dst = sqlite3.connect(str(target))
    src.backup(dst, pages=1024)
    dst.close()
    src.close()

now = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
tip = now + dt.timedelta(minutes=30)
t90 = tip - dt.timedelta(minutes=90)
t88 = tip - dt.timedelta(minutes=88)
def iso(value):
    return value.strftime('%Y-%m-%dT%H:%M:%SZ')
now_s, tip_s = iso(now), iso(tip)
game_id = '9999999999'
picks = sqlite3.connect(str(picks_copy))
picks.execute("""INSERT INTO nba_schedule
(game_id,season,season_type,game_code,game_date,start_utc,away_team,home_team,source,ingested_at)
VALUES(?,2027,'REG','SYNTH-NOPREVIEW',?,?,?,?, 'nba.com', ?)""",
              (game_id, tip.date().isoformat(), tip_s, 'AWY', 'HOM', now_s))
picks.commit()
schedule_rows = picks.execute('SELECT count(*) FROM nba_schedule WHERE game_id=?', (game_id,)).fetchone()[0]
picks.close()
model = sqlite3.connect(f'file:{model_copy}?mode=ro', uri=True)
preview_total = model.execute('SELECT count(*) FROM nba_model_previews').fetchone()[0]
synthetic_previews = model.execute('SELECT count(*) FROM nba_model_previews WHERE game_id=?', (game_id,)).fetchone()[0]
events_before = model.execute('SELECT count(*) FROM nba_model_lock_events').fetchone()[0]
synthetic_events_before = model.execute('SELECT count(*) FROM nba_model_lock_events WHERE game_id=?', (game_id,)).fetchone()[0]
model.close()

sys.path.insert(0, '/root/legendarypicks/backend')
from nba_model_runtime import lock_due_forecasts
result = lock_due_forecasts(model_db_path=str(model_copy), now=now)
model = sqlite3.connect(f'file:{model_copy}?mode=ro', uri=True)
events_after = model.execute('SELECT count(*) FROM nba_model_lock_events').fetchone()[0]
synthetic_events_after = model.execute('SELECT count(*) FROM nba_model_lock_events WHERE game_id=?', (game_id,)).fetchone()[0]
locks_after = model.execute('SELECT count(*) FROM nba_model_locks').fetchone()[0]
model.close()
print(json.dumps({
    'scratch_dir': str(scratch),
    'live_databases_opened_mode_ro': True,
    'synthetic_game_id': game_id,
    'runtime_now_utc': now_s,
    'synthetic_tip_utc': tip_s,
    'synthetic_t90_utc': iso(t90),
    'synthetic_t88_utc': iso(t88),
    'schedule_rows_for_synthetic': schedule_rows,
    'model_preview_rows_total': preview_total,
    'model_preview_rows_for_synthetic': synthetic_previews,
    'lock_due_forecasts': result,
    'lock_events_before_after': [events_before, events_after],
    'synthetic_events_before_after': [synthetic_events_before, synthetic_events_after],
    'locks_after': locks_after,
}, sort_keys=True))
PY
```

Actual output:

```json
{"live_databases_opened_mode_ro": true, "lock_due_forecasts": {"existing_games": 0, "inserted_games": 0, "missed_events_recorded": 0, "missed_window_games": 0, "not_due_games": 0}, "lock_events_before_after": [9, 9], "locks_after": 0, "model_preview_rows_for_synthetic": 0, "model_preview_rows_total": 75, "runtime_now_utc": "2026-10-22T02:42:00Z", "schedule_rows_for_synthetic": 1, "scratch_dir": "/tmp/nba-lock-nopreview-20261021-p4xmx86l", "synthetic_events_before_after": [0, 0], "synthetic_game_id": "9999999999", "synthetic_t88_utc": "2026-10-22T01:44:00Z", "synthetic_t90_utc": "2026-10-22T01:42:00Z", "synthetic_tip_utc": "2026-10-22T03:12:00Z"}
```

This shows the no-preview game was already past T−88, but the existing runtime returned zero missed games and wrote zero events. The scratch directory was removed after verification; live databases remained read-only.

## Preview cadence check for all 54 scheduled games

The live timer listing at 21:43 CDT showed the lock timer last fired at 21:43 and next at 21:44; the preview timer last fired at 21:37 and next at 21:52. Its installed `OnCalendar=*-*-* *:07/15:00` yields ticks at `:07`, `:22`, `:37`, and `:52`. `PREVIEW_MAX_AGE` is 120 minutes (`backend/nba_model_store.py:16-18`). For each of the same 54 REG/CUP games in the preflight window, the immediately preceding scheduled preview tick is exactly **8 minutes** before T−90, leaving 112 minutes inside the age limit. This is scheduled tick arithmetic; it does not assert that the preview job completed or that inputs were available.

| Game ID | T−90 CDT | Immediately preceding preview tick CDT | Gap |
| --- | --- | --- | ---: |
| `0022600093` | Wed Oct 21 20:00 | Wed Oct 21 19:52 | 8 min |
| `0022600006` | Thu Oct 22 16:30 | Thu Oct 22 16:22 | 8 min |
| `0022600007` | Thu Oct 22 19:00 | Thu Oct 22 18:52 | 8 min |
| `0022600008` | Fri Oct 23 16:30 | Fri Oct 23 16:22 | 8 min |
| `0022600094` | Fri Oct 23 16:30 | Fri Oct 23 16:22 | 8 min |
| `0022600095` | Fri Oct 23 16:30 | Fri Oct 23 16:22 | 8 min |
| `0022600096` | Fri Oct 23 16:30 | Fri Oct 23 16:22 | 8 min |
| `0022600097` | Fri Oct 23 16:30 | Fri Oct 23 16:22 | 8 min |
| `0022600098` | Fri Oct 23 17:30 | Fri Oct 23 17:22 | 8 min |
| `0022600099` | Fri Oct 23 17:30 | Fri Oct 23 17:22 | 8 min |
| `0022600009` | Fri Oct 23 19:00 | Fri Oct 23 18:52 | 8 min |
| `0022600100` | Fri Oct 23 19:00 | Fri Oct 23 18:52 | 8 min |
| `0022600101` | Fri Oct 23 19:30 | Fri Oct 23 19:22 | 8 min |
| `0022600102` | Fri Oct 23 19:30 | Fri Oct 23 19:22 | 8 min |
| `0022600103` | Fri Oct 23 19:30 | Fri Oct 23 19:22 | 8 min |
| `0022600104` | Sat Oct 24 15:30 | Sat Oct 24 15:22 | 8 min |
| `0022600105` | Sat Oct 24 17:00 | Sat Oct 24 16:52 | 8 min |
| `0022600106` | Sat Oct 24 17:00 | Sat Oct 24 16:52 | 8 min |
| `0022600107` | Sat Oct 24 17:30 | Sat Oct 24 17:22 | 8 min |
| `0022600108` | Sat Oct 24 17:30 | Sat Oct 24 17:22 | 8 min |
| `0022600109` | Sat Oct 24 17:30 | Sat Oct 24 17:22 | 8 min |
| `0022600110` | Sat Oct 24 18:30 | Sat Oct 24 18:22 | 8 min |
| `0022600111` | Sat Oct 24 19:30 | Sat Oct 24 19:22 | 8 min |
| `0022600112` | Sun Oct 25 14:30 | Sun Oct 25 14:22 | 8 min |
| `0022600113` | Sun Oct 25 15:30 | Sun Oct 25 15:22 | 8 min |
| `0022600114` | Sun Oct 25 16:30 | Sun Oct 25 16:22 | 8 min |
| `0022600115` | Sun Oct 25 16:30 | Sun Oct 25 16:22 | 8 min |
| `0022600116` | Sun Oct 25 16:30 | Sun Oct 25 16:22 | 8 min |
| `0022600117` | Sun Oct 25 17:00 | Sun Oct 25 16:52 | 8 min |
| `0022600118` | Sun Oct 25 18:30 | Sun Oct 25 18:22 | 8 min |
| `0022600119` | Mon Oct 26 16:30 | Mon Oct 26 16:22 | 8 min |
| `0022600120` | Mon Oct 26 16:30 | Mon Oct 26 16:22 | 8 min |
| `0022600121` | Mon Oct 26 17:00 | Mon Oct 26 16:52 | 8 min |
| `0022600122` | Mon Oct 26 17:00 | Mon Oct 26 16:52 | 8 min |
| `0022600123` | Mon Oct 26 17:30 | Mon Oct 26 17:22 | 8 min |
| `0022600124` | Mon Oct 26 17:30 | Mon Oct 26 17:22 | 8 min |
| `0022600125` | Mon Oct 26 18:00 | Mon Oct 26 17:52 | 8 min |
| `0022600126` | Mon Oct 26 18:30 | Mon Oct 26 18:22 | 8 min |
| `0022600127` | Mon Oct 26 19:30 | Mon Oct 26 19:22 | 8 min |
| `0022600128` | Tue Oct 27 17:00 | Tue Oct 27 16:52 | 8 min |
| `0022600129` | Tue Oct 27 17:30 | Tue Oct 27 17:22 | 8 min |
| `0022600130` | Tue Oct 27 17:30 | Tue Oct 27 17:22 | 8 min |
| `0022600131` | Tue Oct 27 20:30 | Tue Oct 27 20:22 | 8 min |
| `0022600132` | Wed Oct 28 16:30 | Wed Oct 28 16:22 | 8 min |
| `0022600133` | Wed Oct 28 16:30 | Wed Oct 28 16:22 | 8 min |
| `0022600134` | Wed Oct 28 16:30 | Wed Oct 28 16:22 | 8 min |
| `0022600135` | Wed Oct 28 16:30 | Wed Oct 28 16:22 | 8 min |
| `0022600136` | Wed Oct 28 17:00 | Wed Oct 28 16:52 | 8 min |
| `0022600137` | Wed Oct 28 17:30 | Wed Oct 28 17:22 | 8 min |
| `0022600138` | Wed Oct 28 17:30 | Wed Oct 28 17:22 | 8 min |
| `0022600139` | Wed Oct 28 17:30 | Wed Oct 28 17:22 | 8 min |
| `0022600140` | Wed Oct 28 17:30 | Wed Oct 28 17:22 | 8 min |
| `0022600141` | Wed Oct 28 18:30 | Wed Oct 28 18:22 | 8 min |
| `0022600142` | Wed Oct 28 19:00 | Wed Oct 28 18:52 | 8 min |

The arithmetic refutes an inherent cadence mismatch. The first game, SAC@LAC, still missed: its T−90 was 20:00 CDT, its scheduled preceding preview tick was 19:52, but its three rows were timestamped 21:07 CDT, 67 minutes after T−90. The interval had a timely tick; the row did not arrive at that tick. The data do not identify whether a particular preview run failed or its source schedule/features were delayed. Operational failures or stalled inputs remain the risk; cadence spacing itself is not.

## Proposal only: schedule-driven missed-window sweep

Use the existing event type `missed_t90_window` (the event table permits only that value and is keyed by `(game_id, model, event_type)`; `backend/nba_model_store.py:136-143`). From the model DB, attach the configured dev `picks.dev.db` read-only as `picks`. Once the full two-minute lock window is closed, select every scheduled game/model that still lacks a lock:

```sql
WITH expected_models(model) AS (VALUES ('G1'), ('G2'), ('G3'))
SELECT s.game_id, s.season, expected_models.model, s.start_utc
FROM picks.nba_schedule AS s
CROSS JOIN expected_models
LEFT JOIN nba_model_locks AS l
  ON l.game_id = s.game_id AND l.model = expected_models.model
WHERE s.season = 2027
  AND s.season_type IN ('REG', 'CUP')
  AND s.source = 'nba.com'
  AND s.start_utc <= :t88_cutoff_utc
  AND l.game_id IS NULL
ORDER BY s.start_utc, s.game_id, expected_models.model;
```

`:t88_cutoff_utc` is `iso_utc(now + 88 minutes)`. That implies T−90 has passed and waits until `[T−90,T−88)` is closed, so a lock attempt at T−90 or T−89 is not prematurely labeled missed. Insert one `missed_t90_window` event for each returned model with `INSERT OR IGNORE`; this catches a game with zero previews and missing members of a partial lock set, while a complete three-model lock set yields no rows.

Call this sweep from `lock_due_forecasts` on its existing once-per-minute path, after `lock_forecasts`, in place of the preview-only `record_missed_windows` call. No implementation or timer change was made.

One regression test that fails today: in an isolated DB, add one season-2027 REG `nba_schedule` row with `start_utc = now + 30 minutes`, no preview rows, and no lock rows; call the missed-window sweep at `now` (T−88 is already past). Assert it writes three `missed_t90_window` rows, one each for G1/G2/G3, and a second call writes zero additional rows. Today `lock_due_forecasts` returns `missed_window_games=0`, `missed_events_recorded=0` for this fixture.

## Scope

Report only. No backend code, live or scratch systemd unit, gate, model, live database, or production data was changed. The synthetic schedule row and runtime execution were confined to the two scratch copies.
