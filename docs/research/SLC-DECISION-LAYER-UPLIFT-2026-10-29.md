# SLC decision layer: where the points come from (2026-10-29)

Research, exploratory. Snapshot 2026_08_CAR_GB, seeds 1 to 100, paired by seed against the same-seed arm named in each row. The
comparison target is the league's own regular-season totals, not this matchup: 2024 averaged 45.82 points a game and 2025 46.03,
with a home margin of 1.87 and 2.07 (`nfl_schedule`, regular season).

## What the layer does

Decision model categories A to N are drawn before each outcome from the offense's team prior for the situation (prior season only),
and the outcome pool is conditioned on the drawn labels in two ways:

1. **Lifts** (`_label_lift`): each label multiplies the outcome weights by its lift, averaged over the labels in log space.
   The lift is measured against the labelled rows' own outcome mix (the charted seasons, 2022 to 2025).
2. **Row filter** (`decision_filter`): the sampled row is drawn from rows that carry the drawn labels, category by category, with a
   fallback when no row matches.

## Arms

| arm | what is on | valid | home | away | total | margin |
|---|---|---:|---:|---:|---:|---:|
| score_clock_v2 | score-clock layer | 99 | 19.78 | 20.21 | 39.99 | -0.43 |
| shares_v2 | + player-share adapter | 99 | 19.78 | 20.21 | 39.99 | -0.43 |
| decision_unfiltered | + decision labels, lifts only | 96 | 19.89 | 23.41 | 43.29 | -3.52 |
| decision_v3 | + decision labels, lifts and row filter | 100 | 26.42 | 23.82 | 50.24 | 2.60 |
| decision_v2 | as decision_v3, before the lift-base fix | 100 | 26.74 | 23.72 | 50.46 | 3.02 |

Paired differences (arm minus shares_v2, game clustered standard error):

- decision_unfiltered: total +3.68 ± 1.63, margin -3.24 ± 1.58.
- decision_v3: total +10.36 ± 1.68, margin +3.25 ± 1.71.
- decision_v3 minus decision_unfiltered: total +6.39 ± 1.78, margin +5.90 ± 1.66. This is the row filter's effect.
- decision_v3 minus decision_v2: total -0.22 ± 0.14. The lift-base fix moved the total by almost nothing.

## Reading

- The lift-base fix was a real bias but a small one. It did not produce the uplift.
- The lifts alone add about 3.7 points. That is closer to the league total (43.3 against 45.9) but still short.
- The row filter adds about 6.4 points on top. It draws the outcome row from a narrow set of rows that carry every drawn label,
  and those rows are not a random draw from the cell. This is a selection effect in the sampler, not better football. We have not
  yet shown which rows are over-represented; that is the next check.
- decision_v3 totals about 50 against a real 46. It overshoots by about four points, so the +10 is not a calibration gain.
- Margins are noisy at this sample size (about ±1.6 standard error per arm), so the margin differences should not be read as
  team effects.

## Recommendation

Do not adopt the filtered layer on the strength of the points. The lift-only arm is the defensible candidate, since it is nearer the
real total and does not narrow the row set. The filter default is a design decision for the owner of this branch. It is left on
here, because changing it would change the arm already recorded above.

## Next checks

1. Find which labelled rows the filter over-samples (compare the mix of sampled rows against the cell's mix, by season and zone).
2. Repeat the three arms on at least two more snapshots before quoting any uplift.
