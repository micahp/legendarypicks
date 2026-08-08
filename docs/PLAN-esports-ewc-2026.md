# Plan — Esports league destination (EWC 2026 tournament center under the Leagues system)

**Plan iteration:** 3 — post-correction rewrite (2026-08-08)
**Implementation status:** PLANNED. The accepted IA was partially applied at `1dab7f7` (EWC module
moved to `/leagues/esports`, Esports card added to `/leagues`, `/esports` slimmed). This plan is the
authoritative post-correction contract: finish the complete Esports league destination, prove the
correction with tests, and preserve every backend contract.
**Release status:** candidate only — no DEV, production, database, or managed-service change.

This plan is the event-specific iteration of `ESPORTS-PRODUCT-DIRECTION.md`. It supersedes the
iteration-2 framing ("/esports behaves like an EWC tournament center"), which was **rejected**.
The Esports World Cup remains the editorial centerpiece of the product, but it lives in the Leagues
system, not on the live board.

## The correction — accepted information architecture (2026-08-08)

1. **`/esports` is the existing live broadcast and match board.** It keeps its confirmed-live hero,
   broadcast continuity, upcoming slate, results, and picks entry — with **no EWC tournament-center
   takeover**. EWC matches appear only as ordinary board rows with their existing live/final/up-next
   behavior. The page file contains no EWC tournament-center module.
2. **`/leagues/esports` is the Esports league destination.** It owns the EWC 2026 tournament center:
   event focus, today/results across titles, the Club Championship rail, and the honest unavailable
   state until a permitted publisher exists.
3. **The main `/leagues` list includes Esports**, using the existing league-card design system.
4. **The EWC backend APIs are preserved as shared contracts**: the projection route, the Club
   Championship reader, explicit `ewcEventId` identity, qualifier exclusion (`c64f6df`), the CoD
   structural pending-participant/TBD repair, and the request budgets.

## Requested outcome

1. A complete Esports league destination at `/leagues/esports`: league-style header/navigation,
   game/title discovery and links, the EWC 2026 tournament center, Club Championship standings with
   source/freshness honesty, live and upcoming EWC schedule, completed results, broader non-EWC
   esports context, direct paths to title pages and picks/prediction, responsive desktop/mobile
   hierarchy, and loading/error/empty/stale states — with continuity to existing streams, results,
   and match identity.
2. Focused tests proving: `/esports` no longer renders the EWC module, `/leagues` links Esports, and
   `/leagues/esports` renders the complete product and all data states responsively.
3. Preserve the EWC APIs, qualifier exclusion, CoD pending-participant repair, request budgets, and
   honest unavailable standings until a permitted publisher is found.

## Research snapshot — 2026-08-08 (preserved from iteration 2)

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

## What we already have (as of iteration 3)

This is a reprogramming and contract-hardening job, not a greenfield esports build.

- `pages/esports.tsx` already renders the live board: confirmed live broadcasts, continuous
  multi-match broadcast identity, upcoming matches, results, and links into picks. It no longer
  renders the EWC module (removed at `1dab7f7`), but the module code still lives in that file —
  Phase B moves it out.
- `pages/leagues/esports.tsx` already exists as a thin wrapper (breadcrumb, header, live link,
  `EwcModule` + standings rail with the responsive 5/10 limit). It is not yet the complete
  destination: no title discovery, no non-EWC context, thin loading/error/empty states.
- `pages/leagues.tsx` already lists Esports with a league card (added at `1dab7f7`).
- `backend/routers/esports/ewc.py` owns the EWC projection
  (`GET /api/esports/events/ewc-2026`) and the Club Championship reader
  (`GET /api/esports/events/ewc-2026/club-standings`), including the honest `unavailable` state.
- `backend/routers/esports/streams.py` and `yt_live_resolver.py` handle the EWC official channel,
  simultaneous arenas, game-first narrowing, YouTube preference, Twitch/Kick fallbacks, language
  ranking, and bounded YouTube API use.
- `backend/routers/esports/pandascore.py` fetches the `codmw` feed and retains enough past matches
  to close the earlier EWC result hole.
- `league_tier.py` treats the EWC main event as Tier 0 and keeps qualifiers demoted.
- The title-scoped routes `/esports/[title]` and `/predict/[title]` support all registered titles;
  `components/Esports/LeagueDesk.tsx` is the per-title desk (title pills, streams, results, picks).
- Finished esports rows carry `endTime`, and `/esports` groups results by viewer-local end day.
- `/scores` CoD path uses Breaking Point first, then the CDL site, then attaches a PandaScore detail
  ID; the EWC bracket reconciliation in `backend/routers/esports/cod_ewc.py` resolves structural
  pending participants so no card shows a raw `TBD`/`TBA`.
