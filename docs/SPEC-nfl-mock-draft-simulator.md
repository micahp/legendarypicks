# SPEC — NFL Mock Draft Simulator

Status: spec only, not built. Written 2026-07-22.

**Update 2026-07-22**: reframed by `SPEC-nfl-product-direction.md` — this is real and still
worth building, but it's no longer the headline NFL feature. The sit/start engine (same
computation as props, near-free once EV/CLV is fixed) and the waiver-wire feed rank higher on
moat-adjacency; this is scoped as an August-relevant feature, not the retention driver. See that
doc for the full reasoning.

## Problem

The Draft Room (`components/Leagues/NflDraftRoom.tsx`) is a cheat-sheet: rank/watch/fade
players against last season's per-game production, for a draft happening somewhere else
(ESPN/Yahoo/Sleeper/Underdog). It's a reference page — opened once while you draft
elsewhere, not something anyone returns to. That's the gap: during the NFL dead period we
want something people come back to repeatedly, not a one-time lookup.

## Scope decision (2026-07-22)

Micah chose "leave Draft Room as a cheat-sheet for now" when asked how far to take it —
this spec exists so that decision can be revisited deliberately later, not so it gets
built immediately. Treat this as ready-to-build-when-asked, not greenlit.

## What it is

A real snake draft against bot opponents: you get an actual draft experience (pick clock,
turn order, roster construction, live board) instead of a static ranked list. Single
player vs. bots for v1 — no real-time multiplayer (that's a materially bigger system:
matchmaking/lobbies/websockets/reconnect-handling — flagged as a stretch goal, not v1).

## Core mechanics

- **Format**: standard snake draft (order reverses each round: 1→12, 12→1, 1→12, ...).
  League size configurable (8/10/12/14 teams), default 12.
- **Roster shape**: standard PPR — QB, RB, RB, WR, WR, TE, FLEX, BENCH×6 (open question:
  confirm exact slot counts before building; the existing draft-board data is PPR-scored
  via `fantasy_ppr_g`, so PPR is the natural default, not standard scoring).
- **Rounds**: roster-size-driven (e.g. 12 teams × 15 rounds = 180 picks for a
  9-starter/6-bench roster).
- **Pick clock**: a visible countdown (e.g. 60s) per pick; auto-picks the bot's (or an
  idle human's) best-available player by rank on timeout — this is what makes it feel
  live rather than a form to fill out.
- **Bot drafting logic**: NOT a deterministic best-player-available sort — that produces
  the identical draft every time, which kills replay value. Bots draft from
  `fantasy_ppr_g` rank plus:
  - Positional need weighting (a bot won't draft a 4th RB before filling its starting
    WR slots without good reason).
  - Injected ADP-style noise (small randomized rank jitter, ±3-5 spots) so bots make
    slightly-suboptimal-but-plausible picks, matching real draft unpredictability.
  - A run-based bump: after 2+ same-position picks in a row, other bots' interest in
    that position ticks up slightly (mimics real "positional runs").
- **Draft board UI**: three panes — available players (filterable/sortable, same
  columns as today's Draft Room table), your roster (filling in live), and a pick
  history feed (who took whom, when). On-the-clock indicator makes it feel live.

## Data this reuses (already built, zero new pipeline)

- `/api/nfl/draft-board` — the exact same ranked player pool (`fantasy_ppr_g`, position,
  team, team_changed) that powers today's cheat-sheet. No new ingestion needed for the
  player pool itself.
- Bot AI needs no external data — it's a deterministic function over the same ranked list
  plus randomness, computed client-side or server-side per pick.

## What's genuinely new

- Draft **state machine**: whose turn, which players are gone, pick clock, round/pick
  counters. This is the actual engine — doesn't exist anywhere in the codebase today.
- **Persistence decision** (open question, pick one):
  - *Session-only* (localStorage): simplest, a draft is lost on device/browser change,
    no sharing. Cheapest v1.
  - *Server-persisted*: a `nfl_mock_drafts` table (draft config + picks log), gives a
    shareable results link ("here's my 2026 mock draft") and resumability. Bigger lift,
    but the shareable-link angle is probably the actual retention driver — a cheat-sheet
    nobody shares, but people DO share/argue about mock draft results.
- **Results/grades view**: post-draft summary — your roster by position, maybe a naive
  "grade" (e.g. average pick-value vs. rank drafted) for a shareable end state.

## Effort tiers

1. **MVP**: single format (12-team PPR snake), client-side state only, no persistence,
   no sharing. Smallest real version of "a thing to do," reuses 100% of existing data.
2. **+ Persistence & sharing**: server-side draft record + shareable results link. This
   is likely the actual value-add over the MVP — a private client-only draft has the
   same "opened once, never again" problem as the current cheat-sheet.
3. **+ Real-time multiplayer**: out of scope for this spec; a genuinely different system
   (lobbies, websockets, real opponents) — only worth it if single-player mock drafts
   prove people actually use this.

## Open questions before building

- Roster slot counts (exact bench size, superflex or not).
- League size default and whether it's configurable at all for v1, or fixed at one size.
- Persistence tier to build (see above) — this is the highest-leverage decision in the
  whole spec, since it determines whether this is a one-time novelty or something people
  come back to and share.
