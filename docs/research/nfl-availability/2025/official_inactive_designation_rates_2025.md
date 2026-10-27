# 2025 official inactive and injury designation rates

## Contract and validation decision

- Exact identity key: `(game_type, week, team, GSIS ID)`, which applies the exact `(week, team, GSIS ID)` rule within regular season or postseason. Only same-franchise code aliases are standardized: `WAS` → `WSH` and `LA` → `LAR`. No GSIS-only or trade-team joins are used.
- Eligibility variant 1 includes only exact roster keys with top-level status `ACT` or `INA`; `INA` is validated, not used as an eligibility filter.
- Eligibility variant 2 excludes `RES` only and includes every other roster status with a GSIS key. Rows without a GSIS ID cannot form the match key and are counted separately.
- `none` means no injury row on the exact key. `unknown` means an exact injury row exists and `report_status` is NULL; these rows are excluded from designation-rate calculations and counted.
- The validation numerator is an official NFL.com `inactive` identity on the exact key. `emergency_qb3` is shown separately in availability tables. Per Micah’s decision, it also counts as inactive for validation precision/recall, while its emergency flag remains separate for the availability target.
- These are retrospective final-table rates. `date_modified` is NULL in every 2025 injury row; it cannot establish publication timing or reconstruct an earlier report state. No probability fitting was done.

## Injury designation table

Official inactive rate is official `inactive` identities / eligible keys in that designation category. Emergency QB3 is an additional separate count. Unknown rows have no rate.

### ACT/INA

| Injury report category | Eligible keys | Official inactive (n / rate) | Emergency QB3 |
|---|---:|---:|---:|
| Out | 1,008 | 1003/1008 (99.50%) | 0 / 0 |
| Doubtful | 112 | 111/112 (99.11%) | 0 / 0 |
| Questionable | 1,203 | 332/1203 (27.60%) | 6 |
| none | 25,443 | 1945/25443 (7.64%) | 106 |
| unknown | 3,204 | 85 (rate excluded) | 0 / 0 |
| **Total eligible** | **30,970** | **3,476 (unknown report_status excluded from designation-rate comparison)** | **112** |

### RES-only excluded

| Injury report category | Eligible keys | Official inactive (n / rate) | Emergency QB3 |
|---|---:|---:|---:|
| Out | 1,011 | 1003/1011 (99.21%) | 0 / 0 |
| Doubtful | 112 | 111/112 (99.11%) | 0 / 0 |
| Questionable | 1,203 | 332/1203 (27.60%) | 6 |
| none | 35,521 | 1945/35521 (5.48%) | 106 |
| unknown | 3,213 | 85 (rate excluded) | 0 / 0 |
| **Total eligible** | **41,060** | **3,476 (unknown report_status excluded from designation-rate comparison)** | **112** |

### By season phase

| Game type | Scope | Injury rows | Out | Doubtful | Questionable | NULL report_status | Eligible ACT/INA | Eligible excluding RES |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| REG | Regular season weeks 1–18 | 5,783 | 1,342 | 119 | 1,217 | 3,105 | 29,548 | 39,183 |
| WC | Wild Card | 136 | 16 | 0 | 37 | 83 | 655 | 864 |
| DIV | Divisional | 85 | 13 | 0 | 17 | 55 | 437 | 577 |
| CON | Conference championships | 44 | 10 | 1 | 9 | 24 | 220 | 289 |
| SB | Super Bowl | 20 | 1 | 0 | 3 | 16 | 110 | 147 |

## Validation metrics

Roster `INA` precision is shown both for ordinary official inactives alone and with emergency QB3 counted as a validation positive. Recall uses exact official identities that fall within that eligibility variant. Emergency QB3 remains separately labeled in the availability target. The final metric column reports ordinary official inactive identities on ACT keys / on eligible statuses other than ACT or INA.

| Eligibility | Scope | Eligible roster keys | INA keys | Ordinary official inactive positives | INA PPV, ordinary only | INA PPV, incl. emergency QB3 | Ordinary recall | Recall incl. emergency QB3 | ACT conflicts / non-ACT-INA conflicts |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ACT/INA | All 2025 | 30,970 | 3,593 | 3,476 | 96.16% (3,455/3,593) | 99.22% (3,565/3,593) | 99.40% (3,455/3,476) | 99.36% (3,565/3,588) | 21 / 0 |
| ACT/INA | REG | 29,548 | 3,419 | 3,314 | 96.31% (3,293/3,419) | 99.24% (3,393/3,419) | 99.37% (3,293/3,314) | 99.33% (3,393/3,416) | 21 / 0 |
| ACT/INA | WC | 655 | 79 | 74 | 93.67% (74/79) | 98.73% (78/79) | 100.00% (74/74) | 100.00% (78/78) | 0 / 0 |
| ACT/INA | DIV | 437 | 53 | 50 | 94.34% (50/53) | 98.11% (52/53) | 100.00% (50/50) | 100.00% (52/52) | 0 / 0 |
| ACT/INA | CON | 220 | 28 | 26 | 92.86% (26/28) | 100.00% (28/28) | 100.00% (26/26) | 100.00% (28/28) | 0 / 0 |
| ACT/INA | SB | 110 | 14 | 12 | 85.71% (12/14) | 100.00% (14/14) | 100.00% (12/12) | 100.00% (14/14) | 0 / 0 |

