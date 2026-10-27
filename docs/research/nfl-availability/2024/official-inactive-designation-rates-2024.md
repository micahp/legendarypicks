# 2024 official inactive designation rates and eligibility

## Contract used

- Match key: exact `(week, team, GSIS ID)`. Team codes are kept as published in each file; no cross-team match is counted.
- Eligible roster population: one roster row on that exact team and week with top-level `status` `ACT` or `INA`. Both statuses are included in eligibility; `INA` is the label being validated, not an eligibility filter.
- Excluded from eligibility: top-level `RES`, `CUT`, `DEV`, `EXE`, and `RET`; also any other status outside `ACT`/`INA`, and official identities with no exact roster row. Excluded counts are reported below.
- Numerator: a published official `inactive` identity on the same exact key. `emergency_qb3` is a known separate designation and is counted separately, never included as an inactive. Unknown source labels are excluded and counted.
- For the adjusted rate only, the 34 roster `INA` keys absent from the NFL.com JSONL are resolved using the same-key official team/gamebook evidence in the [adjudication report](roster_ina_adjudication_2024.md). The one unresolved designation is excluded from adjusted rate denominators and reported.

## Roster population and exclusions

The roster file has 46,579 unique `(week, team, GSIS ID)` rows; no duplicate roster keys were found. Status distribution and eligibility:

| Roster status | Rows | Eligible? |
|---|---:|---|
| `ACT` | 27,369 | Yes |
| `INA` | 3,611 | Yes |
| **Eligible total** | **30,980** | **Yes** |
| `RES` | 5,426 | No |
| `CUT` | 1,028 | No |
| `DEV` | 8,722 | No |
| `EXE` | 13 | No |
| `RET` | 398 | No |
| Other statuses (`E01` 1, `TRC` 6, `TRD` 5) | 12 | No |
| **Roster total** | **46,579** | |

These are key counts, not raw player rows; each key occurs once. The strict `ACT`/`INA` rule was used, so the excluded non-eligible roster statuses total 15,599.

## Official designation source and exact-key join

The official NFL.com JSONL contains 3,586 source rows and 3,583 distinct `(week, team, GSIS ID)` identities. The three duplicate keys are retained in the JSONL; each duplicate is an additional `inactive` source row. After key deduplication:

| Published designation | Source rows | Distinct identities | Treatment |
|---|---:|---:|---|
| `inactive` | 3,434 | 3,431 | Eligible for inactive numerator only on an exact eligible roster key; adjudication can add verified same-key team/gamebook inactives absent from this JSONL. |
| `emergency_qb3` | 152 | 152 | Known designation, excluded from inactive numerator and counted separately. |
| Unknown or null designation | 0 | 0 | Excluded; none found. |

Exact-key matches for official `inactive` identities:

