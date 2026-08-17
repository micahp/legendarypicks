# TASK — close the one-way crosswalk: ESPN-only MLB rows never get an `mlbam_id`

**Owner:** delegated (reasonix / deepseek-v4-flash)
**Status:** not started
**Written:** 2026-08-05

---

## Do NOT use a worktree

`scripts/hermes-worktree.sh` symlinks **only** `picks.dev.db`, never `picks.db`. Pointing
`--db` at `data/picks.db` from a worktree makes sqlite **create a new empty database** and
every check then passes against nothing. Work in `/root/legendarypicks`, absolute DB paths.
**Dev first, prod only when dev is clean.**

---

## Where this stands

Your position-vocabulary work is correct and is committed (`d68d3d2`, `da63c5a`, `405a41e`).
Stopping before prod was the right call. The three columns behave exactly as designed on dev:
`pitcher_role` = SP 152 / RP 240, the `OF` → NULL rule fired on 2 rows, and `P` replaced
`SP`/`RP` everywhere MLB could reach.

The blocker you identified is real, and it is this task. **Prod was never migrated — leave
it that way until step 5.**

## The defect

The MLB ↔ ESPN crosswalk only runs in one direction. On prod:

```
mlb rows total   2454
  both ids        762     <- roster_sync attached espn_id to a known MLB row
  mlbam only     1668
  espn only        21     <- roster_sync's MISSES. dev has 122 of these.
  neither           3
```

`roster_sync.py` matches an ESPN roster entry to an existing row by name and fills
`espn_id`. On a **miss** it inserts a new row:

```python
"INSERT INTO players(name, league, team, position, espn_id, active) VALUES (?,?,?,?,?,1)"
```

— no `mlbam_id`. `grep mlbam roster_sync.py` returns **nothing**: the module has no concept
of MLB's id, because at insert time it holds only ESPN's data and never asks the other
publisher. Then `ingest_mlb_spine_identity.py` reads `WHERE mlbam_id IS NOT NULL` and skips
those rows permanently — so they never get `position`, never get `position_group`, and keep
their stale ESPN `SP`/`RP` in `position` (27 of dev's 29 stale rows are exactly these).

**The data is published. We simply never asked.** Measured against MLB's 2026 publication:

```
DEV  122 rows without mlbam_id: 121 match EXACTLY ONE published mlbam_id, 0 ambiguous, 1 unpublished
PROD  21 rows without mlbam_id:  20 match EXACTLY ONE published mlbam_id, 0 ambiguous, 1 unpublished
```

Tommy Edman → 669242. Cole Irvin → 608344. Ordinary players, never crosswalked.

---

## What to change

**`backend/ingest_mlb_spine_identity.py` only.** One commit.

Add a resolution pass so the script also covers rows that *lack* `mlbam_id`, instead of only
filling team/position for rows that already have one. It already runs after `roster_sync` in
the normal order, so closing it here closes the hole on **every future run** — a one-off
backfill script would leave the next `roster_sync` free to make more, which is not a fix.

The rule, and do not loosen any clause of it:

* Consider only `league='mlb'` rows where `mlbam_id IS NULL OR mlbam_id = 0`.
* Match on the **normalised name** — import `_identity_name_key` from `audit_league_stats`,
  do not write a third normaliser — against MLB's published season roster.
* **The name must match exactly one published player.** Two or more candidates is
  `ambiguous`: skip it, count it, report it. Never take the first.
* **The team must agree.** MLB publishes `currentTeam` on the same endpoint the script
  already reads. A unique name whose team disagrees is a skip, not a match — a traded or
  stale row is exactly where a confident wrong answer would come from.
* **Never overwrite a non-null `mlbam_id`.** Not as a fallback, not "if it looks wrong".
* A player MLB does not publish for the season stays `unknown`. That is the honest answer
  and it is not a failure — report the count, do not widen anything to absorb it.
* Then let the existing team/position/`position_group` fill run over the newly-resolved
  rows in the same pass, so they end up complete.

Print, in both dry-run and apply modes: rows considered, resolved, ambiguous, team-mismatch,
unpublished. Default to a **dry run**; `--apply` writes.

Commit:

```
fix(mlb): resolve ESPN-only rows against MLB's published roster, both directions
```

### Why this is allowed to match on a name, when tonight's disaster was a name match

Read this before you write it. Tonight's corruption wrote a name from an *unrelated column*
(Statcast's `player_name` is the pitcher's) onto a row, with nothing able to detect it. This
is the opposite case: a player's **own** name, against that player's **own** publisher, with
**zero** ambiguous candidates in today's data, a second key (team) required to agree, and a
gate that re-checks the result. `G/published-identity` asserts that every `mlbam_id` carries
the name its publisher gives it — so a wrong id lands red on the very next run.

If you find yourself wanting to relax the unique-match or team-agreement clause to raise the
resolved count, **stop and report instead.** The count is not the goal; the join being
correct is.

---

## Run it

1. Back up dev. Dry run. Report the five counts.
2. `--apply` on dev, then run `roster_sync.py mlb` against dev so the whole chain is exercised
   in its real order.
3. `venv/bin/python -m pytest -q` — the whole backend suite.
4. `audit_league_stats.py --league mlb --db .../picks.dev.db`, all four must hold:
   * `C/vocabulary[position]` **PASS**
   * `C/vocabulary[position_group]` **PASS**
   * `C/vocabulary[team]` **PASS**
   * `G/published-identity` **PASS** — it was green before you started; if the backfill put a
     wrong id anywhere, this is what says so. **A red G here means revert, not investigate-
     and-continue.**
5. **Only if all four hold on dev:** run `backend/migrate_mlb_position_vocabulary.py` against
   **prod** (prod still has neither new column), then repeat 1–4 against prod. Back up first,
   `quick_check` = ok.
6. Row counts unmoved on both DBs: `players`, `player_game_logs`, `props`, `player_stats`,
   `roster_memberships`, `roster_snap`. Resolving an id changes no row count.

If any step fails, **stop and report.** Do not weaken a check to make it pass.

---

## Out of scope

* `roster_sync.py` — do not touch it. Its insert-on-miss behaviour is the upstream cause, but
  it is shared by four leagues and changing it is a separate, riskier task.
* `A/required-stats`, `E/qualifier`, `B/position-content` for MLB — blocked on the counting-
  stats columns (`backend/migrate_mlb_counting_stats.py` already exists). Separate task.
* NFL, NBA, NHL. `dedupe_mlb.py`. `repair_mlb_identity_names.py`. The audit's check logic.
* The 168 pre-existing orphans (`props` 78, `roster_snap` 90).
* Docker: no build, no `up`, no restart. Prod is serving live.
* Host config: `/etc`, systemd, timers, cron. **The props timers write to prod every 30 min**
  — if a run collides with one, say so rather than retrying blindly.
* `git push`. Commit locally.

---

## Report back between `===RESULT===` and `===END===`

1. Backup filenames (dev, prod).
2. The five counts from the dry run, dev and prod.
3. The four gate lines, **verbatim**, dev and prod.
4. `position`, `position_group` and `pitcher_role` histograms, dev and prod.
5. Full `pytest` result line.
6. Row counts before vs after.
7. Every row you did **not** resolve, with the reason (ambiguous / team mismatch /
   unpublished). Name them — that list is the honest remainder and I want to see it.
8. `git -C /root/legendarypicks status --short` and `git log --oneline -3`.

Then stop and wait.
