
## Coverage alone (added 2026-10-29)

Coverage on dropbacks from prior-season defense shares, outcomes conditioned on it, 100 seeds, paired against score-clock SLC:
margin +1.41 ± 1.62, total +1.69 ± 1.85, home win share 0.59. Within noise, like the other single layers.

## All new layers together (added 2026-10-29)

Formation and personnel, team event splits, defensive coverage, player shares and the exact-yard-line draw, 100 seeds, paired against
score-clock SLC: margin +4.65 ± 1.70, total +4.27 ± 1.66, home win share 0.62. The total moves up by about 4 points, toward the 2024
regular-season level, but this is one snapshot and is not a calibration. The team-level formation tendencies and the team score-state
splits were added after this arm was started and are reported separately below.

## Point-based splits alone (added 2026-10-29)

Team score-state splits of the dropback rate (prior seasons, relative to each team's overall rate), 100 seeds, paired against
score-clock SLC: margin -0.74 ± 1.37, total -0.94 ± 1.31, home win share 0.47. Within noise on this snapshot.

## All new layers with team formation and point splits (added 2026-10-29)

All the new layers, with team-level formation and personnel tendencies and team score-state splits added, 100 seeds, paired against
score-clock SLC: margin +3.17 ± 1.56, total +3.21 ± 1.69, home win share 0.62. Smaller than the arm without them (+4.65 ± 1.70), but
the two differ by less than their standard errors, so the change is not established.

## Team win-loss streak splits alone (added 2026-10-29)

Team-level streak splits of the dropback rate (prior seasons, relative to each team's overall rate), 100 seeds, paired against
score-clock SLC: margin +0.08 ± 0.32, total -0.44 ± 0.42, home win share 0.49. No detectable effect on this snapshot.

## League-wide win-loss streak splits alone (added 2026-10-29)

League-wide streak splits (dropback shift by streak state and outcome mix by the offense's streak, from prior-season play-by-play),
100 seeds, paired against score-clock SLC: margin +1.44 ± 1.66, total +0.54 ± 1.79, home win share 0.54. Within noise.

## Basis of the figures in this note (added 2026-10-29)

The seed comparisons from here on use only `valid_full_game` seeds, paired by seed. Earlier sections in this note used seeds with a
final score, which included games blocked before regulation. Where the two differ, the valid-only figures below supersede the earlier
ones. For coverage on seeds 1 to 100, the valid-only figures are margin +1.48 ± 1.69 and total +3.13 ± 1.79 (95 paired seeds). The
earlier figures in the coverage section were margin +1.41 ± 1.62 and total +1.69 ± 1.85.

## Coverage at 300 seeds (added 2026-10-29)

Coverage on dropbacks, seeds 1 to 300, paired against score-clock SLC on the same seeds (`score_clock_300`): margin +0.74 ± 0.97,
total +1.26 ± 0.98, home win +0.04 ± 0.04 (292 paired valid games). Within noise on this snapshot.

## Individual-bucket win-loss streak splits (added 2026-10-29)

Buckets are now the individual streak lengths, W1 to W4, W5+, NONE, L1 to L4 and L5+ (`streak_splits.py`), 100 seeds, paired
against score-clock SLC, valid games only.

- Team: margin -0.49 ± 0.72, total -0.49 ± 0.86 (99 paired). The coarse buckets on the same seeds gave margin +0.08 ± 0.32. No
  detectable effect either way.
- League: margin +1.73 ± 1.60, total +2.15 ± 1.68 (96 paired). The coarse buckets gave margin +1.36 ± 1.70, total +1.59 ± 1.80
  (95 paired). Within noise.

The record of each bucket's win share and points is in `SLC-STREAK-BUCKETS-RECORD-POINTS-2026-10-29.md`.

## Target roles (added 2026-10-29)

Decision category A (target role) on the current code: 100 seeds, paired against score-clock SLC and the player-share arm, valid
games only. Margin 0.00 and total 0.00, with zero standard error. The arm is identical to both on every paired seed.

This is the design, not a dead flag. On the 20-seed check (`target_role_check2.log`), the role is drawn on 1,536 dropbacks
(WR 983, TE 276, RB 268, Other 9), and the receiver differs from the player-share arm on 1,405 of 2,932 decisions. The plays are
identical on all 20 seeds. The outcome is drawn from the play pool and does not depend on who the receiver is, so changing the
receiver changes credit, not points. The role can move points only when it also conditions the outcome, which the decision labels
do (see the next section).

## Decision categories A to N (added 2026-10-29)

The decision layer with its lifts and row filter, and the arm with the row filter off, are in
`SLC-DECISION-LAYER-UPLIFT-2026-10-29.md`. The filter accounts for about +6.4 points a game of the +10.4 total uplift, and the
filtered total is about four points above the real league total. The uplift should not be quoted as a calibration gain.

## Playbook input against the decision-only arm (added 2026-10-29)

Playbook files as the pre-event prior for pass depth, pass location and run gap, replacing the decision draw for those categories where
the playbook has a prior. 100 seeds, paired against the decision-only arm on the same code (valid games only): total -0.86 ± 1.76,
margin -0.47 ± 1.80, home win -0.07 ± 0.08 (98 paired). No detectable difference. The two sources describe the same plays, so this
is the double count the review flagged: the playbook input adds no information beyond the decision prior. Whether it becomes an input
by default is for review.

## Team outcome splits alone, current code (added 2026-10-29)

Team outcome splits only (`--playcall-team-outcomes`), 100 seeds, paired against score-clock SLC on the same code (valid games only):
margin +2.38 ± 1.49, total +2.18 ± 1.36, home win +0.07 ± 0.07 (97 paired). A positive shift on this one matchup, within about 1.6
standard errors. Team strength enters the engine through these splits, and only through them: the baseline has no team scoring term.

## Formation-conditioned outcomes alone, current code (added 2026-10-29)

Formation and personnel with formation-conditioned outcomes (`--playcall-formation`), 100 seeds, paired against score-clock SLC on the
same code (valid games only): total +2.03 ± 1.61, margin +0.90 ± 1.95, home win +0.02 ± 0.08 (94 paired). Within noise on this
matchup. The 2024 replay, which spans the whole season, is the test of whether formation moves the scoring deficit; see the calibration
note once it is complete.
