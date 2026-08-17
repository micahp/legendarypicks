# TASK — find the code that wrote wrong `mlbam_id`s onto MLB player rows

**Owner:** delegated (reasonix / deepseek-v4-flash)
**Status:** not started
**Written:** 2026-08-04 evening
**Type:** READ-ONLY code archaeology. No DB writes, no code changes, no commits.

---

## The defect

`players.mlbam_id` is supposed to be MLB's own id for the person named on that row.
On **223 prod rows and 167 dev rows it is a different player's id**:

```
id=26551 row='Eiberson Castellano'  mlbam=703607  MLB publishes 'Henry Bolte'
id=26567 row='Brady Basso'          mlbam=671289  MLB publishes 'Tyler Freeman'
id=26571 row='Mason Miller'         mlbam=702616  MLB publishes 'Jackson Holliday'
id=26573 row='Yennier Cano'         mlbam=701538  MLB publishes 'Jackson Merrill'
id=26580 row='Adrian Morejon'       mlbam=694212  MLB publishes 'Samuel Basallo'
```

This is not cosmetic. A wrong id does not raise — it mis-joins, and it turns every
id-keyed repair into a corruption. `dedupe_mlb.py` documents a shared `mlbam_id` as
"provably the same person"; 124 of 317 duplicate groups are in fact two different
people.

**Your job is to find what wrote them. Not to fix anything.**

---

## What is already established — do not re-derive this

Verified tonight. Trust it and build on it.

1. **Both databases have it, with the same `players.id` values.** So it predates the
   dev/prod split. A prod-only migration cannot be the cause.
2. **It is present in the oldest backup on disk**, `data/picks.db.bak-20260615-182333`
   (2026-06-15). Every later backup has it too. The backup chain cannot localise it,
   which is why this is a code question rather than a data one.
3. **Concentrated in `players.id` 26000–26999** — 446 rows, and that block has been a
   constant 445–446 rows in every backup since 2026-06-24. It reads like one bulk
   insert that was never revisited. 177 of the wrong rows are in 1000–26999, 46 above
   27000, 1 below 1000.
4. **It is NOT a positional shift inside that block.** For every wrong row, the true
   owner of its `mlbam_id` is not among the 26xxx rows at all. So it is not a simple
   `zip()` of two mis-ordered lists drawn from the same batch.
5. There is now a gate for the state: `audit_league_stats.py` check
   `G/published-identity`, red at 223 (prod) / 167 (dev), with the published map
   committed at `backend/data/published-identity-names.json`.

---

## What to actually do

Code archaeology, in roughly this order. **Read only.**

### 1. Find every writer of `mlbam_id`, including deleted ones

Current tree, then history — the culprit may not exist any more:

```bash
cd /root/legendarypicks
grep -rn "mlbam" --include=*.py backend/ | grep -iE "insert|update|set |=" 
git log --oneline --diff-filter=D --name-only -- 'backend/*.py' | head -60
git log --oneline --before=2026-06-16 -- 'backend/*mlb*.py' 'backend/*statcast*.py'
```

Known writers to start from: `ingest_statcast.py`, `ingest_mlb_logs.py`,
`ingest_mlb_pitcher_logs.py`, `ingest_mlb_counting_stats.py`,
`run_mlb_daily_history_ingest.py`, `merge_mlb_rrbi_from_dev.py`,
`migrate_logs_to_prod.py`, `settlement.py`, `_core.py`.

### 2. Look for the specific bug class

The evidence says ids came from a source **unrelated to the names they landed on**.
Look for:

* a name→id lookup whose miss falls back to an index, a counter, or `next()`
  instead of failing
* two lists combined by `zip()`, `enumerate()`, or shared ordering where one was
  sorted or filtered and the other was not
* an id taken from a loop variable that outlives its iteration
* an `INSERT ... VALUES` whose column order does not match its tuple
* a lookup keyed on a normalised name that collides (two players, one key) and
  silently takes the last writer

### 3. Test the hypothesis against the data

A hypothesis is not an answer. Whatever you suspect, show it *produces these specific
pairings*. Reconstruct from the git version of the file as it stood before
2026-06-15 (`git show <sha>:backend/<file>`), run it against a **copy** of a backup if
you need to — never against `picks.db` or `picks.dev.db`.

Useful anchors: `id=26571 'Mason Miller'` should have carried Mason Miller's real
MLBAM id; it carries `702616`, which is Jackson Holliday's. Explain how those two
became adjacent in whatever the script was iterating.

### 4. If you cannot prove it, say so

"Unknown, here is what I ruled out and how" is a valid and useful answer. A named
suspect without evidence is worse than none — it gets treated as fact later. Do not
guess.

---

## Out of scope

* **Any write to any database.** Read-only connections (`?mode=ro`) or copies only.
* **Any code change, any commit, any push.** This task produces no diff.
* Fixing the corruption. That is `plan_mlb_identity_rebuild.py`'s job and it is not
  yours tonight.
* Docker, host config (`/etc`, systemd, timers, cron), other leagues.

---

## Report back between `===RESULT===` and `===END===`

1. **The verdict**: named file + commit, or "unknown".
2. **The evidence** that makes it more than a hypothesis — the code path, and how it
   yields these exact pairings.
3. **What you ruled out**, so nobody retreads it.
4. Whether the mechanism can still run today (is that code still reachable?).
5. `git -C /root/legendarypicks status --short` — expected unchanged.

Then stop and wait.
