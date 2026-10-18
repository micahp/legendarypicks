# FBS archive audit — 2026-10-18

Phase 2 of the FBS data work: acquire the complete usable historical archive, measure what it covers,
and record what it cannot cover. Branch `feat/fbs-archive`, worktree `/root/lp-fbs-archive`. No
database was written, no bulk parquet is committed, and no missing value was replaced with zero.

**Headline.** 92 college-football releases, 1,999 Parquet files, 4.28 GB, 44.9 M rows. Nearly every
FBS-vs-FBS regular-season game from 2013 to 2025 has play-by-play (9,267 of 9,308, 99.56%; 41 games
missing). Before 2013 the
archive degrades sharply: 91.1% of 2004–2012 games and none of 2001–2003. 32.1% of the bytes are not
observations but the publisher's model output, which is the main leakage risk in the archive.

## 1. What was acquired

Source: every release in `sportsdataverse/sportsdataverse-data` whose tag is college football —
`cfb_*` (24), `espn_cfb_*` (57), `ncaa_mfb_*` (11) and `cfbfastR_cfb_pbp` (1). 93 releases match;
92 carry `.parquet` assets.
The 93rd, `espn_cfb_model_artifacts`, publishes only serialised model objects (29 assets, 28.0 MB of
`.ubj`/`.pkl`/`.json`: `ep.ubj`, `fd_model.ubj`, `wp_spread.ubj`, …), no tables, and was not acquired.

Only `.parquet` was downloaded. The same college releases publish 1,587 CSV assets (20.5 GB), 1,655
RDS assets (3.1 GB) and 402 gzip files (1.2 GB) holding the same tables; across all formats the
college releases total 29.7 GB. Taking one format is what keeps this archive at 4.28 GB.

| item | count |
|---|---|
| releases with data | 92 |
| Parquet files | 1,999 |
| bytes | 4,275.6 MB |
| rows | 44.9 M |
| seasons | 2001–2026 |
| files whose sha256 was recomputed from disk | 1,999 |

Per-file manifest: `research/fbs/parquet/MANIFEST.jsonl`, one row per file with `release`, `asset`,
`season`, `bytes`, `sha256`, `url`, `downloaded_at`, `local_path`, `kind`. `kind` is per file:
`raw` (one row per observed event or player-game), `reference` (identity, schedule, poll tables),
`scored` (the publisher's model output, including EPA/WP/FPI/ratings), `training_matrix` (a derived
feature matrix), `model_artifact` (a fitted object or evaluation output). 423 files are `raw`,
1,220 `scored`, 318 `reference`, 37 `model_artifact`, 1 `training_matrix`.

Files live at `research/fbs/parquet/<release>/<asset>`. `.gitignore` already excludes
`research/fbs/parquet/**/*.parquet`; the manifest, the CSVs below and the scripts are tracked.

## 2. Coverage by category and season

Categories are the six from the execution brief plus model artifacts. A release belongs to one
category; the number in each cell is how many releases carry data for that season.

| season | identity/reference | games/markets | team performance | event level | player/roster | coaching/context | model artifacts |
|---|---|---|---|---|---|---|---|
| 2001 | 3 | 1 | · | · | · | · | · |
| 2002 | 3 | 1 | · | · | 1 | · | · |
| 2003 | 3 | 1 | · | · | 1 | · | · |
| 2004 | 3 | 4 | 20 | 4 | 20 | 8 | · |
| 2005 | 3 | 4 | 20 | 4 | 21 | 10 | · |
| 2006 | 3 | 4 | 20 | 4 | 21 | 10 | · |
| 2007 | 3 | 4 | 20 | 4 | 21 | 10 | · |
| 2008 | 3 | 4 | 21 | 4 | 22 | 10 | · |
| 2009 | 3 | 4 | 21 | 4 | 22 | 10 | · |
| 2010 | 3 | 4 | 21 | 4 | 22 | 10 | · |
| 2011 | 3 | 4 | 21 | 4 | 22 | 10 | · |
| 2012 | 3 | 4 | 21 | 4 | 22 | 10 | · |
| 2013 | 5 | 6 | 23 | 7 | 24 | 11 | · |
| 2014 | 5 | 6 | 30 | 9 | 25 | 11 | · |
| 2015 | 6 | 7 | 30 | 9 | 25 | 11 | · |
| 2016 | 6 | 7 | 30 | 9 | 26 | 11 | · |
| 2017 | 6 | 7 | 30 | 9 | 26 | 11 | · |
| 2018 | 6 | 7 | 30 | 9 | 26 | 11 | · |
| 2019 | 6 | 7 | 30 | 9 | 26 | 11 | · |
| 2020 | 6 | 7 | 30 | 9 | 26 | 11 | · |
| 2021 | 6 | 7 | 30 | 9 | 26 | 11 | · |
| 2022 | 6 | 7 | 30 | 9 | 26 | 11 | · |
| 2023 | 6 | 7 | 30 | 9 | 26 | 11 | · |
| 2024 | 6 | 7 | 30 | 9 | 26 | 11 | · |
| 2025 | 6 | 7 | 30 | 9 | 26 | 11 | · |
| 2026 | 6 | 7 | 30 | 8 | 26 | 11 | · |

