# Esports Product — Loot Box / Card Legality Pressure-Test

**Date:** 2026-07-14
**Companion to:** `ESPORTS-PRODUCT-DIRECTION.md`
**Status:** research + design constraints, **NOT legal advice.** Before any money touches a
pack, a gaming/gambling lawyer must review the final design against the specific launch
jurisdictions. This intersection (crypto-adjacent + prediction + random packs) is precisely the
novel area regulators are actively probing right now.

## The one rule that governs everything: money IN is fine, money OUT is the tripwire

A free-to-play game that sells random packs and cosmetics is the **lowest-risk category** — a game
with in-app purchases. It becomes gambling (or securities) at the moment **real money can come back
OUT**: a cash prize, a card cash-out, or a sanctioned secondary market that gives items real
monetary value. The loot-box economy makes its money on the way *in* (pack + cosmetic sales) and
does **not** require any money-out to be lucrative. So the entire product can be highly monetized
while staying non-gambling — **if we never build a money-out path.**

Hold these three lines and LP stays a "game with IAP," not a regulated gambling/securities product:

1. **Cards never cash out, and LP runs no money-market for them.** No sell-for-money, no
   LP-operated marketplace, no crypto/token wrapper.
2. **Contests never pay monetary prizes.** Winning a division/leaderboard yields **status,
   cosmetics, and more packs** — never cash or crypto.
3. **Paid competition, if any, is peer-to-peer, not vs. the house** (see DFS section).

Cross any of these and a different, heavier body of law switches on.

## Theory 1 — Loot boxes as gambling

Gambling generally requires three elements: **consideration** (you pay) + **chance** (random) +
**prize of value** (a reward worth real money). Packs clearly have the first two. The whole game is
whether the reward has *monetary* value.

- **The precedent in our favor — EA / FIFA Ultimate Team, Netherlands.** The Dutch regulator fined
  EA €10M, but the highest Dutch administrative court (Council of State, 2022) **overturned it and
  ruled FUT packs are NOT a game of chance** — because the packs aren't a standalone game of chance,
  they're part of a **broader game of skill** (Ultimate Team). This is the strongest available
  precedent for the FUT-model and it went the publisher's way. *(cms.law, VGC)*
- **The precedent against — Belgium.** Belgium's Gaming Commission declared paid loot boxes illegal
  gambling; publishers pulled paid packs / FIFA Points from Belgium. A hard-ban jurisdiction; simply
  geo-exclude it. *(background)*
- **United States — not treated as gambling; treated as consumer protection.** No state has enacted
  a loot-box gambling ban. The live risk is the **FTC**: in early 2025 it settled with HoYoverse
  (Genshin Impact) for **$20M** over loot boxes that misled players on real-money cost and targeted
  minors — requiring **odds disclosure, transparent virtual-currency exchange rates, simplified
  purchase flows, and parental consent for under-16 purchases.** State bills (NY A9044, CA, WA, MN,
  HI) mostly target minors + disclosure and have largely stalled. *(Chambers Gaming Law 2025,
  Gamma Law, esportslegal.news)*

**Design constraints from Theory 1:**
- Packs must be **embedded in the skill game** (you rip to field/collect, not as a standalone
  gamble). The Dutch reasoning depends on this.
- **Publish drop odds** (also an App Store requirement, below). Cheap insurance, kills the FTC
  deception angle.
- **Age-gate purchases; get parental consent under 16; never design for or market to minors.**
- **Geo-exclude Belgium** (and re-check any other hard-ban jurisdiction at launch).
- Keep pack reward = **non-cash-value card**. This is what keeps "prize of value" off the table.

## Theory 2 — The pick / fantasy contest as gambling or DFS

This is the leg most people underrate, and 2025 case law is a gift here.

- **Free pick'em is not gambling** — no consideration. The free Pick Desk has essentially no
  gambling exposure regardless of jurisdiction. Ship it freely.
