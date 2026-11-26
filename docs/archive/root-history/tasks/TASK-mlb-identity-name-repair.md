# TASK — repair the MLB player names that belong to a different person

**Owner:** delegated (reasonix / deepseek-v4-flash)
**Status:** not started
**Written:** 2026-08-04 evening

---

## Do NOT use a worktree

`scripts/hermes-worktree.sh` symlinks **only** `picks.dev.db` into a worktree, never
`picks.db`. Pointing `--db` at `data/picks.db` from a worktree makes sqlite **create a new
empty database**, and every step below then reports a clean run against nothing.

Work in `/root/legendarypicks`. Use **absolute** DB paths everywhere.

---

## What is wrong, and which half of the row is the lie

`players` rows for MLB carry `name` and `mlbam_id`. On **223 prod rows and 167 dev rows**
they describe two different people:

```
id=26551  name='Eiberson Castellano'  mlbam_id=703607   MLB publishes 703607 = Henry Bolte
id=26571  name='Mason Miller'         mlbam_id=702616   MLB publishes 702616 = Jackson Holliday
id=26588  name='Walker Buehler'       mlbam_id=669236   MLB publishes 669236 = Jeremiah Jackson
```

**The `mlbam_id` is correct. The `name` is the corruption.** That is not an assumption —
it was traced tonight:

`backend/ingest_statcast.py`, before commit `b03b9c9`, resolved batter names like this:

```python
name = pitcher_id_to_name.get(batter_id)
if not name:
    name = group["player_name"].dropna()
    name = name.iloc[0] if len(name) > 0 else None   # <- the first PITCHER faced
```

Statcast's `player_name` column is the **pitcher's** name on every pitch row. A two-way
player hits the first lookup; a pure batter falls through and inherits the name of whoever
threw their first pitch. `player_id` still came from `batter_id`, which is right. So the
row keeps the correct id and acquires a stranger's name.

Confirmed on the data, not inferred:

* 208 of 216 bad rows changed **name only** between the 06-15 and 06-24 backups.
  `mlbam_id` moved on **0** rows.
* **201 of 203** resolvable wrong names belong to a **pitcher**; **203 of 203** true
  owners of the id are position players (C 36, LF 29, RF 27, CF 24, 2B 24, 3B 22, SS 18,
  1B 14, DH 8, OF 1). Zero pitchers among the owners.
* Not a positional shift: over the 2,271 placeholder rows in id order, offset 0 scores
  1072 correct and every offset from −5 to +5 scores **0**.

So the repair is **id-first**: take the name MLB publishes for that `mlbam_id`. Never
match on a name — name matching is what produced this.

---

## Step 0 — write the repair script

Create **`backend/repair_mlb_identity_names.py`**. This is the only file you create and
the only file you may modify. It must be a real, reviewable, re-runnable script — not a
`python -c` one-liner, because the diff is the record of what was done.

Requirements, all of them:

* Reads the published map from `backend/data/published-identity-names.json`
  (`["leagues"]["mlb"]["names"]`, a `str(mlbam_id) -> full name` dict, already committed).
* Reuses the audit's own normalisation — `from audit_league_stats import _identity_name_key`.
  **Do not re-implement it.** Two rulers is how a repair passes its own gate and fails the
  real one.
* Selects `id, name, mlbam_id from players where league='mlb' and mlbam_id is not null
  and mlbam_id != 0`.
* For each row: if `str(mlbam_id)` is in the map **and**
  `_identity_name_key(name) != _identity_name_key(published)`, set `name = published`
  (verbatim, accents included — the map is stored as MLB spells it).
* Also update the descriptive copies on the same rows:
  `UPDATE player_stats SET player_name=?, name_norm=? WHERE player_id=?` for each repaired
  id. `player_stats` is keyed by `player_id`, so this is the same row identity, not a join.
  Use the repo's existing `_normalize_name` for `name_norm` if `player_stats` rows carry
  it — check what the column already holds before choosing.
* Plain `UPDATE`. **Not `UPDATE OR IGNORE`.** If a constraint blocks a write, that must
  raise, not vanish. (There is no UNIQUE index on `players.name` today; if one appears,
  you want to hear about it.)
* Default is a **dry run**. `--apply` commits. `--db` takes an absolute path.
* Prints, in both modes: rows examined, rows whose id is not in the map (left alone),
  rows already correct, rows repaired — and the first 10 repairs as
  `id / old name / new name / mlbam_id`.

Hard rules for the script:

* **Never writes `mlbam_id`.** Not once, not as a fallback.
* **Never inserts, deletes, or merges a row.** Renaming will create rows that look like
  duplicates. That is expected and correct — it is the dedupe's problem, not yours.
* An `mlbam_id` absent from the published map is `unknown`, **not** a defect. Leave it.

Commit it on its own, before running anything against a database:

