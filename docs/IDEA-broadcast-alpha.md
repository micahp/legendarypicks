# IDEA — Broadcast Alpha (commentator front-running)

**Date:** 2026-07-07, during ARG–EGY extra time. **Status:** parked concept — written down
because the idea is right even though full video access isn't currently practical.

## The insight (Micah, verbatim intent)

> "If we were able to watch the game live and hear the audio, we would be unstoppable.
> The commentators say things you can front-run once they say it, because they're not lying."

Case in point, live as this was written: commentators — ex-teammates — describing *the look
in Messi's eyes* after going down 0–2: "something clicked in him, and you could see it."
Minutes later: two goals, 2–2. That observation was **true, public, expert, and unpriced** —
no data feed carries it, no model reads it, and the market took minutes to reflect it.

## Why commentator speech is alpha

1. **They're not lying.** Commentators are non-strategic truth-tellers — zero incentive to
   deceive, unlike literally every other speaker near a market.
2. **They carry private priors.** Ex-players/teammates recognize body language, effort level,
   a keeper's nerves, a tactical shift — genuine expert testimony streaming in real time.
3. **The soft-signal class is structurally unpriced.** This is NOT about beating goal-latency
   (courtsiders and fast feeds win that race; broadcast delay ~20–60s loses it by design).
   It's about information that **no data feed ever contains** — "something clicked," "he's
   limping," "they've gone to five at the back," "the keeper doesn't want the ball" — which
   prices in over MINUTES, the same window our widget classes and swing legs operate in.
4. It slots directly into the crash-cycle frame: commentator soft signals are the earliest
   detector of the **reversal phase** — before the shots come, before the price moves.

## The pipeline (when/where access exists)

stream audio → streaming ASR (local Whisper, ~seconds behind speech) → LLM extraction pass
over the rolling transcript ("emit tradeable claims: injury, demeanor, tactical change,
momentum language; tag team/player, confidence, timestamp") → signal bus → (a) alert to the
trader, (b) reversal-phase input to the momentum engine's live level, (c) receipt-logged like
every other signal class so the alpha claim gets validated, not assumed.

Vision layer (the "we can see it too" part — body language from video) is a later, heavier
rung; audio alone captures most of it because the commentators narrate what they see.

## Access tiers (the honest constraint map)

| Tier | Source | Status |
|---|---|---|
| **Feasible TODAY** | **Esports official streams (Twitch/YouTube)** — free, public, we already embed them in LP; EWC casters narrate momentum/tilt constantly | The wedge. Same tournament we're already trading |
| **Feasible TODAY** | **Radio play-by-play** — LP already wired free WC audio (iHeart direct stream); NBA team radio planned (`sports-audio-broadcasts.md`) | Legal audio, already flowing through our own product |
| Hard | TV soccer/NBA/MLB video | Rights-locked, streams deliberately hard to source — why this doc is parked rather than spec'd |
| Line not to cross | Restreaming/redistributing broadcast content | Never. Consuming a broadcast and trading on it personally is what every human trader does; the pipeline is a listening tool, not a distribution product |

## Reality checks (so future-us doesn't overbuild)

- Latency: broadcast is BEHIND the venue. Hard events (goals) are already priced when the
  commentator reacts. Only the soft-signal class is front-runnable. Scope extraction to it.
- ASR+LLM per live game costs real compute; start with ONE stream (an EWC esports final or a
  WC radio feed), measure whether extracted claims lead price by minutes, receipts-first.
- The validation harness is the same as everything else: log claim → timestamp → subsequent
  price path → did the claim lead the move? No R-positive receipts, no buildout.

## Relation to existing docs
Crash-cycle frame + live level: `SPEC-momentum-engine.md`. Swing exits: trading repo
`NOTE-2026-07-07-live-soccer-swing-regime.md`. Free audio already shipped: scoreboard WC
audio (iHeart), `docs/sports-audio-broadcasts.md`. Esports stream embedding: the Jul-3
stream pipeline work.
