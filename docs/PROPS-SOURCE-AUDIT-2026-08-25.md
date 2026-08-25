# Leagues Cup prop sources: exhaustive audit, 2026-08-25

Question: **who publishes Leagues Cup player stat props, and can we reach them?**

The 11 markets the board is built for: shots, shots on target, passes attempted,
goals, goalie saves, clearances, assists, attempted dribbles, tackles, crosses,
fouls. The RotoWire relay prices 8 of them (`SOCCER_GAME_MARKETS`), which is why
it is the intended in.

The four fixtures, from ESPN `soccer/concacaf.leagues.cup`:

| Fixture | Kickoff (UTC) | ESPN id |
|---|---|---|
| CF Monterrey vs Chicago Fire | 2026-08-26 00:30 | — |
| Club León vs Real Salt Lake | 2026-08-26 02:30 | — |
| Deportivo Toluca vs Austin FC | 2026-08-27 00:30 | 401911271 |
| Club América vs Columbus Crew | 2026-08-27 02:45 | 401911270 |

## The result

**No reachable source publishes Leagues Cup player stat props.** Two carry the
fixtures; neither prices the markets.

| Provider | Reachable | Leagues Cup | Player stat props |
|---|---|---|---|
| **PrizePicks** | **403 Cloudflare** (5 hosts) | **yes** (confirmed in-app) | **yes** |
| **DraftKings** | **403** (3 endpoints) | **yes** (confirmed in-app) | yes |
| Bovada | 200 | **4 fixtures** | **1 outcome only** (see below) |
| Pinnacle | 200 (26MB) | **4 fixtures** | 0 — team props only |
| Underdog | 200 (23MB) | no — 2 La Liga games | yes, for Europe |
| Sleeper | 200 (6MB) | no — LaLiga + EPL | yes, for Europe |
| Dabble | 200 | no — 4 EU leagues | — |
| MyBookie | 200 | no | — |
| BetPlay (CO) | 200 | no | — |
| RotoWire `lines.php` | 200 | **no** | 8 markets defined, Europe only |
| RotoWire soccer props table | 200 | empty 15 days straight | — |

Refused or unreachable: ParlayPlay 403, Splash 403, Rebet 403, BoomFantasy 401,
Betr 500, OwnersBox 404, Drafters 404, FanDuel 400, BetMGM 403, Caesars 403,
BetRivers 400, PointsBet 403, Betway 405, HardRock 404, BetOnline 403, BetUS 404,
Everygame 404, Bodog 522, Betcris 403, Caliente 403, Codere 404, Betfair 403,
Smarkets 404, Matchbook 530, Cloudbet 401, Stake 403, 1xBet 403, SofaScore 403,
VividPicks / Chalkboard / Fliff / ESPNBet / Fanatics / OddsBlaze / Rushbet: DNS.

## The two findings that cost the most time

**1. A name substring is not a subject.** Underdog's payload contains
`Monterrey` nine times. All nine are **WTA Monterrey**, a tennis tournament.
Matching a club by name alone produced a false positive that survived two passes.
Same shape as `SOCIAL_SOURCES` missing `"x"`.

**2. Bovada's one stat prop is not a market.** The coupon does contain the string
`Shots on Target`, and chasing it down yields exactly one player line across all
four fixtures:

```
Hugo Cuypers 1+ Shots on Target    -400    (Requested Specials, MTY vs CHI)
```

Every other hit is a TEAM combo -- `Each team 2+ Shots on Target`,
`Real Salt Lake 5+ Shots on Target; Club León 2+ Shots on Target`. Parlay
specials, not a player board. What Bovada does have is **636 goalscorer props**
(Anytime + First Goal Scorer, 45-51 players per fixture) at
`soccer/north-america/leagues-cup`. That is 2 of 11 markets: goals and assists.

## RotoWire is the right in, and it is not blocked -- it is empty

From RotoWire's own bundle, `picks/assets/picks-core.js`:

```js
queryFn: async () => await (await fetch(`/picks/api/lines.php`)).json()
```

No parameters, no auth header, memoized, then filtered client-side by
`sport` / `book` / `isSubscribed`. **The anonymous payload is byte-for-byte what
a subscribed browser receives.** This kills three theories at once: that we are
asking wrong, that a parameter exists, and that a subscription would widen it.
Probed `?sport=Soccer`, `?league=lcup`, `?book=prizepicks` -- byte-identical
counts (5572 props, 21 soccer entities) every time.

The relay carries `prizepicks` (2,355 lines) and `draftkings-sb` (2,480) as
books, so it IS the single in for both. Its soccer board is simply 21 athletes
across four European fixtures today.

**Timing, not coverage.** The relay loads soccer near kickoff: the 08-19 archive
carried 370 MLS rows for games *that same day*. All seven archived days
(08-19..08-25), both sides of all 130 fixtures resolved against published
memberships: **zero cross-border pairings**. Every Liga MX fixture was Liga MX vs
Liga MX -- the Apertura, which runs concurrently.

