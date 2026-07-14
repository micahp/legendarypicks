# Spec — Esports Pick Desk (MVP)

**Date:** 2026-07-14
**Part of:** `ESPORTS-PRODUCT-DIRECTION.md` (Layer 1, the free Pick Desk)
**Legal posture:** free, no consideration, no prizes → not gambling. The lowest-risk layer, and it
also manufactures our own crowd line. See `ESPORTS-LEGALITY-PRESSURE-TEST.md`.

## What it is

Before an esports match starts, a user makes a **binary call** — which team wins. When the match
finishes, the call settles against the authoritative winner. The user accumulates a **permanent
public record** (W‑L, streak), and sees their record against the **crowd** (and, later, a house
"desk"). No probabilities shown. No money. This is the CoD-League analyst desk as a product.

## Why this is cheap to build: the settlement engine already exists

The esports slate already produces exactly what a pick needs to settle:

- a stable match identity — `_key = "{title}::{teamA}::{teamB}::{startTime}"`
  (`routers/esports/slate.py`),
- an authoritative **winner** and **finishedAt** in the durable results store
  (`backend/data/esports_results.json`), derived honestly (GRID won-flag / PandaScore winner_id /
  Kalshi settle — never from a partial score),
- a lock signal — the match's `startTime`,
- an "ended, no result" state — `ENDED_UNKNOWN` / `resultUnknown` → the case where a pick **voids**
  instead of losing.

So the Pick Desk is mostly a thin ledger on top of infrastructure that already exists. No new data
feed.

## Data model

```
Pick
  id
  userId              -- see Identity, below
  matchKey            -- the slate _key (title::teamA::teamB::startTime)
  pickedTeam          -- "A" | "B", captured with the team name+logo snapshot at pick time
  createdAt
  lockAt              -- = match startTime (immutable once set)
  settledAt           -- null until the match finishes
  result              -- null | "win" | "loss" | "void"   (void = ENDED_UNKNOWN / match canceled)
  points              -- null until settled; base + contrarian bonus (below)
  crowdShareAtLock    -- % of picks on pickedTeam at lock time (frozen for scoring + receipts)

CrowdTally  (per matchKey, maintained incrementally)
  matchKey
  countA, countB      -- current pick counts per side

UserRecord  (derived / materialized)
  userId
  wins, losses, voids
  currentStreak       -- signed: +4 = W4, -2 = L2
  bestStreak
  points              -- season total
```

Records are **derived** from settled Picks; keep a materialized `UserRecord` for leaderboard speed,
rebuildable from the Pick ledger (the ledger is the source of truth — same discipline as the
results store).

## Rules

- **One open pick per match per user.** Changeable freely **until `lockAt`** (match start), then
  frozen.
- **Lock at start.** No picks accepted once `now >= lockAt`. (Board already knows start times.)
- **Settle on finish.** When the match reaches `FINISHED` with a known winner, every pick on that
  `matchKey` settles win/loss. `ENDED_UNKNOWN` / canceled → `void` (doesn't touch W‑L or streak).
- **Scoring — contrarian, never a probability.** `points = 1 + k * (1 - crowdShareAtLock)`. Calling
  the winner when few agreed pays more; calling a lock pays the base point. The difficulty signal is
  **crowd disagreement**, surfaced as a fact ("only 18% called this"), never as a model %.
  Start `k = 1` and tune.
- **Crowd line.** `crowdShareAtLock` frozen per pick; the live `CrowdTally` drives the split bar and
  is the seed of our own line (the thing that eventually retires Bovada).

## API (additive, under the existing esports router)

```
POST   /api/esports/picks            { matchKey, team }      -> upsert my pick (rejected if locked)
DELETE /api/esports/picks/:matchKey                          -> withdraw before lock
GET    /api/esports/picks/me         [?state=open|settled]   -> my picks + my record
GET    /api/esports/matches/:matchKey/crowd                  -> { countA, countB, shareA }
GET    /api/esports/leaderboard      [?window=season|week]   -> ranked records
```

Settlement runs off the existing slate rebuild / monitor tick: when a match transitions to
`FINISHED`, settle its open picks in the same pass that writes the results store. No new scheduler.

## Identity (the one real dependency)

The ledger needs a stable `userId`. LP is a Flow/Next dapp, so wallet identity exists — but requiring
a wallet connect before a first pick is heavy friction for the free top-of-funnel.

**Recommendation:** allow an **anonymous device-scoped record** to make the first call in one tap
(store a signed device id), and let the user **claim/bind** it to a real account (wallet or email)
to make the record portable and leaderboard-eligible. This keeps the "make your first call in one
tap" empty-state promise while giving a path to durable identity. Flag for decision — this is the
only piece not already sitting in the backend.

## UI surfaces (extend the existing design language; see the UI/UX analysis)

1. **Call card** — the match card gains three states: **open** ("Call it" → team buttons), **locked**
   (your side marked, crowd split bar, live), **settled** (`emerald` = you called it / `punch` =
   missed, points shown). Build once; render on the esports board first, then the scores rail.
2. **Crowd split bar** — a two-tone `zinc` fill with your side marked and the % as `tabular-nums`.
   The one new repeated primitive.
3. **The record desk** (the signature) — a persistent broadcast-style strip: **you · the crowd**
   (house desk added later), each with W‑L + streak. Lives in the header as a compact chip and in
   full on the desk page.
4. **The desk page** — fill `contests.tsx` (don't add a route): my open calls, my settled history
   (the receipts), the leaderboard. `predict.tsx`'s model output moves backstage.
5. **Copy** — "Call it" / "Call {Team}" → "You called it" / "Missed"; record as "18–5 · W4";
   difficulty as "only 18% called this." Empty states: "Make your call" / "Make your first call."

## Scope

**In:** free binary match-winner picks; lock at start; settle from the existing winner; per-match
crowd tally + split bar; contrarian scoring; per-user record + streak; leaderboard; the call-card
states + record desk.

**Out (later layers):** packs, cards, lineups, cosmetics, divisions/badges, any money, any prize,
the house "desk" personas, upset-alert model surfacing. All deferred; none blocks the MVP.

## Build order

1. Ledger + settlement wired into the slate `FINISHED` transition (reuse `matchKey`, winner, void).
2. `POST/GET picks` + crowd tally + `GET crowd`.
3. Call-card states on the esports board (open/locked/settled) + split bar.
4. Record desk (header chip + `contests.tsx` page) + leaderboard.
5. Anonymous device identity + claim-to-account.

## Open decisions

- **Identity:** anonymous-device-then-claim (recommended) vs. wallet-required vs. email. One call
  needed before build.
- **`predict.tsx`:** confirm it moves backstage (model informs, doesn't front-door) rather than
  running as a second prediction surface.
- **Void handling on streaks:** confirm a `void` leaves the streak untouched (recommended) vs.
  resets it.
- **Scoring constant `k`** and whether week vs. season is the primary leaderboard window.
