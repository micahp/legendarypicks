# NBA lock and grade dry run — 2026-10-21

Diagnostic run against a disposable model-database copy. No writes were made to either database in `/root/legendarypicks/backend/data`.

## Outcome

- PHI–CLE (`0022600006`, tip 2026-10-22 23:00Z) produced three immutable G1/G2/G3 locks with `t90-2m-v1` and feature cutoff 21:31Z.
- A synthetic confirmed 110–104 home win produced three locked grades. Manually computed Brier and log-loss match stored values exactly (absolute difference 0 for all six comparisons).
- Exact lock retry and grade retry inserted no duplicates. Lock, grade, missed-window event, and preview-grade update/delete triggers all aborted the attempted mutation.
- In a separate memory-only source snapshot, three missed games produced nine descriptive preview grades. Every model still had `records.locked = 0`; these rows are not part of the locked record. Treating unlocked grades as adoption evidence is Micah’s decision, not mine.

## Test inputs and commands

Code under test was `/root/legendarypicks` HEAD `04a421cfb2b17c2e5c64518da04ecf257f122bc6`.

The persistent scratch database was `/root/.hermes/cache/scratch/nba-lock-dryrun/model-copy.sqlite3`. The runtime calls used:

```sh
NBA_MODEL_DB_PATH=/root/.hermes/cache/scratch/nba-lock-dryrun/model-copy.sqlite3 \
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
PYTHONPATH=/root/legendarypicks/backend python3 - <<'PY'
from datetime import datetime
from nba_model_runtime import build_preview_rows, lock_due_forecasts, grade_due_forecasts
from nba_model_store import open_db, upsert_previews

def utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

# The saved PHI-CLE preview was stale for the simulated 21:31Z lock time.
# Regenerate only its three model rows in the scratch database, using the
# runtime feature builder and the dev picks database opened read-only.
rows = build_preview_rows(
    "/root/legendarypicks/backend/data/picks.dev.db",
    "/root/.hermes/cache/scratch/nba-lock-dryrun/model-copy.sqlite3",
    utc("2026-10-22T21:31:00Z"),
)
rows = [row for row in rows if row["game_id"] == "0022600006"]
con = open_db("/root/.hermes/cache/scratch/nba-lock-dryrun/model-copy.sqlite3")
upsert_previews(con, rows, utc("2026-10-22T21:31:00Z"))
con.close()

for stamp in ("2026-10-22T21:31:00Z", "2026-10-22T21:31:00Z",
              "2026-10-22T21:31:30Z", "2026-10-22T21:32:30Z",
              "2026-10-22T21:33:30Z"):
    print(stamp, lock_due_forecasts(
        "/root/.hermes/cache/scratch/nba-lock-dryrun/model-copy.sqlite3", utc(stamp)))

# A final-confirmed synthetic observation (110–104) was inserted into the copy
# for 0022600006; the runtime grader was called at 2026-10-22T23:10:00Z and
# called again at the same time for idempotency.
print(grade_due_forecasts(
    "/root/legendarypicks/backend/data/picks.dev.db",
    "/root/.hermes/cache/scratch/nba-lock-dryrun/model-copy.sqlite3",
    utc("2026-10-22T23:10:00Z")))
PY
```

The first lock call above was the original run against this copy; the remaining retry and boundary calls were repeated after resuming. The grade-stage body used the following confirmed observation, then tested a mismatched team before invoking the runtime grader twice:

```python
import sqlite3
from datetime import datetime
from nba_model_store import (open_db, store_live_observation, latest_verified_results,
                             grade_forecasts)

def utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

copy_path = "/root/.hermes/cache/scratch/nba-lock-dryrun/model-copy.sqlite3"
lp_path = "/root/legendarypicks/backend/data/picks.dev.db"
con = open_db(copy_path)
con.row_factory = sqlite3.Row
observation = {
    "nba_game_id": "0022600006", "season": 2027, "game_date": "2026-10-22",
    "scheduled_start_utc": "2026-10-22T23:00:00Z",
    "source_event_id": "SYNTHETIC-DRYRUN-0022600006",
    "home_team": "PHI", "away_team": "CLE", "home_score": 110, "away_score": 104,
    "home_stats": {"field_goals_attempted": 85, "free_throws_attempted": 22,
                   "offensive_rebounds": 10, "turnovers": 12},
    "away_stats": {"field_goals_attempted": 88, "free_throws_attempted": 19,
                   "offensive_rebounds": 9, "turnovers": 14},
    "source_hash": "38ca9f608bf2b58e6cdd571128918324e73c40272d6cef1d8c0eafbee9932058",
    "source": "synthetic lock-grade dry run", "final_confirmed": True,
    "observed_at_utc": "2026-10-22T23:10:00Z",
}
store_live_observation(con, observation)
results = latest_verified_results(con)
wrong = {key: dict(value) for key, value in results.items()}
wrong["0022600006"]["home_team"] = "BOS"
grade_forecasts(con, wrong, utc("2026-10-22T23:10:00Z"))  # raises NBAModelStoreError
grade_due_forecasts(lp_path, copy_path, utc("2026-10-22T23:10:00Z"))
grade_due_forecasts(lp_path, copy_path, utc("2026-10-22T23:10:00Z"))
con.close()
```

