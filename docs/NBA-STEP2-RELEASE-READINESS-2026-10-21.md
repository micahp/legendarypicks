# NBA Step 2 release readiness

**Status: not ready for promotion.** The work remains on `feat/nba-step1-data-props`, based at `93e2f391`. This audit and the code changes are local to the feature worktree. Nothing was pushed, merged, or written to production.

The dev snapshot is for the Oct. 21, 2026 slate. The newest quote in the audit was captured at `2026-10-21T13:36:48Z`; the oldest quote still attached to this slate is from `2026-10-18T21:34:19Z`. The offer-level export is [NBA-STEP2-OFFER-AUDIT-2026-10-21.csv](NBA-STEP2-OFFER-AUDIT-2026-10-21.csv).

## SportsDataverse release and current log sources

SportsDataverse does **not** publish 2026–27 NBA player boxscores or game logs yet. The official `nba_stats_player_game_logs` release lists seasons 1997–2026 and says its last asset was written Aug. 13; its season numbers use the ending year, so 2026 means 2025–26 and the new season would be 2027. The official status page also lists player boxscores only through 2026, last file Oct. 1. ([Player-game-log release](https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/nba_stats_player_game_logs), [SportsDataverse status](https://www.sportsdataverse.org/status))

The dev database agrees with that status:

The release page schedules its live GitHub Actions workflow daily at 07:00 UTC during Oct. 18–31. That schedule is not a publication guarantee: at 13:42 UTC on Oct. 21 the public release still had no 2026–27 asset and its newest asset remained from Aug. 13.

| Dataset | Rows / games | Source and season |
|---|---:|---|
| Latest imported SportsDataverse release | 34,786 player rows; 1,322 games; 1,400 schedule rows | `season=2025`, `source_season=2026`; `current_release_available=0` |
| 2026–27 preseason player logs | 2,175 rows across 67 games | ESPN, `game_type=PRE`, Oct. 3–16 |
| 2026–27 regular-season player logs | 84 rows across 3 games | ESPN, `game_type=REG`, Oct. 20 |
| 2026–27 SportsDataverse player logs | 0 rows | No release available; latest DB check at `2026-10-21T11:52:08Z` |

The current-season log rows are ESPN-only. The `player_game_logs_all` view has SportsDataverse columns on both databases; the production SportsDataverse log, game, and release tables currently contain zero rows. I inspected both databases read-only.

| Data need | Free-source status |
|---|---|
| Current-season player-game logs | ESPN has 84 REG appearances from the three Oct. 20 games. SportsDataverse has no 2026–27 release yet. |
| Historical player-game logs | SportsDataverse is available through 2025–26 and already imported on dev. |
| FGM/FTM actual stats for grading | Present in ESPN boxscores and covered by the passing fixture tests. |
| FGM/FTM prop lines | No rows from the current Bovada/RotoWire capture. This audit did not establish whether another book offers them. |
| Complete free odds coverage for all ten markets | Not established. The audit reports the sources already captured by LP; it does not claim those feeds cover every sportsbook. |

## Oct. 21 offer audit

I collapsed duplicate `prop_games` records by date, home/away, player, market, and line. Counts below distinguish a provider quote row from a unique line contract and from an Over/Under selection:

| Market | Quote rows | Unique player/game/line contracts | Side selections | Players | Games | Sources |
|---|---:|---:|---:|---:|---:|---:|
| Assists | 2,114 | 306 | 612 | 135 | 11 | 12 |
| Blocks | 274 | 47 | 94 | 46 | 11 | 8 |
| Points | 7,422 | 1,842 | 3,684 | 170 | 11 | 13 |
| Points + rebounds + assists | 3,428 | 656 | 1,312 | 149 | 11 | 12 |
| Rebounds | 3,642 | 781 | 1,562 | 161 | 11 | 13 |
| Steals | 662 | 115 | 230 | 111 | 11 | 8 |
| Threes | 2,058 | 216 | 432 | 139 | 11 | 13 |
| Turnovers | 52 | 26 | 52 | 26 | 10 | 1 |
| Field goals made | 0 | 0 | 0 | 0 | 0 | 0 |
| Free throws made | 0 | 0 | 0 | 0 | 0 | 0 |
| **Total observed** | **19,652** | **3,989** | **7,978** | **170** | **11** | **13 distinct sources** |

The 19,652 quote rows are **not** 19,652 unique props. They represent 3,989 unique player/game/market/line contracts and 7,978 side selections. The CSV has one row per contract with player, game, line, Over/Under source lists, quote-row count, raw game IDs, and first/last capture time by source.

Observed source labels are `bovada` plus these RotoWire books/feeds: `betmgm-sb`, `betr`, `betrivers-sb`, `caesars-sb`, `draftkings-sb`, `fanduel-sb`, `hardrock-sb`, `pick6`, `prizepicks`, `rtsports`, `sleeper`, and `underdog`. Coverage varies by market: points, rebounds, and threes have all 13 sources; PRA has 12 (no BetMGM); assists has 12 (no Underdog); blocks and steals have eight RotoWire sources; turnovers has PrizePicks only. FGM and FTM are absent from the LP dev captures. This does not prove that no sportsbook offers them; it records the feeds observed here.

The 11 matchups are:

- Charlotte Hornets @ Brooklyn Nets — 1,560 quotes; 343 contracts.
- Dallas Mavericks @ Houston Rockets — 1,982; 413.
- Sacramento Kings @ LA Clippers — 1,154; 122.
- Golden State Warriors @ Los Angeles Lakers — 1,840; 410.
- Utah Jazz @ Memphis Grizzlies — 1,610; 321.
- Minnesota Timberwolves @ Miami Heat — 1,970; 404.
- Indiana Pacers @ New Orleans Pelicans — 1,882; 422.
- Atlanta Hawks @ Orlando Magic — 2,000; 420.
- Phoenix Suns @ Portland Trail Blazers — 1,924; 392.
- Chicago Bulls @ Toronto Raptors — 1,802; 350.
- Milwaukee Bucks @ Washington Wizards — 1,928; 392.

Examples from the captured offer rows and the live Props page:

- AJ Dybantsa, Milwaukee Bucks @ Washington Wizards, points **10.5**, Bovada Over −300 / Under +215, captured at `13:34:23Z`.
- Ace Bailey, Utah Jazz @ Memphis Grizzlies, points **8.5**, Bovada Over −290 / Under +210, captured at `13:05:14Z`.

There is a freshness limit: the props table refreshes rows that reappear but does not retire a line that disappears from a later scrape. Therefore the export is an exact audit of offers stored in LP at capture time, not proof that every old quote is still actionable at its book. Per-source timestamps are included in the CSV; stale-quote expiry/retirement remains open.

## Props page and history

I opened the existing dev Props page in headless Chromium at `2026-10-21T13:42Z`. It loaded without browser errors but still showed **12 cards and 8,132 selections**; Chicago–Toronto appeared twice, with 238 and 616 selections. I then served the feature-branch frontend and backend locally against a disposable copy of the dev database. That page showed **11 matchup cards and 7,978 selections**, with Chicago–Toronto merged to 700.

The existing dev service still serves old code. The feature-branch browser check opened Ace Bailey’s points offer at 8.5 and made a history request with `season=2027`. The chart displayed the L5/L10/L20/season controls and regular-season history. Clicking L5/L10/L20 showed exactly 5/10/20 played games; S showed no games for season 2027. The API returned L5=1.000, L10=1.000, L20=0.950 (n=5/10/20), and current-season S=null (n=0); its 72 returned games are from season 2026. For AJ Dybantsa, the current points offer is 10.5. Clicking it requested `season=2027`, returned no games or rates, and displayed “No history yet.” His four stored current-year rows are PRE.

The feature-branch history results were:

| Player / selected market | Branch L5 / L10 / L20 | Current-season S | Games returned |
|---|---|---|---:|
| Ace Bailey, points 8.5 Over | 1.000 / 1.000 / 0.950 (n=5/10/20) | null (n=0) | 72, all REG from season 2026 |
| AJ Dybantsa, points 10.5 Over | null / null / null (n=0/0/0) | null (n=0) | 0; his four stored rows are PRE |

The old live API returned Ace at 0.800 / 0.900 / 0.900 and AJ with four preseason samples. The branch now renders the “No history yet” state for AJ. Both Props history callers pass the NBA ending-year key (`2027` for Oct. 2026 games). TypeScript transpilation passed, and the helper returned 2027 for Oct. 2026, Jan. 2027 and Jun. 2027. The Jest runner could not load `next/jest` from the installed Next 13.0.0 package, so the UI unit test could not run. **The feature UI was checked locally; the managed dev page still serves the old code.**

## Ingestion and grading

On Oct. 21 at audit time, Oct. 20 was the only completed regular-season date in the current database. Its three games produced 3,220 quote rows, but only 969 unique player/game/market/line contracts and 1,938 side selections. All 3,220 quote rows have results:

| Market | Graded / captured | Wins | Losses | Pushes/voids |
|---|---:|---:|---:|---:|
| Points | 2,522 / 2,522 | 1,261 | 1,261 | 0 |
| Assists | 158 / 158 | 79 | 79 | 0 |
| Rebounds | 428 / 428 | 214 | 214 | 0 |
| Threes | 112 / 112 | 56 | 56 | 0 |

The current dev database still has no completed regular-season date after Oct. 20: it contains 84 ESPN REG player appearances across the three Oct. 20 games. Live multi-date grading therefore remains unverified. Fixture tests exercise the ingest across Oct. 20 and 21 and the settlement runner across two dates, including FGM and FTM. They use mocked ESPN responses and a disposable SQLite database, not live games. Captured output:

```text
2026-10-20: 1 final games fetched
2026-10-21: 1 final games fetched
Done. 2 NBA player-game rows (2, 0 unresolved queued)
Games to settle: 2
  Game 1: NYK @ BOS (nba, 2026-10-21) — 2 unsettled props
    settled=2 void=0 unmappable=0 pending=0 errors=0
  Game 2: NYK @ BOS (nba, 2026-10-20) — 2 unsettled props
    settled=2 void=0 unmappable=0 pending=0 errors=0
Pipeline complete:
  Settled: 4
  Numeric outcomes: 4 / 4 props
2 passed in 0.32s
```

The SportsDataverse grading test also covers all ten markets. It found and drove a small fix: the provider-normalized `3PM` value was not mapped from the ESPN `3PT` market key, leaving threes pending. The branch now maps `3PT` to `3PM`; FGM and FTM map to `FGM` and `FTM` and settle in both multi-date ESPN and SportsDataverse fixtures.

The managed service has not been restarted or changed for this audit. The feature UI check used isolated local services and a disposable database copy; settlement checks used disposable test databases.

## Scope and test results

Both NBA ingest jobs remain dev-only in the registry. The required list check was run with a path whose basename is `picks.db`:

```text
LP_DB_PATH=/tmp/picks.db python3 run_ingest_jobs.py --list
scope: skipped_scope=2 (database=prod)
```

Neither `nba_player_logs` nor `nba_sportsdataverse_logs` appears in the listed jobs. The real schema check finds `player_game_logs_sportsdataverse.player_id` on both databases. Read-only counts show all three SportsDataverse tables empty on prod and 34,786 log rows / 1,322 games / one release on dev; no production data was written.

Focused test command and result:

```text
python3 -m pytest -q test_props_history.py test_nba_sportsdataverse.py \
  test_settlement_db_only.py test_ingest_registry.py test_settle_props_runner.py \
  test_ingest_nba_logs_identity.py test_spine_merge.py \
  test_props_league_is_the_games_league.py
153 passed in 10.58s
```

## Release gates still open

- Wait for SportsDataverse’s 2026–27 boxscore/game-log release, or explicitly accept ESPN as the current-season log source until it exists.
- Get the branch code serving on dev. The isolated feature UI check passed, but managed dev still duplicates Chicago–Toronto and includes preseason history. The Jest UI unit test remains unavailable because `next/jest` is missing from the installed Next 13.0.0 package.
- Capture and grade a second real regular-season date, including an observed FGM and FTM market when a provider offers them. The multi-date fixtures pass, but no second current-season date has finished yet.
- Add or approve a stale-quote retirement rule before treating every stored offer row as currently actionable.
- FGM and FTM player-prop lines are not in the current dev captures. ESPN supplies the actual FGM/FTM boxscore stats for grading, but the available quote feeds did not supply those offers in this snapshot.

Production promotion remains a separate, Micah-approved operation: backup first, retain empty provider tables/view until approval, then import and report new player rows and recheck all ten markets.
