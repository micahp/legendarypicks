# FINDINGS — NFL All Day on-chain verification

Verified against Flow mainnet on 2026-07-27.

## 1. AllDay contract address

**`0xe4cf4bdc1751c65d`** — confirmed via `GET /v1/accounts/<addr>?expand=contracts`.

Contracts deployed:
- `AllDay` — the main contract (Moment NFTs, Series, Sets, Plays, Editions)
- `PackNFT` — pack-related functionality

The legacy Top Shot address (`0x0b2a3299cc857e29`) is NOT the AllDay contract. AllDay is a separate deployment.

## 2. Public collection capability path

**`/public/AllDayNFTCollection`** — confirmed from the contract source:

```
self.CollectionPublicPath = /public/AllDayNFTCollection
```

Borrowed as `&{NonFungibleToken.CollectionPublic}`. The storage path is `/storage/AllDayNFTCollection`.

This differs from Top Shot which uses `/public/MomentCollection`. An address that holds AllDay moments exposes them at this path; an address without one returns an empty collection (capability check fails gracefully).

## 3. Moment metadata — what resolves

Each Moment NFT resolves the standard `MetadataViews` plus AllDay-specific data through the contract's own `getPlayData()`, `getEditionData()`, `getSeriesData()`, and `getSetData()` methods.

### Fields available per moment

| Field | Source | Example |
|-------|--------|---------|
| `id` | NFT ID (UInt64) | `8220605` |
| `name` | Display.name | `"Zach Ertz Reception"` |
| `thumbnail` | Display.thumbnail.uri() | `https://media.nflallday.com/editions/3304/media/image?format=jpeg&width=256` |
| `url` | ExternalURL.url | `https://nflallday.com/moments/8220605` |
| `playerFirstName` | Play.metadata | `"Zach"` |
| `playerLastName` | Play.metadata | `"Ertz"` |
| `playerPosition` | Play.metadata | `"TE"` |
| `teamName` | Play.metadata | `"Washington Commanders"` |
| `playerNumber` | Play.metadata | `"86"` |
| `playType` | Play.metadata | `"Reception"` |
| `tier` | Edition.tier | `"COMMON"` |
| `serial` | Serial.number | `212` |
| `seriesName` | Series.name | `"2024 Season"` |
| `setDisplayName` | Set.name | `"Base"` |
| `editionNumber` | Edition.playID | `3304` |
| `season` | Play.metadata | `""` (often empty) |
| `week` | Play.metadata | `""` (often empty) |

Tiers observed: `COMMON`, `UNCOMMON`, `RARE`, `LEGENDARY`, `ULTIMATE`.

Play types observed: `Reception`, `Pass`, `Rush`, `Forced Fumble`.

Positions observed: `QB`, `RB`, `WR`, `TE`, `DB`.

**season and week are empty strings on all 6 test moments.** The contract stores them as metadata fields but they are not populated for these moments. This means we cannot determine which season/week a moment is from without external data.

## 4. Test address

**`0xa16b948ba2c9a858`** — a Flow account holding 6 NFL All Day moments (all 2024 Season Base Set):

| ID | Player | Position | Team | Play |
|----|--------|----------|------|------|
| 8220605 | Zach Ertz | TE | WAS | Reception |
| 8221003 | Benjamin St-Juste | DB | WAS | Forced Fumble |
| 7932830 | Amon-Ra St. Brown | WR | DET | Reception |
| 8129289 | Brock Purdy | QB | SF | Pass |
| 8225694 | Zach Ertz | TE | WAS | Reception |
| 7766061 | Saquon Barkley | RB | PHI | Rush |

This address is a Hybrid Custody child account of `0xfeb88a0fcc175a3d`. Both parent and child accounts can query using the standard `/public/AllDayNFTCollection` capability — no special custody logic required for reads.

## 5. Fantasy scoring rubric

**No public scoring rubric found.** The NFL All Day platform has a "Challenges" feature and the contract stores `playType` metadata, but Dapper has not published a standard fantasy-points rubric mapping play types to point values.

