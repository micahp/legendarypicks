# SPEC — "Make your pick" on the esports board + inline pick section on the live match (2026-07-15)

Status: **spec / not started.**

## Goal
Let users pick a winner **directly from the esports board** (`/esports`) instead of only on the
separate Pick Desk (`/predict`). Specifically:
1. A **"Make your pick"** affordance on schedule cards.
2. The **pick section from `/predict`** embedded on the **live match card that shows the stream**
   (`LiveCard` in `pages/esports.tsx`) — pick / your-pick / crowd, right under the broadcast.

## Why this is cheap (the key insight)
`/esports` and `/predict` **already consume the same endpoint** — `/api/esports/upcoming`
(`pages/esports.tsx:918` and `pages/predict.tsx:59`). The predict `Match` type reads `matchKey`
off that payload; the board's `UpMatch` type simply doesn't declare it. So:
- The board's matches and the pick store are keyed by the **same `matchKey`**.
- A pick made on the board is the **same pick + same record** as the Pick Desk. One store, one
  record, no reconciliation.
- **No new backend.** Reuse the existing endpoints:
  - `POST /api/esports/picks` `{matchKey, side, lockAt}` (predict `call()`, `pages/predict.tsx:112`)
  - `GET /api/esports/picks/me` (X-Device-Id header) → `{picks, record}`
  - crowd consensus endpoint already used by predict.

## Current state
- **Predict** (`pages/predict.tsx`) owns the full pick UX: pick buttons per side → `call(m, side)`;
  loads my picks + record via `/api/esports/picks/me`; shows crowd share; shows result once settled.
- **Board** (`pages/esports.tsx`) renders `LiveCard` (~L660) with the stream iframe ("watch here ▾"),
  `SeriesStrip`, model/market edge — but **no pick UI**, and `UpMatch` omits `matchKey`.

## Design
1. **Extract a reusable `<MatchPick>` component** from the predict page's pick block.
   Props: `{ matchKey, teamA, teamB, logoA?, logoB?, startTime, existingPick, crowd, onPick }`.
   Renders: two side buttons (or your locked pick + result), crowd share, lock state. It must be
   presentational + call an injected `onPick(side)` so both pages share it.
2. **Lift shared picks state** into a small hook `useEsportsPicks()` (my picks map by matchKey,
   record, crowd, `submitPick(matchKey, side, lockAt)`, `getDeviceId()`), used by BOTH `/predict`
   and `/esports`. Predict is refactored onto it (no behavior change); the board consumes it too.
3. **Board integration:**
   - Add `matchKey` to `UpMatch` (it's already in the payload).
   - **Featured / live `LiveCard`:** render `<MatchPick>` directly under the stream.
   - **Every schedule card:** a compact **"Make your pick"** button that expands `<MatchPick>` inline.
4. **Contrarian/crowd** framing per `docs/ESPORTS-PRODUCT-DIRECTION.md` (you-vs-crowd, contrarian
   bonus) — reuse the crowd share already shown on predict.

## Lock semantics (important open question)
Picks lock at `lockAt = startTime`. The live match **showing the stream is already started**, so it
is typically **already locked** — you can't newly pick it. So on the live card `<MatchPick>` should
show **your existing pick + crowd + (live) result-in-progress**, and only render active pick buttons
for matches **not yet started**. Confirm desired behavior:
- (a) Live match = display-only (show pick/crowd, no buttons) — *recommended, matches lock rules.*
- (b) Allow late picks on live matches (needs a lock-policy change on the backend) — bigger, changes
  the accountability model. Defer.

## Phasing
- **Phase 1:** extract `<MatchPick>` + `useEsportsPicks()`; refactor `/predict` onto them (regression:
  predict unchanged); render `<MatchPick>` on the **featured live `LiveCard`** (display-only if locked).
- **Phase 2:** "Make your pick" button on **every** schedule card (upcoming matches → active buttons).

## Scope guardrails
- **No new backend** — reuse `/api/esports/picks*`. Do not duplicate pick state; single source via the
  hook. Keep `/predict` behavior identical after the refactor.
- Don't autoplay/duplicate streams; `<MatchPick>` is independent of the stream player.

## Open decisions (need the user)
1. Lock semantics on the live match: **(a) display-only** (recommended) vs (b) allow late picks.
2. Placement on `LiveCard`: under the stream (recommended) vs a side rail on wide screens.
3. Phase 1 = featured card only, or ship the per-card button in the same pass?
