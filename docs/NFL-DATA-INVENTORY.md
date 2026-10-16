# NFL data inventory

What is actually stored for the NFL, how much of it there is, who it covers, and what
nothing in the product has ever rendered. Read off `picks.dev.db` on 2026-07-27 with
`json_each` over `player_game_logs.stats`, after the weekly-box-score swap and legacy
writer cleanup.

Pre-swap companion snapshot (the counts below supersede it):
<https://claude.ai/code/artifact/efed2820-383c-4a8a-bd25-ed063544cb74>

| | |
|---|---|
| NFL rows in `player_game_logs` | 11,232 |
| Distinct players | 785 |
| Seasons | 2024 (5,597 rows) and 2025 (5,635 rows) — nothing earlier |
| Distinct stat keys | 29 (one canonical box-score vocabulary plus enrichment) |
| Rows sourced from the published weekly artifact | 11,216 |
| Enrichment-only rows outside the offensive gate | 16 (14 in 2024, two in 2025) |

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

Sixteen rows fall outside that gate but carry real snap counts, so deleting them would
discard another ingest's data. Their box-score keys were removed and their provenance is
now `source='nflverse_snap_counts'`: 14 in 2024 and two in 2025. The two 2025 rows held
phantom targets from two-point plays. The 14 dense legacy rows had no offensive
involvement; 13 have return-touchdown fantasy points in the raw artifact, while one old
six-point value disagreed with it. Keeping only those fantasy values would silently
expand the deliberately narrow offensive row contract. A future `--all-positions` run
can add them canonically; until then the rows are enrichment-only. Their 2024
`game_id`/team/opponent metadata was aligned with the checksummed artifact.

### Retired alias map (zero stored NFL rows)

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
| `fpts_ppr` | 99.96% | 611 | 5,242 | rendered |
| `fpts` | 99.96% | 611 | 5,217 | rendered |
| `off_snaps` | 95.1% | 591 | 5,347 | rendered |
| `off_pct` | 95.1% | 591 | 5,347 | rendered |
| `st_snaps` | 95.1% | 591 | 2,123 | **was unused** |
| `st_pct` | 95.1% | 591 | 2,123 | **was unused** |
| `def_snaps` | 95.1% | 591 | **17** | noise — drop from ingest |
| `def_pct` | 95.1% | 591 | **17** | noise — drop from ingest |
| `targets` | 80.4% | 509 | 4,533 | rendered |
| `rec` | 80.4% | 509 | 4,059 | rendered |
| `rec_yds` | 80.4% | 509 | 4,015 | rendered |
| `rec_td` | 80.4% | 509 | 763 | rendered |
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

2024 holds the same sparse canonical blocks. Its 14 rows outside the offensive gate
contain only snap enrichment, not a second box-score vocabulary.

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

`ingest_nfl_logs.py` is now only the shared `player_game_logs` schema module; executing
it is a no-op. Its retired writer fetched the same weekly data, omitted postseason,
stored legacy aliases, and used row replacement that erased snap and Next Gen fields.

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
now have `game_id`, but still lack `game_date` and `home_away`. This is schedule
enrichment work, not a reason to derive box scores from PBP.

---

## 6. What this changes

1. **Column sets are position-first.** Pruning empty columns is the safety net, not the
   rule. The rule is: WR/TE get Next Gen, RB never does, QB gets the passing block.
2. **`def_snaps` / `def_pct` should come out of the ingest** rather than be filtered
   downstream forever — 17 non-zero rows out of 5,360.
3. **Special teams share explains the low-snap players** the usage surfaces otherwise
   make look inert.
4. **One box-score writer, one vocabulary.** `ingest_nfl_logs.py` is schema-only and
   no NFL row in DEV carries its legacy aliases. Reader fallbacks are now migration
   compatibility, not a description of current DEV data.
5. **Two seasons is the ceiling on trend work.** Anything framed as a career arc has
   2024 and 2025 and nothing else.
6. **Play retention stays additive and separate.** It supports the play-level class of
   analysis without becoming a second, disagreeing box-score implementation.

---

## 7. Projections: what exists and what is not connected

Read 2026-10-16 from `picks.dev.db` (read-only) and the code on `dev`. The Spec B player work
is on `scratch/spec-b-rebase`, which is not merged into `dev`. Its numbers are labeled as
branch results.

### 7.1 Live on `dev`

| Projection | Predicts | Produced by | Stored in | Read by | Measured |
|---|---|---|---|---|---|
| v1 points (frozen) | Win probability, margin, total | `lock_nfl_models.py`, locked no earlier than 90 minutes before kickoff | `game_projections` | Model tab (`routers/nfl_model.py`), home (`routers/home.py`) | Pooled 2010 to 2025, 3,909 games: Brier 0.2244 against 0.2105 for the de-vigged market ([PLAN-nfl-features-2026-10-11.md](PLAN-nfl-features-2026-10-11.md)) |
| v2 EPA | Win probability, margin, total | `lock_nfl_epa.py`, `nfl_epa_model.py` | `game_projections` | Model tab | 2025 Brier 0.2291 against v1's 0.2288 ([RESULTS-A9-nfl-epa-v2-backtest-2026-10-11.md](RESULTS-A9-nfl-epa-v2-backtest-2026-10-11.md)) |
| v1 + Elo | Win probability, margin | `lock_nfl_elo.py`, `nfl_elo_replica.py` | `game_projections` | Model tab | 2011 to 2023 Brier 0.2197 against 0.2229 for recalibrated v1; gap interval -0.0050 to -0.0014 ([RESULTS-nfl-elo-and-era-2026-10-13.md](RESULTS-nfl-elo-and-era-2026-10-13.md)) |
| Playoff odds | Make playoffs, seeding | `jobs/nfl_playoff_odds.py`, `nfl_sim.py` | `playoff_odds`, `team_ratings` | `pages/nfl/playoff-odds.tsx` | No grade found |
| ESPN 2026 season projection | Season totals per player | `ingest_nfl_projections.py`, from a pinned ESPN snapshot | `nfl_player_projections` (11,515 rows, 2026 only) | Offseason board (`routers/nfl_offseason/board.py`), mock draft pool (`routers/nfl_mock_draft/pool.py`) | No grade found |
| Marcel-lite, per game | Recency-weighted mean, median, floor and ceiling for each stat; P(over) for a line | `analytics/projections.py`, served at `/api/projections/player/{id}` | Computed per request from `player_game_logs`; nothing stored | Player pages and the prop chart (`pages/props.tsx`) | Baseline for every branch comparison below. No grade of its P(over) found |

