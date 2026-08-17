# TASK — `players.position` holds two publishers' vocabularies at once

**Owner:** delegated (reasonix / deepseek-v4-flash)
**Status:** not started
**Written:** 2026-08-05

---

## Do NOT use a worktree

`scripts/hermes-worktree.sh` symlinks **only** `picks.dev.db`, never `picks.db`. Pointing
`--db` at `data/picks.db` from a worktree makes sqlite **create a new empty database** and
every check then passes against nothing. Work in `/root/legendarypicks`, absolute DB paths.

**Do dev first, prod second.** This one has a schema migration; unlike the last two tasks
there is a cheap place to be wrong.

---

## The defect

`players.position` for MLB is filled by **two ingests writing two different vocabularies**,
split by the `active` flag. Measured on prod tonight:

```
active=1 (783 rows)   SP 152  RP 240  C 64  1B 37  2B 48  3B 41  SS 45  LF 41  CF 43  RF 44  DH 27  OF 1
active=0 (563 rows)   P 338   C 40    1B 17  2B 15  3B 27  SS 18  LF 34  CF 24  RF 36  DH 13  OF 1
```

* `roster_sync.py` writes the active rows from **ESPN**, which splits pitchers `SP`/`RP`.
* `ingest_mlb_spine_identity.py:140` writes the rest from **MLB**, which has no `SP`/`RP` at
  all — 740 pitchers, every one of them `P`.

So `WHERE position='P'` returns 338 players and **every one is retired**;
`WHERE position IN ('SP','RP')` returns 392 and **every one is current**. Neither query can
return both, and nothing raises. This is the same failure class as the identity defect: a
query that is silently, confidently wrong.

`audit_league_stats.py` check `C/vocabulary[position]` is red on it today.

## Two levels in one column, as well

MLB publishes the position **and its group** as separate fields, and the group is total:

```
abbreviation -> type
  LF, CF, RF, OF -> Outfielder (226)     1B, 2B, 3B, SS -> Infielder (248)
  P -> Pitcher (740)   C -> Catcher (104)   DH -> Hitter (39)   TWP -> Two-Way Player (1)
```

We kept `abbreviation` and dropped `type`, so `WHERE position='OF'` returns **1** of 129
outfielders (Cristian Pache, `mlbam_id=665506`). Both publishers agree he has no designated
spot — ESPN's roster says `OF` and MLB says
`{code:'O', name:'Outfield', type:'Outfielder', abbreviation:'OF'}`.

**Do not remap Pache to LF/CF/RF.** Neither publisher knows his spot; assigning one invents
a fact. See the rule at the end of §5 in `docs/DATA-SPINE.md`.

---

## The design (decided — implement this, do not redesign it)

Three columns, each holding **exactly one level from exactly one publisher**:

| column | publisher | scope | vocabulary |
|---|---|---|---|
| `position` | MLB (`primaryPosition.abbreviation`) | every row with an `mlbam_id` | `P C 1B 2B 3B SS LF CF RF DH TWP` — **specific spots only** |
| `position_group` | MLB (`primaryPosition.type`) | every row with an `mlbam_id` | `Pitcher Catcher Infielder Outfielder Hitter Two-Way Player` |
| `pitcher_role` | ESPN (roster `position`) | active MLB only, nullable | `SP RP` and nothing else |