Rows per era, by category (millions). These are rows delivered, not unique observations: one play
appears in `espn_cfb_pbp`, `cfbfastR_cfb_pbp`, `ncaa_mfb_pbp` and `espn_cfb_model_pbp`, and the same
history is repeated in the concatenated `cfb_model_pbp_2004_2025` file.

| era | identity/reference | games/markets | team performance | event level | player/roster | coaching/context |
|---|---|---|---|---|---|---|
| 2001–2003 | 0.00 | 0.00 | · | · | 0.00 | · |
| 2004–2012 | 0.01 | 0.08 | 0.18 | 2.57 | 1.64 | 0.09 |
| 2013–2020 | 0.04 | 0.20 | 7.32 | 10.29 | 3.44 | 0.19 |
| 2021–2025 | 0.03 | 0.15 | 1.27 | 7.33 | 3.01 | 0.08 |
| 2026 | 0.05 | 0.02 | 0.15 | 0.69 | 0.47 | 0.01 |
| no season (10 files) | 0.09 | · | · | 5.48 | · | 0.00 |

Ten files carry no season because they cover all seasons or none: `cfb_rosters_crosswalk`,
four `cfb_groups` tables, `coach_careers`, the two `cfb_model_artifacts` tables,
`cfb_model_pbp_2004_2025` and `cfb_pbp_train_full_2004_2025`. Those last two are 5.48 M of the
"event level" rows in this table.

Release-level detail, including every release's season range, files, bytes, rows and column count, is
in `research/fbs/archive-releases.csv`; per-release-per-season detail is in
`research/fbs/archive-coverage.csv`; every column of every release is in `archive-schema.json`.

## 3. Games that actually have events

The table that decides what can be modelled. Population is `cfb_schedules` regular-season games where
both teams are FBS. "either" is ESPN or cfbfastR play-by-play; the NCAA column counts games whose
`espn_game_id` appears in `ncaa_mfb_pbp`.

| season | FBS games | ESPN pbp | cfbfastR | either | NCAA pbp | either % |
|---|---|---|---|---|---|---|
| 2001 | 627 | 0 | 0 | 0 | 0 | 0.0% |
| 2002 | 679 | 0 | 0 | 0 | 0 | 0.0% |
| 2003 | 671 | 0 | 0 | 0 | 0 | 0.0% |
| 2004 | 635 | 425 | 0 | 425 | 0 | 66.9% |
| 2005 | 636 | 535 | 0 | 535 | 0 | 84.1% |
| 2006 | 682 | 594 | 0 | 594 | 0 | 87.1% |
| 2007 | 680 | 610 | 0 | 610 | 0 | 89.7% |
| 2008 | 683 | 659 | 0 | 659 | 0 | 96.5% |
| 2009 | 680 | 666 | 0 | 666 | 0 | 97.9% |
| 2010 | 683 | 666 | 0 | 666 | 0 | 97.5% |
| 2011 | 680 | 673 | 0 | 673 | 0 | 99.0% |
| 2012 | 697 | 687 | 0 | 687 | 0 | 98.6% |
| 2013 | 702 | 702 | 0 | 702 | 694 | 100.0% |
| 2014 | 721 | 707 | 706 | 708 | 696 | 98.2% |
| 2015 | 724 | 717 | 717 | 717 | 706 | 99.0% |
| 2016 | 719 | 705 | 706 | 706 | 700 | 98.2% |
| 2017 | 736 | 732 | 732 | 732 | 722 | 99.5% |
| 2018 | 733 | 731 | 731 | 731 | 714 | 99.7% |
| 2019 | 734 | 733 | 733 | 733 | 724 | 99.9% |
| 2020 | 508 | 503 | 489 | 508 | 490 | 100.0% |
| 2021 | 732 | 704 | 732 | 732 | 684 | 100.0% |
| 2022 | 734 | 705 | 734 | 734 | 706 | 100.0% |
| 2023 | 750 | 745 | 750 | 750 | 720 | 100.0% |
| 2024 | 753 | 737 | 752 | 752 | 729 | 99.9% |
| 2025 | 762 | 762 | 762 | 762 | 750 | 100.0% |
| 2026 | 761 | 388 | 388 | 388 | 318 | 51.0% |