Home/away box-score inputs were FGA 85/88, FTA 22/19, offensive rebounds 10/9, and turnovers 12/14. The observation was stored with `final_confirmed=1`. The wrong-home-team call raised `0022600006: result team identity differs from lock` and rolled back before the two valid runtime calls.

For the unlocked path, a SQLite read-only connection to the dev model DB was backed up into `:memory:`. The synthetic results were constructed from each preview’s stored team identity; their event IDs were `SYNTHETIC-UNLOCKED-<game_id>`, source was `synthetic unlocked-preview dry run`, and each source hash was SHA-256 of `unlocked-<game_id>`:

```python
import hashlib
import sqlite3
from datetime import datetime
from nba_model_store import grade_unlocked_previews, export_payload

def utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

source = sqlite3.connect(
    "file:/root/legendarypicks/backend/data/nba-model.dev.sqlite3?mode=ro", uri=True)
memory = sqlite3.connect(":memory:")
source.backup(memory)
source.close()
memory.row_factory = sqlite3.Row
synthetic_results = {}
for game_id, home_score, away_score in zip(
        ("0022600005", "0022600092", "0022600093"),
        (118, 109, 112), (111, 106, 103)):
    preview = memory.execute(
        "SELECT * FROM nba_model_previews WHERE game_id=? ORDER BY model LIMIT 1",
        (game_id,)).fetchone()
    synthetic_results[game_id] = {
        "completed": True, "summary_validated": True,
        "source_event_id": "SYNTHETIC-UNLOCKED-" + game_id,
        "source_hash": hashlib.sha256(("unlocked-" + game_id).encode()).hexdigest(),
        "source": "synthetic unlocked-preview dry run",
        "home_team": preview["home_team"], "away_team": preview["away_team"],
        "home_score": home_score, "away_score": away_score,
    }
grade_unlocked_previews(memory, synthetic_results, utc("2026-10-22T21:31:00Z"))
grade_unlocked_previews(memory, synthetic_results, utc("2026-10-22T21:31:00Z"))
export_payload(memory, 2027, now=utc("2026-10-22T21:31:00Z"))
```

This memory-only run did not write to the scratch file or either dev database.

The initial SQLite backup was made from the source using SQLite's backup API with the source opened as `file:/root/legendarypicks/backend/data/nba-model.dev.sqlite3?mode=ro`. Its SHA-256 was:

```text
8cf4d980fc5bed4e9e3ee2acfb010079f321955c4d40e36ee44aafbba06b5f52
```

At resume, the copy already contained the three PHI–CLE locks and nine missed-window events from the prior pass; its then-current SHA-256 was `0419760b00756870db3f790af87757c5490d32f18cb0ce213bf27b00d419351c`. I continued from that state and did not recreate or reset it. After grading and trigger checks, its SHA-256 was `91a4d9ce3c7dcc6f4841a69cae2e3ebd05ef7af4c38cc71c1b75fb5512e91336`.

## Lock behavior

The PHI–CLE feature cutoff and `locked_at_utc` were both `2026-10-22T21:31:00Z`; scheduled tip was `2026-10-22T23:00:00Z`. All three lock rows had protocol `t90-2m-v1`. The preview feature snapshot included `cutoff_utc=2026-10-22T21:31:00Z`, strictly before tip.

