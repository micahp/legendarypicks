# NHL player prop feasibility

Audited 2026-10-20. Scope: determine whether archived per-player SOG and goalie saves can be populated for the 2018-19 through 2022-23 SBR target games, and whether local player-prop quote records exist. No model was fit and no ROI was calculated.

**Price archive verdict for the target seasons: 0 player-prop quote rows.** The dev database does contain 83,720 NHL player-prop quote rows, but every one is for game dates in 2026. Therefore no historical market comparison, ROI, or price-based verdict is possible for the 2018-19 through 2022-23 target outcomes. Those outcomes could support distributional calibration only.

## 1. Skater shots on goal: available in the archive

The task brief's statement that skaters_gamelogs has no shot count is contradicted by the database schema. Its all-situation rows contain I_F_shotsOnGoal, a direct per-player-game SOG field. The outcome key is (season, gameId, playerId); gameId is the same canonical NHL game ID used by the target crosswalk. The audit also checks source season, date, and team against the canonical game row.

All 4,872 target regular-season games have skater rows. The query found 175,289 distinct skater-games and 175,289 non-null, nonnegative integer SOG values, including 40,224 explicit zero-SOG rows. No SOG row was missing or invalid.

No join from the shots event table was needed. Its season plus local game_id was not used, and this audit does not claim a mapped or unmapped shot-event row count. The canonical game crosswalk below is for the player-game logs, whose gameId is already canonical.

There is an outcome-quality limitation. A targeted comparison against the [official NHL GameCenter boxscore](https://api-web.nhle.com/v1/gamecenter/2018020160/boxscore) for game 2018020160 on 2018-10-28 matched all 36 skater IDs, but two player SOG values differed:

| Player ID | Archived I_F_shotsOnGoal | NHL GameCenter |
| ---: | ---: | ---: |
| 8475906 | 2 | 1 |
| 8476889 | 1 | 2 |

This is one targeted game, not a population-wide official settlement audit. It establishes complete coverage of the archived field, but not that every archived SOG value equals the official settlement value. A full official-outcome audit or import is still needed before treating the entire historical set as official-grade prop settlement data.

## 2. Goalie saves: available and nonnegative

For each all-situation goalies_gamelogs player-game, saves are reconstructed as ongoal - goals. The audit found 10,410 goalie player-games across the target set. Every row had both inputs and produced a nonnegative integer save count. There were no missing, negative, fractional, or non-finite cases.

The same official GameCenter spot-check matched the two goalies with logged appearances on saves, shots against, and goals against. The API also returned two zero-stat goalie slots that were not goalie-game rows in the archive; these are not counted as appearances. This is a one-game check, not a full-season reconciliation.

## 3. Player-prop quote archive: present in 2026, absent in target seasons

The actual dev database is /root/legendarypicks/backend/data/picks.dev.db. It was opened with SQLite URI mode=ro&immutable=1 and PRAGMA query_only=ON.

It contains 83,720 NHL rows with player identity, market, line, capture timestamp, odds, and odds-capture timestamp. These rows cover 678 players and 149 prop games dated 2026-09-29 through 2026-10-20, all assigned start year 2026 (2026-27 season convention). The prop_games schema has no game-type field, so the archive does not distinguish preseason from regular-season games. There are no rows dated in the 2018-19 through 2022-23 target window.

| Market key | Quote rows | Players | Games | Captured before start | At/after start |
| --- | ---: | ---: | ---: | ---: | ---: |
| shots (Shots on Goal) | 28,020 | 442 | 149 | 27,658 | 362 |
| saves (Goalie Saves) | 3,360 | 64 | 142 | 3,296 | 64 |
| goals | 2,060 | 194 | 113 | 2,060 | 0 |
| points | 21,740 | 552 | 112 | 21,740 | 0 |

The goals rows all use a numeric 0.5 line; the database does not store a separate anytime_goal market key. The four relevant numeric market keys (shots, saves, goals, points) account for 55,180 current quote rows. Across all 11 NHL market keys, 83,294 of 83,720 captures were before event start, 426 were at or after start, and none had an unknown start time.

These are current/last-captured quote rows, not a historical line-movement archive. The NHL subset of prop_odds_snapshots has zero rows. The prop ingest upserts existing rows by updating captured_at, odds, and odds_captured_at, so an earlier quote for the same key is not retained there.

The structured research scan checked 30 JSON, JSONL, CSV, and gzip data files (7,313 records; 5,293 records in NHL-labeled paths or records) and found zero NHL player-level records with a player identity, market line, and capture timestamp. The SBR research archive contains 5,132 game-level rows, not player props. research/nhl/prospective-2026-27/market_quotes.jsonl contains 12 Kalshi team-market records, with no player identity or line. Those team markets are not player-prop prices.

## 4. Population anchor and season coverage

The SBR archive was joined to the canonical game table by game date and unordered team pair after mapping SBR team display names to canonical team codes. The crosswalk produced 5,132 unique canonical game IDs, including 4,872 regular-season games and 260 playoff games. There were no unmatched or ambiguous rows. One venue-order mismatch was retained and aligned by team identity: game 2019020740, 2020-01-17, Pittsburgh-Detroit in SBR versus Detroit-Pittsburgh canonically.

The population is the same 4,872 regular-season games as the goalie audit. In the table, goalie player-games are individual goalie appearances, so a game can contribute more than one goalie row.

| Season | Regular games | Skater player-games | Distinct skaters | SOG values | Zero SOG | Goalie player-games | Distinct goalies | Nonnegative saves |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2018-19 | 1,271 | 45,756 | 906 | 45,756 | 10,403 | 2,720 | 93 | 2,720 |
| 2019-20 | 1,082 | 38,931 | 883 | 38,931 | 8,881 | 2,305 | 85 | 2,305 |
| 2020-21 | 868 | 31,196 | 913 | 31,196 | 7,316 | 1,852 | 98 | 1,852 |
| 2021-22 | 1,312 | 47,206 | 1,003 | 47,206 | 10,802 | 2,818 | 119 | 2,818 |
| 2022-23 archive slice | 339 | 12,200 | 761 | 12,200 | 2,822 | 715 | 74 | 715 |
| **Total** | **4,872** | **175,289** | — | **175,289** | **40,224** | **10,410** | — | **10,410** |

The 2022-23 archive is a partial slice: 339 regular-season games from 2022-10-11 through 2022-11-27, about seven weeks. It is not a full-season holdout.

## What is not knowable from the current archive

- Whether all 175,289 archived SOG values agree with official NHL settlement data. The one-game check found player-level disagreements; no all-game official reconciliation was run.
- Historical player-prop prices for the target seasons. The dev database has zero rows in those game dates.
- Historical price movement or closing lines. There are zero NHL prop_odds_snapshots rows, and the current props row is refreshed in place.
- Whether 2026 quote rows are preseason or regular-season markets. prop_games has no game-type field.
- A distinct anytime-goal product separate from the numeric goals line. Current rows use the goals key and 0.5 line.

## Reproduction

From the repository root, with DuckDB installed:

/root/lp-goalie-research/.venv/bin/python research/nhl/prop-feasibility-2026-10-20/check_feasibility.py

The script reads the SBR archive, the canonical CSV at /root/legendarypicks/research/nhl/kalshi-playoff-audit-2025-26/canonical_games_v1_7cd2fc9a6e84470c.csv, /root/nhl_database_2025-26-playoffs.duckdb, and the dev SQLite database. DuckDB is opened read-only; SQLite uses mode=ro&immutable=1. It makes one read-only request to the official NHL GameCenter endpoint for the spot-check above. It prints every count in this report and exits nonzero if a pinned measurement changes.
