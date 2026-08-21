# Landing Manifest — August 21, 2026 Candidate

Candidate branch: `feat/tennis-current-spine`.  This is a dependency and
authorization manifest, not approval to merge, deploy, re-enable a timer, or
write either live database.

## Already handled

`be9783e` was separately cherry-picked as managed-DEV `745de85` for the
mock-draft incident. Do not pick it again.

## Independently reviewable code

| Change | Candidate commit(s) | Gate before landing |
|---|---|---|
| NCAAF publisher-week navigation | `a09fde4` | Browser-check `/leagues/ncaaf?tab=schedule` after a DEV deployment; no DB mutation required. |
| NFL relay settlement | `1155d70`, optionally bounded-driver commits `1aca2af`, `dcf607b`, `95b2418` | Fresh bounded clone probe against the intended target; never run the unbounded driver as a diagnostic. |
| UFC finish settlement and retained fight-stat responses | `39de106`, `75daf38`, current follow-ups | First make the bounded UFC ingest plan against a clone of the intended target. Apply logs/identities only with a verified backup and explicit DB authorization; then settle a bounded exact game. The current-card and historical athlete-overview, competition, status, opponent, and fighter-stat bodies are retained. Other UFC fetchers elsewhere in the repository remain outside this narrow claim. |
| Tennis linking and policy | `9a7a7ed` through `004ef42` | ESPN tennis historical scoreboards currently return 403. Keep unmerged until a live source probe succeeds; do not fabricate results or relax the walkover/retirement policy. |

## Schema/data-coupled work

| Change | Candidate commit(s) | Required order |
|---|---|---|
| Raw publisher ledger | `f5d4040`, `4ed32ab`, `4c12316` | Land code; make verified backups; run `migrate_publisher_captures.py --check` then `--apply` against each named target; verify capture rows on a bounded run. Only after that may props timers be reconsidered. |
| UFC rankings source retention | current follow-up | The rankings scraper now fails before a UFC.com request unless the ledger exists. Land its code and migrate the named target before a bounded ranking refresh; verify the HTML capture and rankings count together. |
| Per-day/live scoreboard source retention | current follow-up | Land code and migrate the named target before re-enabling this candidate path; verify a raw ESPN capture and normalized snapshot in one bounded run. The range-backfill path is not yet covered. |
| Legacy WC null-result repair | `f403720` | Explicit target authorization only. Run `--check`, verify candidate count, use the generated backup, then `--apply`; verify no WC `prop_results` remain and matching `prop_voids` rows exist. No publisher request is involved. |
| MLS 2026 leaders | existing ingest scripts | Refresh bounded missing ESPN summaries into a clone, aggregate the same clone, verify freshness and leaders UI, then obtain explicit authorization for the named target. |

## Timers and source calls

- `legendarypicks-props.timer` and `legendarypicks-props-prod.timer` remain
  disabled. Do not re-enable them before the scheduled target split and raw
  ledger migration have both landed and been verified.
- Candidate pipeline/link/settlement scheduling excludes `wc` even if a
  recent database row exists; it is still not authorization to re-enable a
  timer. Verify the deployed timer command, target database migration, and a
  bounded non-WC run first.
- RotoWire’s archive timer is a single general relay request that retains its
  full body; it is not a World-Cup-specific request.
- No new recurring World Cup fetch is authorized.
