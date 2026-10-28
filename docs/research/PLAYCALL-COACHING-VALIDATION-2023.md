# Coaching feature check: 2023 validation

## Result

Adding the published offensive play-caller by down-and-distance feature slightly improved both metrics on the 2023 validation plays. The feature penalty was selected by 2023 log loss, so these numbers are tuning validation, not independent test performance.

| 2023 plays | Current model log loss | With caller feature | Change | Current Brier | With caller feature | Change |
|---|---:|---:|---:|---:|---:|---:|
| All 33,836 | 0.551694 | 0.550620 | -0.001074 | 0.188277 | 0.187914 | -0.000363 |
| 31,760 with published caller | 0.552838 | 0.551740 | -0.001098 | 0.188680 | 0.188311 | -0.000369 |

Training used 422,251 plays from 2010–2022. The added term was `offensive play caller × 24 down-and-distance cells`; its penalty grid was `{0.3, 3, 30, 300}`, with `3` selected on 2023 log loss. The exact caller-and-cell combination had training support for 25,205 validation plays (74.49%). A known caller name was available on 31,760 plays (93.86%); head coach was known on all 33,836 plays.

## Coaching ledger

The ledger has one row for each of 448 team-seasons from 2010–2023. It records coach names, per-coach game counts, source URLs, as-of dates, and SHA-256 hashes. Head coach attribution is available for all 7,262 regular-season team-games. The caller source covers 6,972 (96.0%); it has no published caller for Minnesota or New England in 2023, so those labels remain unknown.

- Head coach by game: [nflverse games.csv, pinned revision](https://github.com/nflverse/nfldata/blob/9f757c1db27b61966c30956fce4b9b78dc3f274a/data/games.csv), as of 2024-01-15; SHA-256 `7e74008b2f5a17be41a75426980da2131284c6e435247616a9f607901d35d029`.
- Offensive play caller by game: [NFL_public all_playcallers.csv, pinned revision](https://github.com/samhoppen/NFL_public/blob/65827e24649ef606d3c052236f2250f771e28b96/data/all_playcallers.csv), as of 2023-12-22; SHA-256 `a048a51ed8153365c709484eab4fbc8462dd9c46af8eadd3fe2250e6418cf85e`.

Historical franchise labels were explicitly normalized (`WSH` to `WAS`, `LAR` to `LA`, and the applicable older Rams, Chargers, and Raiders abbreviations). The alias audit found no conflicting or unmapped caller rows. The caller file is a published curated dataset but does not provide supporting citations per row; its explicit caller field was used verbatim, with no caller inferred from play outcomes or head-coach identity.

## Scope and files

Only the 2010–2022 training data and 2023 validation data were used. No 2024 or 2025 result was used to choose the feature, no 2026 data was accessed, and no test-season run or production change was made.

- Ledger: [coaching-ledger-2010-2023.csv](../../data/research/coaching-ledger-2010-2023.csv)
- Metrics and tuning detail: [PLAYCALL-COACHING-VALIDATION-2023.json](PLAYCALL-COACHING-VALIDATION-2023.json)
- Bounded runner: [run_coach_playcall_validation.py](../../scripts/nfl_sequence/run_coach_playcall_validation.py)