- Backend tests (fixture-driven, zero external requests): `test_ewc_routes.py`,
  `test_ewc_contract.py`, `test_cod_ewc_reconcile.py`, `test_esports_streams.py`,
  `test_esports_predict_api.py`, `test_wc_context.py`. Frontend: `components/EsportsEwcModule.test.tsx`
  (rail states, module render, GameCard pending labels).

## Skill-driven constraints

This iteration incorporates the local `delightful-design`, `build-league-data-pipelines`,
`espn-request-budget`, and `legendarypicks-esports` skills.

- **Published first:** ingest and validate the complete Club Championship population before one
  atomic publication. The UI top ten is a projection of that population, not the stored universe.
- **One writer:** the standings publisher and every reader are named. No request handler or browser
  may become a competing writer or reconstruct totals from match fragments.
- **Source-native identity:** retain the provider's stable club ID and competition contribution IDs.
  Names are labels and matching candidates, never primary identity.
- **Last good survives:** incomplete pages, duplicate IDs, contradictory totals, or source failures
  do not replace a valid published run.
- **Bounded requests:** one bulk standings request where possible, shared caches/single-flight, and
  a declared per-host request budget. This feature requires **zero new external requests**; the
  title-discovery route reads the already-cached shared slate. ESPN stays out of the esports
  request path entirely.
- **Esports package ownership:** the event routes live in the self-contained
  `backend/routers/esports/` package (`ewc.py`, `predict.py`, `slate.py`), not in
  `sports_service.py` or grafted onto `slate.py`.
- **Matcher scope:** shared `_team_match`/`_same_team` behavior is not loosened for the EWC CoD
  bracket; reconciliation stays local to `cod_ewc.py` with stable IDs first.
- **Quiet interface:** hierarchy comes from type, spacing, alignment, and subtle background shifts.
  The tournament center is one subtle plane, not another wall of bordered cards.

## Verified defect: raw `TBD` on the EWC CoD scoreboard (status: fixed, regression-tested)

Breaking Point identifies the active EWC quarterfinals but intentionally leaves future bracket
participants unresolved. `breakingpoint_client.py` previously converted a missing team lookup
directly to the literal string `"TBD"`. The Phase 1 repair (`184eb21`) introduced structural
pending participants in the backend normalization boundary (`participant: {state: "pending",
feederGameId, outcome, label}`), a narrow EWC/CoD reconciliation layer in `cod_ewc.py`, and
`GameCard` rendering of dependency labels — never a fabricated club, never a bare `TBD`/`TBA`.
The regression suite (`test_cod_ewc_reconcile.py`, incl. `test_no_raw_tbd_anywhere` covering both
`TBD` and `TBA`) pins this. This plan adds one frontend guard so the assertion holds at render too.

## Product shape (corrected IA)

### `/esports` — live broadcast + match board only

The existing board already answers, in order:

1. **What is live now?** One stable featured official broadcast, every other confirmed-live arena
   immediately reachable (broadcast continuity, gap states, up-next).
2. **What is this competition?** Game, stage, teams, series score, and start/live/final state.
3. **What happens today and what finished?** Day-grouped upcoming slate and viewer-local result days.
4. **Where do I make a call?** The existing picks entry.

Contract for this plan: the `/esports` page renders **no** EWC tournament-center elements — no event
focus module, no Club Championship rail. EWC matches are ordinary board rows. `pages/esports.tsx`
contains no EWC module code (Phase B). Non-EWC live content must never disappear.

### `/leagues` — the Esports entry

An Esports card in the `LEAGUES` list (existing league-card design system) linking to
`/leagues/esports`. Already present at `1dab7f7`; kept and verified by test.

### `/leagues/esports` — the complete Esports league destination

Section order (desktop; stacking the same order on mobile):

1. **League-style header/navigation** — breadcrumb to `/leagues`, page title "Esports", one-line
   description, and a persistent "Live esports →" link to the live board.
2. **EWC 2026 tournament center** — the event-focus module: featured live broadcast via the shared
   `LiveCard`/`buildBroadcastViews` machinery (continuity with the board), today's EWC slate across
   titles, and EWC results. One subtle background plane; no nested card walls.
3. **Club Championship rail** — the honest standings surface: rank, club, tabular points, `as of`
   time, source link, visible stale badge, loading skeleton, and the explicit unavailable state
   ("no licensed machine-readable publisher is wired yet — we are not guessing the table"). Real
   `0` points render as `0`; unknown renders as an em dash. Desktop requests ten rows, mobile five
   with an expand action to ten (bounded follow-up request).
