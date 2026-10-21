# NHL official outcome backfill — coverage

Research-only official outcome import. No model fitting, market evaluation, ROI, or production data replacement was performed.

## Population

- Canonical regular-season frame: **4,876** games; season counts `{'2018': 1271, '2019': 1082, '2020': 868, '2021': 1312, '2022': 343}`.
- SBR market population inside that frame: **4,872** games.
- Canonical-only games, outside the SBR market archive: `[2022020001, 2022020002, 2022020175, 2022020185]`. The partial 2022–23 canonical frame covers 2022-10-07 to 2022-11-27 (343 games); its SBR subset covers 2022-10-11 to 2022-11-27 (339 games).
- The goalie experiment remains a separate 4,872-game SBR target population, with 4,763 complete-case rows and 3,509 OOF evaluation rows; these denominators are unchanged.

## Official response and outcome coverage

- Official GameCenter responses validated: **4,876/4,876** unique canonical game IDs.
- Response provenance: `{'official_gamecenter': 4576, 'prior_official_audit_cache': 300}` (the prior audit cache is retained as source data; all newly fetched responses remain individually hash-pinned).
- Team-side rows: 9,752; skater player-game rows: 175,490, including 175,482 positive-TOI appearances, 8 zero-TOI slots, and 0 unknown-TOI rows.
- Goalie rows retained: 19,506, including 9,087 zero-TOI slots. Played-goalie sample rows (TOI > 0): 10,419.
- Player SOG sums versus the official boxscore team SOG totals: `{'PASS': 9732, 'MISMATCH': 20}`.
- Goalie arithmetic identity failures (`saves + goalsAgainst = shotsAgainst`): 2.
- Missing/invalid or duplicate player-ID issues in official rows: 0; all reported quality issues: 22. See `official_quality_issues.csv`.
- Quality issue counts by type: `{'PLAYER_SOG_SUM_VS_TEAM_TOTAL': 20, 'GOALIE_TOTAL_IDENTITY_MISMATCH': 2}`.

| Start season | Games | Team rows | Skater rows | Skater appearances | Skater zero-TOI | Goalie rows | Played goalie rows | Goalie zero-TOI | Team-SOG checks | Goalie arithmetic failures | Identity issues |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|
| 2018 | 1271 | 2542 | 45756 | 45755 | 1 | 5084 | 2720 | 2364 | MISMATCH=2, PASS=2540 | 0 | 0 |
| 2019 | 1082 | 2164 | 38951 | 38949 | 2 | 4329 | 2306 | 2023 | MISMATCH=5, PASS=2159 | 0 | 0 |
| 2020 | 868 | 1736 | 31228 | 31226 | 2 | 3472 | 1852 | 1620 | MISMATCH=6, PASS=1730 | 0 | 0 |
| 2021 | 1312 | 2624 | 47211 | 47208 | 3 | 5249 | 2818 | 2431 | MISMATCH=6, PASS=2618 | 0 | 0 |
| 2022 | 343 | 686 | 12344 | 12344 | 0 | 1372 | 723 | 649 | MISMATCH=1, PASS=685 | 2 | 0 |

## Reproducibility and limitations

- Raw bodies are stored outside Git at `/root/lp-data/nhl-official-outcome-backfill-2026-10-20`. Per-game raw and compressed SHA256 values are in `manifest.jsonl` (manifest SHA256 `0ba44bcebefecb0a8eefbea995e8f5370583600eec77d0be12be574f308d71a2`).
- `official_goalie_outcomes.csv` retains zero-TOI backup slots. Exclude `appeared=0` from played-game goalie prop outcome samples; do not delete those rows from the raw official artifact.
- This report validates official boxscore coverage and reconciles outcome fields against the local historical archive. It does not certify sportsbook settlement rules or stat-correction timing.
- Official boxscores do not contain shift-by-shift data and do not complete the V3 simulation roadmap.
