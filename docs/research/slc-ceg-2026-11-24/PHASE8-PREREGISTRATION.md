# SLC-CEG Phase 8 pre-registration: team strength on the yardage components

Date: 2026-11-24. Written before any Phase 8 fit or score. Base: the Phase 2 arm C components and the Phase 6 terms
(arm E6). Data: the Phase 1 tables (`/root/slc-ceg-data/phase1-2026-11-24/`).

## Why these components

Step 0 (`scripts/nfl_sequence/ceg_signal.py`, `phase8/signal_2022_2024.json`, development seasons only, split halves of
each team-season):

- Offense points per drive is stable within a season (reliability 0.77, true between-team SD 0.40 points per drive);
  defense much less (0.24, SD 0.18).
- The offense rates that predict the other half's points per drive are yardage: yards per play r 0.60, third and fourth
  down conversion 0.53, yards per carry 0.35, yards after the catch 0.31; sack rate -0.34 (already an E6 term).
- Phase 6 put team terms on categorical components only. No yardage component has a team term.

A small per-play gain is expected even for a real team effect: a rate with true SD s around p gains about
s^2 / (2 p (1 - p)) nats per opportunity. The per-play test (H1) decides whether a term is real; the drive test (H2)
decides whether it is useful.

## The term

For a gain component with hazard h(g) from arm C, team T's term shifts every step of the hazard:
logit h_E(g) = logit h_C(g) - b_off(posteam) - b_def(defteam). b > 0 means longer gains (for a defense: allowed).
Each b is fit by penalized maximum likelihood (Newton) on the team's plays in the window (the previous season plus the
target season's weeks before the play's week), with prior b ~ N(0, 1 / lambda). Offense and defense are fit separately
and added. No history: b = 0.

Components and terms: `run_yards` (offense, defense, both), `yac` (offense, defense, both), `scramble_yards` (offense).
lambda grid: 1, 3, 10, 30, 100, 300, 1000 (prior precision per team).

## H1: per-play log score (walk-forward)

- Tune: base C fit on 2022-2023, scored on 2024; lambda chosen per component and term by mean log score.
- Confirm once: base C fit on 2022-2024, scored on 2025 with the chosen lambda. A term counts if E minus C is below zero
  with the 95% game-bootstrap interval below zero (1,000 resamples, as in Phases 2 to 6).
- Reported, not used to choose: 2026 weeks 1 to 11 (examined), with the same lambda.
- Both C and E are scored by the same path likelihood. A gain at or behind the offense's own goal line is scored as the
  stop at that line in both.

## H2: drive points by team (2026 weeks 1 to 11, not used by any earlier phase for these terms)

Every 2026 regular-season offensive drive start in weeks 1 to 11 (from the Phase 1 tables), 4 generated drives each,
through `e1_drive.simulate` with the CEG clock and the Phase 4 kick results for points (a field goal attempt scores
its make probability times 3; a touchdown 7). Arms:

- C: no team terms;
- E6: the Phase 6 terms (dropback outcome offense k 300, targeted outcome defense k 1,000);
- E8: E6 plus every Phase 8 term that counts under H1.

Measures, per arm: mean squared error of the drive's expected points (mean over its 4 draws) against the drive's actual
points; the correlation, over the 32 offenses, of simulated and actual points per drive. Baseline R (no simulator):
each offense's walk-forward points per drive (previous season plus earlier weeks, shrunk to the league with the
pseudo-count tuned on 2024 by the same squared error), plus the league's mean by start field zone.
E8 is useful if its squared error is below C's with the 95% game-bootstrap interval below zero. Its distance to R is
reported: R is the bar a simulator's team strength has to reach.

## H3: games

If E8 is useful under H2, a week 12 2026 forecast with E8 at 200 seeds per game (home-win standard error about 0.035;
Phase 7 used 40 seeds, about 0.079, so most of its spread between games was seed noise), committed before the first
week 12 kickoff (2026-11-25 20:00 ET) and graded after the games beside the frozen E6 forecast (`ada09944`).

## Not in Phase 8

Air yards, fumbles, field-goal and punt components, players (arm D in the runtime, backlog E10), and the regression and
GAM challengers (backlog E9). No large batch: the drive test runs on this box in the background.
