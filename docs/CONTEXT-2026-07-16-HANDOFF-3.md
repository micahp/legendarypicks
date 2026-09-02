# CONTEXT HANDOFF — 2026-07-16 (part 3): CoD pages complete + broadcast-first live board

Read first on a fresh context. This supersedes `CONTEXT-2026-07-16-HANDOFF-2.md` for current state;
part 2 remains useful history for the original stable-stream data problem and the v0.4.0 production
release.

## CURRENT OUTCOME

- The stable broadcast data wall is fixed. The backend emits channel-level `streamKey` plus
  PandaScore `eventId`, including finished matches recovered by verified title/team-pair identity.
- `/cod` Phase 1 is implemented with real CoD data. The CoD game-detail page, grounded context,
  scoreboard links, and Leagues card are also implemented.
- The shared `/esports` stream lifecycle now handles cold reload, `FINAL + Up Next`, scheduled-time
  handoff to `Starting soon`, and provider-live transition without inventing a live score/state.
- The newest UNCOMMITTED change fixes the remaining architectural mistake: continuity is now
  projected for **every on-air broadcast**, not only the one featured hero.

## GIT / WORKTREE — AUTHORITATIVE AT HANDOFF

- Repo: `/root/legendarypicks`, branch `dev`.
- HEAD: `12f3202`; `dev` is **ahead of `origin/dev` by 2**. Nothing from this Codex work was pushed.
- Checkpoint commits created before the newest algorithm change, per user instruction:
  - `9bc58e2 esports: stabilize continuous broadcast identity`
  - `12f3202 cod: add league and grounded match detail pages`
- The only tracked uncommitted file is `pages/esports.tsx` (broadcast-first projection fix).
- Deliberately excluded/unrelated untracked artifacts remain. Do not mass-add them:
  `.hermes/`, `TASK-prop-repair.md`, backend/frontend/tunnel logs, generated esports logo/liveness
  JSON, `backend/scripts/verify_yt_pick.py`, Jul-9 context/handoff docs, and `public/icon-preview.html`.
- Do not commit or push the newest `pages/esports.tsx` change unless the user asks/reviews it.

## RUNNING DEVELOPMENT STATE

- Frontend: Next development server on `127.0.0.1:3097` with hot reload.
- Backend: uvicorn development backend on `127.0.0.1:8096` with reload and dev DB.
- Tunnel verified HTTP 200 at:
  `https://directed-alot-deliver-rows.trycloudflare.com/esports`
- `/esports` and `/cod` both return HTTP 200 through the development server.
- **No production build was run.** Production was not edited, rebuilt, redeployed, committed to, or
  pushed during this work.
- The earlier CDL Whisper listener process is no longer running (previous PID `2062602` is gone).
  Do not claim it is live without relaunching/verifying it.

## WHAT IS IN THE TWO CHECKPOINT COMMITS

### `9bc58e2` — stable broadcast identity + lifecycle baseline

- `backend/routers/esports/pandascore.py`: `_stable_stream_key()` derives a channel-level identity
  (`twitch:`, `kick:`, `ytc:`), rather than a rotating per-game YouTube video ID.
- `backend/routers/esports/slate.py`: attaches `streamKey` and PandaScore `serie.id` as `eventId` to
  slate rows; finished rows can recover the metadata through shared title/team-pair identity.
- `pages/esports.tsx`: consumes stable IDs, preserves the stream through game/desk transitions,
  supports cold-load recovery, removes the Up Next divider, and shows `Starting soon` after a
  scheduled handoff while PandaScore remains scheduled.
- Multiple channels under one event stay separate because the broadcast identity is
  `streamKey + eventId`.

### `12f3202` — CoD league/detail integration

- New `pages/cod.tsx`: real CoD-only league view using shared `LiveNow`/`LiveCard`; stream running
  order, Results, conditional derived standings, `/predict?title=cod` CTA.
- New `pages/game/call-of-duty/[gameId].tsx`: grounded match-detail page.
- New `backend/cod_context.py` and `/api/cod/{game_id}/context` route:
  - recent five series / last ten maps per team;
  - map progress and head-to-head;
  - timestamp-matched booth insights;
  - market snapshot;
  - no discount unless real price history exists;
  - no invented roster facts or ungrounded ASR player attribution.
- BreakingPoint scoreboard IDs remain authoritative for score cards. A separate PandaScore
  `detail_game_id` is attached only after shared opponent+time identity matching.
- CoD scoreboard cards route to the detail page when that verified ID exists and fall back to `/cod`
  otherwise. All four real mappings were verified.
- `/leagues` includes a Call of Duty League card linking to `/cod`.
- `components/Game/BoothFeed.tsx` was parameterized for a context league while World Cup defaults
  were preserved.
- `docs/CODEX-QUESTIONS-cod-league.md` records the exact Phase 1 answers and verification.

## NEW UNCOMMITTED BROADCAST-FIRST FIX

File: `pages/esports.tsx` only. The full 1,158-line file was read before editing.