Totals: 18,102 FBS regular-season games 2001–2026, 15,170 with play-by-play (83.8%).
2013–2025: 9,308 games, 9,267 with play-by-play (99.56%, 41 games missing).
2004–2012: 6,056 games, 5,515 with play-by-play (91.1%, 541 missing).
2001–2003: 1,977 games, none.

2026 is a season in progress (761 FBS games scheduled, 388 played and loaded at fetch time). It is not
a partial archive defect; it is an unfinished season.

## 4. What is irreducibly missing

Events before 2004 do not exist in this archive and are not obtainable from it: 1,977 FBS games with
schedules and final scores only. 2004–2012 has play-by-play for 91.1% of games; the 541 missing games
are concentrated in 2004–2007 (210, 101, 88, 70 missing respectively). Those are gone unless a
different publisher is bought in.

Within seasons that look covered, four real gaps:

1. `espn_cfb_injuries` contains 135 rows in a single file. It is an empty table for practical
   purposes — do not plan injury features on it.
2. `espn_cfb_betting` publishes spread and total only (`game_spread`, `over_under`,
   `home_team_spread`, `home_favorite`, `odds_source`, `game_spread_available`). There is no
   moneyline and no line-movement history. Closing-line work cannot use this table alone.
3. `cfb_matchup_line` starts in 2015 and `espn_cfb_play_participants` in 2014; anything earlier has
   no per-play participation and no pregame feature file.
4. `ncaa_mfb_schedule` only carries `espn_game_id` in 2025–2026, so the NCAA publisher's scores can
   only be cross-checked against the ESPN id space for those two seasons. `ncaa_mfb_pbp` does carry
   `espn_game_id` from 2013 on, which is why the NCAA event counts above start in 2013.

The two play-by-play publishers are not independent. `espn_cfb_pbp` and `cfbfastR_cfb_pbp` share the
ESPN game id space and cover the same games (2014: 707 vs 706 games, union 708; 2021: 704 vs 732).
They are one lineage with two schemas, not two confirmations. `ncaa_mfb_pbp` is the only genuinely
separate event source, and it covers 93–99% of FBS games from 2013.

## 5. Storage cost

| kind | MB | share |
|---|---|---|
| raw | 2,904.0 | 67.9% |
| training matrix | 577.5 | 13.5% |
| scored (publisher model output) | 577.2 | 13.5% |
| model artifacts | 202.6 | 4.7% |
| reference | 14.3 | 0.3% |
| **total** | **4,275.6** | |

Three releases are 77% of the archive: `espn_cfb_model_pbp` 1,111.2 MB, `cfbfastR_cfb_pbp`
1,100.1 MB, `espn_cfb_pbp` 1,084.1 MB. The first of those is not play-by-play: inside that one
release, 577.5 MB is a 427-column training matrix (`cfb_pbp_train_full_2004_2025`), 331.2 MB is a
modelled play-by-play with `ep_before`/`ep_after`/`wp_before`/`wp_after` and model version columns,
and 202.6 MB is 35 RB evaluation artifacts (`rb_eval_rush_plays_*`, `rb_eval_rusher_seasons_*`,
`rb_eval_xrepa_loso_*`).

The files are stored exactly as published, so no re-encoding risk was taken. If disk ever matters,
the 1,372 MB of non-raw files are the first
candidates to drop, because none of them can be used as features without leakage controls anyway.

