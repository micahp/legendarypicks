# Context Summary — August 21, 2026

This is the current operational handoff.  It separates a production incident
that was repaired under explicit authorization from candidate-only data work.
It is not permission to deploy, change a timer, or write DEV/production data.

## Current state

- The public mock-draft **Load Failed** incident is repaired in production.
  The actual cause was a 2.9 MB pool response combined with host-nginx proxy
  temp directories that its `www-data` workers could not write.  The backend
  now returns the 1,027 players that the draft client can actually select
  (instead of 4,550 rows it would discard), and only that exact route has
  proxy buffering disabled.  See `docs/CONTEXT-2026-08-21.md` in managed DEV
  for the incident evidence and verification.
- The host TLS edge is nginx, outside Docker; the application containers remain
  loopback-only.  The incident was an availability failure, not evidence of a
  public data leak.  Do not describe the system as all-Docker ingress.
- Both scheduled broad props timers are disabled and inactive.  They must stay
  that way until a landed target split excludes World Cup and the raw-capture
  schema is present on each named database.  Historical World Cup repair is a
  local database operation and must make no publisher request.
- Candidate recurring pipeline code excludes World Cup from both its database
  discovery query and its link/settlement loops, with settlement bounded to the
  recent three days. This is a landing prerequisite, not permission to
  re-enable either timer.
- The active host's two-minute live-discounts cron no longer sends `wc`; the
  default scoreboard and recap timer selectors also omit it. Explicit manual
  `wc` commands remain available for historical work.
- Props freshness monitoring remains active but no longer self-starts either
  disabled props ingest service on a stale read.
- Candidate branch `feat/tennis-current-spine` holds unlanded data-integrity
  work.  Its raw-payload ledger covers the current Underdog, Bovada, and
  MLS/EPL ESPN-log boundaries; RotoWire already archives whole relay bodies.
  UFC fight-stat ingest retains current-card and historical athlete-overview,
  competition, status, opponent, and per-fighter statistics bodies; the UFC
  rankings job retains its source HTML. This is not a repository-wide claim
  that every publisher response is retained.

## Highest-priority gates

1. **NCAAF opening, August 29.** Candidate week navigation reuses ESPN's
   publisher-defined football weeks.  ESPN exposed 25 Week-1 games in a
   read-only check; the candidate still needs a DEV browser check after an
   authorized landing.
2. **Props integrity.** Tennis historical scoreboards returned HTTP 403 on
   both tested ESPN hosts, so no tennis result was invented.  NFL and UFC
   clone probes proved bounded grading paths, but neither is authorization to
   write a live database.  Legacy World Cup NULL/NULL results have a
   clone-proven void conversion tool. On August 21 it was applied to managed
   DEV only with a verified backup: 1,128 false NULL/NULL result rows became
   explicit void-ledger rows and zero matching result rows remain. Production
   remains untouched.
3. **MLS parity.** DEV has live 2026 standings but season leaders from 2025;
   retained regular-season logs stop at August 8.  Refresh a bounded clone,
   aggregate it, verify freshness, then seek target-specific authorization.
4. **SQLite under real load.** Production has WAL and the busy timeout, but
   only quiet evening props runs have occurred since the change.  Observe a
   daytime run before closing the lock incident.

## Recurrence controls for the mock-draft failure class

These are checks, not a justification for broad nginx policy changes.

| Risk | Required control before calling a route healthy |
|---|---|
| Large JSON list is filtered only in the browser | Measure serialized bytes and rows at the API; query only the selectable/renderable population before serialization. |
| API access log says 200 while the browser fails | Check nginx error logs for the same request window and load the real public URL in a clean browser. |
| A slow reader makes nginx spill a response to disk | Verify the worker can create/remove files in the exact temp path; use route-scoped buffering only after response-size, security, and capacity review. |
| Large authenticated export/download is put on an unbuffered route | Require a separate authorization, cache/privacy review, response budget, and slow-client capacity test.  Do not copy the mock-draft setting wholesale. |
| Host configuration and checked-in configuration diverge | Test nginx configuration before reload and keep the versioned vhost synchronized with the live route-specific stanza. |
| A Docker-only test bypasses the real ingress path | Verify the public TLS path, container loopback bindings, proxy target, and browser rendering; a container-local 200 is insufficient. |
| Build/rebuild overlap hides which code is running | Inspect running images and active build processes; serialize rebuilds and record commit/image identity before making a release claim. |

## Data-ingest failures of the same shape

The analogous data problem is normalizing or discarding publisher material
before it can be audited.  Each ingest boundary should retain the complete
native body with source, endpoint, digest, and observation timestamps before
parsing it.  Capture writes must be transactional with the derived rows, and
an unmigrated target must fail before the first source request.  Do not claim
coverage beyond the boundaries that have been tested.

Managed DEV now has the additive `publisher_captures` migration
(`20260821_001_publisher_captures`) after a verified backup and `quick_check`.
That enables the landed raw-capture contract only when the relevant candidate
code is deliberately deployed; it does not itself start a fetcher, change a
timer, or make production compliant.

For scheduled work, select league targets explicitly and record the request
budget.  A broad `all` target is not an acceptable diagnostic: it can spend
calls on inactive or prohibited leagues.  Repairs and settlement probes must
filter the database before a source call, run against an integrity-checked
clone first, and leave unknown outcomes pending or explicitly void—not
NULL/NULL rows stamped as settled.

## Before the next live change

1. Name the exact target (candidate, managed DEV, or production) and its
   absolute database path if data is involved.
2. Take a verified backup for any write; measure source freshness and record
   before/after counts.
3. Make one bounded, low-priority operation at a time on this constrained
   host.
4. Verify the real requested surface: SQL integrity, API payload, rendered
   public page when applicable, and proxy/service logs in the same time window.
5. Record what remains unproven rather than promoting clone evidence into a
   deployment claim.