4. **Game/title discovery** — pills for every registered title with live/match counts, from the new
   `GET /api/esports/titles` route (one source of truth: the backend registry + the shared slate).
   Each pill links to its title desk `/esports/{slug}`; a secondary link takes the user to
   `/predict?title={slug}`.
5. **Broader non-EWC esports context** — a quiet section linking to the live board (`/esports`, the
   full schedule) and the picks board (`/predict`), so the destination is a league hub, not an
   EWC-only island. No duplicated collectors; the links point at the existing surfaces.
6. **States** — loading skeletons, a fetch-error card with retry, an honest empty state when the
   EWC event is inactive or has no matches, and the rail's current/stale/unavailable states.

Responsive contract: `lg:` two-column (center + rail), single column below; the title pills and any
horizontal nav scroll rather than cram (`overflow-x-auto`); the rail limit follows the viewport
(`matchMedia`), 10 on `>=1024px`, 5 below, expand → 10.

### Club Championship table (preserved contract)

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
the rulebook conditions. If refresh fails, serve the last known good snapshot with
`status: "stale"`; if no valid snapshot exists, show the honest unavailable state rather than an
empty table or zero points. Display semantics are explicit: `0` points means a published real zero;
`null` renders as an em dash and means unknown; movement only between two comparable complete
published runs; eligibility reads only what the source evidence supports; rank ordering follows the
publisher's official tiebreak.

## Data and API design

### Preserved backend contracts (do not regress)

- `GET /api/esports/events/ewc-2026` — the EWC projection over the shared slate, filtered by the
  normalized `ewcEventId` stamped at the backend boundary (never a UI substring search); explicit
  `eventId: "ewc-2026"`; live/upcoming/completed buckets; `active`/`building` so the UI falls back
  honestly when the event expires. Qualifier series stay excluded (`c64f6df`).
- `GET /api/esports/events/ewc-2026/club-standings` — bounded `limit` (1–100) over the published
  snapshot; desktop 10, mobile 5 expanding to 10; honest `unavailable` when no valid publication
  exists; never a self-certified empty success; never silently converts unknown eligibility to
  `false`.
- CoD scoreboard arbitration (`cod_ewc.py` + Breaking Point + PandaScore detail IDs) unchanged.

### New read-only route — `GET /api/esports/titles`

Lives in `backend/routers/esports/predict.py` next to `_title_options` (one source of truth), reads
the already-built shared slate (`esports_upcoming()`, shared cache), and returns:

```json
{
  "titles": [
    { "slug": "call-of-duty", "label": "Call of Duty",
      "match_count": 3, "live_count": 1, "result_count": 5, "next_start": 1786215600000 }
  ]
}
```

No new collector, no new external request — the slate is already fetched and cached by the existing
board path. The client never reconstructs title identity from match labels.

### Request and cache contract (unchanged — this iteration adds zero external requests)

| Host/source | Operation | Calls per cold refresh | Cache/freshness | Failure behavior |
|---|---|---:|---|---|
| Club standings provider | complete standings population | target: 1 bulk call (not yet wired) | publisher cadence, not request-path TTL | retain last good |
| PandaScore `codmw` | bounded EWC match window | reuse existing bulk fetch | existing shared cache | retain BP row/pending state |
| Breaking Point | current/history bracket feed | reuse existing bulk fetch | existing shared cache | existing CDL fallback |
| ESPN hosts | none | 0 | n/a | never introduced as fallback |
| YouTube Data API | none for standings/scores | 0 | existing resolver only | free resolver/fallback policy unchanged |

The standings publisher remains unwired: Phase 0 resolved that no permitted machine-readable Club
Championship publisher exists on this box (official EWC API is Bearer-gated; PandaScore publishes no
cross-title Club Championship; third-party HTML scraping is out of scope). See
`docs/ewc2026/PHASE0-SOURCE-AND-CONTRACTS.md`. Continue source research only through
permitted/authoritative channels; never hard-code or scrape the research top ten.

## Implementation sequence

### Phase A — plan iteration (this document)

Rewrite the plan as the authoritative post-correction contract and commit it separately.

### Phase B — extract the EWC module out of `/esports`

- Move `EwcProjection`, `Standings`, `EwcMatchRow`, `ClubStandingsRail`, and `EwcModule` from
  `pages/esports.tsx` into `components/Esports/EwcModule.tsx` (self-contained, importing the shared
  `LiveCard`/`buildBroadcastViews` machinery and primitives from the board page — one-direction
  dependency, no cycle).
