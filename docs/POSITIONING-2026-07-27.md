# Product positioning — 2026-07-27

**Status:** strategy note, not a committed roadmap item. Nothing here changes v0.7.0 scope or
the ~Aug 22 deadline. See the closing section for the one decision it *does* ask for.

**Scope of what this supersedes:** the one-liner in `ESPORTS-POSITIONING-2026-07-27.md`
("makes internet-native sports feel as trackable as an NBA game on ESPN") is **revised** below —
its research finding about linear TV stands untouched, and so does its ruling that esports is
Layer 2. This note also **revises the build order** carried in `ESPORTS-PRODUCT-DIRECTION.md`
(pick desk → cosmetics → Ultimate Team last). It does not overturn
`COMPETITIVE-ANALYSIS-playerx-2026-07-21.md` or `ESPORTS-LEGALITY-PRESSURE-TEST.md`; it argues
they agree with each other more than has been noticed.

**Trigger:** the NFL All Day research landed on *"we are buying the mechanic, not the
audience,"* and Micah asked for the position to be re-examined with three things in frame at
once: sport.fun, PlayerX, and the legality pressure-test. Mid-discussion he added the sentence
that reorganised the whole note: **"we are an aggregator at the end of the day."**

---

## 1. The correction: it was never the mechanic

"Buying the mechanic, not the audience" is the right instinct with the wrong noun, and the
All Day build is what proves it.

A mechanic is not a moat. *Paste an identifier → get your roster → build a lineup* is a UI
pattern ESPN, Sleeper and Yahoo all ship. Buy that, with All Day as the audience, and you have
bought something you cannot test — the exact failure the sport.fun corpus names, where
direction becomes taste for want of measurement.

What the build actually surfaced is that **the mechanic was trivial and the resolver was not.**
Resolving a foreign identifier space onto our canonical player spine meant handling:

- retired players who still hold moments (`active=0` cannot be excluded),
- generational suffixes and punctuation (`Harrison Jr.`, `St-Juste`, `St. Brown`),
- a smaller position vocabulary (`DB` → our `CB`/`S`/`FS`/`SS`),
- names colliding across eras (two Josh Allens, resolved by position),
- **Hybrid Custody**: the address the user actually sees frequently owns nothing, with the
  moments in a linked child account.

That lands at **~94%**, and none of it is All Day-specific. A Sleeper league, an ESPN league,
a pasted screenshot — same problem, same spine.

> **We are buying the resolver, not the mechanic.** A mechanic is copied in a weekend. A
> resolver compounds with every source added to it.

## 2. "Aggregator" — right about the architecture, dangerous as a strategy

Aggregation is a fair description of what the last three months built: ESPN, nflverse,
PandaScore, GRID, Bovada, YouTube/Twitch, Kalshi, and now Flow, behind one identity.

The caution is that **Aggregation Theory is a demand-side theory.** Aggregators win by owning
the user relationship and commoditising supply. LP has excellent supply and effectively no
demand. An aggregator with no users is not an aggregator; it is an ETL pipeline with a website.

So the sentence is true about the half already won, and silent about the half that is missing.

**The version that holds:** everyone aggregates *content* — scores, odds, streams. ESPN,
theScore and Sofascore all do it, better funded. That lane is commoditised and we lose it.
Nobody aggregates *identity*: the same player across an ESPN id, a gsis id, an nflverse key, a
PandaScore id, a Bovada string, and an All Day play's metadata.

> **LP is an identity aggregator, not a content aggregator.**

This is the same conclusion as §1 reached from the supply side rather than the product side,
and it is what the sport.fun narrative's "common spine" diagram already drew for us.

## 3. What the three competitors actually hold

| | owns | starving on |
|---|---|---|
| **sport.fun** | demand — users, funding, a live market | supply: data depth and explanation (its own Season 2 addendum says so) |
| **PlayerX** | distribution — native iOS/Android, Verizon-funded low-latency video | the record; no verifiable outcome ledger |
| **LP** | supply — `player_game_logs` (111k rows, 4 leagues), prop-outcome history, the identity spine | demand: effectively nobody can open it |

The strategic instruction falls straight out of the table:

> **Every move should convert supply into demand, or sell supply to someone who already has
> demand.**

That is the Phase 2 prop-outcome API thesis restated, and it is why "aggregator" is right but
incomplete. It also reframes sport.fun: its scarcity is our abundance, so it is a plausible
**buyer**, not only a rival.

## 4. Everyone else is fighting over the asset layer, and losing

| | fought over | outcome |
|---|---|---|
| sport.fun | the market layer | a year and five successive mechanisms on market health; a shadow-mode agent that still does not hold the wallet |
| PlayerX | the video layer | moat is Verizon's money, not truth |
| NFL All Day | the asset layer | **primary issuance halted 2026-05-13 — and the moments still resolve** |

All Day is the cleanest evidence available: **the asset died and the identity join survived.**
We read a wallet on a network whose mint has been switched off, and still got players, positions
and gsis ids out of it.

