# Plan — bring back `/esports` around EWC 2026

**Plan iteration:** 2 — research plus repository-skill review<br>
**Date:** 2026-08-08<br>
**Implementation status:** IMPLEMENTED — Phases 0–3 committed in the `lp-ewc-2026` worktree branch (`7afbee2..64711a6`), release-pass cleanup pending final commit<br>
**Release status:** candidate only — no DEV, production, database, or managed-service change

This plan is the event-specific iteration of `ESPORTS-PRODUCT-DIRECTION.md`. It does not replace
the long-term Pick Desk thesis. It changes the immediate programming decision: while the Esports
World Cup is active, `/esports` should behave like an EWC tournament center rather than a generic
list of unrelated matches.

## Requested outcome

1. Bring the esports page back as a first-class surface, with EWC as its editorial and navigation
   focus through the end of EWC 2026.
2. Show the EWC Club Championship standings with honest source and freshness information.
3. Fix `/scores` Call of Duty cards that expose raw `TBD` participants during the EWC bracket.
4. Preserve the work already completed on live streams, match identity, results, picks, and
   viewer-local result days rather than creating a second esports pipeline.

## Research snapshot — 2026-08-08

### What EWC is right now

- EWC 2026 runs July 6 through August 23 and contains 25 competitions across 24 games.
- Call of Duty: Black Ops 7 is an EWC Club Championship competition. Its tournament is active
  August 5–9 and has a $1.8 million game-title prize pool.
- Upcoming tent-pole events after the current week include Chess (Aug 11), CS2 (Aug 12), Rocket
  League (Aug 12), CrossFire (Aug 17), Fortnite (Aug 17), and Trackmania (Aug 19).
- The Club Championship is a real cross-title narrative, not a cosmetic leaderboard. A club must
  place top eight in at least two competitions to be eligible, and must win at least one competition
  to finish first overall. Standard points are 1,000 / 750 / 500 / 300 / 200 for first through the
  common shared placement bands, with narrower 5th–8th values when a title ranks them individually.

Current top ten snapshot (research evidence only; **do not hard-code this table into the UI**):

| Rank | Club | Points |
|---:|---|---:|
| 1 | Team Falcons | 2,600 |
| 2 | Natus Vincere | 2,250 |
| 3 | Virtus.pro | 2,200 |
| 4 | Team Vitality | 2,000 |
| 5 | T1 | 1,750 |
| 6 | Team Vision | 1,750 |
| 7 | ZETA DIVISION | 1,500 |
| 8 | All Gamers Esports Club | 1,400 |
| 9 | Twisted Minds | 1,400 |
| 10 | Team Spirit | 1,200 |

### Sources checked

- Official EWC 2026 global rulebook (competition list, eligibility, point table, tiebreakers):
  https://d3h9qea4qy4169.cloudfront.net/EWC_2026_Global_Rulebook_1_1_55b3cc60e1.pdf
- Official EWC Call of Duty rulebook/resource page:
  https://resources.esportsworldcup.com/en/competitive-ops/rulebooks/cod-mw3
- EWC 2026 media guide (calendar and titles):
  https://cdn.esportsworldcup.com/resources/uploads/EWC_26_Media_Guide_short_d6f73c0f8a.pdf
- Current standings and event schedule cross-check, updated through Aug 7:
  https://escharts.com/special/ewc2026
- Current EWC Call of Duty bracket feed and its unresolved downstream slots:
  https://aws.breakingpoint.gg/matches

The rules and calendar have authoritative official sources. The current standings table found in
research is a third-party live table. Source rights and a stable machine-readable contract must be
resolved before automating ingestion; the browser must not scrape third-party HTML.

## What we already have

This is a reprogramming and contract-hardening job, not a greenfield esports build.

- `pages/esports.tsx` already renders confirmed live broadcasts, continuous multi-match broadcast
  identity, upcoming matches, results, and links into picks.
