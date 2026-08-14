# UFC and MLS prop settlement diagnosis — 2026-08-14

This report records the observed failure before any settlement code was changed. All
production queries used SQLite URI `mode=ro` plus `PRAGMA query_only=ON`. The production
database was never opened writable. ESPN requests used
`LP_ESPN_CACHE_DIR=/tmp/lp-ufc-settlement-espn-cache` and an explicit per-host budget.

## UFC: exact production failure

The walked fight was production `prop_games.id=376`:

| field | value |
|---|---|
| date / start | `2026-07-25` / `2026-07-25T17:20:00+00:00` |
| home / away | `Steve Erceg` / `Ramazan Temirov` |
| stored `espn_event_id` | `401874315` |
| final columns | `final_home=NULL`, `final_away=NULL` |
| unsettled props | 6 |

The six joined prop/player rows are:

| prop ids | player row | player payload | markets |
|---|---|---|---|
| 205922–205924 | 30050 | `Steve Erceg`, team=`Ramazan Temirov`, ESPN id=`4997217` | `win_by_ko`, `win_by_submission`, `win_by_decision`; each over 0.5 |
| 205925–205927 | 30051 | `Ramazan Temirov`, team=`Steve Erceg`, ESPN id=`4895691` | `win_by_ko`, `win_by_submission`, `win_by_decision`; each over 0.5 |

`settle_props.py:23-35` selects this row because it has a non-empty ESPN id and six
props with no `prop_results`. `settle_props.py:74` calls `settle_game(con, 376)`.
`settlement.py:666-673` reads the values above. Because `final_home` is null, execution
reaches exactly `settlement.py:717`:

```text
result = espn.game_result("ufc", "401874315")
```

That calls the site summary URL with `event=401874315`. The real response was HTTP 404.
The exception is caught at `settlement.py:741-743`, producing:

```text
{"settled": 0, "void": 0, "unmappable": 0, "errors": 1,
 "error_msg": "game 376: ESPN pull failed: HTTP Error 404: Not Found"}
```

This is the first stopping point. `401874315` is a fight competition id, despite being
stored in a column named `espn_event_id`. The real `2026-07-25` MMA scoreboard pairs it
with parent card event `600059667`. MMA summary also returned HTTP 404 for that parent
card id, so substituting the parent id would not make the generic summary/boxscore path
work.

## UFC: independent defects after the first stop

This is several incompatible contracts, not one missing map entry.

1. **Finality/id shape.** The site scoreboard's raw competition object for fight
   `401874315` reports:

   ```text
   status.type = {completed: true, state: "post", description: "Final"}
   status.period = 1
   status.clock = 261.0
   status.displayClock = "4:21"
   competitors = [
     {id: "4895691", order: 2, winner: true,  athlete.displayName: "Ramazan Temirov"},
     {id: "4997217", order: 1, winner: false, athlete.displayName: "Steve Erceg"}
   ]
   ```

   The fight has `order`, athlete competitors, and no `homeAway`, team object, or score.
   Generic `game_result()` expects team competitors with `homeAway` and scores. UFC must
   locate the fight inside the card scoreboard and gate on the fight competition's own
   `status.type.completed` field.

2. **No MMA summary boxscore.** Both MMA summary requests returned 404. The raw
   scoreboard competitor objects have `statistics=[]`; there is no generic
   `boxscore.players` surface for this fight. Therefore the call at
   `settlement.py:768` and the team/category extractor at `settlement.py:136` are not
   UFC actuals sources.

3. **No UFC entries in `MARKET_STAT`.** Every production market reaches
   `resolve_market()` as unmapped if execution gets to `settlement.py:794`.
   Production has 122 UFC props: 70 `win_by_decision`, 26 `win_by_ko`, and 26
   `win_by_submission`. The generic unmappable branch at lines 795-800 would insert a
   null result rather than grade them.

4. **The player join itself is not the production blocker.** All 122 UFC props join
   through `props.player_id -> players.id`; 117 have an ESPN athlete id. For the walked
   fight the join is 6/6 and both athlete ids match the publisher. The player `team`
   values are opponent names, so the generic team-group matcher would still be the
   wrong UFC identity contract even though the relational join succeeds.

