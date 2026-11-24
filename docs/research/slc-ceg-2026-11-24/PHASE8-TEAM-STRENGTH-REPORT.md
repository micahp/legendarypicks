# SLC-CEG Phase 8: team strength on the yardage components

Date: 2026-11-24. Pre-registration: `PHASE8-PREREGISTRATION.md` (`04486925`, before any fit). Code:
`scripts/nfl_sequence/ceg_signal.py` (step 0), `ceg_gainteam.py` (H1), `ceg_h2.py` (H2), the `gain_team` hook in
`ceg_generator.py`. Results: `phase8/signal_2022_2024.json`, `phase8/h1_gain_team.json`, `phase8/h2_drive_points.json`.

## Result

1. **The yardage team shifts are real but too small to be useful.** Four terms count per play on 2025 (H1). At drive
   level (H2) E8 lowers the squared error of drive points by 0.12 against C, but the interval crosses zero
   (-0.28 to +0.04). By the pre-registered rule E8 is not useful, so H3 (a 200-seed week 12 forecast) does not run.
   The frozen E6 week 12 forecast (`ada09944`) stays the one to grade.
2. **The simulator still does not rank offenses.** Over the 32 offenses in 2026 weeks 1 to 11, the correlation of
   simulated with actual points per drive is -0.10 for C, 0.04 for E6 and 0.19 for E8. The simple baseline R (each
   offense's past points per drive, shrunk, plus the league mean by start zone) reaches 0.67.
3. **The cause is the shrinkage.** Per-play log score chose the strongest shrinkage in the grid (lambda 1,000): the team
   shift's SD is 0.027 logit, about 0.17 yards per carry, against a true between-team SD of about 0.41 (step 0). The
   per-play gain of a real team effect is tiny next to play-level noise (as the pre-registration predicted), so a
   per-play criterion keeps the teams close to the league. At drive level the team signal is what matters.

## Step 0 (2022-2024, split halves of each team-season)

Offense points per drive: reliability 0.77, true SD 0.40. Defense: 0.24, SD 0.18. The offense rates that predict the
other half's points per drive: yards per play 0.60, third and fourth down conversion 0.53, red-zone touchdown rate 0.39,
yards per carry 0.35, sack rate -0.34, yards after the catch 0.31.

## H1: per-play log score, E minus C (95% game bootstrap)

| component | term | lambda | 2025 | counts | 2026 (examined) |
|---|---|---|---|---|---|
| run yards | offense | 300 | -0.0005 (-0.0015 to +0.0005) | no | -0.0015 (-0.0025 to -0.0004) |
| run yards | defense | 1,000 | -0.0006 (-0.0010 to -0.0001) | yes | -0.0003 (n.s.) |
| run yards | both | 1,000 | -0.0010 (-0.0017 to -0.0004) | yes | -0.0013 (-0.0020 to -0.0006) |
| yards after catch | offense | 300 | -0.0002 (-0.0011 to +0.0008) | no | -0.0019 (-0.0030 to -0.0008) |
| yards after catch | defense | 1,000 | -0.0005 (-0.0009 to -0.0002) | yes | -0.0006 (n.s.) |
| yards after catch | both | 1,000 | -0.0009 (-0.0015 to -0.0002) | yes | -0.0017 (-0.0025 to -0.0008) |
| scramble yards | offense | 100 | -0.0002 (-0.0033 to +0.0032) | no | +0.0001 (n.s.) |

E8 took "both" for run yards and yards after the catch (the pre-registered rule: every term that counts; when several
count, the larger 2025 gain). Note: the yards-after-catch defense term was worse than C at every lambda on 2024 and was
kept by the rule because it counts on 2025.

## H2: drive points, 2026 weeks 1 to 11

3,551 drive starts, 4 generated drives each, the same seeds for every arm, 0 halts.

| arm | mean expected points | squared error | offense correlation | offense SD |
|---|---|---|---|---|
| actual | 2.083 | | | 0.458 |
| R (no simulator) | | 7.919 | 0.669 | 0.263 |
| C | 2.030 | 9.560 | -0.097 | 0.175 |
| E6 | 2.038 | 9.499 | 0.040 | 0.161 |
| E8 | 2.020 | 9.437 | 0.189 | 0.166 |

Differences (95% game bootstrap): E6 minus C -0.060 (-0.194 to +0.072); E8 minus C -0.123 (-0.284 to +0.040);
E8 minus E6 -0.063 (-0.173 to +0.046); R minus E8 -1.517 (-1.770 to -1.287).

Reading it: the simulators' squared error includes Monte Carlo noise from averaging only 4 draws (about the variance
of a drive's points divided by 4). This inflates the gap to R but not the differences between arms, which share
seeds. The ranking result does not depend on it: with about 110 drives and 440 draws per offense, the simulators'
offense SD (0.16 to 0.18) is close to their noise floor, while R's 0.26 is real team spread.

## What this says to do next (not pre-registered here)

- Choose the team-term strength at the level it is used: tune lambda (or a single scale on all team terms) on 2024 by
  drive points or game margin, not by per-play log score.
- Or calibrate the simulator to R: set each team's shifts so its simulated points per drive matches its shrunk
  observed rate, and test whether the components then add anything beyond R.
- Either needs its own pre-registration, a tune on 2024, and a test on a period not used here (2025 drives, or
  week 12 and later).