## 6. Leakage register

The rule for the next phase: **a column is usable as a feature only if its value was fixed before
kickoff.** The archive mixes observations, publisher model output and final results in the same
tables, so the register is per column, not per release.

| release | evidence in the file | risk |
|---|---|---|
| `espn_cfb_pbp` (506 cols across seasons) | `EPA`, `EPA_success`, `wpa`, `wp_before`/`wp_after`, `def_EPA`, `away_wp_before`, `drive.isScore`, `end.homeScore`, `awayFinalScore` | The same row carries the result and a model's view of it. Use only pre-snap fields (`start.down`, `start.distance`, `start.yardsToEndzone`, `start.TimeSecsRem`, `pos_score_diff_start`) and build EPA/success ourselves. Never join `EPA`, `wpa`, `wp_before` as features. |
| `cfbfastR_cfb_pbp` (362 cols) | `EPA`, `ep_before`, `ep_after`, `wpa`, `wp_before`/`wp_after`, `def_EPA`, `success`, `spread`, `formatted_spread`, `team_score`, `opponent_score` | Same. `spread` here is a per-play formatted line, not a pregame market number. |
| `espn_cfb_model_pbp` (43 cols per season file) | `ep_before`, `ep_after`, `epa`, `wp_before`, `wp_after`, `wpa`, `completion_prob`, `cpoe`, `model_pbp_version`, `cp_model_version`, `scored_date` | A modelled play-by-play, not the raw feed. Its EPA/WP are the publisher's. |
| `cfb_pbp_train_full_2004_2025` (427 cols) | a training matrix built on the same plays | Not an observation table at all. |
| `cfb_team_summaries_weekly` (789 cols) | `EPAoff`, `EPAdrive_def`, `success_off_rank`, `playsgame_off_rank`, plus `*_conf_pct` intervals | Season-to-date aggregates and national ranks; a row for week 12 contains week 12 results. Must be rebuilt as-of the target week from events. |
| `cfb_ratings_weekly`, `cfb_ratings` | `adj_off_epa`, `adj_def_epa`, `adj_net`, `fei_off`, `fei_net_rank`, `through_week` | Retrospective opponent-adjusted ratings. `through_week` is the only as-of control; anything later leaks. |
| `cfb_fpi_weekly` (51 cols) | `fpi`, `projectedw`, `probmaketitlegame`, `probwinout`, `snapshot_is_contemporaneous`, `snapshot_out_of_sequence` | ESPN's own projection. Use `snapshot_is_contemporaneous = true` and nothing else; the file also stores end-of-season snapshots. |
| `espn_cfb_power_index` | `gameprojection`, `teampredptdiff`, `teamadjgamescore`, `matchupquality` | An ESPN model's numbers, not observations. |
| `cfb_paper_index_games` | `paper_index_span`, `explosive_epa_margin`, `won` | A rating and the game result in the same row; `won` is the outcome. |
| `cfb_matchup_line` (268 cols) | `home_pregame_elo`, `home_team_talent_weighted`, `home_off_epa`, `home_def_rush_epa`, plus line fields | Pregame by name, but it is a derived file with undocumented provenance. Usable only after its own as-of semantics are verified; not raw. |
| `espn_cfb_adv_*`, `espn_cfb_usage_*`, `espn_cfb_passing`/`rushing`/`receiving` | `EPA`, `EPA_per_Play`, `WPA`, `epa_per_opportunity`, `sack_epa`, `*_rank` | Advanced tables are ESPN's EPA/QBR products, season-aggregated. |
| `cfb_schedules`, `espn_cfb_schedules`, `ncaa_mfb_schedule` | `home_winner`, `away_winner`, `result`, `outcome`, `final` scores | Correct for building labels. They must never be joined as features. |
| `cfb_recruiting_proj` | `pred_wins`, `pred_margin`, `pred_net_epa` | A projection, and it is unclear whether it was published before the season. |
| `cfb_model_artifacts` | `punt_distribution`, `cfb_field_position_ep` | Published fitted distributions; fine as a prior, never as data. |

Two structural rules follow from the register:

