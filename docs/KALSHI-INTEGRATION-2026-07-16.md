# Kalshi integration — the 3 tiers, what's free vs licensed (2026-07-16)

**Question being answered:** we keep circling "embed Kalshi liquidity" on the esports/picks
product. Does Kalshi have a partner program for that, and how does it actually work — because the
answer decides whether it's a code task or a licensing project. This doc is so we stop re-Googling it.

## Product frame (non-negotiable)

LP is **free-to-play: picks + your lineup. No book, no securities, no money custody.** That is the
legal moat, not an accident. Kalshi is the *money* layer, off-platform and regulated. So the only
question is *how much* of Kalshi we can surface, and at what regulatory cost.

Mirror of the product-direction thesis ("the crowd becomes our own line"): here **Kalshi is the money
line we rent, regulated**, while picks stay the free game. **LP does the picks; Kalshi does the money.**

## The three tiers

| Tier | What it lets us do | Who can do it | Gate |
|---|---|---|---|
| **1. Data / API** | Read every market's price + order book; **display** the live Kalshi contract on a pick card; deep-link "Trade on Kalshi →" out | Any **verified Kalshi user** (we already have an account via the trading op) | **None** — free, self-serve REST/WebSocket |
| **2. Own-account trading** | Route *our own* orders via the API | Same verified account | Free, but it's **us** trading our money — does not let LP *users* trade through LP |
| **3. Embedded trading (the moomoo model)** | LP *users* trade Kalshi contracts **inside LP** | **Registered brokers only** | Must be **CFTC-registered Introducing Broker + NFA member** (or partner through one) |

### Tier 1 — the part we can build now, no permission
Free API gives price + order-book data for all markets. We can render the matching Kalshi contract
(price, book, "Trade on Kalshi →") right on a pick card. **LP never touches money.** This is the
picks-native, zero-gate version and it fits everything we've said. Read-only display is API-cheap.

### Tier 3 — the part that's a licensing project, not a code project
To embed an actual *trade button for our users*, Kalshi's stated bar (their brokers page): an
Introducing Broker applicant must be *"validly organized, in good standing, in the United States, and
registered as an Introducing Broker by the CFTC and a member of NFA."* Every named partner — **moomoo,
Webull, Tradeweb** — is an already-licensed broker. So the embedded-trade version = CFTC IB
registration + NFA membership (time, capital, legal), not a sprint. This lines up with the
agent-money-policy line (regulated venues / humans on the cash side) and the Sport.fun caution about
not baking regulatory workarounds into the near-term plan.

## Open unknown — revenue share
**Not published anywhere public.** Whether a deep-link referral pays anything, or only a full IB
earns, is a "contact `institutional@kalshi.com`" question. **Do not assume there's referral money
until they confirm it.**

## Recommendation / decision gate
- **Start with Tier 1** (display + outbound deep-link). Free, buildable now, keeps LP squarely
  "picks, not betting." Ship it as an ambient layer on a pick card where a Kalshi market matches.
- **Tier 3 is a deliberate business decision**, gated behind broker registration — flag it, don't
  drift into it. Revisit only if the picks product has the audience to justify the licensing lift.
- Before leaning on any *revenue* story from Kalshi, email `institutional@kalshi.com` to learn the
  actual partner economics.

## Sources
- Kalshi — Brokers / partners: https://kalshi.com/brokers
- Kalshi — Institutional onboarding: https://institutional.kalshi.com/  (two paths: direct trading; API/data-only)
- Kalshi API — Help Center: https://help.kalshi.com/kalshi-api
- "Kalshi's $44B Bet: Why Embedded Trading Could Be the Real Winner": https://www.ainvest.com/news/kalshi-44b-bet-embedded-trading-real-winner-2606/