## UFC actuals source and market decision

The intended durable actuals source already exists in `player_game_logs`. Production
has 119 UFC log rows covering 99 fights. For the walked fight it has one row per fighter,
keyed by fight id and ESPN athlete id:

| fighter | published log values |
|---|---|
| Ramazan Temirov | `result="W"`, `method="KO/TKO"`, `sigStrikesLanded=27`, `fight_time=4.35`, `fight_time_seconds=261.0` |
| Steve Erceg | `result="L"`, `method="KO/TKO"`, `sigStrikesLanded=11`, `fight_time=4.35`, `fight_time_seconds=261.0` |

Those rows were persisted by the UFC ingest from the publisher's per-fight status and
statistics objects. Across the 114 production UFC props whose games are linked, 89
currently join to such a durable fighter/fight log. A missing log is an ingestion/data
availability gap and must remain retryable; it is not evidence that the fighter recorded
zero.

The evidence-backed settlement split is:

| market strings | decision | published field / rule |
|---|---|---|
| `significant_strikes` | settleable when a matching log exists | numeric `sigStrikesLanded` |
| `fight_time` | settleable when a matching log exists | numeric `fight_time` in minutes |
| `win_by_decision` | settleable when a matching log exists | 1 only for publisher `result="W"` and `method="DEC"`; otherwise 0 |
| `win_by_ko`, `knockouts` | settleable when a matching log exists | the repository records both as win-by-method props; 1 only for `W` + `KO/TKO` |
| `win_by_submission`, `submissions` | settleable when a matching log exists | the repository records both as win-by-method props; 1 only for `W` + `SUB` |
| `finishes` | **not settled by this change** | the source label alone does not define whether DQ or other stoppages count; choosing a method set would invent a grading rule |

The worktree's 272 UFC props comprise 92 `win_by_decision`, 62
`significant_strikes`, 38 `finishes`, 28 `fight_time`, 26 `submissions`, and 26
`knockouts`. Thus 234 have a defined actual contract once their game and durable log are
available; 38 `finishes` remain explicitly unsupported pending a recorded source rule.

## MLS: real event 761469

MLS has a related but different source-shape defect. The worktree's game 692 has 68
props (goals and assists) but was not linked in this older database copy; the measured
publisher event is `761469`, New England Revolution 0–2 Houston Dynamo FC, completed
full time.

`summary.boxscore` is non-empty but contains only `{"teams": [...]}`. It has no
`players`, so adding a guessed category/key pair to `MARKET_STAT` would still make
`_find_player_stat()` return no value. The same summary directly publishes the player
actuals under `summary.rosters[].roster[]`:

```text
athlete.id / athlete.displayName
stats[] = [
  {name: "goalAssists", abbreviation: "A", value: 0.0, ...},
  {name: "totalGoals", abbreviation: "G", value: 0.0, ...},
  ...
]
```

There are two roster groups and 40 unique athlete ids. Against game 692's 68 prop
rows, ESPN-id-first and unique-normalized-name fallback matches 57 rows (39 by id, 18
by name); 11 players are absent from the match roster and should follow the existing
DNP/void contract. The non-zero facts include:

| athlete | `totalGoals` | `goalAssists` |
|---|---:|---:|
| Guilherme Augusto | 1 | 0 |
| Agustín Resch | 1 | 0 |
| Jack McGlynn | 0 | 1 |

Both MLS markets are therefore settleable without inventing keys: `goals` maps to the
publisher's `totalGoals`, and `assists` maps to `goalAssists`, read from the soccer
roster surface rather than generic boxscore players.

## Why World Cup is not the path to reuse

There is no WC special settlement path. WC falls through the generic loop with no
`MARKET_STAT` rows, reaches `settlement.py:795-800`, and inserts a `prop_results` row
whose `actual_value` and `hit` are both null for every unmapped prop. In the worktree
database all 1,128 WC props have result rows, but all 1,128 have null actuals and null
hits. Production has the same pattern for its 392 WC result rows. That is false settled
coverage, not successful grading, and it is not a pattern to copy into MLS or UFC.
