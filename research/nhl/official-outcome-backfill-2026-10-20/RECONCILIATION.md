# NHL official outcomes: archive reconciliation

Outcome-quality audit only. No fitting, forecast, ROI, sportsbook price test, or production data replacement.

## Population

- Canonical official boxscore frame: 4,876 regular-season games.
- SBR regular-season market population: 4,872 games.
- The final partial 2022–23 canonical block is 343 games, 2022-10-07 to 2022-11-27; its SBR subset is 339 games, 2022-10-11 to 2022-11-27.
- Four canonical-only games in that block: `[2022020001, 2022020002, 2022020175, 2022020185]`.
- The goalie experiment population remains 4,872 SBR games; its 4,763 eligible rows and 3,509 OOF rows remain separate and unchanged.

## Reconciliation by season

See `reconciliation_by_season.csv` for row and game counts, exact matches, value discrepancies, missing rows, identity conflicts, official and archive zero-TOI goalie rows, official team-SOG totals, canonical-score checks, and potential cross-source name reviews.

| Season | Canonical games | SBR games | SOG exact / shared | SOG value mismatches | SOG official only | SOG archive only | Goalie appearances | Goalie exact / shared | Goalie value mismatches | Goalie official only | Goalie archive only | Official zero-TOI slots | Archive zero-TOI rows | Potential name-review IDs |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018 | 1271 | 1271 | 45553 / 45753 | 200 | 3 | 3 | 2720 | 2614 / 2720 | 106 | 0 | 0 | 2364 | 0 | 0 |
| 2019 | 1082 | 1082 | 38639 / 38919 | 280 | 32 | 12 | 2306 | 2168 / 2301 | 133 | 5 | 2 | 2023 | 2 | 0 |
| 2020 | 868 | 868 | 31118 / 31195 | 77 | 33 | 1 | 1852 | 1833 / 1852 | 19 | 0 | 0 | 1620 | 0 | 1 |
| 2021 | 1312 | 1312 | 47147 / 47168 | 21 | 43 | 38 | 2818 | 2800 / 2818 | 18 | 0 | 0 | 2431 | 0 | 1 |
| 2022 | 343 | 339 | 12341 / 12343 | 2 | 1 | 1 | 723 | 721 / 723 | 2 | 0 | 0 | 649 | 0 | 4 |

Aggregate row reconciliation:
- SOG: 175,490 official rows; 175,433 archive rows; 175,378 shared game/player IDs; 174,798 exact (99.669286% of shared rows); 580 value mismatches; 112 official-only; 55 archive-only.
- Played goalie outcomes: 10,419 official rows; 10,416 archive rows; 10,414 shared game/player IDs; 10,136 exact across saves, shots against, and goals against (97.330517% of shared rows); 278 value mismatches; 5 official-only; 2 archive-only.
- Maximum side-flip share: 0.478053% at SAVES line 24.5 in start season 2019 (11/2,301).

## Data-quality checks

- Official boxscore game-side rows equal the frozen frame: 9,752 rows for 4,876 game IDs.
- Official team SOG sum mismatches: 20 team-sides. Per-side detail: `official_team_sog_validation.csv`.
- Official boxscore score conflicts with the frozen canonical table: 0 team-sides. Detail: `official_canonical_score_conflicts.csv`.
- Official goalie rows retained in `official_goalie_outcomes.csv`: 19,506; zero-TOI rows: 9,087. Only TOI>0 official rows and archive `icetime>0` rows enter the played-game comparison. Official zero-TOI records remain available in `zero_toi_goalie_slots.csv` and raw payloads; archive zero-ice-time rows are in `archive_nonappearing_goalie_slots.csv`.
- Played-goalie one-sided rows: 5 official-only and 2 archive-only. Detail with names, TOI, and all three outcomes: `played_goalie_one_sided_rows.csv`.
- Identity/source issues: 5. Detail: `archive_identity_issues.csv`.
- Cross-source display-name review: 5 player IDs, 151 shared SOG rows, and 0 shared goalie rows. These are potential alias/spelling/ID conflicts, not automatic corrections; details are in `archive_name_crosscheck.csv`.
- Maximum SOG/Saves side-flip share over the preregistered audit lines: 0.478053%. Per line and season: `prop_side_flip_by_season.csv`.
- Full discrepancy rows: `archive_sog_discrepancies.csv` and `archive_goalie_discrepancies.csv`.
- Player joins use numeric NHL player IDs and canonical game IDs. No name-based fallback or silent team substitution is used.

## Limitations

This audit compares the historical archive with the official GameCenter boxscore snapshots retrieved for this task. It does not certify sportsbook settlement rules, stat-correction timing, or historical player-prop prices. Official boxscores alone do not provide shifts or event order for V3 simulation.