Rationale, so you can resolve anything this spec doesn't cover: MLB reaches **2,430** rows
(vs ESPN's **783**, active-only), is stable where ESPN's is a role that changes mid-season,
and hands us the group level for free. ESPN's starter/reliever split is genuinely useful and
genuinely *different information*, so it gets its own column rather than losing to or
overwriting MLB's.

### The part most likely to be got wrong

**`OF` is a group-level value and must not sit in `position`.** When MLB's `abbreviation`
equals a group-level value (`OF`, and only `OF` in today's data), write `position = NULL`
and let `position_group = 'Outfielder'` carry it. A NULL there is the honest statement
*"MLB does not designate a spot for this player"* — which is true. This is what actually
makes `C/vocabulary[position]` green: one level per column, no parent sharing a column with
its own children.

Never write `SP` or `RP` into `position`. Never write `OF` into `position`.

---

## What to change

1. **`backend/migrate_mlb_position_vocabulary.py`** (new). Follow the house pattern — see
   `migrate_nfl_team_vocabulary.py` and `migrate_nhl_goalie_columns.py`, both use
   `migrate_schema`. Adds `position_group` and `pitcher_role` to `players`, idempotent,
   `--db` argument, backup-first. Nothing else.

2. **`backend/ingest_mlb_spine_identity.py`** — write `position_group` from
   `primaryPosition.type` alongside `position`, and apply the `OF` → NULL rule above. It
   already covers every row with an `mlbam_id`, which is what we want; do not narrow it to
   active players.

3. **`backend/roster_sync.py`** — **MLB only**: stop writing `position`, and write ESPN's
   value to `pitcher_role` instead, only when it is `SP` or `RP` (discard ESPN's hitter
   positions — MLB publishes those better, with the group).
   **NFL, NBA and NHL must be completely unchanged**; ESPN is the only publisher of position
   for those leagues and breaking them is a much worse outcome than this bug. Make the
   branch explicit and narrow, and say in a comment why MLB is the exception.

4. **`backend/audit_league_stats.py`** — add `position_group` to MLB's `single_vocabulary`
   list so the new column is asserted too, not just trusted. **Do not touch
   `position_content`** (see out-of-scope).

5. **Tests** in `backend/test_roster_sync.py` and wherever the spine ingest is tested:
   * an MLB roster entry with ESPN position `SP` sets `pitcher_role='SP'` and leaves
     `position` untouched;
   * an **NFL** roster entry still sets `position` exactly as it does today (regression);
   * MLB `primaryPosition {abbreviation:'OF', type:'Outfielder'}` yields
     `position IS NULL` and `position_group='Outfielder'`;
   * MLB `{abbreviation:'CF', type:'Outfielder'}` yields `position='CF'`,
     `position_group='Outfielder'`.

Commits — **separate, one per slice**:

```
feat(schema): add position_group and pitcher_role to players
fix(mlb): record MLB's published position and its group, one level per column
fix(roster): stop overwriting MLB position with ESPN's role vocabulary
```

---

## Run it — dev first

1. Back up dev, migrate dev, run `ingest_mlb_spine_identity.py --season 2026 --db
   /root/legendarypicks/backend/data/picks.dev.db`, then `roster_sync.py mlb` against dev.
2. `venv/bin/python -m pytest -q` — the whole backend suite, not just your new tests.
3. `audit_league_stats.py --league mlb --db .../picks.dev.db`:
   * `C/vocabulary[position]` must read **PASS**
   * `C/vocabulary[position_group]` must read **PASS**
   * `G/published-identity` must still read **PASS** — it was green before you started
   * `C/vocabulary[team]` must still read **PASS**
4. Sanity-check the shape on dev and report it: the `position`, `position_group` and
   `pitcher_role` histograms, and confirm `P` and `SP`/`RP` no longer coexist in `position`.
5. **Only if all of the above holds**, repeat 1–4 against prod
   (`/root/legendarypicks/backend/data/picks.db`), backup first, `quick_check` = ok.
6. Confirm no row count moved on either DB: `players`, `player_game_logs`, `props`,
   `player_stats`, `roster_memberships`, `roster_snap`.

If any step fails, **stop and report**. Do not weaken a check to make it pass — a gate moved
to fit the data measures nothing.

---

## Out of scope

* `A/required-stats` and `E/qualifier` for MLB (red: no `pa`, `hits`, `runs`, `rbi`,
  `innings`, `era`, `whip` columns) and `B/position-content` (UNVERIFIED). Those need the
  counting-stats columns — note `backend/migrate_mlb_counting_stats.py` already exists — and
  are a **separate task**. Declaring `position_content` now would only add a red gate this
  task cannot turn green.
* NFL, NBA, NHL — any change to their position handling is a failure of this task.
* `sports_service._normalize_name`, `roster_membership.py`'s contract checks, the identity
  gate, `dedupe_mlb.py`.
* The 168 pre-existing orphans (`props` 78, `roster_snap` 90) — known, separate.
* Docker: no build, no `up`, no restart. Prod is serving live.
* Host config: `/etc`, systemd, timers, cron. **The props timers write to prod every 30
  min** — if a run collides with one, say so rather than retrying blindly.
* `git push`. Commit locally.

---

## Report back between `===RESULT===` and `===END===`

1. Backup filenames (dev, prod).
2. Full `pytest` result line.
3. The four gate lines from step 3, **verbatim**, for dev and for prod.
4. Step 4's three histograms, for dev and for prod.
5. Step 6's row counts, before vs after.
6. Anything MLB publishes that this design has no column for.
7. `git -C /root/legendarypicks status --short` and `git log --oneline -4`.

Then stop and wait.
