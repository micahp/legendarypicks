# Decision model, per role: frozen specification (2026-10-27)

Status: frozen before any 2026 result is computed. The 2026 test is run once. Nothing in this document may change after
that run. Any change needs a new version, and the 2026 result stays on record.

Scope: how the AI's offensive decisions match a team's observed decisions, by role, after training on 2025. Outcomes
(yards, points, wins) are not scored. Movement is not modelled here. The physics engine is not involved.

## 1. Question

Given the situation of each play, does a prior trained on 2025 reproduce how each team's offense used its roles in
2026 Weeks 1 to 7? Does a team-specific prior do better than a league prior for the same situations?

## 2. Roles and decisions

Each play is assigned one decision per category. Role labels come from the player position in the players release.
Positions are grouped as: RB (RB and FB), WR, TE, QB, and Other (every other position).

| Category | Plays | Definition | Role labels |
|---|---|---|---|
| A. Pass target role | Pass plays with a receiver ID | Position of the receiver | RB, WR, TE, Other |
| B. Ball carrier role | Run plays (rush attempt flag) | Position of the rusher; scrambles counted as QB | RB, QB, WR or TE, Other |
| C. Run gap | Run plays with an RB carrier and a charted gap | `run_gap` | guard, tackle, end |
| D. Pass depth | Pass plays | `pass_length` | short, deep |
| E. Pass location | Pass plays | `pass_location` | left, middle, right |
| F. Shotgun | All plays | `shotgun` | yes, no |
| G. Play action | Pass plays with charting | `is_play_action` | yes, no |
| H. Motion | All plays with charting | `is_motion` | yes, no |
| I. Blitz | Pass plays with charting | At least one extra rusher: `n_blitzers >= 1` | yes, no |
| J. QB alignment | Plays with a charted alignment | `qb_location` | shotgun (S), under center (U), pistol (P) |
| K. Ball hash | Plays with a charted hash | `starting_hash` | left (L), middle (M), right (R) |
| L. Offensive backfield | Plays with a charted count | `n_offense_backfield` | 0, 1, 2, 3 or more |
| M. Defenders in the box | Plays with a charted count | `n_defense_box` | 5 or fewer, 6, 7, 8 or more |
| N. Pass rushers | Pass plays with a rusher count of 3 or more | `n_pass_rushers` | 3 or 4, 5 or more |

Categories J to N are alignment and pressure labels from charting. They are positional labels, not coordinates. They
describe how a play was set up, not where any player stood during the play.

Excluded and counted, not dropped silently:

- Pass plays with no receiver ID (about 11% of pass plays in both seasons). They are excluded from A only.
- Run plays with no RB rusher, or no charted gap, are excluded from C only.
- Plays with `play_deleted` set are excluded from all categories.
- The code `0` in `qb_location` and in `starting_hash` marks a play with no charted alignment. Those plays are excluded
  from J and K only. In 2026 Weeks 1 to 7 there are about 4,300 such plays, and in 2025 about 11,200. This rule is fixed
  here. It is not changed after seeing any 2026 result.
- Charting codes that are missing (not `0`) are excluded from the category they belong to and counted.
- Pass plays with a rusher count of 0, 1 or 2 are excluded from N only. Non-pass plays are excluded from N.
- The code `0` in `n_defense_box` marks a play with no charted defensive alignment, and about 11,000 plays in 2025 carry
  it. Those plays are excluded from M only. The count `0` is not read as "5 or fewer". This clarification is written
  before the 2026 run.

Defense by role is not in this spec. Defensive players are not identified per play in the 2026 data. The defensive
categories are team-level: blitz (I), defenders in the box (M) and pass rushers (N).

## 3. Situations

Each play gets one situation cell from:

- down: 1, 2, 3 or 4;
- distance: short (1 to 3 yards), medium (4 to 7), long (8 or more);
- zone: red (`yardline_100` of 20 or less) or other.

That is 24 cells. The team's own prior is conditioned on the cell.

## 4. The prior

For each team T, category X, situation cell s, and role r:

p_T(r | s) = (n_T(r, s) + k * p_L(r | s)) / (n_T(s) + k)

where p_L is the league prior for the same category and cell, trained on all teams in the training window, and k is the
shrinkage weight. Where a cell has no team plays, p_T equals p_L. Binary categories use the same form with two outcomes.

## 5. Training, validation and freezing (2025 only)

1. Training window: 2025 regular-season plays in Weeks 1 to 9.
2. Validation window: 2025 regular-season plays in Weeks 10 to 18.
3. k is chosen from {5, 20, 80} by the lowest mean total-variation distance (section 6) on the validation window. Ties
   go to the smaller k.
4. After k is chosen, the prior is refit on all 2025 regular-season plays, Weeks 1 to 18, and frozen with its hash.

## 6. Metric

For each category X and play set P (all plays where X is defined):

- predicted share of role r: the average of p_T(r | s) over plays in P for team T;
- observed share of role r: the frequency of r over plays in P for team T;
- total-variation distance: TVD = 0.5 * sum over r of |predicted - observed|, for multi-role categories, and
  |predicted - observed| for binary categories.

The headline score is the unweighted mean of TVD over the fourteen categories A to N, pooled over teams (weighted by
plays). Lower is better. The headline is also reported for categories A to I alone, which are the play-by-play and
play-type categories, so that the charting categories can be read separately.

Uncertainty: 2,000 bootstrap resamples of games, with a fixed seed of 20261027.

Secondary, reported but not used for the headline: the mean per-play log loss of the prior on the observed role.

## 7. Baselines and comparisons

- League prior: the same prior with k set to infinity. It uses no team information.
- Team prior: the frozen prior from section 5.

