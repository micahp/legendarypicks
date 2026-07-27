# NFL data inventory

What is actually stored for the NFL, how much of it there is, who it covers, and what
nothing in the product has ever rendered. Read off `picks.dev.db` on 2026-07-27 with
`json_each` over `player_game_logs.stats`, after the weekly-box-score swap.

Pre-swap companion snapshot (the counts below supersede it):
<https://claude.ai/code/artifact/efed2820-383c-4a8a-bd25-ed063544cb74>

| | |
|---|---|
| NFL rows in `player_game_logs` | 11,232 |
| Distinct players | 785 |
| Seasons | 2024 (5,597 rows) and 2025 (5,635 rows) — nothing earlier |
| Distinct stat keys | 41 (includes aliases on 14 legacy 2024 holdovers) |
| Rows sourced from the published weekly artifact | 11,216 |

---

## 1. The two seasons now share one box-score schema

`ingest_nfl_weekly_stats.py` copies both seasons from nflverse's maintained
`stats_player` weekly artifact (`source='nflverse_weekly'`). The emitted box-score
blocks are sparse and canonical-keyed in both years: a key exists only when that phase
applies. Snap counts and Next Gen fields are preserved from their separate ingests.

The narrow v1 gate includes passers, rushers, receivers, and conversion-only scorers;
defensive and kicking row expansion remains behind `--all-positions`. It added the
postseason as continued numeric weeks 19–22. Both the 2024 and 2025 artifacts were
checked to contain REG 1–18 and POST 19–22 with no season-type week collision.

Sixteen enrichment-bearing rows fall outside that gate and therefore were not rewritten:
14 retain `source='nflverse'` in 2024 and two retain `source='nflverse_pbp'` in 2025.
Only the 14 old 2024 rows still carry legacy box-score aliases. Readers should keep the
normalizer until those enrichment-only holdovers are either expanded from the artifact
or retired.

### Retired alias map

| Legacy | Canonical |
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

Spelled identically in both vocabularies: `targets`,
`carries`, `off_snaps`, `off_pct`, `st_snaps`, `st_pct`, `def_snaps`, `def_pct`,
`adot`, `air_yds_share`, `cushion`, `separation`, `yac_above_exp`.

The weekly source now supplies `pass_epa`, `cpoe`, and `air_yds` for both seasons.

---

## 2. Every key, 2025

Coverage is share of the season's 5,635 rows, including 258 postseason rows.

| Key | Coverage | Players | Non-zero | Status |
|---|---|---|---|---|
| `fpts_ppr` | 100% | 611 | 5,242 | rendered |
| `fpts` | 100% | 611 | 5,217 | rendered |
| `off_snaps` | 95.1% | 591 | 5,347 | rendered |
| `off_pct` | 95.1% | 591 | 5,347 | rendered |
| `st_snaps` | 95.1% | 591 | 2,123 | **was unused** |
| `st_pct` | 95.1% | 591 | 2,123 | **was unused** |
| `def_snaps` | 95.1% | 591 | **17** | noise — drop from ingest |
| `def_pct` | 95.1% | 591 | **17** | noise — drop from ingest |
| `targets` | 80.5% | 509 | 4,535 | rendered |
| `rec` | 80.5% | 509 | 4,059 | rendered |
| `rec_yds` | 80.5% | 509 | 4,015 | rendered |
| `rec_td` | 80.5% | 509 | 763 | rendered |
| `carries` | 41.8% | 339 | 2,355 | rendered |
| `rush_yds` | 41.8% | 339 | 2,285 | rendered |
| `rush_td` | 41.8% | 339 | 425 | rendered |
| `adot` | 21.5% | 210 | 1,213 | rendered |
| `air_yds_share` | 21.5% | 210 | 1,213 | rendered (feeds WOPR) |
| `separation` | 21.5% | 210 | 1,213 | **was unused** |
| `cushion` | 21.5% | 210 | 1,213 | **was unused** |
| `yac_above_exp` | 21.5% | 210 | 1,202 | **was unused** |
| `att` | 12.2% | 103 | 684 | rendered |
| `cmp` | 12.2% | 103 | 653 | rendered |
| `pass_yds` | 12.2% | 103 | 651 | rendered |
| `pass_td` | 12.2% | 103 | 459 | rendered |
| `intc` | 12.2% | 103 | 297 | rendered |
| `dropbacks` | 12.2% | 103 | 690 | rendered |
| `pass_epa` | 12.2% | 102 | 689 | **was unused** |
| `air_yds` | 12.2% | 103 | 681 | **still unused** |
| `cpoe` | 12.0% | 95 | 677 | **was unused** |

