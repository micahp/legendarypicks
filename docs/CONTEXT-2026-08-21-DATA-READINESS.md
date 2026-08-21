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
- `4c12316` applies the same source-native capture rule to the MLS/EPL soccer
  ingest.  It retains each ESPN season, type, event-collection, and match
  summary document before reading its fields; an unmigrated target is rejected
  before the first publisher request.
- `75daf38` carries each raw ESPN UFC fight-status payload with the immutable
  current-card plan and captures it in the same transaction before its
  result/method fields write a log. The follow-up candidate change carries the
  complete per-fighter ESPN statistics response the same way, including a
  valid response with no usable stat categories. It also retains the raw ESPN
  card scoreboard used to identify the fight, before normalizing that same
  response—no second request. The historical runner also carries its athlete
  overview, competition, status, and opponent documents. An HTTP 404 is not
  stored as a fabricated empty source body. This completes the UFC
  fight-stat-ingest source boundary; unrelated UFC fetchers elsewhere in the
  repository are outside this claim.
- The UFC rankings scraper now requires the ledger before it requests
  `ufc.com/rankings`, then retains the complete HTML response in the same
  transaction before replacing derived ranking rows. A malformed scrape still
  leaves the last-good rows intact.

RotoWire is a separate, already-compliant retention boundary rather than a
candidate ledger gap: `ingest_rotowire_archive.py` preserves the complete
relay body as received before `ingest_rotowire_props.py` filters it. A
read-only audit found three daily raw archives (Aug. 19–21, 2.1 MB compressed)
and an enabled daily archive timer. This is one general relay request, not a
World-Cup-targeted request; the props timers that invoked Bovada's broad `all`
target remain disabled.

Focused checks:

```text
22 passed — Underdog, Bovada, and soccer/ESPN capture boundary tests
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

Legacy World Cup rows are a separate historical repair, not a request to the
publisher. `f403720` adds a backup-first tool that selects only World Cup
`prop_results` rows where both `actual_value` and `hit` are NULL, writes an
explicit `prop_voids` audit row with reason `legacy_world_cup_ungraded`, then
removes the misleading result row. On an integrity-checked DEV clone it
converted all 1,128 candidates, left zero WC result rows, and passed
`quick_check`. It has not run against DEV or production.

## Settlement clone evidence

`settle_props.py` now supports explicit `--league`, `--game-id`, `--through`,
and `--limit` filters.  These constraints are applied by SQL before the driver
can call a publisher; do not use the legacy unbounded all-league path as a
diagnostic probe on this host.

On separate low-priority, integrity-checked DEV clones:

- Two completed NFL games from Aug. 20 graded 18 of 22 relay props with numeric
  outcomes. Four stayed pending because the needed published player statistic
  was absent; there were zero errors and zero unmappable markets.
- A UFC finish-market game initially remained pending because DEV had zero
  durable UFC logs for its valid ESPN fight ID, not because the finish grader
  lacked a mapping. A bounded current-card plan then added 24 completed-fight
  logs and 47 ESPN identity bindings to the clone only. Re-running the exact
  completed fight graded all 16 props, including `finishes`, `knockouts`, and
  `submissions`, with numeric outcomes and `quick_check = ok`.
- A completed linked ATP game was probed separately. Its clone remained
  unchanged because both tested ESPN tennis scoreboard hosts returned HTTP 403
  for the historical date; the settlement driver recorded one retryable source
  error and wrote no result row. This is an upstream-availability gate, not a
  walkover/retirement decision or a reason to synthesize results.

This establishes the required order for a real target: first obtain the
verified UFC log/identity plan for that target, then apply it only with an
explicit backup and authorization, and only then run a bounded settlement
probe. Do not infer a zero-settlement diagnosis from props alone.

## Still unproven

- Full publisher-payload retention is wired for Underdog, Bovada, the
  MLS/EPL ESPN soccer-log boundary, and RotoWire's raw archive. Other ESPN and
  publisher ingest boundaries still need the same before-normalization ledger
  treatment before claiming “all publisher data is retained.”

### Direct-fetch audit scope

A source audit found 63 Python files with a direct fetch primitive or a call to
the shared ESPN fetcher. The completed work covers the high-priority props
paths above; it does **not** yet cover unrelated roster, standings, news,
scoreboard, MLB/NHL/NCAAF log, esports, or one-shot backfill fetchers. Treat
the following statement as the only supported one today: **full native payload
retention is present for the current Bovada, Underdog, RotoWire, and MLS/EPL
soccer-log ingestion paths.** Do not generalize it to the repository.
- Tennis/NFL/UFC settlement candidate work is not deployed or applied to DEV;
  its clone evidence must be remeasured against the target at apply time.
- No real daytime props run after the SQLite-lock remediation has yet been
  observed through its complete ingest/settlement window, so the lock issue is
  not closed.