- `pages/esports.tsx` keeps only board code: no EWC types, no EWC components. `Eyebrow`,
  `SectionHeader`, `TeamCrest`, `localDateKey`, `groupTime` remain available to the module (exported
  or copied as pure helpers).
- Update `components/EsportsEwcModule.test.tsx` imports to the new location.

### Phase C — titles route

- Add `GET /api/esports/titles` to `predict.py`; bounded, reads the shared slate.
- Add fixture-driven backend tests (no network): titles derived from the slate, live/match/result
  counts, unknown titles excluded, zero external requests.

### Phase D — league hub build-out

- Rework `pages/leagues/esports.tsx` into the complete destination per "Product shape": header,
  title discovery, EWC center, Club Championship rail, non-EWC context, picks links, and the full
  loading/error/empty/stale state set. Keep the responsive 5/10 standings limit.
- Keep the existing EWC fetch logic (projection + standings) and add the titles fetch; poll the
  projection at the existing cadence; no new collectors.

### Phase E — focused tests

- `/esports`: render the board with mocked fetch; assert no `EWC 2026` module header and no
  `Club Championship` rail, while non-EWC live content still renders (live/non-EWC content not
  lost).
- `/leagues`: render the list; assert the Esports card links to `/leagues/esports`.
- `/leagues/esports`: render the hub with mocked fetch (projection, standings, titles); assert the
  complete product (header, title pills → `/esports/{slug}`, picks links, EWC center, rail) and all
  data states (loading, current, stale, unavailable, inactive/empty, error) plus the responsive
  limit (matchMedia 10 vs 5).
- GameCard: assert pending labels never render raw `TBD`/`TBA`.
- Backend: qualifiers stay excluded (existing suite), titles route (new), projection/standings
  contracts (existing suite) — all fixture-driven.

### Phase F — release gates

- Backend: run the EWC-adjacent pytest suite from the venv interpreter with cwd in `backend/`
  (fixture-driven, zero external requests). All green.
- Frontend: run Jest via the shared binary only (`/root/legendarypicks/node_modules/.bin/jest`)
  from the worktree. All green.
- `git diff --check` clean; secrets scan clean; worktree clean at the end.
- No DEV/production DB write, no managed-service restart, no deploy, no push, no tag move; the
  disposable preview directory `/root/lp-ewc-preview-BIEs6Q` is untouched (Codex rebuilds it).
- Browser verification is out of scope for this iteration by constraint (no next/browser commands in
  the worktree); the static render guarantees are covered by the Jest suite.

## Acceptance criteria

- `/esports` renders no EWC tournament-center elements — proven by test, and by the page file
  containing no EWC module code.
- Non-EWC live content is not lost on `/esports`.
- `/leagues` shows an Esports card linking to `/leagues/esports`.
- `/leagues/esports` renders the complete destination: header/nav, title discovery (pills linking to
  title desks and picks), EWC tournament center (live, today, results), Club Championship rail with
  source/`as of`/stale/unavailable honesty, non-EWC context links, and responsive desktop/mobile
  hierarchy.
- The standings API never emits a self-certified empty success and never silently converts unknown
  eligibility to `false`; the UI shows the honest unavailable state until a permitted publisher
  exists.
- EWC qualifiers stay excluded from the event focus (`c64f6df` preserved, suite green).
- No `/scores` EWC CoD card displays a raw `TBD`/`TBA` team name — backend suite and the new
  frontend guard both prove it.
- The landing page requests only the five or ten standings rows it renders; expanding mobile
  standings performs the bounded follow-up request.
- Zero new external requests; the declared per-host matrix is unchanged.
- Existing Call of Duty league pages, picks, result grouping, stream continuity, and other sports
  scoreboard cards retain their current behavior.
- The EWC APIs and CoD scoreboard reconciliation remain shared backend contracts, unchanged.

## Explicit non-goals for this iteration

- No new collector, no second esports pipeline, no rewrite of the existing esports state machine or
  stream resolver.
- No Ultimate Team, packs, marketplace, or new monetization system; no model probabilities.
- No browser-side scraping and no hard-coded standings, bracket winners, dates, or club totals.
- No DEV/production restart, deployment, database write, or tag move without separate authorization.
- No npm/npx/yarn/next/browser commands from `/root/lp-ewc-2026`; no alteration of
  `/root/legendarypicks/node_modules` or the managed `:3096`/`:8096`/tunnel services.

## Post-implementation decision record

To be appended at completion: page hierarchy, standings rail content, final standings data provider,
release-pass evidence, and candidate-vs-DEV/prod status.