"was unused" = surfaced by this pass (`nfl_usage.py` → the Usage card). `air_yds` stays
unused: the raw total is redundant next to `adot` and `air_yds_share`.

2024 now holds the same sparse canonical blocks, apart from the 14 legacy holdovers
described above.

---

## 3. Who each block covers

Distinct 2025 players with at least one non-empty value.

| Pos | Players | Off snaps | Targets | Carries | NGS recv | NGS pass | ST snaps |
|---|---|---|---|---|---|---|---|
| WR | 226 | 224 | 224 | 85 | **151** | 10 | 171 |
| RB | 139 | 136 | 123 | 137 | **0** | 6 | 98 |
| TE | 126 | 126 | 125 | 24 | **59** | 3 | 115 |
| QB | 81 | 80 | 10 | 78 | **0** | 78 | 0 |
| FB | 12 | 11 | 12 | 9 | 0 | 0 | 11 |
| P | 6 | 0 | 0 | 2 | 0 | 4 | 6 |
| OT/G/C | 13 | 0 | 13 | 0 | 0 | 0 | 0 |

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

## 5. Weekly box scores and raw plays have separate jobs

`ingest_nfl_weekly_stats.py` is the only writer of the maintained offensive
per-player-game box score. It maps published columns directly, plus the checked
`dropbacks = attempts + sacks_suffered` value; it does not derive stats from plays.

`ingest_nfl_pbp_logs.py` has no rollup or fantasy scorer. It retains regular-season
plays in the additive `nfl_pbp` table for play-level analysis. The DEV database holds
46,452 plays from 272 games. Its current physical table predates the latest schema
expansion (34 populated columns); the preserved ingest contract is a curated 50
columns and widens the table on the next PBP refresh.

Two consequences worth knowing before promising anything play-level:

**Available from weekly logs** — anything at per-game or per-week grain:
CPOE vs EPA/dropback scatters, week-over-week efficiency lines, separation and cushion
distributions, target-share and snap-share trends, position leaderboards.

**Available from retained plays** — anything at per-play grain: win-probability-added swings
within a game, EPA by run gap or by direction, air-yards pass charts plotting individual
throws, drive- or series-outcome breakdowns, situational splits (down, distance, field
position, personnel).

### Related: postseason date/home-away metadata is still absent

The weekly artifact supplies `game_id`, team, and opponent, but not `game_date` or an
explicit home/away field. Existing 2025 regular-season metadata survived the upsert;
the 258 newly inserted postseason rows have both fields NULL. All 5,597 2024 rows
still lack both fields. This is schedule enrichment work, not a reason to derive box
scores from PBP.

---

## 6. What this changes

1. **Column sets are position-first.** Pruning empty columns is the safety net, not the
   rule. The rule is: WR/TE get Next Gen, RB never does, QB gets the passing block.
2. **`def_snaps` / `def_pct` should come out of the ingest** rather than be filtered
   downstream forever — 17 non-zero rows out of 5,360.
3. **Special teams share explains the low-snap players** the usage surfaces otherwise
   make look inert.
4. **One normalizer, not scattered COALESCE pairs.** Only 14 enrichment-only 2024
   holdovers still need the legacy aliases, so readers should keep one shared fallback
   until those rows are expanded or retired.
5. **Two seasons is the ceiling on trend work.** Anything framed as a career arc has
   2024 and 2025 and nothing else.
6. **Play retention stays additive and separate.** It supports the play-level class of
   analysis without becoming a second, disagreeing box-score implementation.
