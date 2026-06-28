# Writeup — the esports opportunity

Status: strategy note, not a committed roadmap item. Author prompt: "esports has a huge following
of people just as cracked-out paying attention — could be a huge opportunity." This lays out the
case, the fit with what we've already built, what's unknown, and a concrete first step. Honest
about what we don't know yet — claims that need validation are marked **[verify]**.

## The thesis
Esports has the one thing our whole model is built around: an audience that follows competitive
outcomes and player performance obsessively. The viewership for top titles (CS2, League of Legends,
Valorant, Dota 2, CoD) is large and young, the fandom is forum-deep and stats-literate, and there's
an active betting market around it. That's the same shape as the NBA/NFL hardcore we're courting —
just a different sport. We already have a toe in: **CoD is on the scoreboard today** (via
`breakingpoint_client` / `cdl_client`).

The honest uncertainty (the prompt named it): we don't know yet whether the esports audience *bets*
at the same rate per fan as traditional-sports fans, or how mature esports prop markets are. That's
the main thing to validate before investing heavily. **[verify]**

## Why it fits what we've already built
Our engine is league-agnostic: **scoreboard → props → stats/leaderboards → per-player game logs →
modeling**. Esports maps onto every layer:
- **Scoreboard** — matches with states (upcoming/live/final), same as CoD already does.
- **Stats / leaderboards** — every title has per-player performance stats (CS: K/D, ADR, rating;
  LoL: KDA, CS/min, gold; etc.). Same Stats-tab shape we're building for traditional leagues.
- **Per-match player logs** — the esports analog of `player_game_logs`. The prop-outcome engine
  ("did the line hit") generalizes directly: maps, kills, rounds are countable outcomes.
- **Brackets / pick'em** — esports playoffs are bracket-shaped and a huge engagement moment. This is
  the *same* bracket/pick'em feature already on the v0.3.0 roadmap for World Cup + CoD.

So the marginal cost of adding an esports title is mostly **data ingestion + identity**, not new
product surface. That's the strategic point: we don't build a separate thing, we add a league.

## Data — the deciding factor per title (researched 2026-06-28)
Esports lives or dies on data accessibility, and the key finding is that **data accessibility and
bettor overlap pull in OPPOSITE directions**:
- **Dota 2 — best data, lower betting profile.** **OpenDota** (free, open-source, built on Valve's
  WebAPI + automated replay parsing) and **STRATZ** (free, the most comprehensive 3rd-party Dota stats;
  heavy commercial users are asked to meet a small referral quota + represent the brand). Lowest data
  friction of any title, commercial-friendly, no approval gate. **[verified — opendota.com/api-keys, stratz.com/api]**
- **CS2 — best betting audience, worst data access.** Deepest bettor culture (DraftKings runs CS2 map +
  prop markets). But **HLTV has no official API** — only unofficial scrapers (Selenium/BeautifulSoup) or
  paid third-party scrapers (Apify), both ToS-risk and fragile. My earlier "accessible data" claim here
  was wrong. To do CS2 right you'd likely **pay an aggregator** (GRID / PandaScore / Abios). **[verified — no official HLTV API]**
- **LoL / Valorant (Riot) — official API but approval-gated.** Riot has a real API, but **public/commercial
  use requires an approved Production key** (personal keys are barred from public consumption), and Valorant
  player data needs an RSO OAuth opt-in. A betting-adjacent product may not get approved — verify before
  counting on it. **[verified — developer.riotgames.com/terms]**
- **CoD** — we already ingest it (breakingpoint.gg); a proven path to extend, not start from zero.
- **Aggregators (Abios, PandaScore, GRID)** cover many titles with official, licensed feeds — the clean
  legal path, but **paid**. The build-vs-buy call: free scraping (ToS risk, fragile) vs a paid aggregator.

Identity resolution is the recurring tax (our spine rule applies): players use handles, switch teams,
and span titles — resolve by a stable per-title source ID, never by name (`AGENTS.md §7`).

## Where the money/risk sits
- Esports betting is real and growing, but **per-title** markets and prop depth are uneven; aggregate
  is meaningful, any single title may be thin. **[verify market size + prop availability]**
- Scenes are more volatile than traditional leagues (titles rise/fall, orgs fold, patches reshape
  meta). Favor titles with durable competitive ecosystems (CS, LoL, Dota have lasted a decade+).
- Our edge is the same as everywhere: **selection + the prop-outcome data layer**, not being a book.

## Recommended first step (cheap, falsifiable)
Don't commit to "esports" broadly. Pick **one** title where the data is most open and the betting
overlap is clearest, and run it through the existing engine end-to-end as a probe:
1. **Validate demand + market** first (a day of research): is there prop-betting interest and data we
   can legally use for this title? Kill the idea here if not. **[verify]**
2. If yes, **extend the CoD pattern**: a scoreboard client for the chosen title (matches + state),
   then per-match player logs (the `player_game_logs` analog), then a Stats leaderboard, then — if
   prop lines exist — props. Reuse `_core` + the routers; it's a new league, not a new app.
3. **Brackets/pick'em** is the natural engagement hook (shared with the WC/CoD bracket work) and is
   title-agnostic — a fast way to draw the esports audience in before full prop depth exists.

Leading candidate to probe first: **CS2** (deepest bettor culture + scrapeable stats) or **Dota 2**
(most open free API, lowest data friction). Decide on data access, not vibes.

