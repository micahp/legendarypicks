# TASK — dedupe MLB duplicate player rows on PROD, then unblock roster_sync

**Owner:** delegated (reasonix / deepseek-v4-flash)
**Status:** not started
**Written:** 2026-08-04 evening

---

## Do NOT use a worktree

`scripts/hermes-worktree.sh` symlinks **only** `picks.dev.db` into a worktree, never
`picks.db`. Running `--db data/picks.db` from a worktree makes sqlite **create a new
empty database**, and every step below then reports a clean run against nothing.

Work in `/root/legendarypicks`. Use **absolute** DB paths.

---

## Why

`roster_sync` cannot apply for MLB on prod. It reports `identity_incomplete` with **48
unresolvable of 785** ESPN roster entries = **6.1%**, over the 2% floor at
`backend/roster_sync.py:39`.

**46 of those 48 are not ambiguity — they are duplicate rows of the same player**, same
name, same team, same `mlbam_id`:

```
Mookie Betts    [LAD]  id=114 team=LAD mlbam=605141   id=26622 team=LAD mlbam=605141
Freddie Freeman [LAD]  id=109 team=LAD mlbam=518692   id=26611 team=LAD mlbam=518692
```

`team` cannot disambiguate, because both rows *are* the same player on the same team.

Prod has **317 `mlbam_id` values carrying more than one row — 634 rows, 317 redundant.**
Only 1 of those groups has byte-identical names; the rest are the same player ingested
twice under different spellings by two publishers sharing one MLB id.

Collapsing them should take unresolvable from 48 to ~2 (≈0.25%), under the floor, and
MLB applies.

The remaining 2 are real and are expected to survive: stale trade data (JoJo Romero
STL→MIL, Adley Rutschman BAL→BOS) and one genuine collision (Max Muncy — LAD
`mlbam=571970` vs ATH `mlbam=691777`, two different people).

---

## Step 0 — one code change, and only this one

`backend/dedupe_mlb.py` line 20:

```python
REF_TABLES = ["player_game_logs", "props", "player_stats", "predictions"]
```

Add `roster_memberships` and `roster_snap`:

```python
REF_TABLES = ["player_game_logs", "props", "player_stats", "predictions",
              "roster_memberships", "roster_snap"]
```

Both carry a `player_id` and neither is repointed today. They hold **0** rows for
duplicate-group players *right now* only because MLB roster_sync has never applied — the
moment it does, a later dedupe would orphan them. Note that the loop swallows
`sqlite3.OperationalError` and passes, so a missing or misspelled table name fails
**silently**; do not rely on it erroring.

Commit this one change on its own before running anything:

```
fix(dedupe): repoint roster_memberships and roster_snap too
```

**No other code changes anywhere in this task.**

---

## Step 1 — back up prod

```bash
cd /root/legendarypicks/backend
cp data/picks.db "data/picks.db.pre-mlb-dedupe-$(date -u +%Y%m%dT%H%M%SZ).bak"
venv/bin/python -c "import sqlite3;print(sqlite3.connect('data/picks.db').execute('pragma quick_check').fetchone())"
```

Do not continue unless `quick_check` prints `ok`. Record the backup filename; you will
report it.

## Step 2 — record the before state

```bash
cd /root/legendarypicks/backend
venv/bin/python -c "
import sqlite3
c=sqlite3.connect('file:data/picks.db?mode=ro',uri=True)
print('mlb players total:', c.execute(\"select count(*) from players where league='mlb'\").fetchone()[0])
print('dup mlbam groups :', c.execute(\"select count(*) from (select mlbam_id from players where league='mlb' and mlbam_id is not null and mlbam_id!=0 group by mlbam_id having count(*)>1)\").fetchone()[0])
for t in ('player_game_logs','props','player_stats','roster_memberships','roster_snap'):
    print(f'{t:20s}', c.execute(f'select count(*) from \"{t}\"').fetchone()[0])
"
```