```
feat(identity): repair MLB player names from the published mlbam_id map
```

**No other code changes anywhere in this task.**

---

## Step 1 — back up prod

```bash
cd /root/legendarypicks/backend
cp data/picks.db "data/picks.db.pre-identity-repair-$(date -u +%Y%m%dT%H%M%SZ).bak"
venv/bin/python -c "import sqlite3;print(sqlite3.connect('data/picks.db').execute('pragma quick_check').fetchone())"
```

Do not continue unless `quick_check` prints `ok`. Record the filename; you will report it.

## Step 2 — the before measurement

```bash
cd /root/legendarypicks/backend
venv/bin/python audit_league_stats.py --league mlb --db /root/legendarypicks/backend/data/picks.db 2>&1 | tail -20
```

Record the `G/published-identity` line **verbatim**. Expect `FAIL` at **223**.

## Step 3 — dry run

```bash
cd /root/legendarypicks/backend
venv/bin/python repair_mlb_identity_names.py --db /root/legendarypicks/backend/data/picks.db
```

Expect **223 rows repaired**. If the number differs materially, **stop and report** — do
not apply. A count that drifts means the selection rule is not the one that produced 223.

## Step 4 — apply to prod

```bash
cd /root/legendarypicks/backend
venv/bin/python repair_mlb_identity_names.py --db /root/legendarypicks/backend/data/picks.db --apply
```

## Step 5 — the gate must go green

```bash
cd /root/legendarypicks/backend
venv/bin/python audit_league_stats.py --league mlb --db /root/legendarypicks/backend/data/picks.db 2>&1 | tail -20
```

`G/published-identity` must read **PASS**, 0 mismatches. Anything else: **stop and
report.** Step 1's backup is the restore path.

Then confirm nothing else moved:

```bash
cd /root/legendarypicks/backend
venv/bin/python -c "
import sqlite3
c=sqlite3.connect('file:data/picks.db?mode=ro',uri=True)
print('mlb players       :', c.execute(\"select count(*) from players where league='mlb'\").fetchone()[0])
print('distinct mlbam_id :', c.execute(\"select count(distinct mlbam_id) from players where league='mlb' and mlbam_id is not null and mlbam_id!=0\").fetchone()[0])
for t in ('player_game_logs','props','player_stats','predictions'):
    print(f'{t:20s}', c.execute(f'select count(*) from \"{t}\"').fetchone()[0])
"
```

`mlb players` and every table count must be **identical** to Step 2's database. A rename
changes no row count. If one moved, the script did something it was told not to.

## Step 6 — same thing on dev

Repeat Steps 1–5 against `/root/legendarypicks/backend/data/picks.dev.db`.
Expect **167**, not 223. Back it up first, same as prod.

## Step 7 — re-measure the dedupe blocker, do not act on it

The dedupe was blocked because 124 of 317 duplicate `mlbam_id` groups were **two different
people**. Renaming should collapse that. Measure it on prod and report the number:

```bash
cd /root/legendarypicks/backend
venv/bin/python -c "
import sqlite3, json, sys
sys.path.insert(0,'.')
from audit_league_stats import _identity_name_key as k
c=sqlite3.connect('file:data/picks.db?mode=ro',uri=True)
g={}
for i,n,m in c.execute(\"select id,name,mlbam_id from players where league='mlb' and mlbam_id is not null and mlbam_id!=0\"):
    g.setdefault(m,[]).append((i,n))
dup={m:v for m,v in g.items() if len(v)>1}
split=[m for m,v in dup.items() if len({k(n) for _,n in v})>1]
print('duplicate mlbam groups        :', len(dup))
print('  groups that are 2+ DIFFERENT people:', len(split))
for m in split[:10]: print('   ', m, dup[m])
"
```

**Report the number. Do not run `dedupe_mlb.py`.** Whether the dedupe is safe is a
decision for the next task, not this one.

---

## Out of scope

* Any code change other than Step 0's new file.
* **`dedupe_mlb.py` — do not run it, in any mode, including dry run.**
* Any write to `mlbam_id`, or to any other league.
* Docker: no build, no `up`, no restart. Prod is serving live.
* Host config: `/etc`, systemd units, timers, cron.
* `git push`. Commit Step 0 locally; do not push.
* Deleting either backup.

---

## Report back, between the literal markers `===RESULT===` and `===END===`

1. Both backup filenames (prod, dev).
2. The `G/published-identity` line **verbatim**, before and after, for prod and for dev.
3. Rows repaired on each, and the first 10 repairs from the prod dry run.
4. Step 5's table counts, before vs after, side by side.
5. Step 7's two numbers.
6. `git -C /root/legendarypicks status --short` and `git log --oneline -2`.

If any step failed, report the failure and what you did **not** do because of it. A
partial run reported honestly is worth more than a clean-sounding summary. Then stop and
wait.
