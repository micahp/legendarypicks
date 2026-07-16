# SPEC — Call of Duty game-detail page — 2026-07-16

Status: **spec / not yet scheduled to build** (league page `/cod` goes first). Mirrors the World Cup
game-detail intelligence (`pages/game/[league]/[gameId].tsx` + `components/Game/{WCContext,BoothFeed}.tsx`,
"The Read", discount play) for CDL. This is where the pick thesis lives per-match.

## Why (the receipt)
Same 2026-07-16 CDL Champs broadcast: the Whisper booth surfaced, in real time, the intel that repriced
Riyadh Falcons ~7%→~50% — *"they just made a roster change two weeks ago… let go of one, welcoming a
rookie… filling Pred's shoes… everybody's writing these guys off,"* then the rookie posting *"1.8,
matching Selium's damage."* A CoD game-detail page turns that into a **pre-match read + a value lean**
the user would have seen instead of missing.

## Route & data
- **Route:** `pages/game/call-of-duty/[gameId].tsx` (mirror the WC route shape). `gameId` = the match's
  `psId` (PandaScore id, already emitted on board matches).
- **Backend:** a CoD game-context endpoint mirroring the WC one (find the WC context route under
  `backend/` — do NOT modify the WC one; add a parallel CoD path). It assembles: matchup + state (from
  the slate), recent form / head-to-head / map history (PandaScore `codmw` past matches), and the
  Whisper booth reads for this match (from `prediction-market-trading/data/broadcast/<tag>_signals.jsonl`).

## Sections (mirror WC game detail)
1. **Matchup header.** Teams, logos, live/FINAL state + score, favorite/market %. Reuse the
   case-file header treatment the user liked (`CASE · <id> — <event> / FINAL` mono eyebrow) if adopted.
2. **Game context** (replaces any raw AI story): recent form (last N maps W/L), head-to-head, map
   pool / map win-rates from PandaScore `codmw` — data-grounded, labelled unambiguously.
3. **From the Booth** — the Whisper reads for this game (reuse `components/Game/BoothFeed.tsx`),
   roster-normalized, deduped. This is where "roster change / filling Pred's shoes / writing them off"
   lands as intel, not raw quotes.
4. **The Read** — synthesized intel over the raw quotes (reuse the WC synthesis path). MUST fold in
   **roster changes** as a first-class signal (the alpha): "Falcons benched Pred, rookie <name> filling
   in — market fading the change, booth says he's overperforming."
5. **Discount play** (optional; team / player / none, per `feedback_buy_only_value_discounts`): a
   market-priced-unlikely outcome the read makes more likely — e.g. "Falcons +underdog while the market
   still fades the roster change." Team odds are free from the board `favorite`; NEVER a forced pick.
   Value-discount philosophy only — no momentum-chasing.

## Roster-change intel (the thing the user actually wants — spec the source)
- A per-team "recent change" record: dropped/added players + date, surfaced on the header and The Read.
- Source: same open question as the league page Phase 2 (PandaScore roster diff vs Whisper booth vs
  curated). Booth already PROVES the signal exists in the transcript — cheapest v1 may be to extract
  roster-change mentions from the Whisper feed and confirm against PandaScore rosters. Recon before
  building; do NOT assume a source works.

## Scope guardrails
- Parallel to the WC feature — **add CoD paths, never edit the WC ones** (`WCContext.tsx`, the WC
  context endpoint, the WC route stay untouched). Reuse `BoothFeed.tsx` and the synthesis as-is if
  generic; if they're WC-hardcoded, add a CoD-parameterised path, don't fork-and-diverge silently.
- Grounding rule (per `feedback_no_assumptions_first_principles`): every stat/claim tied to a real
  source (PandaScore field or a Whisper quote); no invented numbers.
- Build only after `/cod` (the league page) lands and the featured-stream build is validated on prod.