`backend/watch_rotowire_lcup.py` polls every 15 min and ingests the moment a
fixture passes the cross-club guard. It picks up DraftKings and PrizePicks lines
together, because both are books in that one payload.

## What would unblock the 7 markets

1. **The relay posts them near kickoff** -- watcher is running, costs nothing.
2. **A PrizePicks payload fetched off a non-datacenter IP.** The block is
   IP-level Cloudflare on every host including `prizepicks.com` itself. One
   `curl` from a laptop produces a file the ingest can consume.
3. **the-odds-api.com** returns HTTP 401 to a fake key, i.e. it is reachable and
   only needs a real one. Free tier is 500 requests/month. Only route here that
   is a signup rather than a network change.

---

# Second pass, 2026-08-25 evening

The table above stands. This pass did not overturn it; it closed three sources it
had left open, corrected one claim made earlier today, and found that the ceiling
was not where we thought it was.

## 1. The relay defines TWELVE soccer markets, not eight

The section above says the relay "prices 8 of them (`SOCCER_GAME_MARKETS`)". That
is a statement about our mapping, not about the publisher. Measured across the
seven archived payloads plus the live one, `markets[]` where `sport == "Soccer"`
and `category == "Game"`:

```
 id  name                days seen   props
147  Chances Created         6          53
148  Fouls Committed         1           1     <- was discarded
151  Goals Allowed           2           2
152  Shots on Target         7         138
154  Saves                   7         138
155  Shots                   7         231
156  Passes                  3          26     <- was discarded
157  Clearances              6          47
158  Tackles                 5          16     <- was discarded
159  Crosses                 6          17
160  Fantasy Score           1           1     <- left absent on purpose
161  Passes Attempted        6         268
```

Three real stat markets were being counted as UNMAPPED and thrown away on every
run. Measured through `parse()` with the old and new mapping over the same five
archived days: **44 props recovered**, 1,446 -> 1,532 rows.

```
2026-08-21  230 -> 236     2026-08-24  220 -> 238
2026-08-22  442 -> 472     2026-08-25   62 ->  66
2026-08-23  492 -> 520
```

`160 Fantasy Score` stays unmapped deliberately, the same way the MLB Fantasy
Score ids do: it is a composite of a scoring formula the publisher does not send,
so nothing downstream could settle it. It still reports as UNMAPPED.

This does not by itself put a Leagues Cup prop on the board. It raises the ceiling
from 8 markets to 11 for the moment the relay posts one.

Gate: `TheSoccerCatalogueIsThePublishersNotOurs` in
`backend/test_ingest_rotowire_props.py`. Two assertions, deliberately different in
kind: one pins the mapping so weakening shows in a diff, one reads the archived
payloads and fails when the publisher ships an id we do not carry. Verified to
fail on the pre-fix mapping.

## 2. ESPN publishes 14 per-player stat fields for this competition; we store 4

The settlement half of the question, which the first pass did not ask.
`player_game_logs` for MLS holds `{"goals","assists","shots","sot"}` and nothing
else, across 21,177 rows. ESPN's own summary for a completed Leagues Cup fixture
(`soccer/concacaf.leagues.cup/summary?event=401863625`) carries fourteen, under
`rosters[].roster[].stats` -- not under `boxscore`, which holds only `teams`:

```
appearances      foulsCommitted   foulsSuffered   ownGoals
redCards         subIns           yellowCards     goalsConceded
saves            shotsFaced       goalAssists     shotsOnTarget
totalGoals       totalShots
```

Five of those settle markets we now map: `foulsCommitted`, `goalsConceded`,
`saves`, `shotsOnTarget`, `totalShots`. With goals, assists and cards that is
**eight settleable player stat markets for Leagues Cup, from a publisher we
already call**, at the cost of reading fields we currently discard.

Not published by ESPN, so still unsettleable if priced: passes, passes attempted,
tackles, clearances, crosses, chances created.

Related defect, unfixed: the props table carries both `sot` (21 rows) and
`shots_on_target` (12) for MLS. One stat, two keys.

## 3. Three sources closed

- **Kalshi.** Enumerated all 3,511 series under `category=Sports`. Eleven Leagues
  Cup series exist (`KXLEAGUESCUP`, `...GAME`, `...SPREAD`, `...TOTAL`, `...BTTS`,
  `...SCORE`, `...FTTS`, `...ADVANCE`, `...TEAMTOTAL`, `...1H*`) and every one is
  team-level. There is **no soccer player-stat series anywhere on Kalshi**, for
  any competition. Not a coverage gap for this tournament; the product does not
  exist there.
- **Action Network.** `api.actionnetwork.com/web/v2/scoreboard/<slug>` answers
  unauthenticated. Soccer is Europe only (epl, laliga, seriea, champions, europa).
  The `mls` slug is valid and returns 0 games for 08-24..08-27 while returning
  472KB for 08-29, so the emptiness is the tournament pause, not a broken slug.
  No Leagues Cup.