The legality pressure-test says the same thing in legal language — *money in is fine, money out
is the tripwire* — and Theory 3 (Sorare) is the specific case where a tradable asset triggers
gambling and securities scrutiny simultaneously.

So the asset layer is expensive **three independent ways**: economically (sport.fun's year),
legally (the money-out tripwire), and empirically (All Day switched it off).

The resolution layer is the only part nobody owns, nobody has out-funded us on, and **nobody can
sue us over** — its money-out surface is zero.

## 5. The regulator and sport.fun's P&L are giving the same instruction

This is the part that has not been noticed, and it is the most useful thing in this note.

- **The law says:** no money out → no tradable assets → no market to run.
- **sport.fun's year says:** running the market is the expensive, low-fun part; the founder's
  own list of what is fun — discovery, seeing other managers' picks, competing with friends,
  pack openings — does not include the market. Trading is described as *depth*, the retention
  scaffolding under the fun, not the fun itself.

The constraint that reads as a handicap is a subsidy: **we are legally barred from the thing
that is eating our competitor's company.**

It converges on revenue too. The legality doc says monetise on the way *in*. sport.fun's Season 2
moved to Season Pass / subscription over transaction fees, and the corpus reading already
concluded: *do copy subscription rather than transaction-fee revenue.* Their premium tier leads
with a "Best in class AI Assistant" — data at the decision point — which is precisely our
abundance and their scarcity.

## 6. Build-order revision: research subscription before cosmetics

`ESPORTS-PRODUCT-DIRECTION.md` sequences pick desk → cosmetics → Ultimate Team last. On the
evidence above the first monetisation should be **a research subscription**, ahead of cosmetics:

- **Zero regulatory surface.** No consideration, no chance, no prize. None of the seven
  guardrails in the legality doc even engage — nothing to age-gate, nothing to geo-exclude, no
  odds to publish, and normal payment rails stay open.
- **It is the one validated need we have.** The 2026-07-26 user had no draft-research home at
  all — not a preferred competitor, a vacancy.
- **It does not require an audience to work.** Cosmetics and Ultimate Team monetise retention.
  We do not have retention yet, so they are monetisation of a thing that does not exist.
- **A funded competitor has already validated it as sellable** at the premium tier.

Ultimate Team is not cancelled — it is demoted behind evidence of retention, on the same
reasoning that put player-shares in Phase 3.

## 7. The distinction not to blur — two different "records"

The brand already means picks **plus an earned record**. But "the record" is two assets and
conflating them produces a promise the product cannot keep:

| | what it is | worth at zero users |
|---|---|---|
| **Record A** | what *players* did — did the prop hit | **Valuable now.** Sellable. Independent of users |
| **Record B** | what *you* picked and whether you were right | **Worthless.** An accountability ledger about nobody is nothing |

**Lead with A as the capability, B as the promise.** B only becomes real after R6 ships and
someone makes a pick. Pitching B today is a promise against an empty ledger.

## 8. The line

sport.fun has settled on **"Picks. But you own it."** The counter that costs us no asset layer,
no market, and no legal exposure:

> ## Picks. But they're on the record.

It sits on the brand name we already have, it describes an asset we already own, and the
accent-marks-absence doctrine in `.claude/skills/honest-data-ui/SKILL.md` is already the visual
form of the same idea — ink goes to the holes, because the holes are what nobody else shows.

Replaces "makes internet-native sports feel as trackable as an NBA game on ESPN," which claimed
**coverage**. Coverage is the axis where four products share one nav bar, and it is the axis the
PlayerX analysis diagnosed as the problem.

## 9. What would falsify this

Recorded honestly, because the note is worth less if the weak points are not written down.

1. **The B2B ledger thesis has zero validated buyers.** The consumer NFL pitch has exactly one
   validated signal. One real user outranks a clean thesis — so pitch consumer-first and keep
   the ledger as the moat we do not lead with.
2. **Identity aggregation may be worth less than argued if the sources stay easy.** The claim
   rests on the join being hard. It was hard for All Day. If Sleeper and ESPN turn out to expose
   clean ids, the moat is thinner than §1 implies. Testable the first time a second source is
   wired.
3. **This is all still taste until R6.** GA4 is built (`components/Analytics/GoogleAnalytics.tsx`,
   wired in `pages/_app.tsx`) but **prod is v0.6.7**, so nothing is being measured. The
   sport.fun corpus's sharpest operating lesson is that every roadmap in it was corrected by
   contact with user behaviour. We cannot be corrected yet.

## 10. The one decision this asks for

Nothing here changes v0.7.0 or the ~Aug 22 draft deadline. The mock draft is the **acquisition
surface**; the ledger is the **moat**. Reposition the story, not the build — which is exactly
what sport.fun did, holding one thesis while replacing the machinery beneath it five times.

The single ask: **ship R6.** Until prod moves off v0.6.7, the analytics that would settle any of
this are measuring an empty room.
