# NFL All Day — what it is doing to stay relevant, as of 2026-07-27

Research commissioned while `docs/TASK-nfl-allday-lineups.md` was already in flight. Read
this before deciding how much further to invest in the All Day thread. It does **not**
invalidate the v1 task — see §5.

---

## 1. Primary issuance is over

**On 2026-05-13, Dapper Labs stopped issuing new NFL All Day NFTs.** Announced around
9:00 pm ET by CEO Roham Gharegozlou: *"collectors are owners, not consumers. today we are
stopping primary issuance for our NFL ALL DAY product, and announcing the signing of a new
licensing agreement with the NFL."*

- **Existing Moments remain fully authenticated and tradeable.** The marketplace continues
  without interruption. Only *new* supply stopped.
- **A new NFL licensing agreement was signed at the same time**, with details promised
  "as the season approaches" — i.e. approximately now. Dapper says it is "hard at work on the
  next evolution of NFL digital collectibles."
- Collector sweeteners: a **"Founding Collector"** badge, and a **5% Dapper balance rebate**
  that only releases after holding the purchase for a year.
- Collectors were audibly unhappy; some reported standing offers being filled after the
  announcement, buying into an immediately devalued asset.

## 2. They already shipped the feature we specced — but not the game

Three free-to-play games launched for the 2025 season:

| Game | Mechanic |
|---|---|
| **Playbook** | Pick a roster of players from Moments you own; hit yardage/play milestones (50/75/100 yds by tier) to unlock exclusive reward Moments. Rookie and All-Pro tiers run separate scoring. |
| **One and Done** | Same shape, but each player may be used only **once per season**. |
| **Pick'Em** | Straight prediction game. |

Also shipped: **autographed collectibles** (a verified digital autograph paired with a
highlight) and **in-stadium activations** with the Patriots, Bengals, Jaguars and Texans
handing out free digital collectibles.

**So "build a lineup from the Moments you own" exists.** But read what it actually is: a
*rewards/challenge* loop whose payout is more Moments. It is retention machinery for the
collection. It is **not** head-to-head fantasy, and it is not a research tool.

## 3. The market is very small

From on-chain reporting around the halt:

| | |
|---|---|
| Daily sales volume before the announcement | had exceeded **$10,000 only once, ever** |
| Wednesday (announcement day) | ~**$32,000** |
| Thursday (panic day) | **$53,000+** |
| Unique sellers | **<100/week → 400+** on the spike day |

Those are the *elevated* numbers. The addressable universe is **hundreds of people, not
thousands**, with no new supply arriving and a publisher that has stopped feeding it.

## 4. Sources

- [Decrypt — NFL All Day Stops Issuing NFTs](https://decrypt.co/367926/nfl-all-day-stops-issuing-nfts-dapper-labs-future-plans-league) (pub. 2026-05-14; the volume figures above)
- [roham on X](https://x.com/roham/status/2054731360888406296) (the announcement itself)
- [KuCoin flash](https://www.kucoin.com/news/flash/nfl-all-day-halts-new-nft-issuance-dapper-labs-signs-new-nfl-licensing-agreement) (Founding Collector badge, 5% rebate terms)
- [GamesBeat — autographs + F2P gaming](https://gamesbeat.com/nfl-all-day-digital-collectibles-gets-autograph-and-f2p-gaming/) (Playbook / One and Done / Pick'Em)
- [Dapper Labs ecosystem release, 2026-02-07](https://www.globenewswire.com/news-release/2026/02/07/3234119/0/en/Dapper-Labs-Ecosystem-Disney-Pinnacle-NFL-ALL-DAY-and-NBA-Top-Shot-Drive-Consumer-Engagement-on-Flow.html)
- [NFL All Day blog — Playbook](https://blog.nflallday.com/posts/a-new-path-to-top-moments-playbook-is-back)

**Caveat on method:** `nflallday.com` and `cryptoslam.io` both return **403** from this box —
the datacenter-IP bot-wall documented in `[[reference_datacenter_ip_blocks_wayback]]`. The
figures above are second-hand from Decrypt's on-chain reporting, not a live pull. If an exact
current holder count matters, **measure it on-chain ourselves** — we have working Flow
mainnet REST access from this box, which is the same path the v1 task uses.

## 5. What this changes, and what it does not

### The case against going deeper
Building *for All Day holders* is building for a few hundred people on a shrinking base. If
the hope was that All Day collectors convert into Legendary Picks users, that is a rounding
error and should not be planned around.

### The case for building v1 anyway — this is the real one
**We are buying the mechanic, not the audience.**

- *"Paste an identifier → get your players → build a lineup"* is the **same flow** whether
  the roster comes from an NFT wallet, a Sleeper league, or an ESPN import. All Day is the
  cheapest possible place to build and prove that flow, because the data is **public and
  permissionless** — no OAuth, no partner deal, no ToS negotiation, no rate limit, nobody to
  ask for approval. Every other roster source costs a relationship.
- **The issuance halt helps a third-party index.** The set is now closed and finite; it will
  never drift underneath us.
- **Moments are on-chain and permanent.** A read-only viewer keeps working no matter what
  Dapper does next.
- If Dapper ships its "next evolution" this season, already being the third-party tool for
  All Day collectors is a reasonable place to be standing when it lands.

### The risk to watch
If the new licensing deal moves the next product **off Flow or onto a different contract**,
our read path does not follow it. Existing Moments survive and keep resolving, but there is
no bridge to whatever replaces them.

### Decision
**Build v1 exactly as scoped** — read-only, paste-an-address, no wallet connect, no contests.
Treat it as a **prototype of the lineup mechanic**, not a bet on All Day's audience. Do not
invest past v1 on the strength of this market; invest past v1 only if the mechanic itself
proves out and can be pointed at a roster source with real users.

Micah's call, recorded 2026-07-27: aware of all of the above, wants v1 built regardless.
That is consistent with the reasoning here — the mechanic is worth having.