- `backend/routers/esports/streams.py` and `yt_live_resolver.py` already handle the EWC official
  channel, simultaneous arenas, game-first narrowing, YouTube preference, Twitch/Kick fallbacks,
  language ranking, and bounded YouTube API use.
- `backend/routers/esports/pandascore.py` already fetches the `codmw` feed and retains enough past
  matches to close the earlier EWC result hole.
- `league_tier.py` already treats the EWC main event as Tier 0 and keeps qualifiers demoted.
- The title-scoped routes `/esports/[title]` and `/predict/[title]` already support Call of Duty and
  the other registered titles.
- Finished esports rows already carry `endTime`, and `/esports` groups results by viewer-local end
  day.
- `/scores` has a separate CoD path: `GET /api/cod/games` uses Breaking Point first, then the CDL
  site, and only attaches a PandaScore detail ID afterward. That separation is the source of the
  present EWC placeholder problem.

## Skill-driven constraints

This iteration incorporates the local `delightful-design`, `build-league-data-pipelines`,
`sqlite-database-ops`, `espn-request-budget`, and `legendarypicks-esports` skills.

- **Published first:** ingest and validate the complete Club Championship population before one
  atomic publication. The UI top ten is a projection of that population, not the stored universe.
- **One writer:** name the standings publisher and every reader. No request handler or browser may
  become a competing writer or reconstruct totals from match fragments.
- **Source-native identity:** retain the provider's stable club ID and competition contribution IDs.
  Names are labels and matching candidates, never primary identity.
- **Last good survives:** incomplete pages, duplicate IDs, contradictory totals, or source failures
  do not replace a valid published run.
- **Bounded requests:** use one bulk standings request where possible, shared caches/single-flight,
  and a declared per-host request budget. This feature requires **zero ESPN requests**; adding ESPN
  as a fallback would spend the wrong publisher's budget and is out of scope.
- **Esports package ownership:** the event routes belong in a self-contained
  `backend/routers/esports/ewc.py` module wired through the package `__init__.py`, not directly in
  `sports_service.py` or grafted onto `slate.py`.
- **Matcher scope:** do not loosen shared `_team_match`/`_same_team` behavior to make the EWC CoD
  bracket fit. Use stable IDs first and a narrow EWC reconciliation layer with focused fixtures.
- **Quiet interface:** hierarchy comes from type, spacing, alignment, and subtle background shifts.
  Do not turn the EWC module into another wall of bordered cards.

## Verified defect: raw `TBD` on the EWC CoD scoreboard

Breaking Point currently identifies the active EWC quarterfinals but intentionally leaves future
bracket participants unresolved. On Aug 8 its public bracket showed:

- Team Falcons vs Gentle Mates and FaZe vs OpTic as named quarterfinals;
- Team Heretics vs `TBD` and 100 Thieves vs `TBD` in the Aug 9 semifinals;
- `TBD` vs `TBD` in the third-place match and grand final.

`breakingpoint_client.py` converts a missing team lookup directly to the literal string `"TBD"`.
`GET /api/cod/games` returns that shape, `services/sports.ts` preserves it, and `GameCard` renders
it as though it were a team name.

There are two different states that must not be conflated:

1. **Stale/unresolved identity:** the tournament has determined the participant but one source has
   not populated it. Resolve from the canonical EWC/PandaScore match index.
2. **Genuinely undecided bracket slot:** the feeder match is not final. Display a bracket dependency
   such as `Winner of Falcons–Gentle Mates`, never a fabricated club and never a bare `TBD`.

## Product shape

### `/esports` during EWC

The first screen should answer four questions in order:

1. **What is live now?** One stable featured official broadcast, with every other confirmed-live
   arena immediately reachable.
2. **What EWC competition is this?** Game, stage, teams, series score, and start/live/final state.
3. **What happens today?** A compact EWC-only day slate across titles, followed by results.
4. **Who is winning the Club Championship?** A standings rail with points, movement when known,
   eligibility state, `as of` time, and source link.

Desktop layout: live/event content in the main column and Club Championship top ten in a visually
quiet right rail. Mobile layout: live content, today's EWC slate, then a collapsed top-five standings
section with an expand action. The complete generic esports schedule remains below the EWC module;
non-EWC live matches must not disappear.