## Step 3 — dry run

```bash
cd /root/legendarypicks/backend
LP_DB_PATH=/root/legendarypicks/backend/data/picks.db venv/bin/python dedupe_mlb.py
```

Expect **317 mlbam_ids with duplicate rows** and **317 rows merged/deleted**. If the
number differs materially, **stop and report** — do not apply.

## Step 4 — apply

```bash
cd /root/legendarypicks/backend
LP_DB_PATH=/root/legendarypicks/backend/data/picks.db venv/bin/python dedupe_mlb.py --apply
```

## Step 5 — verify nothing was orphaned

This is the check that matters. Every reference table must have **zero** rows pointing at
a `player_id` that no longer exists, and the **total row counts must be unchanged** from
step 2 (repointing moves rows between players, it never deletes them).

```bash
cd /root/legendarypicks/backend
venv/bin/python -c "
import sqlite3
c=sqlite3.connect('file:data/picks.db?mode=ro',uri=True)
print('mlb players total:', c.execute(\"select count(*) from players where league='mlb'\").fetchone()[0])
print('dup mlbam groups :', c.execute(\"select count(*) from (select mlbam_id from players where league='mlb' and mlbam_id is not null and mlbam_id!=0 group by mlbam_id having count(*)>1)\").fetchone()[0])
bad=0
for t in ('player_game_logs','props','player_stats','roster_memberships','roster_snap','predictions'):
    try:
        n=c.execute(f'select count(*) from \"{t}\" where player_id is not null and player_id not in (select id from players)').fetchone()[0]
        tot=c.execute(f'select count(*) from \"{t}\"').fetchone()[0]
        print(f'{t:20s} total={tot:8d}  ORPHANED={n}')
        bad+=n
    except Exception as e: print(t,'ERR',e)
print('ORPHAN TOTAL:', bad, '(must be 0)')
"
```

`dup mlbam groups` must now be **0**. `ORPHAN TOTAL` must be **0**. If either is not,
**stop and report** — the backup from step 1 is the restore path.

## Step 6 — re-fill the spine

The spine fill keys its lookup by `mlbam_id` in a **dict**, so for a duplicate pair only
one of the two rows ever received `team`/`position`. After the dedupe the surviving
canonical row may be the one that missed out, so run it again:

```bash
cd /root/legendarypicks/backend
venv/bin/python ingest_mlb_spine_identity.py --season 2026 \
  --db /root/legendarypicks/backend/data/picks.db
```

## Step 7 — the payoff: re-run roster_sync for MLB

```bash
cd /root/legendarypicks/backend
LP_DB_PATH=/root/legendarypicks/backend/data/picks.db venv/bin/python roster_sync.py mlb 2>&1 | tail -25
```

Expected: `complete`, 30/30 teams, and MLB active dropping from 2,750 to roughly **785**
(the number of entries ESPN actually publishes).

If it still says `identity_incomplete`, **that is a valid answer** — report the
unresolvable count and stop.

**Do NOT** lower `_MAX_UNRESOLVABLE_SHARE`, do NOT set `LP_ROSTER_MAX_UNRESOLVABLE`, do
NOT edit the matching logic. The floor is the safety property; making it pass by moving
it writes a wrong roster.

---

## Out of scope

* Any code change other than Step 0.
* Docker: no build, no `up`, no restarts. Prod is serving live.
* Host config: `/etc`, systemd units, timers, cron.
* `git push`. Commit Step 0 locally; do not push.
* Other leagues. MLB only.
* Deleting the backup from Step 1.

---

## Report back, between the literal markers `===RESULT===` and `===END===`

1. the Step 1 backup filename
2. Step 2 before-counts and Step 5 after-counts, side by side
3. `ORPHAN TOTAL` and `dup mlbam groups` after the apply
4. Step 7's status line **verbatim**, and the final MLB active count
5. `git -C /root/legendarypicks status --short` and `git log --oneline -1`

Then stop and wait.
