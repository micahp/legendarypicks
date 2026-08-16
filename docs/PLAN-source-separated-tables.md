# Plan — separate tables by publisher, and stop `players` being a dumping ground

**Status:** proposed, 2026-08-05. Not started.
**Constraint that shapes everything below:** the product's one validated use case is
NFL fantasy draft research and drafts happen in the next 3–5 weeks. Nothing here may
block that window. An independent architecture audit is running against this proposal;
where it disagrees, it wins and this document gets corrected.

---

## 1. The problem, stated once

Shared tables are written by four or more publishers per league, and **nothing in the
schema records which publisher said what.** Every defect found on 2026-08-04/05 is a
consequence:

* `players.position` held ESPN's `SP`/`RP` on active MLB rows and MLB's `P` on the rest.
  `WHERE position='P'` returned only retired players. Neither query could return both.
* NFL's `position` today holds real positions in **two spellings** (`K`/`PK`, `S`/`SAF`),
  a parent beside its child (`FB` under `RB`), and **96 rows that are not people**
  (32 D/ST, 32 TQB, 32 head coaches).
* `roster_sync` deactivated 32 D/ST rows; `ingest_nfl_adp.py` reads
  `position='DEF' AND active=1`; its fail-closed preflight then aborted every run, and
  `injury_status` stopped updating for **6,486 NFL players**. Production's draft board
  showed nobody as injured. No error anywhere.

The last one is the shape that matters: **two features that should never have met,
fighting over one column, in silence.**

### The distinction that was collapsed and must not be again

| | what it is | fix |
|---|---|---|
| MLB `SP` vs `P` | two publishers describing **the same fact** in different words | one vocabulary per column; parent level gets its own column |
| NBA `G` vs `PG` | same — a parent level and a child level of one vocabulary | same |
| NFL `DEF`/`TQB`/`HC` | **a different kind of entity** wearing a position label | not a vocabulary problem at all — separate the entity |

A team defence is not a person playing a position. Treating it as vocabulary pollution
is what produced a fix that would have left `TQB` and `HC` as the next two bugs.

**ESPN never confuses the two, and we already store its marker.** Fantasy constructs
exist only in `lm-api-reads.fantasy.espn.com`, never in `sports.core.api.espn.com`, and
ESPN signs their ids **negative**. Measured on prod 2026-08-05: 97 negative ids, and
they are exactly the 96 constructs plus one unresolved row named `?`. Zero false
positives against 11,000+ real athletes.

---

## 2. Target shape

Three layers, each with one job:

**`players` — the spine.** Canonical id, name, league, and the publisher crosswalk
(`espn_id`, `mlbam_id`, `nfl_gsis_id`, `nhl_id`, `nba_id`). Humans only. Nothing writes
a descriptive attribute here that a publisher owns.

**`espn_core_*` — what `sports.core.api.espn.com` publishes.** Real athletes, real
positions, positive ids. What `roster_sync` and the stats ingests read and write.

**`espn_fantasy_*` — what the fantasy API publishes.** ADP, ownership, PPR ranks,
eligible slots, and the constructs that exist nowhere else: D/ST, TQB, HC. Negative ids
live here and only here.

Under that shape, today's outage is **structurally impossible**: `roster_sync` cannot
deactivate a D/ST because a D/ST is not in the table it reads.

For leagues with no fantasy layer (MLB, NBA, NHL) the same principle applies one level
down — store the publisher's vocabulary as published, and add a parent-level column only
where the publisher genuinely publishes one (`position_group` already exists for MLB from
`primaryPosition.type`).

---

## 3. What already exists and should be reused

Do not rebuild these:

* **`entity_type` on `players`** (shipped 2026-08-05, `840d2e7`). Records
  `player` / `team_defense` / `team_qb` / `coach` / `unknown`, backfilled from the
  negative-id marker on both databases. **This is the cheap version of the split** — it
  records the same distinction without moving a row, and `entity_type='team_defense'` is
  exactly the predicate that selects rows into `espn_fantasy_*` later. It is forward
  compatible; nothing below invalidates it.
* **Boundary modules** — `season_keys.py`, `team_codes.py`, `provenance.py`. The pattern
  is correct and proven: normalise where the foreign value is read, never in a query.
  New source tables get the same treatment.
* **The gate system** — `audit_league_stats.py`, MANIFEST-driven, checks A–G, universal
  across leagues. It is the only reason any of this was found.
* **`diff_databases.py`** — prod vs dev on schema, seasons and row counts.

---

## 4. Sequencing

Ordered by value per unit of risk, not by architectural tidiness. **Phase 1 and 2 are
independent of the refactor and should happen regardless of what the audit concludes.**

### Phase 1 — protect the draft window (days, do first)
Nothing structural. The draft board is the product for the next five weeks.
1. Add a gate that asserts `injury_status` / `last_news_date` are non-empty for the NFL
   pool. Today's outage was invisible because nothing measured it — the API returned the
   keys, always null.
2. Add `entity_type` to `diff_databases.py`'s schema comparison so the two databases
   cannot silently diverge on it.
3. Fix `K`/`PK` and `S`/`SAF` — one spelling per position. This is a real drafting bug:
   a board filtering `position='K'` misses every kicker written as `PK`.

### Phase 2 — migration discipline (days, do second)
Seven dev-only fixes reached production only because someone found them by hand. That is
a systems problem and it will recur.
1. **Use `schema_migrations`.** It exists on dev with **zero rows** — built and never
   adopted. Every `migrate_*.py` records its version there on apply.
2. A single runner that applies pending migrations to a named database and refuses to
   start the app against an un-migrated one. SQLite with no ORM makes this cheap.
3. `diff_databases.py` runs in the release preflight (already wired, advisory).

### Phase 3 — the split (weeks, after the draft window)
1. `espn_fantasy_entities` — move the 96 constructs out of `players`. Highest value and
   lowest blast radius, because `entity_type` already identifies them exactly.
2. `espn_fantasy_adp` — `nfl_adp` is already source-scoped in all but name.
3. `espn_core_athletes` — the big one. Every read path touches it. Do it last, behind a
   view named `players` if that is what it takes to avoid a flag-day rewrite.

### Non-goals
Not in scope: rewriting the gate system, an ORM, Postgres, changing the frontend
contract, or touching leagues with no fantasy layer beyond the `position_group` work
already done for MLB.

---

## 5. Risks

* **The refactor competes with draft season.** This is the main risk and the reason
  Phase 3 sits behind Phase 1. A half-finished table split during the only weeks that
  matter is worse than the current mess, which is at least understood and now measured.
* **A partial migration is worse than none.** Precedent: translating only
  `20252026 -> 2026` would have left `20242025` as `MAX(season)` — a two-year-old season
  served as current, from a migration that reported success. Migrate a league entire or
  not at all.
* **Read paths are undercounted.** `players` is referenced across routers, ingests and
  scripts. Enumerate every reader before moving a column, not during.
* **Prod and dev diverge while this runs.** Every phase applies to both databases in the
  same session, verified with `diff_databases.py`, or it is not done.

---

## 6. Open questions for the audit

1. Is source-separated tables the right shape, or is a `source` column on the existing
   tables sufficient? The latter is far cheaper and might get 80% of the benefit.
2. Should `players` keep descriptive columns at all, or become a pure crosswalk?
3. Is SQLite still the right store at this size (250MB prod, 40 tables), or is the
   single-writer lock — which killed a backfill mid-run today — the real constraint?
