# FBS prop field coverage - 2026-10-17

For each prop market: does a stored CFBD stat answer it, and how much of the market does that stat cover? The stored log publishes components, not markets, so a market with no single answering key is a sum of components and a different code path.

## 1. The prop population

| measure | count |
|---|---|
| props for ncaaf | 81030 |
| of those, settled | 64416 |
| of those, on a linked fixture | 80058 |

## 2. Per-market field coverage

`answerable` is the share of settled props on a linked fixture whose player has a stored log row carrying at least one of the market's answering keys. `single key` means one key answers the whole market; `components` means the market is a sum of keys and the coverage is the share with all of them.

`all keys present` is what a sum-of-components implementation needs. `any key present` is what a fail-closed grader needs, and it is gradeable only if the implementation treats an absent key as a published zero. CFBD publishes a key only when that component is nonzero, which is why the two columns differ so much.

| market | answering keys | items | all keys | coverage | any key | coverage | kind |
|---|---|---|---|---|---|---|---|
| extra_points_made | (none) | 0 |  |  | no stored key |
| field_goals_made | (none) | 0 |  |  | no stored key |
| interceptions_thrown | intc | 110 | 110 | 100.0% | 110 | 100.0% | single key |
| kicking_points | def_int | 0 |  |  | no items |
| pass_attempts | att | 808 | 808 | 100.0% | 808 | 100.0% | single key |
| pass_completions | att | 616 | 616 | 100.0% | 616 | 100.0% | single key |
| passing_rushing_yards | pass_yds, rush_yds | 1092 | 1072 | 98.2% | 1092 | 100.0% | components |
| passing_touchdowns | pass_td | 1684 | 1684 | 100.0% | 1684 | 100.0% | single key |
| passing_yards | pass_yds | 6098 | 6098 | 100.0% | 6098 | 100.0% | single key |
| receiving_yards | rec_yds | 15850 | 15342 | 96.8% | 15342 | 96.8% | single key |
| receptions | rec | 3220 | 3166 | 98.3% | 3166 | 98.3% | single key |
| rushing_receiving_touchdowns | rush_td, rec_td | 44 | 8 | 18.2% | 44 | 100.0% | components |
| rushing_receiving_yards | rush_yds, rec_yds | 1832 | 1432 | 78.2% | 1832 | 100.0% | components |
| rushing_touchdowns | rush_td | 6 | 6 | 100.0% | 6 | 100.0% | single key |
| rushing_yards | rush_yds | 9918 | 9890 | 99.7% | 9890 | 99.7% | single key |
| total_passing_touchdowns | pass_td | 320 | 320 | 100.0% | 320 | 100.0% | single key |
| total_touchdowns | pass_td, rush_td, rec_td, def_td | 3134 | 2 | 0.1% | 3134 | 100.0% | components |

## 3. The kicking markets

`kicking_points`, `extra_points_made` and `field_goals_made` have no answering key in the stored CFBD log. The data-coverage audit measured this from the release side: the ESPN player-box release publishes `totalKickingPoints` and the `fieldGoalsMade/fieldGoalAttempts` and `extraPointsMade/extraPointAttempts` strings, so the coverage exists in the publisher but not in our stored log. The field coverage here is 0 for all three, and that is a gap in the ingest, not in the publisher.

- `kicking_points`: 0 settled items with a stored log row, of which 0 have a stored kicking field.
- `extra_points_made`: 0 settled items with a stored log row, of which 0 have a stored kicking field.
- `field_goals_made`: 0 settled items with a stored log row, of which 0 have a stored kicking field.

## 4. Market aliases

Two prop markets exist under more than one name for the same statistic. The coverage audit counts them separately, which understates the market; the settlement diagnosis named the alias as a latent defect. Both are measured here rather than mapped.

- `passing_touchdowns`: 2756 props
- `total_passing_touchdowns`: 708 props

The settlement diagnosis recorded that `total_passing_touchdowns` props would become unmappable if linked without an alias, because the NCAAF market map accepts `passing_touchdowns` and these rows use `total_passing_touchdowns`. That is measured here as a naming divergence, not fixed.