| RES-only excluded | All 2025 | 41,060 | 3,593 | 3,476 | 96.16% (3,455/3,593) | 99.22% (3,565/3,593) | 99.40% (3,455/3,476) | 99.36% (3,565/3,588) | 21 / 0 |
| RES-only excluded | REG | 39,183 | 3,419 | 3,314 | 96.31% (3,293/3,419) | 99.24% (3,393/3,419) | 99.37% (3,293/3,314) | 99.33% (3,393/3,416) | 21 / 0 |
| RES-only excluded | WC | 864 | 79 | 74 | 93.67% (74/79) | 98.73% (78/79) | 100.00% (74/74) | 100.00% (78/78) | 0 / 0 |
| RES-only excluded | DIV | 577 | 53 | 50 | 94.34% (50/53) | 98.11% (52/53) | 100.00% (50/50) | 100.00% (52/52) | 0 / 0 |
| RES-only excluded | CON | 289 | 28 | 26 | 92.86% (26/28) | 100.00% (28/28) | 100.00% (26/26) | 100.00% (28/28) | 0 / 0 |
| RES-only excluded | SB | 147 | 14 | 12 | 85.71% (12/14) | 100.00% (14/14) | 100.00% (12/12) | 100.00% (14/14) | 0 / 0 |

## Official-list roster disposition

These counts are distinct resolved official identities, joined to the roster only after name-to-GSIS resolution. Status exceptions are not used to change player identity.

| Official list label | ACT | INA | RES | CUT | DEV | EXE | RET | Other status | No exact team-week row; same GSIS elsewhere | No exact roster identity anywhere that week |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| inactive | 21 | 3,455 | 1 | 0 | 0 | 0 | 0 | 0 | 5 | 0 / 0 |
| emergency_qb3 | 2 | 110 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 |

### Exact-key roster exceptions and attribution notes

| Result | Game type | Week | Official team | Name | GSIS ID | Roster context |
|---|---|---:|---|---|---|---|
| RES conflict | REG | 2 | GB | Brenton Cox | 00-0038463 | RES |
| same-week other-team attribution | REG | 5 | CIN | Jordan Jefferson | 00-0039743 | SF/INA |
| same-week other-team attribution | REG | 9 | NE | John Saunders | 00-0040310 | MIA/INA |
| same-week other-team attribution | REG | 12 | KC | Josh Williams | 00-0040429 | TB/RES |
| same-week other-team attribution | REG | 15 | NYG | Ryan Miller | 00-0038824 | TB/INA |
| same-week other-team attribution | REG | 16 | PIT | Brodric Martin-Rhodes | 00-0038939 | LV/INA |

The one RES conflict (Brenton Cox, REG Week 2, GB) is excluded from both eligibility variants. The five same-week, other-team rows are attribution notes only; they are not exact roster matches and do not change identity or eligibility. Unresolved GSIS rows are listed separately.

Eligibility row accounting: the 2025 roster file has 46,849 total rows and 46,820 exact GSIS team-week keys; duplicate keys: 0. Strict ACT/INA status counts are 27,377 ACT and 3,593 INA. The RES-only-exclusion population contains 41,060 keys. There are 29 roster rows without GSIS IDs (all are excluded because they cannot form the exact key): REG/DEV=25, REG/RES=3, WC/DEV=1.

### Full roster status counts

| Roster status | Roster rows | Rows with GSIS key | ACT/INA eligible | RES-only variant eligible |
|---|---:|---:|---|---|
| ACT | 27,377 | 27,377 | Yes | Yes |
| INA | 3,593 | 3,593 | Yes | Yes |
| RES | 5,763 | 5,760 | No | No |
| CUT | 951 | 951 | No | Yes |
| DEV | 8,783 | 8,757 | No | Yes |
| EXE | 7 | 7 | No | Yes |
| RET | 361 | 361 | No | Yes |
| TRC | 7 | 7 | No | Yes |
| TRD | 7 | 7 | No | Yes |

The 29 roster rows without GSIS IDs are unkeyable and excluded under both variants: REG/DEV=25, REG/RES=3, WC/DEV=1. These rows are subsets of the raw roster counts above.

## Official identities without an exact injury row

**2,056** resolved official identities have no `nfl_hist_injuries` row on the exact game-type/week/team/GSIS key: 1,950 ordinary inactives and 106 emergency QB3s. 0 have a same-week injury row under a different team code; those rows are attribution context only and do not count as matches. The complete row-level list, including any same-team other-week records, is in [the CSV](official_inactives_without_exact_injury_row_2025.csv). Unresolved identities cannot be checked for an exact injury key and are listed separately.

## Injury source accounting

`nfl_hist_injuries` contains 6,068 rows for season 2025 across REG and playoffs. Exact injury keys are unique (no duplicate or conflicting versions); `date_modified` is NULL in 6,068/6,068 rows. Source status totals are `Doubtful` 120, `NULL` 3,283, `Out` 1,382, `Questionable` 1,283.

## Reproducibility

- NFL.com inactive articles: 64 rendered source pages listed in [page coverage](inactive_page_coverage_2025.json); all 285 games and 570 team lists reconcile to the schedule. Examples: [Week 1](https://www.nfl.com/news/inactive-reports-for-sunday-s-week-1-games-of-2025-nfl-season), [Week 18](https://www.nfl.com/news/nfl-week-18-inactives-players-ruled-out-for-sunday-s-14-games), [Super Bowl LX](https://www.nfl.com/news/super-bowl-lx-inactives-seattle-seahawks-vs-new-england-patriots).
- Identity resolution uses `/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/avail/players.parquet`; roster rows were not used to select GSIS IDs.
- Eligibility roster: `scratchpad/avail/rosters/roster_weekly_2025.parquet`. Injury source: read-only `/root/legendarypicks/backend/data/picks.db`, table `nfl_hist_injuries`, season 2025.
- 2024 source JSONL was not edited. No probability fit was made during this analysis.
