# TASK (next release, AFTER v0.8.0): make player identity portable

Repo **/root/legendarypicks**, branch `dev`. Written 2026-08-17. Measurements below were taken that
day — **re-measure before acting on any of them.**

**Do not start this before v0.8.0 is cut and deployed.** The ordering is not a preference; see §1.

---

## 1. Why this waits for the release

The core change is `UNIQUE(league, espn_id)` on `players`. A UNIQUE index is an assertion the
**writer** has to satisfy, and prod's writer is baked into a container image — only `backend/data` is
bind-mounted. Apply it before the release and the index goes live instantly while the code that
handles the constraint never arrives.

That exact mistake was made on 2026-08-17 with `ux_prop_games_event`: the index went live, the
`_link_or_fold` code that handles the IntegrityError it creates did not, and the stale container's
`except Exception: pass` left a duplicate row permanently **unlinked** — its props stranded, and
indistinguishable from a fixture the publisher had not posted yet.

So the order is: **release, then constrain.** Not the other way around.

## 2. The problem, stated as infrastructure

**Prod and dev are not a replica pair. They are two databases forked from a common ancestor, both
written to independently by live ingests ever since.** Each has its own `AUTOINCREMENT` sequence, so
from the point they diverged, both handed the same integers to different people.

```
dev   max(id)=59638  count=54541
prod  max(id)=59363  count=44938
```

Measured 2026-08-17:

| measurement | value |
|---|---|
| ids present in both databases | 44,450 |
| …naming a **different league** on each side (cannot be one person) | **1,379** |
| …carrying an `espn_id` on both sides that **disagrees** | 3,323 |
| top league pairs (dev → prod) | ncaaf→mls 722, mls→atp 133, mls→wta 131, mls→nhl 75 |
| tables joining on `players.id` | 14, >300k rows |

A concrete one: **`id=29174` is Paul George (nba) on dev and Max Kepler (mlb) on prod.**

This is the root cause behind the repeated promotion backfills. It is not a bug in any one merge
script — those scripts are downstream of a system that has no portable name for a player.

## 3. What makes it fixable

**The natural key already exists and is already unique.** No conflict resolution needed:

| measurement | DEV | PROD |
|---|---|---|
| players carrying at least one publisher id | 99.6% | 99.9% |
| `(league, espn_id)` groups with more than one row | **0** | **0** |
| UNIQUE indexes on `players` | only the automatic one on `id` | same |
| rows in `player_source_ids` (the crosswalk built for this) | **10** | absent |

So the failure is not that identity is hard here. We have a working identity, use a surrogate
instead, and then move rows between files where the surrogate means something different.

## 4. Scope, in order

### 4.1 Declare the natural key

`UNIQUE(league, espn_id)` on `players`, and the same for the other publisher-id columns where the
data supports it (`mlbam_id`, `nfl_gsis_id`, `nhl_id`, `nba_id` — **measure each before declaring
it**, do not assume they are as clean as `espn_id`). Register it through
`backend/migration_manifest.py`, which migrates both databases in one invocation and makes the app
refuse an un-migrated one.

Verify BEFORE applying, on both DBs, that the constraint holds against current data. A migration
that has to delete rows to satisfy its own constraint is not a migration, it is a data decision
wearing one.

### 4.2 Populate `player_source_ids`

Schema already exists on dev: `UNIQUE(source, league, source_player_key) -> player_id`. It holds 10
rows. Every non-ESPN source — Bovada, RotoWire, Underdog — currently resolves **by name on every
run**, which is the ambiguous-key class that has already cost this repo a full identity repair, and
which produced the surname-first misses (Xinyu Wang ↔ Wang Xinyu) still open in the backlog.

Backfill it from the resolutions we already make, then make the resolvers read it first and fall
back to name matching only for genuinely new athletes — recording the result when they do.

### 4.3 Convert promotion from row-copy to re-running the ingest

**The pattern that works already ran.** On 2026-08-17 the tennis spine reached prod via
`LP_DB_PATH=…/picks.db ingest_tennis_players.py`: identity came from ESPN, so there was nothing to
reconcile. 2 requests, 300 rows, zero id remapping, four minutes, no deploy. The same rows copied
out of dev would have needed exactly the reconciliation that produced collisions.

Audit the promotion scripts and classify each: **can this be re-run against prod instead of
copying?** Where it can, that IS the promotion. Where it genuinely cannot, it must match on the
publisher id and never on `players.id`.

### 4.4 Reconcile the ids that have already diverged

Last, because it is the expensive one and the three steps above shrink it. Use the mapping artifacts
recorded under the guardrail below. Any row whose identity cannot be established from a publisher id
is a **finding to report, not a row to guess at** — see the standing rule that a trust list may never
be keyed on a name alone.

## 5. Guardrail for anything that lands before this task starts

A merge that allocates fresh target ids widens the fork one-way — precisely what §4.4 has to undo.
That should not block the release, but any such merge **must record the mapping it used**: source id,
target id, and the publisher id that justified each, in a committed artifact. Un-recorded, the next
pass has to re-derive it from names, which is the class that created this problem.

## 6. Definition of done

- `(league, espn_id)` is declared UNIQUE on both databases and the app refuses an un-migrated one.
- `player_source_ids` is populated for every source that currently resolves by name, and the
  resolvers read it before falling back.
- Every promotion script is classified re-runnable or copy-only, and no copy-only path joins on
  `players.id`.
- A written answer to: **after this, what still keys on a database-local surrogate?** If the answer
  is "nothing else", say how that was verified across all 14 tables.

## 7. Reading first

- `docs/BACKLOG-holes.md` rows **54–56** — the measurements above, with the sequencing decision.
- `docs/ROADMAP.md`, the 2026-08-17 CURRENT block — deployment target and why code cannot reach prod
  without a release.
- Skills: **`published-first`** (before any backfill or derived value) and **`fail-loudly`** (before
  any join that feeds a page). Both are directly on point — a wrong join key here does not raise, it
  misses, and a missed identity renders as a plausible empty page.