- Compute every team/player aggregate from the event tables with an explicit as-of cutoff, then assert
  the cutoff in the output. Do not use `cfb_team_summaries_weekly`, `cfb_ratings_weekly`,
  `cfb_fpi_weekly`, `espn_cfb_power_index` or any `*_rank` as an input.
- Any EPA/success/WP value in a model must be produced by our code from raw play fields, so the same
  estimator is used in training and in production. The publisher's EPA columns answer a different
  question with an unknown model.

## 7. Do the sources agree?

Four score checks, all "cfb_schedules" against another publisher on games present in both.

| check | compared | disagree | rate |
|---|---|---|---|
| `espn_cfb_schedules` (home/away points) | 19,134 | 17 | 99.91% |
| `espn_cfb_linescores` (sum of periods per team) | 18,950 | 20 | 99.89% |
| `espn_cfb_pbp` (running score at the last play) | 18,106 | 249 | 98.62% |
| `ncaa_mfb_schedule` (stats.ncaa.org scores, 2025–2026 only) | 2,352 | 0 | 100.00% |

Reading:

- Schedules, linescores and the NCAA publisher agree to within 0.11%. The 17–20 disagreements are
  real discrepancies (cancelled, forfeited or amended games); they are left visible in
  `archive-reconcile-scores.csv` rather than resolved by rule.
- Deriving a final score from play-by-play is **not** reliable: 249 of 18,106 games (1.38%) do not
  match, and the error rate is worst in 2007 (4.1% of games) and 2021–2022 (2.8–3.1%). Final scores
  must come from `cfb_schedules`/`linescores`, never from the last play of a pbp table.
- The NCAA check is the only one between genuinely different publishers, and it is perfect — but only
  2,352 games are joinable, because the NCAA schedule file carries `espn_game_id` only from 2025.

## 8. Verification performed

- Download: 1,986 assets in the first pass, then 13 more after the `cfbfastR_cfb_pbp` tag was found to
  sort outside the `cfb_` prefix (capital `R`, no underscore). Every file's byte size was checked
  against the release metadata at download time; 0 missing, 0 wrong size.
- Integrity: `sha256` recomputed from disk for all 1,999 files when the manifest was rebuilt.
- Readability: `backend/smoke_fbs_archive.py` decoded the first rows of the newest file in every
  release — 92 readable, 0 failures.
- Structure: `backend/audit_fbs_archive.py` read the footer of all 1,999 files — 0 unreadable.
- Content: the coverage, reconciliation and game-coverage scripts read real columns (schedules, pbp,
  linescores, NCAA schedule, team box) across all seasons, not just footers.
- One measurement defect was found and fixed while auditing: multi-season files
  (`cfb_model_pbp_2004_2025`, `cfb_pbp_train_full_2004_2025`) were being labelled season 2025,
  inflating that season's event-level row count from 1.6 M to 7.1 M. `season_of()` now returns null
  for a year range, and `kind` is decided per file rather than per release.

## 9. Reproducing it

```
backend/venv/bin/python backend/fetch_fbs_archive.py            # download (idempotent by size)
backend/venv/bin/python backend/rebuild_fbs_manifest.py         # manifest from the bytes on disk
backend/venv/bin/python backend/audit_fbs_archive.py            # releases + coverage CSVs
backend/venv/bin/python backend/audit_fbs_game_coverage.py      # FBS games with events
backend/venv/bin/python backend/reconcile_fbs_archive.py        # cross-source counts and scores
backend/venv/bin/python backend/inventory_fbs_schema.py         # per-release column inventory
backend/venv/bin/python backend/smoke_fbs_archive.py            # read a sample of every release
```

(`backend/venv` in this worktree has no interpreter of its own; the commands were run with
`/root/legendarypicks/backend/venv/bin/python`, which has pyarrow.)

## 10. What this supports

- 2013–2025 is a complete FBS event archive: 9,267 of 9,308 games with play-by-play, schedules with
  divisions and results, player box scores, rosters, drives and participation. This is the window for
  any model that needs play-level history.
- 2004–2012 is usable for game-level and season-level work on 91.1% of games, and for play-level work
  only if the 541 missing games are accepted as missing — never imputed as zero.
- 2001–2003 are schedule-and-score only.
- 2026 is in progress and is development evidence, not a held-out set.
- The archive contains no market line history beyond a single spread/total snapshot per game, so
  anything that needs line movement needs a different source.