Unlocked previews (`locked = 0`) also land in `game_projections`, written by
`nfl_projection_preview.py`.

### 7.2 On `scratch/spec-b-rebase`, not merged

The v2 player engine (`backend/nfl_player_projection_v2.py`, job `nfl_player_projections_job.py`)
projects targets, receptions, receiving yards and TDs, carries, rushing, and QB passing. It
returns a mean, p10, p90 and P(over). The v2 job and the ESPN weekly capture both write
`player_projections` on the dev DB (17,860 rows).

2025, weeks 3 to 18, RB/WR/TE with 3+ earlier games (n = 3,945). MAE from the 2026-10-12 run,
against Marcel-lite, which is the live route:

| Stat | v2 | Marcel-lite | Read |
|---|---|---|---|
| Targets | 1.578 | 1.589 | tie |
| Receptions | 1.216 | 1.237 | small gain; interval touches zero |
| Receiving yards | 15.910 | 16.431 | gain; interval excludes zero |
| Carries | 1.182 | 1.108 | worse |
| Rushing yards | 6.602 | 6.536 | tie |

The 2026-10-13 re-run on the re-ingested DB gave receiving yards 15.832 against 16.431 for
Marcel-lite. The gate still passes.

- v2 under-projects every stat, by about 3.5 receiving yards per player-game. Not investigated
  or fixed.
- Quarterback passing (slice 4.5): gate passed on 403 QB-games, and every stat beats
  Marcel-lite. Rushing is not published.
- Prop probabilities (v2 default engine, 2026 weeks 2 to 5, walk-forward, not captured before
  kickoff): 32,810 items on 902 player-games. Brier 0.2746 against 0.2458 for the market. The
  observed over rate barely moves across our probability bins. Items on one player-game are
  alternate lines, so they are not independent.
- ESPN weekly benchmark (2025, 2,427 player-games): v2 is level with ESPN on receptions and
  receiving yards, worse on targets, and better on TDs. It does not beat ESPN.

### 7.3 Spec B tables on `dev` that no dev code reads

The branch's code wrote these to the dev DB. No dev code reads them.

| Table | Rows | Written by | Read by dev code |
|---|---|---|---|
| `player_game_availability` | 67,179 | branch code (`migrate_player_game_availability.py` holds the schema) | none |
| `player_game_shares` | 53,458 | `build_player_game_shares.py` (branch) | none |
| `nfl_team_game_totals` | 700 | `build_player_game_shares.py` (branch) | none |
| `nfl_snap_team_sources` | 1,218 | `ingest_nfl_snap_counts.py` (branch) | none |
| `player_projections` | 17,860 | `nfl_player_projections_job.py`, `capture_espn_weekly_projections.py` (branch) | none |
| `player_projection_grades` | 0 | `grade_nfl_player_projections.py` (branch) | none |
| `player_team_shares` | 4,984 | `build_player_shares.py` (dev) | no projection |

### 7.4 How they are not connected

1. **Team models stop at the game.** `game_projections` holds one row per game: projected score,
   margin, total and win probability. No code turns those into player lines. The player code
   reads its own logs and team-share history, never `game_projections`.
2. **Player volume ignores the game script.** The v2 engine's team volume comes from observed
   team shares. A margin-based game-script adjustment was tested on the branch and not adopted,
   because 2025 team and player MAE rose.
3. **Availability is not in any live projection.** The live route reads only `player_game_logs`.
   The availability and snap tables that would feed a projection are branch-only (7.3).
4. **The live props page runs on Marcel-lite.** Its P(over) comes from the same route. The graded
   prop numbers in 7.2 are from the unmerged v2 engine. No grade of the live probabilities is
   recorded in these docs.
5. **The ESPN season projection feeds only the offseason pages.** The in-season player page and
   the props page do not read `nfl_player_projections`. ESPN's weekly projections are captured
   only on the branch.
6. **No grade spans both levels.** Team models are graded on game results. Player models are
   graded on stat MAE and prop Brier. Nothing checks that a player forecast agrees with the team
   forecast for the same game.
7. **The branch has open decisions before merge.** Merging lets the installed availability
   timer's snap ingest create `nfl_snap_team_sources` on PROD. The branch's status doc lists that
   as a decision to make first. Switching `/api/projections/player/{id}` to v2 is Micah's call,
   and so is mean versus median. The median version (P_LOG) fixed bias and RMSE but worsened MAE,
   so it was not adopted under the MAE gate. Browser checks of the branch's pages are not done.

### 7.5 What replacing the live player projections needs

- The merge decision in 7.4 item 7, then browser checks of `/nfl/projections`, the Without
  control, and the projection record panel.
- Micah's call on mean or median, and on switching the live route.
- Rushing stays on Marcel-lite, because the carries gate failed.
- A pre-kickoff capture of the v2 numbers, graded after the week finishes. The 2026 prop numbers
  above are walk-forward, not captured before kickoff.