- **Paid contests fall under Daily Fantasy Sports (DFS) law.** Federally, UIGEA (2006) carves
  fantasy sports out of gambling *if* the outcome reflects the **skill** and **relative performance
  of multiple real athletes** (not a single team's score / a point spread), and prizes are **fixed
  and announced in advance**. Esports DFS is broadly legal (DraftKings runs it). *(Wikipedia DFS,
  esports.net)*
- **But "pick vs. the house" is under active crackdown.** Prop-style "pick'em" (over/under vs. the
  operator) is being treated as disguised sports betting: **Michigan banned pick'ems**, and in
  **July 2025 the California AG opined DFS is illegal** under state law, pushing operators to
  restrict CA. Washington and Nevada already treat paid DFS as illegal/unlicensed. *(deadspin,
  saturdaydownsouth, usaonlinesportsbooks)*
- **The survivors went peer-to-peer.** **PrizePicks moved to a peer-to-peer model ("PrizePicks
  Arena", Aug 2025)** — users compete against each other, not the house — specifically to survive
  regulatory pressure. *(deadspin)*

**This directly validates the product design.** "You vs. the crowd," with entry pooled among
players and the platform taking no position, is the **structurally safer** shape — and it's what
we already want. The dangerous shape is picks settled **against LP as the house**.

**Design constraints from Theory 2:**
- **Keep contests peer-to-peer**, not house-banked, the moment any payment is involved.
- **Predominantly skill, multi-player performance.** A pick-desk "who wins this match" call is
  closer to a single-game wager than DFS multi-player skill — so a paid winner-pick pool is *more*
  betting-shaped than a salary-cap lineup. **Money-prize winner-picks are the riskiest sub-feature;
  keep those free** (status only) and reserve any paid contest for **lineup/squad skill** formats.
- If a paid contest ever launches: **prizes announced in advance, state-by-state geo-restriction
  (exclude WA, NV, and the DFS-hostile states), and DFS-style compliance.** Or — much simpler —
  **never pay cash and this whole theory stays off** (prizes = cosmetics/packs/status).

## Theory 3 — Securities (the Sorare cautionary tale)

- **Sorare is the live test case for tradable-NFT fantasy cards — and it is being prosecuted.** The
  UK Gambling Commission **charged Sorare with providing unlicensed gambling facilities** (Sept
  2024, its first action against a blockchain platform, after a ~3-year inquiry). Sorare pleaded not
  guilty, arguing it's a "prize competition"; **trial is now set for June 2027.** France's ANJ also
  forced Sorare to amend its rules (strengthen free access) in 2021-22. *(coindesk,
  gamblingcommission.gov.uk, gamblinginsider)*
- The reason Sorare draws fire and FUT doesn't: **Sorare cards are tradable NFTs with real
  secondary-market money value.** That simultaneously (a) gives the "loot box" a prize of value
  (gambling), and (b) makes the card look like an investment asset (securities / the Howey test:
  money in a common enterprise with profit expectation from others' efforts).

**Design constraints from Theory 3:**
- **FUT model, not Sorare.** Cards are game items with utility + prestige, **not** tradable NFTs and
  **not** tokenized. No crypto wrapper on cards in the near-term design.
- **No player "shares," no tradable player assets, no token issuance** — already Micah's ruled-out
  path; this is the legal reason to keep it ruled out. Reintroducing crypto re-opens securities,
  money-transmission, AND the Sorare-style gambling scrutiny simultaneously.

## App stores, payments, and minors (the operational layer)

- **App Store odds disclosure:** Apple (since 2017) and Google (since 2019) require published
  loot-box drop rates. Do it regardless.
- **Payments:** gambling is a prohibited/restricted category for most processors (Stripe included).
  Staying non-gambling keeps normal payment rails open — relevant given inbound money runs on
  Micah's own account (agent-money policy).
- **Minors:** COPPA (under-13 data) + the FTC's under-16 parental-consent expectation for loot-box
  purchases. Age-gate spend; don't target minors.

## Verdict

The FUT-style model Micah wants is **defensible and has a favorable top-court precedent (Dutch
EA)** — provided we hold the money-OUT line. The version that gets prosecuted is the tradable-crypto
model (Sorare), which we already reject. And the pick-vs-house format regulators are killing is one
our "you vs. the crowd" design naturally avoids.

**Concrete guardrails to build against:**

| # | Rule | Protects against |
|---|---|---|
| 1 | Cards never cash out; no LP money-market; no crypto/tokens | Securities + gambling "prize of value" |
| 2 | Contest prizes = status / cosmetics / packs, never cash | DFS + gambling |
| 3 | Any paid contest is peer-to-peer, never vs. the house | Sports-betting reclassification (the PrizePicks lesson) |
| 4 | Paid contests, if ever, favor skill/lineup formats over single-match winner picks | DFS skill-predominance test |
| 5 | Publish pack drop odds | FTC deception + App Store rules |
| 6 | Age-gate purchases; parental consent under 16; no minor targeting | FTC/COPPA (the HoYoverse settlement) |
| 7 | Geo-exclude hard-ban jurisdictions (Belgium; DFS-hostile US states if paid contests launch) | Jurisdictional bans |

**The single sentence:** monetize on the way *in* (packs + cosmetics), never build a way *out*
(cash prizes, card cash-out, tradable/tokenized cards), keep any paid competition peer-to-peer, and
disclose odds. Get a gaming lawyer to sign off on the final design and jurisdiction list before the
first dollar.

## Sources
- Dutch EA/FIFA ruling: [VGC](https://www.videogameschronicle.com/news/dutch-court-overrules-decision-to-fine-ea-e10-million-for-fifa-loot-boxes/), [CMS Law](https://cms.law/en/nld/legal-updates/Dutch-court-rules-FIFA-loot-boxes-not-a-game-of-chance-revokes-EA-penalty)
- Sorare prosecution: [Gambling Commission](https://www.gamblingcommission.gov.uk/news/article/consumer-information-notice-sorare-com-prosecution), [CoinDesk](https://www.coindesk.com/policy/2024/09/27/fantasy-sports-company-sorare-charged-with-providing-unlicensed-gambling-facilities-in-uk), [Gambling Insider (trial → June 2027)](https://www.gamblinginsider.com/news/27019/sorare-faces-trial-for-alleged-uk-gambling-law-violations)
- US loot-box / FTC HoYoverse: [Chambers Gaming Law 2025 (USA)](https://practiceguides.chambers.com/practice-guides/gaming-law-2025/usa), [Gamma Law](https://gammalaw.com/how-does-us-consumer-protection-law-apply-to-video-game-loot-boxes-and-gacha-mechanics/), [esportslegal.news](https://esportslegal.news/2025/12/11/us-uk-and-eu-loot-box-strategies/)
- DFS / pick'em / PrizePicks peer-to-peer: [Deadspin DFS legal states](https://deadspin.com/dfs-legal-states/), [Deadspin — PrizePicks peer-to-peer](https://deadspin.com/legal-betting/prizepicks-transitions-to-nationwide-peer-to-peer-daily-fantasy-contests/), [Saturday Down South](https://www.saturdaydownsouth.com/dfs/legal-states/)