The main comparison is the team prior minus the league prior, per category and pooled, with its bootstrap interval.

## 8. The one test on 2026

- Test set: 2026 regular-season plays in Weeks 1 to 7. These are the weeks the playbook is frozen to. Week 8 onward is not
  used.
- Priors: the frozen 2025 prior only. No refit, no k change, no category change, no week change.
- Run once. The result is written to the record whatever it shows.
- A null result is reported as null. If the team prior does not beat the league prior, the report says so.

## 9. What this test does not show

- It does not test movement or positions. Those need tracking data, which is not on disk for 2025 or 2026.
- It does not test outcomes.
- It does not test defense by role. Its defensive categories (I, M, N) are team-level.

## 10. Data sources

- Play-by-play: nflverse release, `play_by_play_2025.parquet` and `play_by_play_2026.parquet` (raw download, pinned in the
  manifest).
- Charting: `ftn_charting_2025.parquet` and `ftn_charting_2026.parquet`. Join to play-by-play on game ID and play ID
  verified at 100% for both seasons, with no duplicate keys.
- Players: `players.parquet` (position by `gsis_id`). Every receiver and rusher ID in 2025 and 2026 matched a player.
- Team codes: play-by-play uses `LA` for the Rams and `WAS` for Washington. The NGS releases use `LAR` for the Rams and
  `WAS` for Washington. Play-by-play `LA` maps to `LAR` for any join with NGS (corrected 2026-10-27, before any 2026 result;
  the earlier text said no mapping was needed, which was wrong for the Rams).

## 11. Version 2: NGS team-style layer (WITHDRAWN 2026-10-27, before any 2026 result)

Status: withdrawn. Nothing below is used. The text is kept on record so the withdrawal is visible.

Reason: the NGS releases are aggregated per player-week. They are not play-by-play. Section 11 applied a team-week NGS
composite to every play in the following week, which turns an aggregate into a single-play multiplier. That is not
supported by the data, so version 2 is not part of this test. NGS may be used later only in a separate analysis that
compares aggregates with aggregates (for example, team-week NGS against team-week observed mixes), with its own spec.

Version 1 (sections 1 to 10) is the only model tested on 2026.

The original text of section 11 follows, unused.

### 11.1 Measures and the style group

For team T and week w (w of 2 or more), the style group uses only team T's regular-season team-week from week w minus 1
of the same season. Week 0 rows (season totals) and postseason rows are never used.

| Measure | NGS file | Weight |
|---|---|---|
| Time to throw | `ngs_passing`, `avg_time_to_throw` | attempts |
| Aggressiveness | `ngs_passing`, `aggressiveness` | attempts |
| Share of attempts against eight or more defenders | `ngs_rushing`, `percent_attempts_gte_eight_defenders` | rush attempts |
| Receiver separation | `ngs_receiving`, `avg_separation` | targets |

Each measure is standardised with the frozen constants below. The composite is the equal-weight mean of the four
standardised measures. The group is:

- low, if the composite is below -0.20449;
- mid, if it is from -0.20449 up to 0.15432;
- high, if it is 0.15432 or more.

Frozen constants (fitted on 2016 to 2024 team-weeks only, 3,979 team-weeks, from `scripts/nfl_sequence/splits/ngs_style_frozen.py`):

| Measure | Mean | Standard deviation |
|---|---|---|
| Time to throw | 2.75549 | 0.27433 |
| Aggressiveness | 16.03334 | 7.39773 |
| Eight-plus defenders | 22.86914 | 17.14245 |
| Separation | 2.90207 | 0.68184 |

Composite cut points: low and mid at -0.20449; mid and high at 0.15432.

### 11.2 Fallbacks and coverage

- Week 1 has no prior week in the season. Version 2 uses the version 1 prior for every week 1 play.
- If the prior week has no NGS row for team T (for example, a bye week), version 2 uses the version 1 prior for that team's
  plays that week. The count of such plays is reported.
- For 2026, the style group for week w uses NGS from weeks 1 to w minus 1. Week 7 plays use week 6 NGS.

### 11.3 The version 2 prior

For team T, category X, situation cell s, and style group g:

p2_T(r | s, g) = (n_T(r, s, g) + k * p1_T(r | s)) / (n_T(s, g) + k)

where p1_T(r | s) is the version 1 team prior from section 4, and k is the same shrinkage weight chosen for version 1 in
section 5. This makes version 2 nest version 1. If n_T(s, g) is zero, version 2 equals version 1.

### 11.4 Validation and freezing (2025 only)

1. Compute the style group for each 2025 play with weeks 2 to 9 of 2025 for training and weeks 10 to 18 for validation,
   using the rule in 11.1.
2. Choose k for version 1 and for version 2 separately, from {5, 20, 80}, by the lowest mean total-variation distance on
   the 2025 validation window. Ties go to the smaller k.
3. Refit both versions on all 2025 regular-season plays and freeze the code and the fitted tables before the 2026 run.

### 11.5 The one test on 2026

- Test set: 2026 regular-season plays in Weeks 1 to 7, as in section 8.
- Both versions use the frozen 2025 fits, the frozen k values, and the frozen constants. No refit, no changed rule.
- Headline: the mean total-variation distance over categories A to N, for version 1 and for version 2.
- Decision rule, fixed here: the NGS layer counts as adding information only if version 2 has a lower headline than
  version 1 and the bootstrap interval of (version 2 minus version 1) excludes zero. Otherwise the report says the NGS
  layer shows no support on this test. Version 1 is also compared with the league prior, as in section 7.
- The result is written to the record whatever it shows.