| Call time (UTC) | inserted games | existing games | missed-window games | newly recorded missed events |
|---|---:|---:|---:|---:|
| 21:31:00 first call | 1 | 0 | 0 | 9 |
| 21:31:00 retry | 0 | 1 | 0 | 0 |
| 21:31:30, inside window | 0 | 1 | 0 | 0 |
| 21:32:30 | 0 | 0 | 1 | 0 |
| 21:33:30, window closed | 0 | 0 | 1 | 0 |

The requested brief described 21:32:30 as still inside the two-minute window. For a 23:00Z tip, that window is 21:30–21:32Z, so 21:32:30 is outside it. At both post-window calls, the existing PHI–CLE lock remained intact and no row was inserted; the runtime reported `missed_window_games=1` for those calls despite the existing lock.

The nine first-call missed events were three models each for three earlier games: `0022600005` LAL–GS, `0022600092` POR–PHX, and `0022600093` LAC–SAC. The lock table remained at three rows throughout.

## Grading and independent score check

The synthetic final was PHI 110, CLE 104, so the home-win outcome was 1. The formulas independently applied were Brier `((p_home - 1) ** 2)` and log-loss `(-ln(p_home))`.

| Model | Home-win probability | Stored Brier | Manual Brier | Stored log-loss | Manual log-loss | Absolute deltas (Brier, log-loss) |
|---|---:|---:|---:|---:|---:|---:|
| G1 | 0.5022560267866565 | 0.24774906287020562 | 0.24774906287020562 | 0.6886452757838631 | 0.6886452757838631 | 0, 0 |
| G2 | 0.5131657152559199 | 0.23700762080228005 | 0.23700762080228005 | 0.6671564542869168 | 0.6671564542869168 | 0, 0 |
| G3 | 0.52099609375 | 0.2294447422027588 | 0.2294447422027588 | 0.652012734857645 | 0.652012734857645 | 0, 0 |

G1’s home-points, away-points, spread, and total absolute-error fields were all NULL because G1 has no score forecast. The mismatched identity raised `0022600006: result team identity differs from lock`.

First runtime grade call: `graded=3`, `already_graded=0`, `awaiting_verified_final=0`; unlocked path in that same call: `preview_graded=0`, `preview_already_graded=0`, `preview_awaiting_verified_final=69`. Second identical call: `graded=0`, `already_graded=3`, `awaiting_verified_final=0`; unlocked path again had `preview_graded=0`, `preview_already_graded=0`, `preview_awaiting_verified_final=69`.

## Immutable-trigger checks

Each attempted update and delete was blocked with `sqlite3.IntegrityError`; the tested rows and counts remained present.

| Table | UPDATE and DELETE error |
|---|---|
| `nba_model_locks` | `NBA locked forecasts are immutable` |
| `nba_model_grades` | `NBA forecast grades are immutable` |
| `nba_model_lock_events` | `NBA lock events are immutable` |
| `nba_model_preview_grades` (memory-only clone) | `NBA preview grades are immutable` |

## Unlocked previews remain separate

First memory-only pass: `preview_graded=9`, `preview_already_graded=0`, `preview_awaiting_verified_final=63`. Second pass: `preview_graded=0`, `preview_already_graded=9`, `preview_awaiting_verified_final=63`. Counts after the run were 72 previews, 9 preview grades, 0 locks, 0 locked grades, and 0 lock events. The other 63 preview rows were future relative to the simulation time and awaiting a verified final.

The three games each had status `unlocked`, `locked_at_utc=null`, and three model forecasts marked `locked=false` with grades present. Per-model aggregates were:

| Model | `records.locked` | locked `records.graded` | unlocked previewed | unlocked graded |
|---|---:|---:|---:|---:|
| G1 | 0 | 0 | 3 | 3 |
| G2 | 0 | 0 | 3 | 3 |
| G3 | 0 | 0 | 3 | 3 |

These are synthetic descriptive grades for unlocked previews, not part of the immutable locked record and not evidence for model adoption. Whether to count them as adoption evidence is Micah’s decision.

## Row counts and read-only verification

The source counts below were read through SQLite `mode=ro` before and after this resumed run. SQLite listed **eight** `nba_model_*` tables; the brief expected nine, but no ninth table existed.

| Source table | Before | After |
|---|---:|---:|
| `nba_model_grades` | 0 | 0 |
| `nba_model_history` | 11,976 | 11,976 |
| `nba_model_live_game_observations` | 5 | 5 |
| `nba_model_lock_events` | 0 | 0 |
| `nba_model_locks` | 0 | 0 |
| `nba_model_meta` | 5 | 5 |
| `nba_model_preview_grades` | 0 | 0 |
| `nba_model_previews` | 72 | 72 |