**Decision: do not build scoring in v1.** The task already scopes this out. We already compute PPR ourselves from `player_game_logs`. If a rubric is discovered later, we can score AllDay lineups directly from the DB.

## 6. Identity resolution — the join works

**100% hit rate on test data (5/5 moments resolved)** when using a relaxed matching strategy:

| Moment | DB Match | Notes |
|--------|----------|-------|
| Zach Ertz | Zach Ertz (TE/WAS) | active=0 — must include inactive players |
| Benjamin St-Juste | Benjamin St-Juste (CB/GB) | Position DB→CB OK; team changed WAS→GB |
| Amon-Ra St. Brown | Amon-Ra St. Brown (WR/DET) | Exact match |
| Brock Purdy | Brock Purdy (QB/SF) | Exact match |
| Saquon Barkley | Saquon Barkley (RB/PHI) | Exact match |

### Rules for the join

1. **Name match**: case-insensitive exact match on `players.name`. The AllDay name format `"firstName lastName"` matches our `players.name` directly.
2. **Include inactive players** (`active=0`). Players like Zach Ertz (retired) and DeAndre Hopkins (inactive) still hold AllDay moments from past seasons.
3. **Position reconciliation**: AllDay's `DB` → our `CB`/`S`/`DB`. AllDay's position vocabulary is smaller than ours but maps cleanly.
4. **Team is not a join key** — players change teams. Use it for display only.
5. **Potential ambiguity**: players with identical names across eras (e.g. "Josh Allen" matches both a QB and a C). Resolve by position when multiple matches exist.

### Pitfalls

- Generational suffixes: `Murvin Kenion III` vs `Murvin Kenion` — our DB may strip suffixes. Handle with a LIKE fallback.
- Hyphenated names: `St-Juste`, `St. Brown` — match exactly as-is; DB stores them the same way.
- The DB has 2,926 active NFL players and many more inactive. The join pool is large enough to resolve most AllDay moments.

## Cadence script reference

The working script is checked in at `backend/routers/nfl_allday.py`. It:

1. Borrows the public `AllDayNFTCollection` capability
2. Iterates `collection.getIDs()`
3. For each ID: resolves `MetadataViews.Display`, `Edition`, `Serial`, `ExternalURL`
4. Casts to `&AllDay.NFT` to access `AllDay.getEditionData()` → `AllDay.getPlayData()` → metadata
5. Returns `[{String: AnyStruct}]` — one dict per moment

The script executes via `POST https://rest-mainnet.onflow.org/v1/scripts` with base64-encoded Cadence and JSON-Cadence arguments.

---

# ADDENDUM — verification pass, 2026-07-27 (later same day)

The findings above were written off a **single 6-moment test wallet**. Re-verified
against nine wallets discovered on-chain, three claims needed correcting and three
new defects surfaced. Original text is left intact above; this section supersedes
it where they conflict.

## A. How to find real holders (the marketplace is not needed)

`nflallday.com` is behind a bot-wall from this box, but holders are discoverable
directly from the chain. Scan `A.e4cf4bdc1751c65d.AllDay.Deposit` events over recent
blocks via `GET /v1/events` (250-block maximum range per request) and read the `to`
field. 15,000 blocks returned 81 deposits across 14 unique addresses.

Collection sizes for those addresses, measured with a `getIDs().length` script:

| address | moments |
|---|---|
| `0xb09562a023f25262` | **66,387** |
| `0xc2544e942028e947` | 6,772 |
| `0x379c2a0e88d8081f` | 5,731 |
| `0x6d9da560c16a2498` | 4,178 |
| `0x3d99869d46ecad15` | 2,270 |
| `0x7de2c3a8c5838385` | 1,392 |
| `0xf471482157b596fe` | 1,254 |
| `0xdc033ea7e143cf39` | 572 |
| `0x5191a7333fe8e63b` | 193 |
| `0xb01d7e57aa56e639` | 84 |
| `0x5f3f7a1c61b09bab` | 18 |
| `0x4ace3f038541b83e` | 0 (has a collection, holds nothing) |

