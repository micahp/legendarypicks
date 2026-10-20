# Goalie keep-rule identity-join and eligibility audit

**Audited:** 2026-10-20, before fitting.
**Inputs:** the committed Phase 1 `goalie_features.csv`, the SBR archive, and `/root/legendarypicks/research/nhl/kalshi-playoff-audit-2025-26/canonical_games_v1_7cd2fc9a6e84470c.csv`.

## Identity join

The SBR archive has no canonical game ID. Each SBR row was reconciled to exactly one official canonical row by game date and unordered pair of mapped team codes, using the existing `SBR_TEAM_CODES` crosswalk in `research/nhl/newinfo-audit-2026-10-20/audit_nhl_sources.py`. The result was one-to-one: **5,132 SBR rows, 5,132 unique canonical game IDs, zero unmatched or ambiguous rows**. The committed goalie CSV also has exactly those 5,132 unique IDs; the feature and crosswalk ID sets are equal. The executable `run_goalie_keep.py --audit-only` repeats these checks and fails on any mismatch.

Feature home/away labels were checked against the canonical game ID. Opening prices and SBR finals were aligned by the identities of the two teams, never by the SBR row's home/away position.

## Venue reversal

Exactly one SBR venue order differs from canonical home/away order:

| Game ID | Date | SBR order | Canonical order | Treatment |
| --- | --- | --- | --- | --- |
| `2019020740` | 2020-01-17 | Pittsburgh home, Detroit away | Detroit home, Pittsburgh away | Swap SBR side prices and finals by team identity before comparing to canonical home/away or scoring. |

This row remains eligible if it passes the registered completeness rules. No exclusion or home/away positional join is used.

## Source-result reconciliation

The target is canonical `official_home_winner`. SBR final scores are required for eligibility and independently checked by team identity; any SBR/canonical winner disagreement stops the run. SBR score totals are not substituted for the canonical target.

There are two scoreline discrepancies after identity alignment; both have the same moneyline winner in SBR and canonical data:

| Game ID | Date | Canonical teams | SBR mapped final | Canonical official final | Winner agrees |
| --- | --- | --- | ---: | ---: | --- |
| `2020020003` | 2021-01-13 | Toronto–Montreal | 1–0 | 5–4 | Yes |
| `2021020682` | 2022-01-17 | Buffalo–Detroit | 0–1 | 2–3 | Yes |

Across regular-season target rows with both SBR final scores, there are **zero winner disagreements** and **zero tied SBR finals**. Both scoreline differences are disclosed and retained; the canonical winner is the binary outcome used for training and scoring.

## Eligibility and separate denominators

The source population is **4,872 regular-season games**. A game is feature-complete only when all six registered values are present on both sides. Then it must also have both opening moneyline quotes and both SBR final scores. The two missing-quote/result rows are distinct and have complete goalie features.

| Season | Regular target games | Complete six-feature rows | Eligible rows | Role |
| --- | ---: | ---: | ---: | --- |
| 2018-19 | 1,271 | 1,254 | 1,254 | Training only |
| 2019-20 | 1,082 | 1,064 | 1,064 | OOF evaluation |
| 2020-21 | 868 | 851 | 849 | OOF evaluation |
| 2021-22 | 1,312 | 1,289 | 1,289 | OOF evaluation |
| 2022-23 archive slice | 339 | 307 | 307 | Partial OOF evaluation |
| **Total** | **4,872** | **4,765** | **4,763** | |

The 2018-19 season contributes **1,254 training rows** and no OOF evaluation rows. The four out-of-fold evaluation blocks contain **3,509 eligible games**: 1,064 + 849 + 1,289 + 307. The total eligible 4,763 and the OOF 3,509 are distinct denominators.

The 2022-23 archive covers only **339 games from 2022-10-11 through 2022-11-27**, a seven-week slice. Its 307 eligible rows are a partial final evaluation block, not a full-season holdout. There are three complete OOF season blocks and one partial block.

The six-feature null rule excludes **107 regular-season games**. Among the feature-complete regular rows, one lacks an opening quote pair (`2020020316`, 2021-02-25, Columbus–Chicago) and one lacks a final score pair (`2020020371`, 2021-03-04, Vancouver–Toronto). Both fail eligibility; neither is counted as a pass or loss.

## Opening-price pairs

American opening quotes are converted to decimal prices, and implied probabilities are normalized across the canonical home and away teams. All eligible opening pairs, including all **three underround pairs**, remain in the analysis and the no-vig policy control. These are identified explicitly so their control bets are visible:

| Game ID | Date | Canonical matchup | Home/away decimal opening prices |
| --- | --- | --- | ---: |
| `2021020034` | 2021-10-17 | Ottawa–Dallas | 1.552486 / 6.570000 |
| `2021020906` | 2022-03-08 | Pittsburgh–Florida | 1.546448 / 5.800000 |
| `2021020945` | 2022-03-13 | Pittsburgh–Carolina | 2.650000 / 2.620000 |

## Frozen pre-fit audit command

From the repository root:

`cd research/nhl/goalie-features-2026-10-20 && /root/lp-goalie-research/.venv/bin/python run_goalie_keep.py --audit-only`

This command checks the crosswalk, orientation, missing-row counts, scoreline reconciliation, feature completeness, and the frozen season denominators. It does not fit, predict, score, or calculate policy results. `--fit` refuses to run unless the Git worktree is clean and both this audit and `MODEL-SPEC.md` are committed.
