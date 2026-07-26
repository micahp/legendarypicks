# NFL data inventory

What is actually stored for the NFL, how much of it there is, who it covers, and what
nothing in the product has ever rendered. Read off `picks.dev.db` on 2026-07-26 with
`json_each` over `player_game_logs.stats`.

Companion page (same numbers, scannable):
<https://claude.ai/code/artifact/efed2820-383c-4a8a-bd25-ed063544cb74>

| | |
|---|---|
| NFL rows in `player_game_logs` | 10,717 |
| Distinct players | 776 |
| Seasons | 2024 (5,340 rows) and 2025 (5,377 rows) — nothing earlier |
| Distinct stat keys | 28 |
| Ingested and rendered nowhere, before this pass | 8 |

---

## 1. The two seasons are different schemas

Not just renamed — differently *shaped*.

**2024 is dense and legacy-keyed.** Source is nflverse's pre-built weekly summary
(`source='nflverse'`). Every row carries all 14 box-score keys, zero-filled.
`carries` is present on 100% of rows and non-zero on 42%.

**2025 is sparse and canonical-keyed.** Source is nflverse play-by-play
(`source='nflverse_pbp'`, see `ingest_nfl_pbp_logs.py`). A key exists only when the
phase applies. `carries` is present on 41.9% of rows and non-zero on every one.

> **Presence means nothing in 2024 and everything in 2025.** Any coverage check or
> "does this player rush" test written against one season is wrong on the other.

No row mixes the two vocabularies, so a player whose only season is 2024 drops out of
every canonical-key lookup **silently**. This has already caused two real bugs — the
player-page projections and the game-log table both lost every 2024 player before the
normalization was added.

### Rename map

| 2024 | 2025 |
|---|---|
| `fantasy_points` | `fpts` |
| `fantasy_points_ppr` | `fpts_ppr` |
| `receptions` | `rec` |
| `receiving_yards` | `rec_yds` |
| `receiving_tds` | `rec_td` |
| `rushing_yards` | `rush_yds` |
| `rushing_tds` | `rush_td` |
| `passing_yards` | `pass_yds` |
| `passing_tds` | `pass_td` |
| `attempts` | `att` |
| `completions` | `cmp` |
| `interceptions` | `intc` |

Spelled **identically** in both, safe to read without a COALESCE: `targets`,
`carries`, `off_snaps`, `off_pct`, `st_snaps`, `st_pct`, `def_snaps`, `def_pct`,
`adot`, `air_yds_share`, `cushion`, `separation`, `yac_above_exp`.

Present in **2025 only** — 2024's source does not carry them: `pass_epa`, `cpoe`,
`air_yds`.

---

## 2. Every key, 2025

Coverage is share of the season's 5,377 rows.

| Key | Coverage | Players | Non-zero | Status |
|---|---|---|---|---|
| `fpts_ppr` | 100% | 605 | 5,000 | rendered |
| `fpts` | 100% | 605 | 4,977 | rendered |
| `off_snaps` | 99.7% | 591 | 5,347 | rendered |
| `off_pct` | 99.7% | 591 | 5,347 | rendered |
| `st_snaps` | 99.7% | 591 | 2,123 | **was unused** |
| `st_pct` | 99.7% | 591 | 2,123 | **was unused** |
| `def_snaps` | 99.7% | 591 | **17** | noise — drop from ingest |
| `def_pct` | 99.7% | 591 | **17** | noise — drop from ingest |
| `targets` | 80.3% | 502 | 4,320 | rendered |
| `rec` | 80.3% | 502 | 3,872 | rendered |
| `rec_yds` | 80.3% | 502 | 3,828 | rendered |
| `rec_td` | 80.3% | 502 | 721 | rendered |
| `carries` | 41.9% | 335 | 2,254 | rendered |
| `rush_yds` | 41.9% | 335 | 2,188 | rendered |
| `rush_td` | 41.9% | 335 | 414 | rendered |
| `adot` | 22.6% | 210 | 1,213 | rendered |
| `air_yds_share` | 22.6% | 210 | 1,213 | rendered (feeds WOPR) |
| `separation` | 22.6% | 210 | 1,213 | **was unused** |
| `cushion` | 22.6% | 210 | 1,213 | **was unused** |
| `yac_above_exp` | 22.5% | 210 | 1,202 | **was unused** |
| `att` | 12.3% | 102 | 662 | rendered |
| `cmp` | 12.3% | 102 | 624 | rendered |
| `pass_yds` | 12.3% | 102 | 622 | rendered |
| `pass_td` | 12.3% | 102 | 437 | rendered |
| `intc` | 12.3% | 102 | 281 | rendered |
| `pass_epa` | 12.3% | 102 | 662 | **was unused** |
| `air_yds` | 12.3% | 102 | 652 | **still unused** |
| `cpoe` | 12.0% | 92 | 646 | **was unused** |

