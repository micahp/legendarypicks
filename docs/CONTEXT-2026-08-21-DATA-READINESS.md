# Context Summary — Data Readiness — August 21, 2026

This is a candidate-branch handoff, not a release claim.  Nothing in this
document was applied to managed DEV, production, a timer, or either database.

## Candidate work completed

- `4ed32ab` retains the complete native Bovada coupon before the scraper
  flattens it into events.  Repeated identical bodies deduplicate by SHA-256
  while retaining the first/last observation timestamps and count.  The
  explicit `publisher_captures` migration remains a required rollout gate;
  normal parsing fails closed when it has not been applied.
- `a09fde4` generalizes the existing NFL publisher-week contract to NCAAF.
  It does not invent week boundaries: ESPN's 2026 catalog names the regular
  season `2:1` through `2:15`, and the new endpoints preserve that identity.

Focused checks:

```text
24 passed — Bovada capture / existing publisher-capture / schedule-target tests
7 passed  — NFL + NCAAF week-contract tests
```

Live read-only ESPN verification on 2026-08-21 found 25 games in NCAAF's full
2026 Week 1 (`season_type=2`, `week=1`), including the August 29 slate.  This
is source availability evidence only; candidate code is not deployed.

## MLS: exact readiness state

Managed DEV's current MLS tables, inspected read-only:

| Surface | Current evidence | Meaning |
|---|---|---|
| standings | 2026, in progress, two conference groups | live publisher standings work |
| regular-season logs | 4,516 rows, 675 players, 147 games; Feb. 21–Aug. 8 | trustworthy but stale source material |
| season leaders | 850 rows, all season 2025 | production-facing leaders lag the live standings season |
| DB integrity | `PRAGMA quick_check = ok` | no SQLite corruption finding |

On a disposable verified clone of that DEV database,
`ingest_mls_season_stats.py --season 2026 --apply` produced 675 2026 season
rows from those logs, with `quick_check = ok`.  This proves the publisher-log
aggregation and schema can publish leaders.  It does **not** prove current
leaders: the newest retained game log is Aug. 8.

Before any DEV or production write, the ordered gate is:

1. Take a verified backup of the explicit target database.
2. Refresh the bounded missing MLS summaries from ESPN, paced and with a
   measured request budget; do not re-fetch already-current games.
3. Re-run the season aggregate against that same clone and verify source-game
   freshness, resolved-player count, and `quick_check`.
4. Obtain explicit authorization for a serialized apply to the named target.
5. Verify `/api/mls/leaders` on the actual target reports 2026 and inspect the
   rendered leaders view.

## Scheduled props and World Cup

Both `legendarypicks-props.timer` and
`legendarypicks-props-prod.timer` are currently `disabled` and `inactive`.
Historical journal output from earlier on August 21 shows the old `all` target
could still skip/request World Cup as part of the broad invocation.  Do not
re-enable either timer until the candidate scheduled-target code is landed and
the explicit capture migration has been applied to each named database.

## Still unproven

- Full publisher-payload retention is only wired for Underdog and Bovada in
  this candidate.  ESPN and other ingest boundaries need the same
  before-normalization ledger treatment before claiming “all publisher data is
  retained.”
- Tennis/NFL/UFC settlement candidate work is not deployed or applied to DEV;
  its clone evidence must be remeasured against the target at apply time.
- No real daytime props run after the SQLite-lock remediation has yet been
  observed through its complete ingest/settlement window, so the lock issue is
  not closed.
