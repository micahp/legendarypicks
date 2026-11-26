# CANONICAL CONTEXT HANDOFF — 2026-07-21 14:38 CDT

> [!IMPORTANT]
> Read this file first after reset. It supersedes /root/legendarypicks/docs/CONTEXT-2026-07-21-HANDOFF.md, whose
> in-flight warnings are now historical. Nothing described here is still mid-edit.

## Reset status

- The requested WC chronology, player detail, PropChart recovery, title-scoped Predict, shared
  esports league page, and Plays retirement work is complete.
- Every shipped change is committed separately by concern and pushed to origin/dev.
- Repository: /root/legendarypicks
- Branch: dev
- HEAD == origin/dev == a60c257
- Annotated release tag v0.5.6 is pushed to origin and resolves to a60c257.
- There are no tracked working-tree edits. Existing untracked files belong to the user and must be
  preserved.
- Production and the trading fleet were not changed.
- There is no required in-flight task. A context reset is safe.

## Ownership and coordination

Micah explicitly split the work this way:

- **Codex:** backend, APIs, data contracts, correctness, and backend tests.
- **Claude:** frontend, UX/UI, visual/browser acceptance, design, and devops.

Keep changes logically separated and commit/tag them by feature. Do not combine unrelated audit
items into one commit. Sync before touching the other agent's area. Claude's working tmux pane has
been money:0.0; inspect only recent output and do not copy old launch commands because they may
contain credentials.

## Current development environment

Verified from the host at handoff time:

- Frontend is listening on 127.0.0.1:3096, PID 2209887.
- Backend is listening on 127.0.0.1:8096, PID 2160973.
- /root/legendarypicks/.env.local has API_PROXY_TARGET=http://localhost:8096 and is intentionally
  gitignored.
- The dev tunnel used for acceptance is
  https://entertainment-bailey-types-switches.trycloudflare.com and its Cloudflare process is
  running.
- Production remains on its existing Docker services at :3100 and :8100; do not deploy without
  Micah's explicit authorization.
- Do not stop or restart the dev services merely to begin a new session. Claude owns devops, and a
  restart needs current authorization when it is actually necessary.

## Shipped commits — one concern per commit

Newest first:

| Commit | Concern |
| --- | --- |
| a60c257 | chore(navigation): retire Plays from primary nav |
| 04b435a | feat(esports): generalize CoD league desk into a shared title surface |
| d7df094 | feat(predict): title-scoped Predict UI |
| d024ab1 | fix(players): profile states, season stats, and retry |
| 0ec468d | fix(props): PropChart zero-filter recovery |
| 7ce574f | feat(esports): add title-scoped league slate |
| bd698eb | fix(players): keep search results profile-ready |
| da19772 | feat(wc): match-minute chronology + terminal-state UI in Game Context / Booth |
| 32d512b | feat(esports): add title-scoped predict slate |
| 276460f | fix(wc): align booth receipts to match clock |

The frontend audit fixes were deliberately kept in five independent commits: 0ec468d, d024ab1,
d7df094, 04b435a, and a60c257. Preserve this separation in future backports, tags, and release notes.

## What now works

### WC Game Context and From the Booth

- Match wc/760517 resolves ESPN's terminal AET state as **Final / Complete**, not a stale second
  half, and completed matches stop polling.
- The catch-up line correctly says Spain beat Argentina 1–0 after extra time and Ferran Torres
  scored at 106'.
- Booth episode cards and expanded receipts lead with match-clock chronology, not wall-clock or
  transcript-capture timestamps.
- Exact/stated times are unmarked (75', 83'); inferred times are visibly approximate
  (~90+3', ~87'). Phase-only receipts use HT, ET HT, Pens, or FT.
- The phase-aware episode model, evidence grounding, duplicate collapse, route-history distinction,
  enrichment backfill, and fail-closed roster-name resolution are in place. Same-surname Martinez
  collisions no longer attribute a quote to the wrong player.
- The shared BoothFeed retains a legacy branch for the CoD flat-insights schema; that behavior was
  not changed.

### Player search and detail

- Search suppresses identities with no logs, props, or season statistics and ranks usable results.
- The player-profile contract includes season_stats, coverage, and data_status.
- Stats-only players no longer land on a blank profile. Loading, not-found, error, unavailable, and
  genuine retry states are explicit.
- Aleksander Barkov (/player/26034) renders NHL 2024–25 stats; Zack Wheeler (/player/2) renders
  season stats, current props, projections, and recent games.

### PropChart

- A filter combination with no matching games no longer destroys the chart UI until reload.
- Controls and the chart header stay mounted; an honest empty state and **Reset filters** remain
  available, and reset restores the plot immediately.
- Filters reset when the underlying series changes, and zero samples display an em dash rather than
  a misleading 0%.

### Predict

- /predict is title/league scoped and URL driven.
- It consumes bounded /api/esports/predict?title=... data instead of the large all-title upcoming
  payload.
