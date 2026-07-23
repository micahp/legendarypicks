# Adding Underdog props to the board + settling them (2026-07-23)

Follow-up to `docs/UNDERDOG-API-RECON-2026-07-23.md` (what's in the API). This doc is about the
two things actually asked for: (1) what it'd take to put these lines on our board across every
sport the API covers, not just UFC, and (2) whether we can compute hit/miss after the
game/match/fight ends — including esports. Short answer on settlement: **it depends entirely on
whether a durable per-player actuals record already exists for that sport**, and that varies a
lot by sport — this isn't one uniform lift.

## The board side (adding the lines)

Mechanically straightforward regardless of sport, because it reuses the existing `props` table
shape: `source='underdog'` alongside the existing `source='bovada'` rows, same
player/market/line/side columns. The only real per-sport work is a market-name mapping (Underdog's
`over_under.title` strings → our canonical market names), same kind of mapping
`bovada_scraper.py`'s `MARKET_MAP` already does for Bovada. One meaningful schema wrinkle: Underdog
has no traditional odds (see the open question in the recon doc — DFS payout structure, not
American odds), so whatever ingestion script is built needs an `odds` column strategy — likely
NULL/omitted for Underdog rows, with EV computation skipped for that source (edge = our projection
vs. their line directly, not de-vig).

## The settlement side (computing hit/miss) — this is the part that varies

Settlement needs one thing: a durable, post-game record of the REAL final stat value for that
exact player in that exact game/match/fight, to compare against the line. Checked what actually
exists per sport, not assumed:

### Already have it — settlement is straightforward

**MLB, NBA, NHL, UFC**: all have real durable per-game actuals in `player_game_logs` already
(statcast/statcast_pitcher, espn, nhle.com, and tonight's new espn_mma_stats respectively).
Settlement here is the same pattern already used for Bovada props — join a settled prop's
player_id + game_date to the matching `player_game_logs` row, extract the stat, compare to the
line. No new infrastructure, just a market-name mapping per sport (same shape as the
`_LEAGUE_MARKET_STAT` dicts added tonight for EV, though settlement and EV-projection are separate
concerns using the same underlying table).

### Reachable live, but NOT persisted anywhere — needs new capture work

**Esports (CS2/Dota via GRID, LoL via Riot's live-stats)**: checked the actual client code, not
assumed. `backend/routers/esports/grid.py`'s `_grid_state()` pulls `players { name kills deaths }`
from GRID's live series-state API — real per-player data, but series-level (not confirmed
per-map, and GRID's schema may support more than we currently request — headshots isn't even
asked for today) and used ONLY to enrich the live board display in-memory. Nothing writes it to a
durable table. `backend/routers/esports/lol.py` similarly pulls real per-player
kills/deaths/assists from Riot's live-stats window — also live-only, also never persisted.
**To settle an Underdog esports prop, someone has to build a "capture player stats at match-end and
write them somewhere durable" step that does not exist today** — the data is reachable, it's just
never saved past the live view. Also needs confirming GRID's schema actually supports per-map
breakdowns and headshots specifically (Underdog's markets are literally "Kills on Maps 1+2" and
"Headshots on Maps 1+2" — if GRID only gives series totals, that's a mismatch to resolve first).

### Nothing exists yet — this is a from-scratch build

**Tennis**: zero actuals infrastructure. Confirmed directly: `player_game_logs` has 0 rows for
league IN ('atp','wta'). There's no per-match stat source connected anywhere in this codebase
today (unlike esports, which at least has a *live* feed to build on) — settling a tennis prop
("1st Set Games Played") needs a real per-match data source found and ingested from zero, not
just a persistence layer added to something that already exists.

### Doesn't apply

**NFL**: Underdog's NFL board is season-long futures only (confirmed in the recon doc), so
"settle after the game" isn't the right frame for it at all — a season-total prop settles at
season's end, not per-game. Not blocked on anything, just a different kind of market.

## Suggested sequencing, if this gets built

Not a decision, just the order the evidence points to: MLB/NBA/NHL/UFC first (zero new
infrastructure, pure mapping work, and NBA/NHL are off-season so verifiable-but-not-provable the
same way tonight's EV/CLV work is), esports second (real work — a capture-at-match-end
persistence layer, plus confirming GRID's per-map/headshot support), tennis last (genuinely
new data-source recon, comparable in size to the UFC ESPN-stats work from tonight, not a quick
add).