The initial backup, made earlier when the source had three live observations, contained 72 previews, 11,976 history rows, 3 live observations, and zero rows in locks, grades, preview grades, and lock events. At the start of this resumed run the scratch copy already had three locks and nine lock events from the first lock pass, plus zero grades and three live observations. After this run its counts were: 72 previews, 3 locks, 3 locked grades, 0 preview grades, 9 lock events, 4 live observations, 11,976 history rows, and 5 metadata rows. The memory-only clone began with the then-current source counts and ended with 9 preview grades; its lock, locked-grade, and lock-event counts remained 0.

Read-only dev checkout checks before and after were unchanged:

- `git rev-parse HEAD`: `04a421cfb2b17c2e5c64518da04ecf257f122bc6`
- `git ls-remote origin refs/heads/dev`: `ea1db7645558e4032d7505b708c1ae60fb830d2a`
- `git diff --stat`: `research/nhl/prospective-2026-27/forecasts.jsonl | 30 ++++++++++++++++++++++++` (`1 file changed, 30 insertions(+)`)
- `git status --porcelain` was identical before and after this run: the modified NHL forecast file and the untracked paths listed below.
- No files in `/root/legendarypicks` were staged, edited, or committed by this run.

The five NBA code paths modified in `04a421cf` relative to `origin/dev` are:

```text
backend/nba_model_runtime.py
backend/nba_model_store.py
backend/test_nba_game_model_phase1.py
components/Leagues/NbaModelTab.test.tsx
components/Leagues/NbaModelTab.tsx
```

This corrects the original brief’s six-file **uncommitted** list: those five NBA files are now committed locally in `04a421cf`, while the NHL forecast file is the only tracked working-tree modification. The dev model page and timers use this local checkout; the NBA code is committed locally but is **not pushed** to `origin/dev` (`origin/dev` remains `ea1db764`). The working tree also contained these pre-existing untracked paths, which were left untouched:

```text
backend/data/backups-fbs-model/
backend/data/backups-nfl-identity-20261020/
backend/data/backups-tennis-20261013/
backend/data/fbs-model.dev.sqlite3
backend/data/fbs-parity-certificate.json
backend/data/nba-model-source/
backend/data/nba-model.dev.sqlite3
backend/data/nfl_projections_legacy_backup.json
backend/data/sim_2026_cold_seed1.json
backend/data/sim_2026_cold_seed2.json
backend/data/sim_2026_frozen_seed3.json
backend/data/simbt_2024_k0.json
backend/data/simbt_2024_k05.json
backend/data/simbt_2025_k0.json
backend/data/simbt_2025_k05.json
backend/data/tennis_point_archives/
data/prizepicks_drop/
picks.db
public/capture-catalog.html
public/paper-strategy-results.html
research/nhl/fullframe-event-audit-2026-10-21/
research/nhl/kalshi-playoff-audit-2025-26/
research/nhl/model-call-research-2026/run_favorite_puckline.py
```

## Interpretation

The lock, grade, score calculation, idempotency, identity rejection, and database immutability paths passed on the disposable copy. This proves the code path in a controlled dry run; it does not prove that the live timer will create tomorrow’s prospective lock or that a real final will grade successfully.

**One-line answer:** The pipeline is validated on a copy for tomorrow’s 16:30 CT lock window, but live execution remains unproven until dev records a real lock and grade.

## Later read-only observation after the push

At 2026-10-22 02:00:25Z, a final read-only check of the managed dev database found six `nba_model_lock_events`, all with `recorded_at_utc=2026-10-22T02:00:00Z`: G1/G2/G3 for `0022600005`, and G1/G2/G3 for `0022600092`. The dev source still had 0 locks and 0 grades; its other table counts matched the before-run values above. The immediate post-dry-run check had shown 0 source lock events. These later rows appeared after the dry run; this run wrote only to its scratch copy and the memory-only clone.

The NHL forecast file’s tracked diff also grew from 30 to 36 inserted lines between the immediate post-dry-run check and this final check. Its status path was pre-existing and was not edited by this run. The report’s `+30` diff statistic records the immediate post-dry-run snapshot; the later observed statistic was `1 file changed, 36 insertions(+)`.
