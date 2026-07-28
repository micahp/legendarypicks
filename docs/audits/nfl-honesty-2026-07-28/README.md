# NFL data honesty audit — 2026-07-28

Read-only audit of the managed `:8096` draft board, mock-draft pool, and player-detail payloads. No application, database, frontend, server, branch, or production state was changed.

## Result

- 243 unique players have target share wrong because published zero-target weeks are absent from the aggregate.
- 284 unique players have snap percentage wrong or missing because only snap values attached to stat-log weeks are averaged.
- 373 unique source-absent players are rendered with `games_played=0` and `team_games=17` rather than null.
- 34 offensive skill players with an official 0.0 PPR season are rendered as null.
- Brandon Aubrey's fake-punt carry leaks into the mock pool and detail as offensive PPR 0.0 and xFP 0.8; the board suppresses both.
- One same-name PFR/GSIS collision corrupts Jonah Williams' weekly availability strip, and one multi-position depth join duplicates Eli Heidenreich.
- PK scoring: 0 disagreements across 32 populated active kickers (38 active PK entities). D/ST scoring: 0 disagreements across 32 of 32 team defenses.
- Pool vs player-detail parity: 0 disagreements across 300 players × 17 numerical/list fields (5,100 comparisons). Defects present in the pool therefore reproduce exactly in detail.

## Worst target-share disagreements

| Player | Ours | Published | Delta |
|---|---:|---:|---:|
| Tom Kennedy (12510) | 14.8% | 2.5% | +12.3 pp |
| Britain Covey (4838) | 11.8% | 2.0% | +9.8 pp |
| George Holani (10218) | 10.0% | 1.0% | +9.0 pp |
| Ty Chandler (3946) | 13.3% | 4.4% | +8.9 pp |
| Jaret Patterson (17271) | 10.5% | 1.8% | +8.7 pp |
| Corey Kiner (12617) | 10.7% | 2.7% | +8.0 pp |
| Gunner Olszewski (16886) | 10.2% | 2.6% | +7.6 pp |
| Rasheen Ali (406) | 11.0% | 3.7% | +7.3 pp |
| Dylan Drummond (6141) | 14.2% | 7.1% | +7.1 pp |
| Nick Kallerup (12301) | 8.3% | 2.1% | +6.2 pp |
| Ronnie Bell (1633) | 11.8% | 5.9% | +5.9 pp |
| Isaiah Williams (24145) | 14.6% | 8.8% | +5.8 pp |
| Malik Davis (5432) | 7.1% | 1.4% | +5.7 pp |
| Caleb Williams (24033) | 5.9% | 0.3% | +5.6 pp |
| Jawhar Jordan (12179) | 11.2% | 5.6% | +5.6 pp |

## Worst snap-percentage disagreements

| Player | Ours | Published | Delta |
|---|---:|---:|---:|
| Tom Kennedy (12510) | 65.0% | 12.0% | +53 pp |
| Jalen Royals (19264) | 67.0% | 19.0% | +48 pp |
| Britain Covey (4838) | 55.0% | 10.0% | +45 pp |
| Drake Dabney (5163) | 88.0% | 52.0% | +36 pp |
| Efton Chism III (4058) | 53.0% | 18.0% | +35 pp |
| Josh Johnson (11645) | 80.0% | 49.0% | +31 pp |
| Moliki Matavao (14390) | 50.0% | 21.0% | +29 pp |
| Anthony Gould (8304) | 36.0% | 9.0% | +27 pp |
| Jahdae Walker (23116) | 42.0% | 15.0% | +27 pp |
| Shane Zylstra (25124) | 66.0% | 40.0% | +26 pp |
| Jalen Brooks (2669) | 55.0% | 30.0% | +25 pp |
| Ronnie Bell (1633) | 53.0% | 29.0% | +24 pp |
| Nick Kallerup (12301) | 48.0% | 24.0% | +24 pp |
| Jake Tonges (22385) | 57.0% | 33.0% | +24 pp |
| Devin Culp (5068) | 29.0% | 6.0% | +23 pp |

## Exact lead checks

- Justin Jefferson (11274): ours 11.9 PPR/game, 30.7% target share, 14.7 xFP/game. Published: 201.5 PPR / 17 = 11.8529, weekly target-share mean 30.6696%, and 249.14 xFP / 17 = 14.6553. All three round to ours; the 2.8/game underperformance is source-real.
- Brandon Aubrey (882): published week 15 has one carry, six yards, 0.6 PPR and 0.77 xFP. Pool/detail expose 0.0 PPR/team-game and 0.8 xFP/game as if they were kicker metrics. Board correctly emits null.

## Source evidence

- `/tmp/stats_player_week_2025.parquet` — 852,704 bytes — SHA-256 `afc45559f6385a3f253887f37efcb1124006db799c91a58d8c7151429136f0cc`
- `/tmp/stats_team_week_2025.parquet` — 126,702 bytes — SHA-256 `3916967bb228efef7b42bab7eec7d8c956cfe5aaf886828c784cc91f061bb3a7`
- `/tmp/claude-0/-root/f9798c80-dc52-45bd-ba98-be25c4818df0/scratchpad/snap_counts_2025.parquet` — 242,090 bytes — SHA-256 `af7b7b38c8ed0c39a46486941eb919b07adcf8ddf5568a3cb403d263bff4968c`
- `/tmp/claude-0/-root/6ef0e1d1-5fb0-4a29-88fd-6692fb36ea86/scratchpad/ep_weekly_2025.parquet` — 1,131,415 bytes — SHA-256 `b1d0153f01eb56fd7832f220da600150c0f4315b4cbcda38b9a020c7318fcdd4`
- `/tmp/claude-0/-root/6ef0e1d1-5fb0-4a29-88fd-6692fb36ea86/scratchpad/depth_charts_2026.parquet` — 1,777,828 bytes — SHA-256 `346cc0cead22e006dd77c4d0c90d7f9b18893bc14fc7bdd3be4dea46dee6d9ea`
- `/tmp/games.csv` — 2,172,886 bytes — SHA-256 `de3ce5e93087fe8b312e014e48ce872a2adf0224ff4f9a207f1c33b31a16b365`
- Published snap rows unresolved by the published PFR→GSIS crosswalk: 4,768; these were not guessed or name-derived.

## Exhaustive disagreements

`all-disagreements.csv` contains 3,543 rows with ours and published side-by-side. Severity 5 is live ESPN ADP/ownership refresh drift, retained for completeness but not classified as an aggregation bug.

Counts by finding:

- live ADP source refresh drift: 1,984 surface-field disagreements
- source absence rendered as a number: 816 surface-field disagreements
- snap percentage omits published snap weeks: 320 surface-field disagreements
- target share drops published zero weeks: 304 surface-field disagreements
- published zero PPR rendered as null: 70 surface-field disagreements
- target share loses weekly precision: 32 surface-field disagreements
- draft-board aggregate rounding disagreement: 6 surface-field disagreements
- depth number paired with stale position label: 4 surface-field disagreements
- snap percentage loses weekly precision: 3 surface-field disagreements
- Brandon Aubrey offensive-stat category leak: 2 surface-field disagreements
- multi-position depth row duplicates player: 1 surface-field disagreements
- snap identity crosswalk collision: 1 surface-field disagreements

Generated 2026-07-28T21:04:03.436386+00:00.