The standings treatment has no outer border and no vertical grid lines. Use aligned tabular numbers,
strong rank/club typography, generous row spacing, and at most low-contrast horizontal row rules.
Give the EWC focus one subtle background plane; do not stack border + shadow + tint on the same
element. Status pills are reserved for meaningful `LIVE`, `STALE`, and eligibility states, not
decoration.

Replace the hard-coded MSI-special decision in `pages/esports.tsx` with an event-focus contract.
For EWC dates the focus is `ewc-2026`; after Aug 23 the module expires automatically and the page
falls back to the existing generic broadcast-first board. Do not encode the current week or current
leader in React.

### Club Championship table

Minimum row contract:

```json
{
  "rank": 1,
  "clubId": "team-falcons",
  "clubName": "Team Falcons",
  "logo": null,
  "points": 2600,
  "eligibleTopEightCount": null,
  "titleWins": null,
  "eligibleToWin": null,
  "movement": null
}
```

Top-level response contract:

```json
{
  "event": "ewc-2026",
  "standings": [],
  "asOf": "absolute ISO timestamp",
  "source": { "label": "...", "url": "..." },
  "status": "current | stale | unavailable"
}
```

`eligibleToWin` stays `null` unless the publisher contains enough per-title placements to compute
the rulebook conditions. Do not infer eligibility from total points. If refresh fails, serve the last
known good snapshot with `status: "stale"`; if no valid snapshot exists, show an honest unavailable
state rather than an empty table or zero points.

Display semantics are explicit:

- `0` points means the source published a real zero; `null` renders as an em dash and means unknown.
- Movement is computed only between two comparable complete published runs; otherwise it is absent,
  not zero.
- Eligibility reads `Eligible`, `Not yet eligible`, or `Eligibility unavailable` only when the source
  evidence supports that exact statement.
- The points heading includes the standings `as of` time. A stale badge must be visible without
  opening a tooltip.
- Rank ordering follows the publisher's official tiebreak result. The UI does not break equal-point
  clubs alphabetically and imply a sporting order.

## Data and API design

### 1. One EWC projection over the existing match slate

Add a server-side EWC projection, not a new collector. Candidate route:

`GET /api/esports/events/ewc-2026`

It filters the existing normalized esports slate by a normalized event ID and returns live, upcoming,
and completed matches plus current/next competition metadata. Tournament identity must be explicit
(`eventId: "ewc-2026"`) at the backend boundary; a UI substring search for `"world cup"` is not an
acceptable contract.

### 2. A published Club Championship snapshot

Candidate route:

`GET /api/esports/events/ewc-2026/club-standings`

The route accepts a bounded `limit` over the complete published population. Desktop requests ten;
mobile requests five and requests ten only when the user expands. A complete full-table route may be
added when there is a design that renders it; the landing page must not download an unrendered full
leaderboard.

Before implementation, complete a source spike in this order:

1. Identify an official EWC JSON/data endpoint or licensed feed used by the official standings
   surface and document its terms and identifiers.
2. If no usable official machine-readable endpoint exists, choose an allowed provider and document
   attribution, refresh limits, and redistribution terms.
3. Publish atomically to a complete validated snapshot. The request path reads only the last valid
   publication; it does not scrape external pages or recalculate the championship.

Proposed SQLite ownership, if the source spike confirms durable movement/history is useful:

- `ewc_standings_runs`: `run_id`, event, source, source timestamp, fetched/published timestamps,
  source-reported/fetched club counts, payload checksum, status, and validation note.
- `ewc_standing_rows`: `run_id`, source club ID, canonical slug, rank, points, contribution payload,
  title wins, eligibility evidence, and display metadata.
- The API selects exactly one `published` run. A failed candidate run is recorded for diagnosis but
  never becomes readable. Publication of run + complete rows + active marker is one transaction.