| Exact roster result | Count | Treatment / detail |
|---|---:|---|
| Eligible `INA` | 3,426 | Included in inactive numerator. |
| Eligible `ACT` | 3 | Included in inactive numerator; these are `ACT`/official-inactive conflicts. |
| `RES` | 1 | Excluded from eligibility and reported as a conflict: Armon Watts, Week 13 NYG, GSIS `00-0034992`, is listed `inactive` in the NFL.com JSONL while the roster row is `RES`. |
| No exact roster row | 1 | Excluded from eligibility: Yannick Ngakoue, Week 10 NE, GSIS `00-0033123`. The roster snapshot carries him under BAL for that week, status `INA`/description `W03`; Baltimore released him Nov 7 and New England claimed him Nov 8. The New England inactive is a separate team key. This is a trade-week attribution note, not an identity error. [Ravens release](https://www.baltimoreravens.com/news/keaton-mitchell-yannick-ngakoue-ravens-transactions-bengals) · [Patriots transactions](https://www.patriots.com/team/transactions/2024) · [Patriots Week 10 inactives](https://www.patriots.com/news/week-10-inactives-patriots-at-bears) |
| `CUT`, `DEV`, `EXE`, or `RET` | 0 | No official inactive identities matched these roster statuses. |
| Other non-eligible roster status | 0 | No official inactive identities matched `E01`, `TRC`, or `TRD`. |

Among the 152 emergency-QB3 identities, the exact roster status is `INA` for 151 and `ACT` for 1. These are included in the eligibility denominator but excluded from the inactive numerator. There are no unknown designation labels.

## Rates

The strict JSONL-only comparison counts official `inactive` identities on eligible exact roster keys. The adjudication-adjusted comparison also includes the 23 verified inactive identities among the 34 unmatched `INA` rows, keyed to their roster team and week. The unresolved row is excluded from the adjusted known-outcome denominator.

| Measure | Strict JSONL only | Adjudication-adjusted |
|---|---:|---:|
| Eligible roster keys in denominator | 30,980 | 30,979 (one unresolved key excluded) |
| Official inactive identities in numerator | 3,429 | 3,452 (= 3,429 + 23 adjudicated inactives) |
| Official inactive rate among eligible keys | 11.07% (3,429/30,980) | 11.14% (3,452/30,979) |
| `INA` keys validated inactive | 3,426 | 3,449 (= 3,426 + 23 adjudicated inactives) |
| Known `INA` keys in denominator | 3,611 | 3,610 (one unresolved key excluded) |
| Positive predictive value of roster `INA` | 94.88% (3,426/3,611) | 95.54% (3,449/3,610) |
| Recall of roster `INA` among eligible official inactives | 99.91% (3,426/3,429) | 99.91% (3,449/3,452) |

The roster's `INA` designation rate itself is 3,611/30,980 = 11.66%. The three official inactive identities whose roster status is `ACT` are false negatives for the `INA` label; they remain eligible and in the official inactive numerator.

For the adjusted binary comparison, excluding the one unresolved key: `INA` true positives 3,449; `INA` false positives 161; `ACT` false negatives 3; `ACT` true negatives 27,366. The 161 known non-inactive `INA` keys consist of 151 emergency-QB3 designations, 9 adjudicated not on the game roster, and 1 adjudicated on IR. The 34 adjudications break down as 23 inactive, 9 not on game roster, 1 on IR, and 1 unresolved.

## Reproducibility and constraints

- Roster input: `/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/avail/rosters/roster_weekly_2024.parquet`.
- Official inactive input: `/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/avail/inactives/official_inactives_2024_full.jsonl`.
- The JSONL was not edited. No repository files were changed. No commits, pushes, or probability fits were made.

## Injury designation table (2024 REG, weeks 1–18)

This section uses the injury report status from `nfl_hist_injuries`. The join key is exact `(week, team, GSIS ID)` after standardizing only source aliases for the same franchise: `WAS` → `WSH` and `LA` → `LAR`. No GSIS-only or trade-based team matching is used. This reconciles 43 same-week WAS/WSH inactive keys and 32 LA/LAR keys; no other team-code aliases are applied.

Eligibility variants:

- **ACT/INA:** exact roster key with top-level status `ACT` or `INA`.
- **RES-only exclusion:** exact roster key with any top-level status other than `RES`.
- Neither variant includes an identity with no exact roster row. Seven roster rows have no GSIS ID (all are DEV rows) and cannot form the required key; they are excluded and counted separately.

`None` means there is no `nfl_hist_injuries` row on the exact key. `Unknown` is a present exact-key injury row whose `report_status` is SQL NULL; it is counted but excluded from designation-rate calculations. The source also has the non-null value `Note` (its text says there is no game status), shown separately rather than recoded. The displayed inactive rate is official inactive identities divided by eligible keys in that designation row. `emergency_qb3` is always separate.

| Injury report category | ACT/INA eligible keys | Official inactive (n / rate) | Emergency QB3 | RES-only eligible keys | Official inactive (n / rate) | Emergency QB3 |
|---|---:|---:|---:|---:|---:|---:|
| Out | 797 | 788/797 (98.87%) | 0 | 801 | 788/801 (98.38%) | 0 |
| Doubtful | 166 | 160/166 (96.39%) | 1 | 166 | 160/166 (96.39%) | 1 |
| Questionable | 1,349 | 360/1,349 (26.69%) | 13 | 1,350 | 360/1,350 (26.67%) | 13 |
| None (no exact-key injury row) | 24,101 | 1,888/24,101 (7.83%) | 123 | 33,813 | 1,888/33,813 (5.58%) | 123 |
| Unknown (`report_status` is NULL; excluded from rate) | 3,141 | 77 (rate excluded) | 0 | 3,146 | 77 (rate excluded) | 0 |
| Other: `Note` (non-null source value) | 5 | 0/5 (0.00%) | 0 | 6 | 0/6 (0.00%) | 0 |
| **Total** | **29,559** | **3,273 (aggregate rate omitted; NULL statuses excluded)** | **137** | **39,282** | **3,273 (aggregate rate omitted; NULL statuses excluded)** | **137** |

### Roster and source accounting

- The scoped weekly roster has **44,473 rows**, **44,466 valid GSIS team-week keys**, no duplicate valid keys, and **7 rows without GSIS IDs**.
- ACT/INA eligibility is **26,121 ACT + 3,438 INA = 29,559 keys**. The RES-only-exclusion population is **39,282 keys**. Its excluded rows are 5,184 RES and the seven unkeyable rows.
- Strict ACT/INA excludes these roster rows by status: `RES` 5,184, `CUT` 1,018, `DEV` 8,306, `EXE` 13, `RET` 381; other statuses (`E01`, `TRC`, `TRD`) total 12.
- Official inactive source: 3,278 rows collapse to 3,275 exact identities after duplicate-key removal. **137 emergency-QB3 rows** resolve to 137 identities.
- Two official inactive identities are outside both eligibility populations: **one RES conflict** (Armon Watts, NYG Week 13) and **one with no exact roster row** (Yannick Ngakoue, NE Week 10). Ngakoue has the same GSIS ID under BAL in the weekly roster; this is a team-attribution mismatch, not an identity error. Neither is used as an eligible numerator.

The injury source has 5,954 rows and 5,952 exact keys in this scope. Two Week 15 keys have multiple report versions with conflicting status; the latest `date_modified` version is used. Cade Stover and Tyler Conklin both resolve to the later `Out` report. Across the deduplicated injury keys, `report_status` is Out 1,091, Doubtful 190, Questionable 1,462, NULL 3,203, and Note 6.

### Official inactives without an exact injury row

**1,888 distinct official inactive identities** have no injury row on the same week/team/GSIS key. The complete list is in [the CSV detail](official_inactives_without_exact_injury_row_2024_reg_w1_18.csv), including each official key, exact roster status, and any injury keys for that GSIS ID elsewhere in the 2024 regular season.

Among those misses: **1,159** no other 2024 REG injury row for GSIS ID; **698** same team, other week; **31** other team and week only. There are no same-week/different-team rows after the two franchise aliases above are standardized. Other-week or other-team rows are listed as attribution context only and are not joined.

### Reproducibility

- Injury table: read-only `/root/legendarypicks/backend/data/picks.db`, table `nfl_hist_injuries`; filter `season=2024`, `game_type=REG`, weeks 1–18.
- Eligibility roster: `/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/avail/rosters/roster_weekly_2024.parquet`.
- Official inactive source: `/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/avail/inactives/official_inactives_2024_full.jsonl`; SHA-256 `040e5af6d704820e32fdfe97b205401ae546e5ada221601fa13c1aa396c8a1be` (unchanged).
- No adjudicated INA identities were added to the official inactive numerator. The JSONL was not edited; no repository files were changed; no commit, push, or probability fit was made.
