# League data sources & field classification (2026-08-06)

Branch: feat/league-mls-ncaaf. This doc answers, per league: which publisher is
the source of truth (and why), what the publisher provides, and which fields we
ingest. Written BEFORE the ingests run — the field lists below are the contract
the MANIFEST entries in audit_league_stats.py assert.

## Source selection

### MLS — ESPN `soccer/leagues/usa.1` (PRIMARY; only free no-key option)
Alternatives checked 2026-08-06:
- FotMob / FBref: publish the data but have no stable public API; FBref is
  scrape-only and ToS-restricted. Rejected (scraping hostile surface).
- MLS official (mlssoccer.com): no public stats API for player game logs.
- Underdog/Bovada prop feeds: odds only, not game logs.
ESPN's core API (sports.core.api.espn.com) publishes season types, event
collections with limit=1 count envelopes, and per-game summaries with rosters —
the same contract the NFL/NBA/NHL/MLB ingests already reconcile against. It is
the only source that satisfies the project's published-first doctrine (count
envelopes to prove completeness).

### NCAAF — ESPN `football/leagues/college-football` (PRIMARY for reconcile; CFBD for log rows)
Alternatives checked 2026-08-06 (docs/PROVIDER-AUDIT-2026-08-06.md):
- CollegeFootballData (api.collegefootballdata.com): **CORRECTED — the earlier
  "season-level not per-game" claim was WRONG** (recorded without an endpoint —
  a published-first §2b violation). CFBD publishes per-game player box scores:
  `GET /games/players?year=&seasonType=regular&classification=fbs` → player,
  team, opponent, week, position, category, stat/value (passing/rushing/
  receiving/defensive). Free tier = 1,000 calls/mo, no card. Request cost ~1-6
  per season vs 888 ESPN per-game summaries. **ADOPT for log rows**; ESPN group-80
  retained for count envelopes/reconcile.
- cfbfastR (sportsdataverse): a wrapper — and it wraps ESPN's own endpoints
  (espn_cfb_game_player_statistics etc.). Rejected (indirection + R dependency).
- Sports Reference: scrape-only, ToS blocks bots. Rejected.
ESPN remains the reconcile authority (group 80 published counts); CFBD becomes
the per-game log source. Both vocabularies must converge on the same team codes
and the same game population (CFBD seasonType=regular + classification=fbs vs
ESPN group 80) — that convergence is a reconcile check, not an assumption.

### Tennis (props only) — Bovada primary, Kalshi second book, ESPN for match shape
Bovada's open coupon API is the existing prop source (bovada_scraper.py),
verified 188 ATP + 187 WTA props. Kalshi ALSO publishes tennis match markets
(VERIFIED live 2026-08-06: series KXATPMATCH/KXWTAMATCH, ATP Montreal + WTA
Toronto; read API api.elections.kalshi.com/trade-api/v2 public, no key) —
the fallback book is now real for Kalshi. tennis-data.co.uk provides free
historical results + closing odds (ATP 2000+, WTA 2007+) for prop backtests
(not live). Underdog has tennis as a product but tennis rows unconfirmed in
payload — treat as fallback, verify shape at implementation. ESPN tennis/atp
+ tennis/wta provide scoreboard/summary shape. No game-log stats are ingested
for tennis (see gaps).

## Field classification

### MLS — ESPN soccer summary `rosters[].roster[].stats`
Published per-player stat labels (measured from a completed 2025 summary):
appearances, minutes (sometimes), goals, assists, shots, shots on goal, fouls,
offsides, and per-match event counts. We map ONLY:

| our key | published alias(es) | notes |
|---|---|---|
| goals | goals / goal / totalgoals | `_TARGET_STATS` in ingest_soccer_logs.py |
| assists | assists / assist / goalassists | |
| shots | shots / shot / totalshots | |
| sot | sog / sot / shotsongoal / shotsontarget | shots on target |
| (context cols) | game_id, game_date, team, opponent, home_away, game_type | written NOT NULL from the published type name |

Not ingested (documented gap, do not claim): fouls, offsides, yellow/red cards,
minutes when ESPN omits it, expected goals (ESPN publishes xG only for some
matches), saves (goalkeeper line — GK records no saves in this summary shape;
see LEAGUE-STAT-GAPS). A substitute appearance is a PLAYED row — the row exists;
minutes is the honest denominator and the UI shows it when present.

### NCAAF — ESPN football summary `boxscore.players[].statistics[]`
Published stat groups per completed FBS summary (measured): passing
(C/ATT, YDS, AVG, TD, INT, QBR), rushing (CAR, YDS, AVG, TD, LONG), receiving
(REC, YDS, AVG, TD, LONG), plus defensive/tackles and kicking groups. We map
ONLY the offensive line (football fantasy-relevant):

| our key | published (group, label) | notes |
|---|---|---|
| att | passing C/ATT | `_STAT_MAP` in ingest_ncaaf_logs.py |
| pass_yds | passing YDS | |
| pass_td | passing TD | |
| intc | passing INT | |
| rush_yds | rushing YDS | |
| rush_td | rushing TD | |
| rec | receiving REC | |
| rec_yds | receiving YDS | |
| rec_td | receiving TD | |
| (context cols) | game_id, game_date, team, opponent, home_away, game_type='REG' | group 80 (FBS) only |

Not ingested (documented gap): passing AVG/QBR, rushing AVG/LONG, receiving
AVG/LONG, ALL defensive/tackles, kicking/punting, fumbles, penalties. A
quarterback's rushing line is included (dual-threat QBs carry both groups).

### Tennis — Bovada prop markets (atp/wta)
Bovada slugs: `{BOVADA}/tennis/atp` and `{BOVADA}/tennis/wta`. Player-attributed
match-level markets parsed by `_parse_tennis_props` (verified live 2026-08-06,
ATP Montreal + WTA Toronto):
- match winner (moneyline) → `match_winner` (yes/no per player)
- player total games O/U ("Total Games O/U - <Player>") → `total_games`
- set betting ("<Player> 2 - 0" exact-set ladders) → `set_betting___<sets>_<sets>`
- player to win at least one set ("Will <Player> Win At Least One Set?") → `win_a_set`
`total_sets` is published but is match-level only (O/U 2.5, no player attribution)
— deferred, same as UFC fight-level markets; no player-attributed form exists.
Charting from player_game_logs requires a tennis game-log ingest that does not
exist — `_MARKET_STAT_KEY` entries for atp/wta are None until that lands (never
fabricate a stat key).

## Completeness measurement (published-first §6)
Expected totals come from ESPN limit=1 count envelopes, asserted by
reconcile_totals.py:
- MLS 2025: type 1 (Regular Season) = 510 events, teams = 30.
- NCAAF 2025: type 2 (Regular Season) group 80 = 888 events, teams = 146.
Coverage rows land via `reconcile_totals.py --write-coverage`; only
`status=complete` is offered in the UI.
