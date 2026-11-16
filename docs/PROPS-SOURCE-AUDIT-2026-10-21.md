# Props source audit, 2026-10-21: what three reachable books add

Follows [PROPS-SOURCE-AUDIT-2026-08-25.md](PROPS-SOURCE-AUDIT-2026-08-25.md). That audit
found most books refused this box. This one re-probes ten books with a browser User-Agent,
then catalogs the three that answer (Sleeper, Pinnacle, FanDuel) against the markets we
already store per league (prod `props`, last 7 days).

**Bottom line.** PrizePicks and DraftKings still block this box at the edge; a browser
User-Agent changes nothing. We already get both, and FanDuel and Sleeper, through the
RotoWire relay. The three reachable books add a handful of markets we do not store, a
sharp reference price (Pinnacle), and direct lines instead of relayed ones. None of them
is a results source: NBA game results still come from ESPN alone for 2026-27.

## Method

- One GET per site, browser User-Agent, no retries, nothing to get past a block. A 403 or
  429 stopped that site.
- Catalog pass paced at 1.5 s per request: Sleeper 1 request, Pinnacle 1 per sport (7),
  FanDuel 1 league page plus 1 game page plus each player-prop tab of that game.
- Run from this box: Contabo, St. Louis, US (AS40021).
- A 400 or 404 means the endpoint guess was wrong. It is not recorded as a block.

## Reachability

| Book | Result | Edge | Reading |
|---|---|---|---|
| PrizePicks | 403 | Cloudflare | blocked, as in August |
| DraftKings | 403 | Akamai challenge | blocked, as in August |
| Caesars | 403 | CloudFront | blocked |
| BetMGM | 403 | Cloudflare | blocked |
| ParlayPlay | 403 | Cloudflare challenge | blocked |
| BetRivers | 400 | Cloudflare | wrong endpoint, unknown |
| Hard Rock | 405 | Cloudflare | wrong endpoint, unknown |
| **FanDuel** | **200** | CloudFront | **open**; August's 400 was a wrong endpoint |
| **Pinnacle** | **200** | Cloudflare | open (guest API) |
| **Sleeper** | **200** | Cloudflare | open, no key |

Not a book, but probed in the same pass: `cdn.nba.com` live boxscores return **403 Access
Denied (Akamai)**, like `stats.nba.com`. The NBA's own feeds are not a second results source
from this box.

## Endpoints

```
Sleeper   https://api.sleeper.app/lines/available                      (all sports, one call, ~6 MB)
Pinnacle  https://guest.api.arcadia.pinnacle.com/0.1/sports/{id}/matchups?withSpecials=true&brandId=0
          sport ids: basketball 4, football 15, hockey 19, baseball 3, soccer 29, mma 22, tennis 33
FanDuel   https://sbapi.oh.sportsbook.fanduel.com/api/content-managed-page?page=CUSTOM&customPageId={nba|nfl|nhl|mlb|ncaaf}&_ak=FhMFpcPWXMeyZxOx
          https://sbapi.oh.sportsbook.fanduel.com/api/event-page?_ak=FhMFpcPWXMeyZxOx&eventId={id}&tab={tab-slug}
```

FanDuel lists simulated games on the NBA page (team names like "ABYSS" in parentheses)
alongside real ones; filter them out. MLB game names carry starting pitchers in parentheses,
so a parentheses filter drops real MLB games too. `customPageId` values for MLS, UFC and
tennis (`mls`, `soccer`, `ufc`, `mma`, `tennis`, `atp`) all returned 404 and are unknown.

## Markets we do not store, by league

| League | Missing market | Sleeper | Pinnacle | FanDuel |
|---|---|---|---|---|
| NBA | **steals** (10-market scope) | 82 | | O/U and 1+..5+ ladder |
| NBA | **blocks** (10-market scope) | 35 | | 1+..4+ ladder |
| NBA | PTS+REB, PTS+AST, REB+AST | 149, 121, 118 | | yes |
| NBA | 1st-quarter points | 92 | | yes |
| NBA | double-double, BLK+STL | 25, 7 | | |
| NBA | made-threes ladder (1+..8+) | | | yes |
| NHL | power-play points | 17 | | |
| NHL | 1+/2+/3+ points, assists, SOG ladders | | | yes |
| MLB | runs, singles, RBIs, batter walks, stolen bases | 18, 18, 12, 15, 4 | | |
| MLB | home runs | | 18 | |
| NFL | fantasy points | 91 | | |
| NFL | 2+/3+ TD scorer, quarter yards, alt lines | | | yes |
| NCAAF | fantasy points, field goals made | 66, 1 | | |
| UFC | takedowns | 6 | | |

Counts are lines on 2026-10-21 for that day's slate. MLB is the World Series (two teams).
RotoWire already relays most of the NBA rows; steals and blocks were mapped in the 10-20
NBA work but had not been ingested yet when this was written.

NBA field goals made and free throws made were not found on 2026-10-21 in Sleeper's feed,
Pinnacle's NBA specials, the one FanDuel NBA game scanned (Hawks @ Magic), or that day's
RotoWire relay. That is one day and one FanDuel game, not a finding that no book offers them.

## What each book is good for

- **Sleeper**: the widest pick'em catalog we can reach. One request covers every sport.
  Lines carry Sleeper's own `subject_id`, not names, so an ingest must resolve identity
  through a published roster and queue misses, never mint `players` rows. Its public feed
  has **no MLS** today: soccer is EPL, La Liga and the Champions League only (51 lines,
  mostly goalkeeper goals-against). The app does show MLS lines (Micah, 2026-10-21: Cavan
  Sullivan 0.5 goals), and neither this feed nor the RotoWire relay carries that line, so
  the app reads a different, signed-in feed. Building on a signed-in personal token is
  against Sleeper's terms and is not done.
- **Pinnacle**: the sharp book, and the one book here RotoWire does not relay. Player
  props are core markets only (NBA points, rebounds, threes, assists; NFL and NHL core;
  MLB total bases, home runs, pitcher outs, strikeouts). Not yet confirmed whether every
  "Total Points" special is a single-game line; the same listing also holds season-long
  specials such as "Total Regular Season Wins". Soccer is team markets only.
- **FanDuel**: deepest per-game menus (NBA 151 player market types on one game, every
  runner priced). Already relayed by RotoWire for the main lines; direct adds ladders,
  quarter props and alternates. Player markets live on per-game tabs, so a full slate is
  one request per tab per game.

## Not settled here

- FanDuel MLB, MLS, UFC and tennis: page ids unknown.
- BetRivers and Hard Rock: the endpoints were guesses; reachability unknown.
- Pinnacle single-game vs season-long specials.
- Where Sleeper's app gets MLS lines.