"was unused" = surfaced by this pass (`nfl_usage.py` → the Usage card). `air_yds` stays
unused: the raw total is redundant next to `adot` and `air_yds_share`.

2024 holds the same blocks under legacy names at 100% presence for every box-score key
and 23.5% for Next Gen.

---

## 3. Who each block covers

Distinct 2025 players with at least one non-empty value.

| Pos | Players | Off snaps | Targets | Carries | NGS recv | NGS pass | ST snaps |
|---|---|---|---|---|---|---|---|
| WR | 226 | 224 | 224 | 84 | **151** | 6 | 171 |
| RB | 137 | 136 | 120 | 136 | **0** | 5 | 98 |
| TE | 126 | 126 | 125 | 22 | **59** | 2 | 115 |
| QB | 81 | 80 | 10 | 78 | **0** | 76 | 0 |
| FB | 11 | 11 | 11 | 9 | 0 | 0 | 11 |
| P | 6 | 0 | 0 | 2 | 0 | 3 | 6 |
| OT/G | 9 | 0 | 9 | 0 | 0 | 0 | 0 |

**Next Gen receiving is a WR/TE dataset. Zero RBs, zero QBs.** A back's blank
aDOT/AY%/WOPR/Separation is not missing coverage — those columns can never fill for
him. Any surface that leads with WOPR is a receiver surface by construction. This is
why the Usage card picks its columns off position first and prunes empties second.

Even inside WR, Next Gen reaches 151 of 226 — the back half of the position is dashes.

Offensive linemen with targets and punters with passing metrics are trick plays, not
bad data, but they will surface as absurd rows in any leaderboard that does not filter
by position.

---

## 4. NFL data outside `player_game_logs`

| Table | Rows | Contents | Read by |
|---|---|---|---|
| `nfl_adp` | 9,611 | ADP, percent owned, percent started, ESPN PPR/standard rank. **2026 season only**; 2,511 rows carry an actual ADP | Draft Room, draft board, transaction significance |
| `nfl_transactions` | 754 | Dated team transactions from ESPN's public feed | `/api/nfl/transactions` |
| `strength_snap` | 19,347 | Team win pct / point differential over time, all leagues | `_core.py` |
| `roster_snap` | 97 | Point-in-time roster capture. 97 rows is a stub, not a dataset | `_core.py` |

`nfl_adp` is the only table that knows what the **market** thinks of a player, and the
player page never mentions it. Percent-owned beside snap share is the most direct
expression of "should I make this pick" available in the data as it stands.

---

## 5. The play-by-play is downloaded and thrown away

`ingest_nfl_pbp_logs.py` calls `nfl.import_pbp_data([year])` — the full nflverse
play-by-play, every play of the season — then groups it to per-player-per-game lines
and writes only the rollup. **The plays are never persisted.** There is no play table
in the schema (`scoring_plays` is unrelated and not NFL play-by-play).

This is a storage decision, not an access problem. The pipeline already has the data in
memory each run.

Two consequences worth knowing before promising anything play-level:

**Reproducible from what is stored today** — anything at per-game or per-week grain:
CPOE vs EPA/dropback scatters, week-over-week efficiency lines, separation and cushion
distributions, target-share and snap-share trends, position leaderboards.

**Needs the plays retained** — anything at per-play grain: win-probability-added swings
within a game, EPA by run gap or by direction, air-yards pass charts plotting individual
throws, drive- or series-outcome breakdowns, situational splits (down, distance, field
position, personnel). Every one of these is a staple of the public NFL analytics
community, and none of them can be built from the rollup.

### Related: `game_date` and `home_away` are NULL on every NFL row

Not a source limitation. `ingest_nfl_pbp_logs.py` passes literal `None` for both
columns on insert, while the source frame carries the game date and the home/away teams.
Week (`game_no`) is currently the only thing identifying an NFL game, and a renderer that
assumed `home_away` printed "@ OPP" for home games until it was removed. Fixing this is
two values in one INSERT.

---

## 6. What this changes

1. **Column sets are position-first.** Pruning empty columns is the safety net, not the
   rule. The rule is: WR/TE get Next Gen, RB never does, QB gets the passing block.
2. **`def_snaps` / `def_pct` should come out of the ingest** rather than be filtered
   downstream forever — 17 non-zero rows out of 5,360.
3. **Special teams share explains the low-snap players** the usage surfaces otherwise
   make look inert.
4. **One normalizer, not scattered COALESCE pairs.** The 2024/2025 split needs a single
   function every reader goes through; it is currently rediscovered per query.
5. **Two seasons is the ceiling on trend work.** Anything framed as a career arc has
   2024 and 2025 and nothing else.
6. **Retaining play-by-play is the single highest-leverage ingest change available** —
   it is already downloaded, and it is the difference between per-game tables and the
   entire class of play-level analysis.