- Title pills, selected-title record/history, one initial fetch, error/retry, and honest empty states
  are implemented. Live CS2 and empty CoD states were both accepted.

### Esports league surface

- /esports/[title] is the canonical shared league desk and supports eight titles through
  /api/esports/league/{slug}.
- /cod returns a 307 redirect to /esports/call-of-duty.
- The surface includes live, schedule, and results; mobile title pills scroll horizontally.
- Counts are bounded and honest, multi-day rows show dates, unknown results say **Result
  unavailable**, and rows without streamKey remain visible under **Other matches**.
- Only CoD rows link to a supported match-detail route. No fake standings or unsupported detail
  links were introduced.

### Plays decision

- Micah's product decision is that the curated Plays page has no value in its current state.
- Plays was removed from primary navigation and /plays 307-redirects to /props.
- The /api/plays backend was retained; no trading code was changed.
- LiveDiscounts remains available on Scores and /api/live/discounts remains part of the existing
  live API contract. Do not recreate or duplicate that contract.

## Verification evidence

- Focused backend suite: **36 passed in 2.28s** across:
  - backend/test_wc_context.py
  - backend/test_players_profile_api.py
  - backend/test_esports_predict_api.py
- Desktop 1440x900 and mobile 390x844 browser acceptance passed with no page/console errors and no
  horizontal overflow for the changed surfaces.
- Player search-to-profile, PropChart zero-result-to-reset, WC phase/receipt expansion, Predict title
  switching, and esports league states were exercised with real local API data.
- Redirects were verified: /cod to /esports/call-of-duty, /plays to /props.
- Browser reports and screenshots are preserved in /tmp for the life of the host:
  - /tmp/lp-audit-results.json
  - /tmp/lp-player-search-results.json
  - /tmp/lp-prop-chart-results.json
  - /tmp/lp-wc-audit-results.json
  - /tmp/lp-desktop-esports-cs2.png
  - /tmp/lp-mobile-esports-cs2.png
  - /tmp/lp-desktop-wc-loaded.png

## Product direction that should survive reset

- **Product A:** historical props versus projections, using the existing props ingestion/data
  foundation. This is the nearer-term product.
- **Product B:** fantasy sports for esports and other streamable sports. It still needs validation of
  live per-player data latency and the real-money-versus-points-only model.
- Mobile is a real requirement. The current proposal is to validate Product A distribution first
  with a Capacitor iOS wrapper before committing to a larger mobile rewrite.
- Full analysis lives in the preserved untracked documents:
  - docs/COMPETITIVE-ANALYSIS-playerx-2026-07-21.md
  - docs/PRODUCT-A-B-IOS-BUILD-PLAN-2026-07-21.md
- The next candidate investigation, not yet authorized or started, is why Product A's EV values have
  reportedly been all zero. Treat that as a new task, not unfinished work from this session.

## Known unrelated or pre-existing issues

- A full-repository TypeScript check still reports unrelated pre-existing failures: missing
  @onflow/fcl, @onflow/typedefs, and services/nbaGames, plus an existing Set-iteration target error
  in pages/scores.tsx. The files changed in this work introduced no new TypeScript errors.
- The third-party Kick embed can return 403/dynamic-module failures in a headless/datacenter browser;
  the same failure reproduces on the pre-existing esports page. Twitch embedding works.
- Claude observed a pre-existing /props slate-fetch error that was outside this work.

## Preserve these user-owned untracked files

Do not clean, delete, reset, or accidentally commit these as part of unrelated work:

- .context/retros/2026-07-17-1.json
- .hermes/
- TASK-prop-repair.md
- backend/be8095.log
- backend/be8096.log
- backend/data/esports_team_logos.json
- backend/data/esports_yt_liveness.json
- backend/scripts/verify_yt_pick.py
- cf3095.log
- docs/COMPETITIVE-ANALYSIS-playerx-2026-07-21.md
- docs/PRODUCT-A-B-IOS-BUILD-PLAN-2026-07-21.md
- docs/TASK-esports-local-day-endtime.md
- docs/TASK-props-ingest-start-time.md
- docs/TASK-props-market-first-board.md
- docs/TASK-props-tabs-v0.5.0.md
- docs/TASK-ufc-predict-tab.md
- docs/TASK-wc-logs-ufc-chart-state.md
- next3095.log
- next3096.log
- public/icon-preview.html
- public/props-layout-comparison.html

## Safe start for the next session

1. Read this file, then cd /root/legendarypicks.
2. Confirm git status --short --branch and git rev-parse HEAD; expected head is a60c257 on dev,
   synchronized with origin/dev.
3. Preserve all untracked files above and avoid broad cleanup/reset commands.
4. Check the already-running :3096 and :8096 services before considering a restart.
5. Keep backend/API work with Codex and frontend/UX/devops work with Claude, with separate commits
   for separate audit items.
6. Wait for Micah to choose the next product task. There is no mandatory recovery or unfinished
   implementation from this session.