- **Bovada, properly asked.** Dropping `marketFilterId=def` from the per-event
  path returns **64 market groups instead of 3**, including `Player Specials` and
  `Requested Specials` that the coupon view never shows. Scanned every outcome on
  all four fixtures -- **2,213 of them**. The only stat vocabulary present is
  `assist` (115, all inside combo parlays) and `shots` (36, nearly all combos).
  Zero passes, tackles, clearances, saves, fouls, offsides, crosses. The first
  pass's "1 outcome only" was right; this says it exhaustively.

## 4. A correction to a claim made earlier today

The OpticOdds 401 does **not** confirm that `north_america_-_leagues_cup` is a
valid league id. The endpoint authenticates before it validates:

```
league=north_america_-_leagues_cup   -> 401 {"error":"API key is required"}
league=zzz_not_a_real_league_xyz     -> 401 {"error":"API key is required"}
sport=underwater_basketweaving       -> 401 {"error":"API key is required"}
no parameters at all                 -> 401 {"error":"API key is required"}
```

All four are byte-identical. The 401 proves the host is reachable and nothing
more. OpticOdds' own public `/sports/soccer` page names MLS and Liga MX and does
not mention Leagues Cup or CONCACAF anywhere; its sitemap (1,259 URLs) is
marketing only, with no per-league coverage pages. Their Leagues Cup support is
still plausible and still unverified.

## 5. Also re-measured, no change

PrizePicks refuses `api.`, `partner-api.`, `app.` and `www.` with the **same
Cloudflare ray id** on all four, which is an estate-wide IP block rather than one
gated endpoint. Sleeper (6.4MB, unauthenticated) is LaLiga + EPL. Underdog
(22MB, unauthenticated) carries 21 FIFA fixtures, all European, and 8 soccer stat
markets -- the product exists, the competition does not. Dabble's US competition
list has no soccer at all. RotoWire's own soccer sportsbook table
(`/betting/soccer/tables/all-bets-props.php?date=`) supports five markets and all
five are goal-scoring; empty across 15 days either way.

---

# CORRECTION, 2026-08-25 ~19:20 UTC: it was never timing

The section "**Timing, not coverage**" above is **WRONG** and is superseded by
this one. It is left in place because the reasoning that produced it is the
thing worth keeping.

## The observation

The user, looking at PrizePicks directly on a non-blocked machine, saw Leagues
Cup player props live on the board:

```
Victor Olatunji    Salt Lake - Attacker   @ Leon Tue 9:30pm    2.5  Shots
Saba Lobjanidze    Salt Lake - Attacker   @ Leon Tue 9:30pm    2.5  Shots
Alfonso Alvarado   Leon - Attacker        vs Salt Lake         1.5  Shots
Dominik Marczuk    Salt Lake - Attacker   @ Leon Tue 9:30pm    1.5  Shots
```

The live relay payload was searched for those four surnames and for all eight
Leagues Cup clubs at the same moment. **Zero hits in 6.6MB.** The relay's entire
PrizePicks soccer board was 22 props on ONE fixture, Real Madrid vs Real
Sociedad: Mbappe, Vinicius, Bellingham, Courtois, Huijsen, Aramburu, Gomez.

## What that means

**RotoWire's relay is a curated subset of PrizePicks, not a mirror of it.** It
republishes a marquee European fixture and drops CONCACAF. `lines.php` carrying
`prizepicks` as a book means we can reach *what RotoWire chose to republish* --
not that we can reach PrizePicks.

The earlier reasoning was sound and still wrong. `lines.php` takes no parameters,
the anonymous payload is byte-identical to a subscribed browser's, and the 08-19
archive did carry 370 MLS rows for same-day games. Every one of those is true.
The conclusion drawn from them -- that an empty soccer board meant "not posted
yet" -- was never tested against what PrizePicks itself was showing at that
moment. **A publisher's silence is only evidence about the publisher.** We had no
independent read on the upstream, so "not posted yet" and "not carried at all"
were indistinguishable, and the audit picked one and wrote it down as fact.

## Consequences

1. `backend/watch_rotowire_lcup.py` will not find these props no matter how long
   it polls. It is not worth waiting on for this tournament. It is still correct
   for MLS, where the relay does carry the board.
2. The only route to Leagues Cup player stat props is a PrizePicks fetch from a
   non-datacenter IP. `backend/tools/pull_prizepicks.py` does that: standard
   library only, no arguments, writes one bundle and prints the soccer markets
   it found. Verified to fail loudly with the right message from this box.
3. Item 1 under "What would unblock the 7 markets" above is withdrawn. Item 2 is
   the whole answer.

## The shape, for next time

This is the same shape as the 2026-08-12 `SOCIAL_SOURCES` miss and the ESPN
"gap is a statement about which endpoint we asked" rule: **a relay's book list is
a claim about the relay, not about the book.** Before treating a downstream feed
as a proxy for an upstream one, get one independent read of the upstream -- even
a screenshot from a phone -- and diff them. One such read this afternoon would
have saved the entire watcher premise.