If movement/history is not required, use the existing esports atomic-file pattern instead of adding
schema. Make this an explicit Phase 0 decision; do not create both stores.

Validation rejects duplicate ranks/club IDs, negative points, rank inversions, missing timestamps,
an incomplete source population, fetched/source count disagreement, and a point total regression
unless explicitly identified as a publisher correction. Record the stable normalized source payload
and checksum so the published run reproduces.

Before any SQLite rehearsal, resolve an absolute existing `LP_DB_PATH`, inspect the schema and writer
ownership read-only, and capture `PRAGMA quick_check` plus protected-table fingerprints. Create a
disposable clone with `VACUUM INTO` from a read-only connection—never plain `cp` against a live/WAL
database—and verify the clone before applying additive schema.

### 3. Repair CoD scoreboard source arbitration

Keep Breaking Point's useful CDL history, but stop treating it as the sole participant authority for
EWC bracket games.

- Fetch/index the PandaScore `codmw` EWC window once per refresh, not once per scoreboard row.
- Match by explicit source ID when available; otherwise require event + bounded start time + both
  known participants. Never resolve an EWC game using time alone.
- For a matched row, use the freshest trustworthy participant, state, score, and winner fields and
  retain Breaking Point's ID separately from PandaScore's detail ID.
- Represent unresolved sides structurally, for example
  `participant: { state: "pending", feederGameId, outcome: "winner", label }`, rather than placing
  `"TBD"` in `team.name`.
- Extend the frontend `Game` boundary with an optional participant label. `GameCard` renders the
  dependency label; it never invents a score, logo, or detail link for an unresolved participant.
- Once a feeder match becomes final, the next refresh must replace the dependency with the real
  club. No restart or build should be required.
- Keep reconciliation local to the CoD/EWC adapter. Do not add another fuzzy tier to shared esports
  identity functions, and do not treat zero prefix-duplicates as sufficient identity evidence.

If PandaScore lacks the bracket dependency graph, derive that graph only from a source that exposes
round/slot/predecessor IDs. Do not hard-code the Aug 9 clubs or bracket in application code.

### 4. Request and cache contract

Phase 0 must publish a request matrix before any collector is run:

| Host/source | Operation | Calls per cold refresh | Cache/freshness | Failure behavior |
|---|---|---:|---|---|
| Club standings provider | complete standings population | target: 1 bulk call | publisher cadence, not request-path TTL | retain last good |
| PandaScore `codmw` | bounded EWC match window | reuse existing bulk fetch | existing shared cache | retain BP row/pending state |
| Breaking Point | current/history bracket feed | reuse existing bulk fetch | existing shared cache | existing CDL fallback |
| ESPN hosts | none | 0 | n/a | never introduced as fallback |
| YouTube Data API | none for standings/scores | 0 | existing resolver only | free resolver/fallback policy unchanged |

The final source spike must replace `target: 1` with a measured count and print actual requests spent
per host. Configure budgets in the callable fetch function, not only a CLI entrypoint. Cache keys
include event and source generation; elapsed TTLs use a monotonic clock; concurrent cold misses use
single-flight; failures never poison or replace the last-good generation. State worker-local versus
cross-process behavior explicitly.

Read-path budgets for the two new routes must name maximum rows/bytes, cold and warm latency, and
maximum staleness after a successful publication. Measure database read, transformation, JSON
serialization, proxy transfer, and browser render separately before calling the route fast.

## Implementation sequence

### Phase 0 — source contracts and fixtures

- Capture current EWC event, standings, and CoD bracket fixtures with source timestamps.
- Decide and document the Club Championship publisher and usage rights.
- Map EWC event IDs and CoD match IDs across the current esports slate, PandaScore, and Breaking
  Point; record collisions and unresolved rows.
- Write the complete source/ID/writer/reader/request matrix, including reported and fetched club
  counts, pagination/sorting behavior, nullability, checksum, and per-host cold-refresh cost.
- Choose exactly one standings persistence contract: versioned SQLite runs when history/movement is
  required, otherwise the existing atomic esports snapshot pattern.
