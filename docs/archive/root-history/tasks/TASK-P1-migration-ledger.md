# TASK P1 — a migration ledger, so "it works on dev" stops meaning "it is not in prod"

**Phase:** P1 · **Effort:** 1–2 weeks · **Do after P0, before any table split.**
**Why:** on 2026-08-05, **seven** separate defects were correct in code and absent from
production, each found by hand, one at a time, over a single night:

| what | dev | prod |
|---|---|---|
| NFL `rush_td`/`rec_td` | populated | **0 rows through three releases**, while the changelog announced the feature |
| NBA season stats 2026 | 576 rows | served 2023 |
| MLB counting stats | 23 columns | column absent → gates read `no such column: pa, era` |
| NHL goalie columns | 11 columns | absent |
| NHL season keys | migrated 2026-08-02 | **48,017 rows** still on the publisher's raw key, so a season-scoped join returned **0** for that league |
| NHL game logs | 1,312 games | 1,230 — 82 missing, reconciled against ESPN |
| NHL goalie boxscore stats | 2,877 rows with `saves` | 0 |

Seven instances of one failure is not seven mistakes. Both databases answered `200`
throughout and the gates were green — **against dev**.

---

## The mechanism, precisely

There are **20** `migrate_*.py` scripts in `backend/`, each hand-run against whichever
database the operator had open. Nothing records that a script ran **against a database** —
only the operator's memory does. `schema_migrations` exists on dev with **zero rows** and
**does not exist on prod at all**: built, never adopted.

That is mechanically identical to how "NBA season stats: dev 576, prod 2023" happens. A
script runs once, succeeds, and no durable fact anywhere ties that run to that file.

## What to build

1. **Make `schema_migrations` load-bearing.** Numbered migrations
   (`migrations/0047_add_nhl_goalie_columns.sql` or a numbered Python module), a runner
   that checks the ledger before applying and inserts a row after. Idempotent: re-running
   is a no-op that reports zero applied.
2. **One invocation, both databases.** The runner takes prod and dev together by default.
   The reason six of the seven happened is that "verify on dev" and "ship to prod" are two
   manual actions with nothing coupling them. Do not add a reminder; remove the second
   action.
3. **Refuse to serve an un-migrated database.** The app checks the ledger at startup and
   fails loudly rather than serving a schema it was not built for. `no such column: pa`
   should be impossible to reach in production.
4. **Data backfills need the same ledger.** They are not schema changes and are just as
   forgettable: `scripts/merge_nba_identities.py` is documented as *"ported, tested,
   verified on a prod copy — not applied to prod."* Without a run record, "ready but not
   applied" silently becomes "forgotten." The NBA `F/identity-crosswalk` failure — 269
   athletes split across two rows, stats on one and logs on the other — is that script,
   still unapplied.
5. **Adopt the existing 20 retroactively.** For each `migrate_*.py`, determine whether it
   has been applied to each database and write the ledger row. Where it cannot be
   determined, say so in the row rather than guessing — an unknown recorded is worth more
   than an assumption.

## Backup retention — do this with it

`backend/data/` is **15GB across 95 `.bak` files**, several 200MB+ apiece, no policy. This
already cost once: a bare `*.bak` pattern in `.dockerignore` does not cross a `/`, so 7.7GB
of backups were baked into the production image (`c6b2728`).

* A retention rule (keep N most recent per prefix, or age out).
* **`VACUUM INTO`, never `cp`.** Proved 2026-08-05: a `cp` of the live database produced a
  snapshot that reported `database disk image is malformed` while the source passed a full
  `integrity_check`. Every `.bak` taken by hand that night has the same defect and none of
  them are trustworthy.

---

## Frontend

**None.** This phase changes no schema, no API contract and no served value. If a frontend
change appears necessary, something has been mis-scoped — stop and re-read.

## Done means

* `schema_migrations` exists and is populated **on both databases**
* every one of the 20 existing migrations has a ledger row, or an explicit "unknown"
* the runner applied to a deliberately-stale copy brings it level and reports what it did
* the app refuses to start against a database missing a migration (prove it)
* `diff_databases.py` reports no SCHEMA differences
* backups under a stated policy, and the retention rule documented where the next person
  will find it