### The bug

The prior code correctly built every `(streamKey, eventId)` group into `onAir`, but converted only
one group into `featStream`. The secondary grid was rebuilt from raw PandaScore `live` matches.
Therefore a lower-ranked stream such as R6 could be confirmed online with a scheduled next game and
still remain invisible until PandaScore marked that match live. Prominence tiers were not the
continuity mechanism; they merely exposed this single-hero projection bug.

### The fix

- `buildBroadcastViews()` creates an independent view for every proven broadcast.
- Each view is one of:
  - `live`: provider says the match is live;
  - `gap`: previous `Final` remains in place with `Up Next`;
  - `starting`: confirmed broadcast is online and the next match is pregame/overdue while the
    provider still says scheduled.
- All views render. Prominence only orders them and chooses the default hero.
- Promoting a secondary broadcast moves it to the hero without removing or duplicating the others.
- `LiveCard` now accepts the broadcast's current watch source separately from the displayed match.
  A finished match can therefore display while borrowing the next fixture's confirmed stream.
- React keys use stable broadcast identity, so the same iframe node survives
  `Final + Up Next -> Starting soon -> Live` when its source has not changed.
- Secondary gap cards also show `Up Next`; continuity is no longer hero-only.
- Provider-live matches without stable broadcast identity still render as standalone raw cards.
- A backend fallback like `streamKey="event:505"` is **not** treated as a proven stream. `eventId`
  alone cannot distinguish two parallel YouTube-only arenas, so those matches are not glued together.
- Generic visibility guardrails currently encoded:
  - first-match pregame: confirmed source within 90 minutes;
  - scheduled provider lag: up to 6 hours;
  - previous/next sequence: scheduled starts within 12 hours.
  These affect only whether an online broadcast gets a card; they never invent live status or scores.

### Exact behavior/limitation

- If a match actually begins early but PandaScore still says scheduled, stream liveness alone cannot
  prove gameplay has begun. The broadcast is visible as pregame/`Starting soon` (or prior
  `Final + Up Next`) until PandaScore marks it live. This is intentionally honest.
- A stable real channel key plus event ID is required for cross-game continuity. Unknown identities
  fail open only for raw provider-live match display, never for guessed grouping.

## VERIFICATION — NO PRODUCTION BUILD

Controlled Playwright slate (`/tmp/verify_broadcast_projection.js`):

- Six independent cards rendered: CoD hero gap, secondary R6 `Starting soon`, first-match Valorant
  pregame, two parallel streams in one event, and one unkeyed provider-live fallback.
- Event-only stream fallback did not become a continuity card.
- `Final + Up Next -> Starting soon -> Live` occurred on schedule/provider updates.
- The exact same iframe DOM node survived both transitions.
- Promoting R6 kept all six broadcasts and returned CoD to the grid.
- No page errors.

Real API + browser (`/tmp/verify_broadcast_projection_real.js`):

- At verification time, provider-live CoD, R6, and NACL broadcasts all appeared; none were missing.
- Confirmed-online scheduled Valorant and two parallel CS2 arena broadcasts also appeared as
  independent `Starting soon` cards.
- Exactly one hero, six total broadcast cards, zero page errors, zero failed local responses.
- Mobile viewport: `scrollWidth=390`, `clientWidth=390` (no overflow).
- Development routes `/esports` and `/cod`: HTTP 200.
- `git diff --check`: clean.
- Repository-wide `tsc` still has unrelated longstanding missing Flow dependencies/errors, but
  `pages/esports.tsx` itself produces no TypeScript diagnostics after replacing Map iterator spreads
  with `Array.from`.

## PRODUCT DIRECTION / DO NOT LOSE THIS

- Continuous-stream behavior is generic across the mixed esports hub. Do not hardcode CDL, R6, or
  prominence tiers into lifecycle eligibility. Tiers/order only decide presentation.
- Intel/discount plays are not necessarily player props and are not forced every game. A play can be
  a match winner (e.g. Argentina while down), team outcome, player outcome, or no play. The point is
  a temporary market discount plus new grounded information that changes the read—not mechanically
  buying every bottom or selling every top.
- Roster/news intel should be conceived like Underdog's league/team news feed and notifications.
  Primary sources should be official/team/social accounts and structured roster pages. Booth audio
  provides live game context; it is not the canonical source for roster-change news.
- The Riyadh ~7% discount was transient: after the upset/context became known, the same tournament
  would not offer that price again. Product value comes from combining context, new intel, and the
  price at that moment.
- No roster-news feed was implemented; item 2 stopped after source reconnaissance.

## SAFE NEXT ACTIONS

1. Have the user review the live tunnel behavior and the uncommitted `pages/esports.tsx` diff.
2. If explicitly approved, commit that single tracked file as its own broadcast-first change.
3. Push only if explicitly requested; branch is currently ahead by two local commits.
4. Do not run a production build; continue verifying through the development server/tunnel.
5. Preserve all unrelated untracked files and avoid branch checkout/reset under running Next dev.

