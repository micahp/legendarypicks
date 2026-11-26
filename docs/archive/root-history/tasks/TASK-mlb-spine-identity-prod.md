# TASK — fill MLB team + position on the PROD spine

**Owner:** delegated (DeepSeek via Hermes)
**Status:** not started
**Written:** 2026-08-04 evening

---

## Do NOT use a worktree

`scripts/hermes-worktree.sh` symlinks **only** `picks.dev.db` into a worktree. It
does not symlink `picks.db`. If you run this task from a worktree with
`--db data/picks.db`, sqlite will **create a brand new empty database** at that
path, the script will report a clean run against nothing, and prod will be
untouched while the report says otherwise.

Work in the main checkout, `/root/legendarypicks`, and use the **absolute** DB
path every time. Never a relative one.

---

## Background

`players.position` is 100% blank for MLB on prod and `team` is set on only 313 of
2,750 active rows. `roster_sync` (the ESPN path) cannot fix this: it matches by
normalized name and disambiguates by `espn_id` then `team`
(`backend/roster_sync.py:237-248`). Prod MLB has zero `espn_id` and almost no
`team`, so neither narrowing step fires, 179 entries stay ambiguous (6.5%, over
the 2% floor at `roster_sync.py:39`), and the whole league rolls back.

`backend/ingest_mlb_spine_identity.py` does not go through ESPN. It reads MLB's
own `sports/1/players?season=YYYY` and joins on **`mlbam_id`**, which prod has on
2,747 of 2,750 rows. It is structurally immune to the name ambiguity.

A `--dry-run` against prod on 2026-08-04 reported:

```
published    1358
position_set 1324
team_set     1136
not_in_spine   34
no_current_team 0
unchanged      0
```

---

## The work

Exactly these steps, in this order. Nothing else.

### 1. Back up prod first

```bash
cd /root/legendarypicks/backend
cp data/picks.db "data/picks.db.pre-mlb-spine-$(date -u +%Y%m%dT%H%M%SZ).bak"
venv/bin/python -c "import sqlite3;print(sqlite3.connect('data/picks.db').execute('pragma quick_check').fetchone())"
```

Do not continue unless `quick_check` prints `ok`.

### 2. Record the before state

```bash
cd /root/legendarypicks/backend
venv/bin/python -c "
import sqlite3
db=sqlite3.connect('file:data/picks.db?mode=ro',uri=True)
print(db.execute(\"select count(*), sum(team is not null and team!=''), sum(position is not null and position!='') from players where lower(league)='mlb' and active=1\").fetchone())
"
```

### 3. Re-run the dry run and confirm it still matches the numbers above

```bash
cd /root/legendarypicks/backend
venv/bin/python ingest_mlb_spine_identity.py --season 2026 \
  --db /root/legendarypicks/backend/data/picks.db --dry-run
```

If `published`, `position_set` or `team_set` differ materially from the table in
Background, **stop and report** rather than applying.

### 4. Apply

```bash
cd /root/legendarypicks/backend
venv/bin/python ingest_mlb_spine_identity.py --season 2026 \
  --db /root/legendarypicks/backend/data/picks.db
```

### 5. Record the after state

Re-run the step 2 command verbatim and report both numbers.

### 6. Re-run roster_sync for MLB only, and report the number — do not fix it

```bash
cd /root/legendarypicks/backend
LP_DB_PATH=/root/legendarypicks/backend/data/picks.db \
  venv/bin/python roster_sync.py mlb 2>&1 | tail -20
```

The open question this answers: with `team` now populated, does the
`team == abbr` narrowing at `roster_sync.py:243-246` bring the unresolvable
count under the 2% floor? Report the status line and the unresolvable count
verbatim. **Whatever it says, stop there.** If it still reports
`identity_incomplete`, that is a valid result and the answer to the question —
do not lower the floor, do not pass `LP_ROSTER_MAX_UNRESOLVABLE`, do not edit
the matching logic.

---

## Out of scope — do not touch

* Any file outside `backend/data/picks.db`. **No code changes at all.** This task
  runs existing scripts; it does not modify them.
* `_MAX_UNRESOLVABLE_SHARE` / `LP_ROSTER_MAX_UNRESOLVABLE`. The floor is the
  point of the exercise. Do not weaken it to make step 6 look better.
* `picks.dev.db`, and every other league. MLB only.
* Docker: no `docker compose build`, no `up`, no restarts. Prod is serving.
* Host config: `/etc`, systemd units, timers, cron. Worktrees do not isolate
  these and nothing here needs them.
* Git: do not commit, do not branch, do not push. This task produces **no diff**.
  If `git status` shows a modified tracked file when you finish, something went
  wrong — report it.

---

## Report back

1. before / after `(active, team, position)` counts for MLB
2. the apply run's JSON summary
3. step 6's status line and unresolvable count, verbatim
4. `git status --short` output (expected: unchanged from when you started)

Then stop and wait. Do not proceed to any follow-up work.
