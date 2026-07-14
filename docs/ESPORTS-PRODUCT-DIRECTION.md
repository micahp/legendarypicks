# Esports Product Direction

**Date:** 2026-07-14
**Author:** Claude (with Micah), esports counterpart to Codex's `feat/leagues-hub`
recommendations. That doc designs a cross-sport stats hub and reaches esports by analogy.
This one is written *for* esports as its own product.

## The thesis

The esports product is not a board you look at. It is a game you play by **making
accountable calls and building a permanent record.** One primitive underneath everything:

> A user commits to a call. It settles against reality. The record is permanent and public.

That single ledger is, at once: the free-to-play game, the skill system, the content engine
(geoppls-native receipts generate themselves), and — once there is volume — **our own market
line**, so we stop renting someone else's odds.

Viewing the match is the ambient layer around the call. It is not the point, and "show the
moment that's changing" is a viewing feature, not a business.

## Calls are binary. Records, not probabilities.

The model for the prediction layer is the **CoD League / LoL / CS analyst desk**, not a
sportsbook. Before a match, the desk each makes a straight pick — *this team wins* — and the
broadcast tracks every analyst's season record. Fans vote too, and the fan pick and fan record
are shown next to the experts'.

That is the product:

- **Every user is an analyst with a W‑L record.** You pick a winner. It settles. Your record,
  streak, and division update. No probability, no Brier score, no math literacy required.
- **Show the house desk, the crowd, and you — each with a record.** "The desk is 34‑12. Fans are
  61% on Team A. You're 18‑5, W4." Legible accountability creates the rivalries: you vs. the
  experts, you vs. your friends, you vs. the crowd.