**The "tiny market" conclusion is about trading volume, not collection size.** Wallets
are large. Any design assuming a user pastes an address and gets a screenful is wrong.

## B. CORRECTION — the one-script design breaks past ~600 moments

§6's "100% hit rate" and the original implementation both rested on 6 moments.
Resolving a whole collection in one Cadence script **exceeds Flow's per-script
computation limit** between 572 (works) and 1,254 (fails). The node answers `400`,
so the four largest wallets above returned a `502` from our API — the feature was
broken for exactly the users who own the most.

Fixed by splitting the read in two: `CADENCE_IDS` gets the id list cheaply, then
`CADENCE_MOMENTS` resolves metadata for an explicit page of ids, batched at 200.
`66,387` moments now answers in **3.6s**.

## C. CORRECTION — the real match rate is ~94%, not 100%

Measured per page of 200 after adding suffix/punctuation normalisation:

| wallet size | matched | unmatched | rate |
|---|---|---|---|
| 18 | 17 | 1 | 94.4% |
| 193 | 181 | 12 | 93.8% |
| 572 | 189 | 11 | 94.5% |
| 1,254 | 187 | 13 | 93.5% |
| 6,772 | 193 | 7 | 96.5% |

Normalising generational suffixes and punctuation moved the 193-moment wallet from
164 to 181 matches. The residual ~6% is mostly retired/pre-2020 players and
offensive linemen who have no row in our NFL spine. **The join works, but plan for
roughly 1 in 16 moments to be unresolvable** — the UI must show those honestly
rather than dropping them.

## D. Hybrid Custody — why "paste your address" can return nothing

This is the trap the `@onflow/fcl` SDK hides and a raw REST read does not.

Dapper accounts use **Hybrid Custody**: the address a user sees in the NFL All Day
UI is frequently a **parent** account that owns no NFL NFTs itself. The moments live
in a **child** account linked to it. The original test wallet `0xa16b948ba2c9a858` is
itself a child of `0xfeb88a0fcc175a3d`.

So a naïve read of the pasted address returns an empty collection and the user
concludes the feature is broken. The endpoint now, when the pasted address has no
collection of its own, borrows `HybridCustody.Manager` from
`0xd8a7e05a7ac670c0` at `HybridCustody.ManagerStoragePath`, reads
`getChildAddresses()`, and aggregates the children (capped at 10). The response
reports which accounts the moments came from in `sources`, and the UI says
"via linked account 0x…" when they differ from what was pasted.

Reading a child directly still works — no custody logic is needed for reads, only
for *discovery* from the parent side.

## E. Empty is three different facts

`total: 0` was returned for all of: an address that never existed, an address with
no AllDay collection, and a collection holding nothing. The API now returns a
`status` of `no_account` / `no_collection` / `empty` / `ok`, and the UI writes a
different sentence for each. Absence is a claim about us; nonexistence is a claim
about the address, and they must not render identically.

Worked example: `0xa184e13ef8c3e0ef` exists and holds Toucans, two
`UniversalCollection` items, FlowToken, USDC and a `TopShotBETAVault` — but has no
`/storage/AllDayNFTCollection` and no child accounts. It is a genuine wallet that
has simply never held All Day.

## F. Two more defects found and fixed

- **Upstream errors leaked.** Flow failures returned
  `Flow API error: 400 Client Error ... https://rest-mainnet.onflow.org/v1/scripts`
  straight to the browser, exposing our request URL. Now logged server-side, with a
  generic 502 to the client. Regression-tested.
- **A SQLite connection per moment.** `_resolve_player()` opened a fresh connection
  and ran up to two queries *for every moment* — 200 connections and 400 queries per
  page against a table small enough to hold in memory. Replaced with `PlayerResolver`,
  which loads the NFL spine once per request into a name-indexed dict.
- **Every player link 404'd.** Moments linked to `/players/{id}`; the route is
  `/player/[id]`.