## Live-stream embedding — free content as an engagement moat
The sharpest part of the opportunity: most esports streams **free** on YouTube/Twitch via official
org channels (Riot/`twitch.tv/lec` + `twitch.tv/riotgames` for LoL, ESL for CS2, plus Dota 2 and
Valorant). Both platforms ship a **sanctioned embed player**, so we could put the live match *inside
our site*, next to our scoreboard / props / projections. "Watch + the stats and lines in one view" is
a real engagement hook and a differentiator — and it's content we don't pay for or produce.

It's not only esports. There's a class of **free, embeddable competitions ESPN hasn't locked up**:
- **PWHL** streams every game free on YouTube (and thepwhl.com), US + worldwide except Canada/Czechia/
  Slovakia (regional rights). **[verified — PWHL "Where to Watch"]**
- **NOT MLS** (corrected): MLS is **exclusive to Apple TV** — all 2026 matches are under the Apple TV
  subscription, and the standalone Season Pass folded in after 2025. No Twitch, not embeddable. An
  earlier draft of this doc wrongly listed MLS/NWSL as free Twitch; that came from a low-quality
  streaming listicle, not a real rights check. NWSL is likewise on paid/linear (Prime/ESPN/CBS).
- The counter-weight the prompt named is the whole point: big platforms **buy exclusivity** —
  **Apple (MLS)**, **ESPN/ESPN+** (much of the minor-league / college / niche space). Those aren't
  embeddable. The play is only the leagues that *choose* free distribution to grow reach (PWHL, most
  esports orgs). **Every candidate needs a real per-league rights check before it counts.**

**Embedding reality (don't skip this):** embeddable ≠ free-for-all.
- **YouTube** allows display only through its embeddable player, "as permitted by the Service"; its ToS
  forbids broadcasting/displaying content otherwise, and embedding does **not** grant copyright immunity.
- **Twitch** embeds require SSL + a `parent` (domain) parameter and compliance with its Developer
  Services Agreement, and Twitch can **revoke embed access at any time**.
- So: only embed **official/sanctioned** org streams via the platform players; never restream or
  rebroadcast; confirm rights per competition. Treat it as "we surround a free official embed with our
  data," not "we host the broadcast." **[verify per-competition + ToS before building]**

**Research to do (the prompt asked for it):** catalog which competitions are (free × officially
embeddable × audience that bets/engages) — esports majors, PWHL, MLS/NWSL, others — versus the
ESPN-locked set. That list, crossed with where we can get stats/props, is the real target map.

## Answers to the open questions (researched 2026-06-28)

**Q: Does the esports audience bet enough to justify the build?** Yes, directionally. The global
**esports-betting market is ~$18.5B in 2026** (up from ~$16.3B in 2025), forecast ~$51.7B by 2034
(~13.7% CAGR), on **640M+ viewers (2025) → 700M+ (2026)**. Prop markets already exist on US books —
**DraftKings is the most active** (match, map, and props like total headshots / most assists / live
micro-bets); FanDuel is narrower. Caveat: the dollar figures are market-research-firm projections
(directional, not gospel); the *verified* facts are "real, large, growing, and props exist on DraftKings."

**Q: Which single title is best (data × bettor-overlap × durability)?** No title wins all three — the
core tension is data-vs-audience:
- **Dota 2** wins on **data** (free open APIs, no gate) and durability (decade+ scene), but has a
  smaller betting profile than CS2.
- **CS2** wins on **betting audience + durability**, but has the **worst data access** (no official API).
- **LoL/Valorant** have a real API but it's **approval-gated** and may reject gambling-adjacent apps.
- **Recommendation:** prove the engine on **Dota 2** (cheapest, cleanest data — fastest end-to-end
  probe), and if the bettor-draw thesis holds, invest in **CS2** via a **paid aggregator** (GRID/
  PandaScore/Abios) since that's where the betting audience is. CoD is the already-working third option.

**Q: Legal/ToS on the stats sources?** Varies hard (see the data section): Dota (OpenDota/STRATZ) = free
+ commercial-OK (STRATZ asks heavy users for a referral quota). Riot = official but production-key
approval required, no public use on personal keys, Valorant needs RSO opt-in. HLTV (CS2) = **no official
API**, scraping is ToS-risk → the clean path is a **paid licensed aggregator**. Embedding streams =
official platform players only, no rebroadcast (see streaming section).

**Q: Does the prop-outcome engine need title-specific outcome types?** Minor extension, not a rebuild.
Esports outcomes are countable and map onto our existing "did the line hit" shape: **series structure**
(best-of-X → map-winner / total-maps, the CoD/tennis-set pattern we already handle) plus **per-player
counting stats** (kills, headshots, assists for CS2; kills, last-hits, GPM for Dota). Add per-title
market definitions to `_MARKET_STAT_KEY` and a per-match player-log ingest; the modeling layer is reused.

## Still genuinely open (need a decision, not just research)
- **Build-vs-buy for CS2 data:** scrape HLTV (free, fragile, ToS-risk) vs pay an aggregator (clean, $$$).
- **Which title actually first** — Dota (build-cheap) vs CS2 (audience) — is a strategy call, not a fact.
- The **free × embeddable × bettor** competition catalog (the streaming research map) is still to compile.

## Sources
Esports betting market + props: businessresearchinsights.com, marketresearchfuture.com, Bleacher Nation
(DraftKings/FanDuel esports). Data/ToS: opendota.com/api-keys, stratz.com/api, developer.riotgames.com/terms,
HLTV (no official API — unofficial scrapers only). Streaming: thepwhl.com, dev.twitch.tv/docs/embed,
youtube ToS, mlssoccer.com (MLS→Apple TV exclusive).
