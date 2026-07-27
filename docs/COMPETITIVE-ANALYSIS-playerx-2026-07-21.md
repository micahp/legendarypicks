# Competitive analysis — PlayerX (World Champion Fantasy, Inc.)

Status: strategy note, not a committed roadmap item. Trigger: Micah pasted PlayerX's product pitch
and flagged that Legendary Picks (LP) might be "trying to do too much" while still searching for
product-market fit, and that PlayerX looks better competitively positioned right now. This doc lays
out the comparison, the diagnosis it confirms, and the decisions made from it on 2026-07-21.

## What PlayerX is

An all-in-one fantasy esports + live-stream platform. One screen: HD stream + real-time stat
overlay (kills/deaths/assists/economy/objectives) + title-specific fantasy scoring (scoring rules
tuned to each game's actual mechanics, not football rules bent onto esports) + gamification
(avatars, theme music) + social (chat, GIFs, DMs). Explicitly non-gambling, family-friendly.
Covers VALORANT, League of Legends, CS2/CS:GO, Call of Duty. Native iOS + Android + web, synced
accounts. Infra: partnered with Verizon for 5G/cloud-backed low-latency video and real-time data
sync — a funded infrastructure advantage, not something built in-house on a bootstrap budget.

## What LP actually is today

Not one product — four, running in parallel:
1. **Traditional-sports scores/stats** — MLB/NBA/NFL/NHL/UFC via the ESPN backend.
2. **Esports fan board** — live match board, stream embeds (YouTube-default/Twitch-fallback
   resolver, team-matching, live-state detection), pick'em.
3. **Props-data business** — player prop lines + outcome tracking ("did it hit"), Bovada odds
   ingestion. The lower-risk B2B angle from the Phase 2 plan.
4. **Prediction-market trading tool** — the Plays board: curated Kalshi-adjacent conditional plays
   with entry/stop/target/R-multiple framing, plus the WC "Booth Intelligence" layer (LLM-synthesized,
   evidence-cited, phase-aware commentary episodes gated against market moves).

Four different products, four different audiences, sharing one nav bar.

## Head-to-head

| | PlayerX | Legendary Picks (pre-2026-07-21) |
|---|---|---|
| Core loop | Fantasy roster + live video + real-time scoring, one screen | No fantasy/roster mechanic anywhere |
| Vertical | Esports only (4 titles) | Traditional sports + esports + WC, all at once |
| Moat | Verizon-funded low-latency video + data-sync infra | LLM-synthesized, evidence-graded Booth Intelligence — real IP, nobody else has it |
| Audience / tone | Non-gambling, family-friendly, gamified | Plays board speaks in entry/stop/target/R — a trader's frame, not a fan's |
| Platform | Native iOS/Android + web, synced | Web only |

## The diagnosis this confirms

LP's esports board already ran the "casual esports fan engagement" experiment — heavy build-out,
~0 real traffic (per prior session notes), which is why the props-outcome-data angle got prioritized
instead. Copying PlayerX's fantasy-esports mechanic now would mean picking a fight, underfunded, in
the exact lane already tested and found not to pull. The "too much" problem is concrete: Booth
Intelligence and Plays are genuinely novel; a bolt-on fantasy layer would just be chasing PlayerX on
PlayerX's own turf, without PlayerX's infra money behind it.

**Counter-point that changes the picture:** LP is not starting from zero on PlayerX's ingredient
list. The esports stream-resolver (YouTube/Twitch, team-matched, live-state-aware) and the
ESPN-backed live-stats pipeline already exist and ship today. That's most of what "stream + live
stats overlay" needs — just not packaged as fantasy scoring. The gap to a PlayerX-shaped product is
narrower than it first looks, if the scope is narrowed to sports LP can actually stream.

## Decisions made 2026-07-21

- **Plays is dead.** "No value in its current state." Distinction worth keeping straight: Plays
  (the `/plays` curated trading board) is a separate subsystem from the WC Booth Intelligence engine
  (`/game/wc/[id]` Game Context + From the Booth). Killing Plays does not require killing Booth
  Intelligence — the episode/evidence-grounding engine is reusable as the stats/intel layer under
  either surviving product.
- **Two products going forward:**
  1. **Historical props vs. projections** — the existing Phase 2 props-outcome-data plan. Lower
     risk, closer to done, B2B-shaped.
  2. **Fantasy sports, scoped to esports / streamable sports only** — the PlayerX-shaped bet, but
     narrowed to sports LP can actually embed a stream for, rather than generic NFL/NBA fantasy.
     Reuses the existing stream-resolver + stats pipeline rather than starting cold.
- **Mobile app is a real requirement**, not deferred — "most people don't have desktops."

## Mobile / iOS — current infrastructure assessment

Current stack: Next.js web frontend (`output: 'standalone'`) + FastAPI backend serving JSON. No
native or React Native code exists anywhere in the repo today. Three paths, fastest first:

1. **Capacitor wrap of the existing Next.js app.** Ships an actual App Store binary in days/weeks,
   reuses ~100% of the current frontend, zero backend changes (already a JSON API). Risk: it's a
   WebView, not native rendering — fine for stats/cards/lists, riskier for a synced live-video +
   real-time-overlay experience (product B's core loop) unless a native video plugin is used instead
   of an iframe.
2. **React Native rebuild.** Reuses the API and business logic; the UI layer is a full rewrite (RN
   doesn't run the existing JSX/Tailwind components as-is). Weeks-to-months, better feel than a wrap.
3. **Full native Swift.** Slowest, best experience, backend untouched, everything else rebuilt.

Recommendation: Capacitor first — cheap enough to be reversible if product direction shifts again,
and it answers "does mobile distribution actually move the needle" before paying for a rebuild.
Revisit React Native/native if product B (fantasy + live video) proves out and the WebView video
experience isn't good enough.

## Open questions

- Does product B's fantasy-scoring engine need to be built per-title (like PlayerX's title-tuned
  scoring) from day one, or can a v0 launch with 1-2 titles reuse the esports board's existing data?
- Video-in-WebView feasibility for the fantasy product specifically — needs a concrete technical
  spike before committing to Capacitor for that surface, separate from the rest of the app.
- Whether products A and B share one app shell/brand or ship as separate surfaces — audience/tone
  overlap between "props data buyer" and "casual fantasy fan" is unclear.