- **Difficulty comes from the crowd, not a model.** A correct pick is worth a base point; a
  *contrarian‑correct* pick is worth more, scaled by how few people were on it ("only 12% picked
  this — you called it, +bonus"). This rewards finding value / fading the favorite — Micah's
  buy‑low DNA — **without ever showing a probability.** The difficulty signal is crowd
  disagreement, which we own, not an odds line we rent.
- **Probabilities stay backstage.** If a model exists, it powers upset alerts and internal
  ranking, never the user-facing surface. The face of the product is picks, W‑L, and streaks.

**Phasing out Bovada falls out of this for free.** Early on, "who's the favorite" can be tagged
from a line. The moment there are enough users, the *crowd consensus* is the favorite and the
crowd split is the difficulty multiplier. We've built a no-money prediction market that is
ownable, defensible, and is itself the "you vs. the market vs. the match" content — except the
market is now ours.

## Why esports specifically (the honest version)

Not because the data is live — traditional sports are live too. The real reasons:

1. **The audience is the audience.** Crypto-native, degen, second-screen, Discord/Twitch. This
   is the geoppls-adjacent crowd, already primed for picks, packs, status, and rivalry.
2. **Broadcast culture already IS this format.** Analyst pick desks with tracked records are
   native to esports broadcasts. We're productizing a ritual fans already engage with, not
   teaching a new behavior.
3. **Roster churn is perpetual narrative.** Esports players get benched, transferred, and
   rebranded constantly. That is a live drama engine traditional in-season rosters don't have —
   and it feeds the card economy directly (below).
4. **Cross-title orgs have no traditional-sports equivalent.** FaZe, G2, Falcons field teams
   across CS2, Valorant, CoD. That is a collection structure *and* a discovery bridge that
   simply does not exist in the NFL.
5. **Streams embed.** For most tiers there is no rights lock — we can host the watch experience
   next to the game, which we cannot do for the NFL/NBA.
6. **The space is underserved.** Traditional daily-fantasy/pick'em is saturated
   (DraftKings/FanDuel). Esports pick'em + fantasy is wide open. Room to own it.

## Layer 1 — The Pick Desk (free, first)

The whole of the above, shipped alone: free binary pick'em, permanent records, you vs. the desk
vs. the crowd, contrarian-correct bonus, streaks, divisions, badges. Frictionless top of funnel,
and it *manufactures the crowd line* we'll later use to retire Bovada. This is what ships first.

## Layer 2 — Ultimate Team (the lootbox engine, done legally)

The monetization, and the answer to "are pack rips still worth it without player shares?" — yes,
if what you rip you **field** instead of **trade.**

The model is **FIFA Ultimate Team**, not Sorare. Rip packs → collect player *cards* → you can only
field players whose cards you own → your lineup scores on real match stats → climb → earn or buy
more packs. FUT prints ~$1B+/year for EA almost entirely on pack sales, and those cards are **not
cash-redeemable** — their value is squad utility + rarity + the dopamine of the rip.

This keeps the entire lootbox money machine with **zero securities exposure**, and it re-fuses
pack rips to lineups: in the shares model a pack gave you a tradable asset; here a pack gives you
a squad piece and a collectible. Same collect-and-use dopamine, no financial instrument.

**The bright line you cannot cross:** cards may carry prestige and in-game utility, but there is
**no official cash-out and no LP-run money market** for them. The instant cards trade for money,
we're back to securities and the path Micah already ruled out. Keep it FUT, not Sorare.

### The esports-native mechanics that make this ours

These are why this isn't a reskinned FUT, and they're the parts Micah lit up on:

- **Roster churn as live drama.** A card is a *player on a current team*. Benchings and transfers
  are in-app events: "your carded star just got benched." FUT fakes roster life with static
  ratings; esports has it for real, continuously.
- **Collect the org across titles.** Complete FaZe across CS2 / Valorant / CoD. A collection hook
  and the cross-title **discovery bridge** in one — the mechanic pulls a CS fan into Valorant to
  finish the set. No traditional sport can do this.
- **Card prestige = "I called it early."** Card an unknown before the crowd, they pop off, your
  card's prestige and leaderboard weight rise. The buy-low / called-it-first receipt, expressed as
  a game object instead of a security. The prediction skill and the collection economy are the
  same skill.

## Layer 0 — Cosmetics (the always-legal money floor)

Card frames, badges, animated match-cards, profile flair. Pure cosmetic, no mechanics, no legal
surface. Esports fans already spend enormously on cosmetics (see the CS2 skin economy). This can
run from day one alongside the free Pick Desk and never depends on the card economy landing.

## Scoring philosophy (the Sport.Fun lesson)

Sport.Fun's black-box Skill Rating failed because users couldn't see or control it. So:
**transparent, binary, legible.** Explicit points for explicit correct calls. Visible W‑L,
streaks, leaderboards, divisions, badges. The contrarian bonus is shown as a crowd fact ("12%
were on this"), never as a model probability. Receipts, not a mystery number.

## Legal guardrails (non-negotiable)

Pressure-tested in `ESPORTS-LEGALITY-PRESSURE-TEST.md`; the box that must stay true as this gets
built: **monetize on the way IN (packs + cosmetics), never build a way OUT.** A game that sells
random packs is a low-risk game-with-IAP; it becomes gambling or securities the moment real money
can come back out. So — cards never cash out and are never tradable or tokenized (no crypto: the
tradable-card model, Sorare, is under active UK gambling *prosecution*; the field-don't-trade model,
FUT, was cleared by the Dutch top court as part of a skill game); contest prizes are
status/cosmetics/packs, **never cash**; any *paid* contest is **peer-to-peer**, never vs. the house
(the format regulators are killing — PrizePicks fled to peer-to-peer to survive); publish pack drop
odds; age-gate spend and require parental consent under 16; geo-exclude Belgium. Not legal advice —
a gaming lawyer signs off on the final design and jurisdiction list before the first dollar.

## Build order (taste = restraint)

1. **Pick Desk** — free binary pick'em, records, you vs. desk vs. crowd, contrarian bonus.
   Ships alone. Gets users and builds the crowd line.
2. **Cosmetics store** — safe money floor, runs in parallel.
3. **Ultimate Team** — cards, packs, lineups. The heavy build and the real revenue. Only after
   there's a crowd and enough engagement to make squads *matter*; a card economy with no one to
   compete against is dead on arrival.

Do **not** build Ultimate Team first, do not show probabilities, do not reintroduce tradable
player shares, and do not let this collapse back into "polish the esports board."

## Open questions / to pressure-test before building

- **Loot box regulation** — pressure-tested (see the Legal guardrails box above and
  `ESPORTS-LEGALITY-PRESSURE-TEST.md`). Belgium hard-bans paid loot boxes; the Netherlands now
  permits FUT-style packs (EA won on appeal). Left to confirm at launch: the final jurisdiction
  list and a gaming-lawyer sign-off on the exact design.
- **Account/revenue ownership.** Inbound money runs on Micah's account per the agent-money
  policy; agents build, humans own the ledger.
- **Data rights at monetization.** GRID Open Access is non-commercial/pre-revenue; PandaScore and
  the paid tiers have commercial terms. Pick'em on public results is cheap; a card economy priced
  on live per-player stats may cross a paid tier. Cost the data before the economy depends on it.
- **Which titles first.** CS2 + Valorant + LoL have the cleanest per-player stat shape for cards
  and lineups; CoD/S&D is Micah's native scene and the pick-desk culture home. Sequence titles by
  where the pick-desk audience and the card-stat data overlap.

## What this is not

Not a probability engine. Not player shares. Not a cross-sport stats hub (that's the leagues-hub
doc). Not more board polish. It is an accountable-pick game with a FUT-style collectible economy,
native to a scene Micah is native to.