- Add contract tests first for named, stale, pending-winner, pending-loser, and fully unavailable
  participants.

### Phase 1 — scoreboard repair

- Introduce structured pending participants in the backend normalization boundary.
- Reconcile EWC CoD rows against the indexed canonical match feed.
- Render feeder labels on `/scores`; retain real names as soon as they resolve.
- Keep non-EWC CDL behavior unchanged.

This phase ships independently because it fixes a visible correctness problem during the active CoD
tournament.

### Phase 2 — EWC event and standings APIs

- Add explicit EWC event identity to normalized match rows.
- Add `backend/routers/esports/ewc.py`, wire its router through `routers/esports/__init__.py`, and
  keep the existing slate response contract stable.
- Add the EWC projection route and one atomic standings publisher/reader.
- Add stale/unavailable telemetry and last-good behavior.

### Phase 3 — EWC-focused page

- Replace the MSI-specific hero switch with the event-focus module.
- Add EWC live/today/results sections and Club Championship rail.
- Preserve generic non-EWC live broadcasts and full schedule below.
- Add title and club deep links only where canonical destinations exist.
- Use an open, border-light standings table and verify the hierarchy at mobile and desktop widths;
  do not nest cards inside the live module.

### Phase 4 — release gates

- Fixture/unit tests for projection, standings validation, CoD reconciliation, and pending labels.
- Targeted frontend tests for top-ten/top-five layouts, loading, stale, unavailable, and bracket
  dependency states, including zero-versus-unknown and eligibility-unknown distinctions.
- Browser verification at desktop and mobile widths for `/esports`, `/scores`, date navigation,
  `?league=Call%20of%20Duty`, and a CoD detail link.
- Capture before/after esports JSON and compare response keys/contracts separately from volatile live
  values. Verify `watch` remains `{platform, url, channel, online}`.
- Verify each local-calendar day label appears once and in chronological order; backend prominence
  ordering must not split one day into multiple groups.
- Live comparison against the chosen standings publisher and two independent CoD bracket sources.
- Verify official YouTube selection for each concurrent EWC arena without spending routine YouTube
  Data API quota.
- Confirm no unrelated sports route, managed process, database, or production service changed.
- If SQLite is selected, rehearse additive schema/publication on a verified `VACUUM INTO` clone,
  re-run `PRAGMA quick_check`, and compare protected fingerprints. A passing clone is candidate
  evidence only and grants no permission to mutate DEV or production.
- Run backend checks from `backend/venv`; use the repository/shared frontend binaries in an isolated
  worktree rather than installing dependencies. Verify the static `/esports` HTML produced by the
  build as well as hydrated browser behavior.

## Acceptance criteria

- `/esports` visibly identifies EWC 2026 as the active focus and shows all current EWC broadcasts
  without hiding non-EWC live matches.
- Club standings display at least the current top ten on desktop and top five on mobile, with source,
  `as of`, and honest stale/unavailable states.
- The standings API never emits a self-certified empty success and never silently converts unknown
  eligibility to `false`.
- The published standings population matches the source-reported club count, has unique stable club
  IDs, and reproduces its checksum; the UI display limit does not define completeness.
- The landing page requests only the five or ten standings rows it renders, and expanding mobile
  standings performs the bounded follow-up request.
- No `/scores` EWC CoD card displays a raw `TBD`/`TBA` team name.
- A decided participant resolves to the real club on refresh; an undecided slot displays its bracket
  dependency; an unresolvable data fault displays `Participant unavailable` and is logged.
- EWC CoD live/final series scores agree with the selected authoritative feed for every card in the
  verification window.
- Existing Call of Duty league pages, picks, result grouping, stream continuity, and other sports
  scoreboard cards retain their current behavior.
- Cold/warm latency, response bytes, request counts per host, cache generation, concurrency, and
  maximum stale age meet the bounds recorded in Phase 0.

## Explicit non-goals for this iteration

