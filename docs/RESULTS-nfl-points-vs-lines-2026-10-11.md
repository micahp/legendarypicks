# RESULTS: projected points against the closing spread and total, QB and injury terms, 2026-10-11

Script and pre-registered rules: `backend/nfl_points_lines_backtest.py` (committed in `e7f676d`
before its only run). Read-only on the dev DB; nothing recorded, ingested or locked. Lines are the
nflverse closing lines without timestamps. Brier for a cover or over probability is compared with
the line's own 0.5 (Brier 0.25) by a paired bootstrap; negative means better than the line.
Pushes are excluded and counted. Break-even hit rate at -110 is 52.38%.

Models: v1 (frozen), B (v1 restacked on earlier seasons: margin and total), MP (B plus the
market-implied prior, margin only), QBE (expected starter = previous game's starter, injury
replacement from 2024), QBA (actual starter, hindsight, a proxy for information known 90 minutes
before kickoff), INJ (B plus non-QB skill-player injury load, 2024-2025 only).

## Verdict

**Neither the projected margin nor the projected total beats its closing line.** Every cover
and over Brier is worse than the line's 0.25 in 2011-2023, with intervals excluding zero. In
2024-2025 the spread Brier is still worse for every model; the total Brier intervals span zero
(not distinguishable from the line). No hit rate is above 50% with an interval that excludes it,
except B's 2024-2025 totals (0.5422 [0.5010, 0.5855]), which do not exceed the 52.38% break-even
and fail in 2011-2023 (0.4853).

## Spread (cover)

| Model | 2011-2023 hit (n 3,076, 92 pushes) | Brier minus line | 2024-2025 hit (n 507, 5 pushes) | Brier minus line |
|---|---|---|---|---|
| v1 | 0.4837 [0.4655, 0.5020] | +0.0129 [+0.0092, +0.0166] | 0.4911 [0.4477, 0.5345] | +0.0179 [+0.0082, +0.0272] |
| B | 0.4883 [0.4704, 0.5065] | +0.0103 [+0.0070, +0.0137] | 0.4813 [0.4379, 0.5247] | +0.0160 [+0.0072, +0.0246] |
| MP | 0.5101 [0.4919, 0.5276] | +0.0043 [+0.0014, +0.0072] | 0.4773 [0.4339, 0.5207] | +0.0122 [+0.0044, +0.0201] |
| QBE | 0.4795 [0.4610, 0.4974] | +0.0117 [+0.0083, +0.0151] | 0.4773 [0.4339, 0.5207] | +0.0140 [+0.0054, +0.0223] |
| QBA (hindsight) | 0.4867 [0.4685, 0.5042] | +0.0104 [+0.0073, +0.0135] | 0.4892 [0.4458, 0.5325] | +0.0124 [+0.0043, +0.0204] |
| INJ | = B | = B | 0.4852 [0.4418, 0.5286] | +0.0173 [+0.0082, +0.0259] |

## Total (over)

| Model | 2011-2023 hit (n 3,136, 32 pushes) | Brier minus line | 2024-2025 hit (n 509, 3 pushes) | Brier minus line |
|---|---|---|---|---|
| v1 | 0.4821 [0.4636, 0.5000] | +0.0122 [+0.0089, +0.0157] | 0.5206 [0.4774, 0.5639] | +0.0088 [-0.0002, +0.0177] |
| B (and MP) | 0.4853 [0.4672, 0.5029] | +0.0089 [+0.0060, +0.0119] | 0.5422 [0.5010, 0.5855] | +0.0060 [-0.0017, +0.0135] |
| QBE | 0.4853 [0.4672, 0.5029] | +0.0091 [+0.0062, +0.0120] | 0.5206 [0.4794, 0.5639] | +0.0076 [+0.0001, +0.0152] |
| QBA (hindsight) | 0.4978 [0.4799, 0.5153] | +0.0077 [+0.0050, +0.0105] | 0.5167 [0.4735, 0.5619] | +0.0060 [-0.0014, +0.0133] |
| INJ | = B | = B | 0.5344 [0.4912, 0.5776] | +0.0049 [-0.0036, +0.0134] |

## QB and injury terms against B

| Term | 2011-2023 win Brier | spread Brier | total Brier | 2024-2025 win Brier | Kept |
|---|---|---|---|---|---|
| QBE (honest) | +0.0005 [-0.0006, +0.0016] | +0.0014 [+0.0003, +0.0026] | +0.0001 | -0.0019 [-0.0039, -0.0001] | no: fails 2011-2023 |
| QBA (hindsight) | -0.0017 [-0.0030, -0.0005] | +0.0001 | -0.0012 [-0.0023, -0.0000] | -0.0031 [-0.0064, +0.0001] | meets the rule, but uses hindsight starters |
| INJ (2024-2025 only) | n/a | n/a | n/a | +0.0014 [-0.0008, +0.0037] | no |

- Starter changes: on 705 of 7,360 graded team-games (2011-2025) the actual starter differed from
  the previous game's. In 2024-2025, 31 expected starters were listed Out or Doubtful and
  replaced.
- INJ: 351 of 2024-2025 games had any listed non-QB load. Its cross-fitted coefficients are
  unstable (margin -0.9 from 2025 data, -12.9 from 2024 data; total +5.9 both), so the term is
  noise at this sample. Offensive line and defense are not covered (no 2024 snap data).
- QBA meeting the rule means: knowing the real starter helps win Brier and totals by about 0.001
  to 0.002. That is the information available at a 90-minute lock, but our history only records it
  after the fact, so this is an upper bound, not a forecast result. The market already prices it:
  QBA is still +0.0107 behind the moneyline in 2011-2023.

Sam's model: we have none of its numbers, so nothing here compares with it.
