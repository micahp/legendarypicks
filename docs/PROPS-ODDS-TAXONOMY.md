# Props odds taxonomy: real sportsbook odds vs pick'em placeholders

Measured 2026-08-29, dev DB (`picks.dev.db`), DB-only (no network re-reads).
This doc answers three questions: which `props.source` values carry real
sportsbook odds, which league+market combinations have real coverage at all,
and which offer the props board must pick as its default line. It is the spec
the MarketSlateBoard default-line rule implements.

## 1. The classification

The relay (`lines.php`) reports an `odds` value for every book, but the pick'em
books' values are **not prices** — they are a flat placeholder, identical on
every row regardless of the actual offer. Measured across 400 sampled rows per
source:

| source | rows sampled | distinct odds | verdict |
|---|---|---|---|
| `bovada` | 400 | 69 | **REAL** — true American prices |
| `underdog` (direct ingest) | 400 | 187 | **REAL** — true prices (UFC only, see §4) |
| `rotowire:sleeper` | 400 | 60 | **REAL** — Sleeper is a sportsbook here |
| `rotowire:draftkings-sb` | 400 | 178 | **REAL** |
| `rotowire:fanduel-sb` | 322 | 59 | **REAL** |
| `rotowire:caesars-sb` | 400 | 95 | **REAL** |
| `rotowire:hardrock-sb` | 400 | 55 | **REAL** |
| `rotowire:betmgm-sb` | 2,856 (all) | — | **REAL** |
| `rotowire:betrivers-sb` | 126 (all) | — | **REAL** |
| legacy: `kambi`, `rotowire:pick6`, `rotowire:rtsports` | all | varied | **REAL** |
| `rotowire:prizepicks` | 400 | **1** (-137) | **PLACEHOLDER** |
| `rotowire:underdog` | 400 | **1** (-137) | **PLACEHOLDER** |
| `prizepicks`, `prizepicks-demon`, `prizepicks-goblin` (direct pull) | 1,543 | 0 (odds NULL) | **PLACEHOLDER** |

The `-sb` suffix in a relay source name means "sportsbook". Every `-sb` source
carries varied, book-specific prices; every pick'em source carries -137 or NULL.

## 2. Real-vs-real agreement, and why the default book matters

29,554 pairs exist where two REAL sources price the identical
(game, player, market, line, side). Books genuinely disagree:

| metric | value |
|---|---|
| median odds delta | 17 |
| mean odds delta | 65.3 |
| favorite/underdog SIGN flips | 6,280 pairs (21.2%) |
| within ±10 | 38.1% |

Heaviest overlap: hardrock↔sleeper (5,000), DK↔hardrock (4,206), DK↔sleeper
(3,824). By league: MLB 29,028 pairs, NFL 526 (and NFL is tight — median delta
5-12 on yardage markets). Two books rarely agree exactly, so **which book is
the default is a product decision, not a detail** — this doc fixes it to
"lowest line among real-odds offers" so it is at least deterministic.

## 3. Market-by-market: who has real odds

### Bovada is the ONLY real source (11 league/markets)

- **ATP/WTA**: `match_winner`, `total_games`, `win_a_set` — all tennis
- **MLB**: `total_doubles`, `total_hits,_runs_and_rbis` (27,205 rows),
  `total_pitcher_walks`
- **MLS**: `card_shown`
- **UFC**: `win_by_decision`
- **WC**: `goals`, `assists`, `shots`, `shots_on_target`
- **LCUP**: `goals`, `first_goal_scorer`

### Bovada co-exists with other real books (7)

MLB `earned_runs`, `hits_allowed`, `outs`, `strikeouts`, `total_bases`;
MLS `goals`, `first_goal_scorer`, `goal_or_assist`, `assists` (vs legacy
`kambi`).

### Bovada absent, other real books cover (16)

- **MLB hitting**: `hits`, `runs`, `rbis`, `hits_runs_rbis`, `batter_walks`,
  `doubles`, `home_runs`, `walks` — sleeper/hardrock/DK/betmgm. (Bovada's
  `total_hits,_runs_and_rbis` is a different market KEY than the relay's
  `hits_runs_rbis`; they overlap semantically, not in the table.)
- **NFL core player board**: `passing_yards`, `receiving_yards`,
  `rushing_yards`, `receptions`, `passing_touchdowns`, `total_touchdowns`,
  `passing_rushing_yards`, `rushing_receiving_yards`,
  `interceptions_thrown` — via the relay `-sb` books + sleeper. Bovada carries
  zero NFL player props (team markets only; see `bovada_scraper/parsers.py`
  team-market fix, 2026-08-24).
- **UFC stats**: `significant_strikes`, `finishes`, `knockouts`,
  `submissions`, `fight_time` — direct `underdog` only.

### NO real source at all — placeholder-only markets

These exist in `props` ONLY through the -137 placeholder sources:

- **MLS, all 7 depth markets** (the ones RotoWire was brought in for):
  `passes_attempted`, `saves`, `shots`, `shots_on_target`, `clearances`,
  `crosses`, `chances_created`
- **NFL special teams / depth**: `kicking_points`, `field_goals_made`,
  `extra_points_made`, `pass_attempts`, `pass_completions`,
  `rush_attempts`, `sacks`, `targets`, `rushing_touchdowns`,
  `rushing_receiving_touchdowns`

56.6% of placeholder line-slots (2,506 of 4,426) have no real book on that
line. **This is why the placeholder sources must keep being ingested**: they
are the sole coverage for MLS entirely and NFL depth markets. Dropping them
empties those boards.

## 4. Underdog direct vs relay underdog — no conflict

`underdog` (direct ingest) and `rotowire:underdog` (relay) have ZERO overlap:
different competitions (direct = UFC only, all six capture dates are UFC
cards; relay = NFL/MLB etc.), zero shared game_ids, zero shared player_ids.
They are different products from the same publisher: the direct feed prices
UFC props with real odds; the relay carries pick'em lines for team sports.
No dedupe decision is needed between them.

## 5. The default-line rule (the spec this doc exists for)

Scope: the props page **Props tab** (`components/Props/MarketSlateBoard.tsx`)
only. Game detail's Props tab is out of scope.

The board consolidates props into one card per (player, market, game); each
card's dropdown lists offers as `line · source`. Today the default selection
is `row.lines[0]` after a (line, source) sort — the lowest line regardless of
whether its odds are real. The rule:

1. Classify each offer by its `source` against the table in §1. The
   classification lives in the frontend (a source-name set) — the `source`
   column is already on every row the API returns; no backend change.
2. **If any offer on the card has real odds**, the default selection is the
   offer with the **lowest line among real-odds offers** (its real odds are
   then what the card displays).
3. **If no offer has real odds**, fall back to today's behavior: lowest line
   overall (placeholder odds shown — for the MLS/NFL-depth markets in §3 that
   is the only option).
4. The dropdown still lists every offer, real and placeholder. The rule only
   picks the initial selection; a user can always switch.

Ties (two real books, same lowest line): prefer the source listed first in
§1's REAL table order — stable, and deterministic across renders.

## 6. What would change this doc

- A pick'em book publishing real prices (PrizePicks odds stopping being -137)
- A relay `-sb` book appearing with constant odds
- A real book adding MLS depth markets (then §3's placeholder-only table
  shrinks and the default rule covers more of the board)