- No Ultimate Team, packs, marketplace, or new monetization system.
- No model probabilities or new live-stat vendor integration.
- No rewrite of the existing esports state machine or stream resolver.
- No browser-side scraping and no hard-coded standings, bracket winners, dates, or club totals.
- No DEV/production restart, deployment, database write, or tag move without separate authorization.

## Decisions still needed before implementation

1. Approve this page hierarchy: EWC live/today first, Club Championship second, generic board below.
2. Decide whether the standings rail should show only points or points plus per-title contribution
   chips when the source contract supports them. Recommendation: include the chips; they explain why
   the cross-title club race matters.
3. Approve the final standings data provider after the Phase 0 rights/endpoint spike. The current
   research table is evidence, not yet an ingestion contract.

## Release pass evidence — 2026-08-08 (final)

Worktree `/root/lp-ewc-2026` (isolated branch from committed HEAD). Implementation commits:
`7afbee2` Phase 0 contracts, `184eb21` Phase 1 CoD raw-TBD repair, `e7fd8bd` Phase 2 projection +
standings routes, `64711a6` Phase 3 EWC-focused page; plus the final release-pass commit below.

**Backend tests (run from `backend/venv`, fixture-driven, no network): 109 passed.**
`backend/test_cod_ewc_reconcile.py` (26) — includes three new regressions added during review:
decided-`loser` feeder resolves the other opponent (never the winner), Tier-1 ambiguous name
association returns `None` (never the first hit), missing feeder node labels structurally
("Winner/Loser of preceding match", never literal `TBD`). Also `test_ewc_contract.py`,
`test_ewc_routes.py` (56) and `test_esports_streams.py`, `test_esports_predict_api.py`,
`test_wc_context.py` (53).

**Browser gate — desktop PASS, mobile FAIL (not claimed as passing).**
`docs/ewc2026/fixtures/browser-esports-desktop.png` renders (1440×900, pixel-verified non-white);
the YouTube iframe shows Google's headless-browser sign-in interstitial, which is unrelated to our
code. The mobile capture was a white "Internal Server Error" page — the isolated backend/API proxy
was down during that capture — and the invalid PNG was **not** committed. Regeneration is blocked:
the shared frontend install `/root/legendarypicks/node_modules` is empty and the worktree `.next`
holds no build output; per AGENTS.md a worktree must not reinstall, so this is recorded as the
documented Next build blocker, not retried. Frontend jest/next binaries are likewise unavailable,
so the frontend unit suite was not re-runnable this pass.

**Request counts (this pass: zero external requests — all 109 tests are fixture-driven).**
Declared per-host matrix unchanged (Phase 0 §4): PandaScore 1 bracket call per 120 s cold window
plus the existing bulk title feeds (shared caches); Breaking Point existing 300 s cache; ESPN **0**
(never introduced as fallback); YouTube Data API **0** for standings/scores.

**Candidate vs DEV/production.** Everything above ran in the isolated worktree only. No DEV or
production DB write (standings persist via the atomic-file snapshot pattern; SQLite was never
selected, so the VACUUM INTO rehearsal gate is vacuous — Phase 0 §5), no managed-service restart,
no deployment, no push, no tag move.

**Cleanup and hygiene.** `git diff --check` clean (plan header trailing spaces → `<br>`; probe
trailing whitespace stripped in `docs/ewc2026/probes/`). Secrets scan (API keys, PEM/private keys,
bearer tokens, password assignments) across `docs/ewc2026/`, the plan, `scripts/verify-ewc-browser.js`,
and the backend diff of the four esports commits: zero matches. `backend/data/esports_team_logos.json`
is tracked and unmodified. Kept: `scripts/verify-ewc-browser.js` (repeatable gate harness),
`browser-esports-desktop.png`, `candidate-projection-live.json` (live API snapshot). Scratch probes
moved out of the worktree; no mobile PNG committed.

**Open decision 3 resolution (recorded).** Phase 0 spike found no permitted machine-readable
standings publisher, so the standings route serves the honest `status: "unavailable"` contract and
the validation-gated publisher awaits a permitted source — no browser scraping, no hard-coded table.
