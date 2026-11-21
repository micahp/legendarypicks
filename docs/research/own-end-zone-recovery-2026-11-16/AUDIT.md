# Own end zone fumble recovery audit, 1999 to 2025

Date: 2026-11-16. Scope: fumble plays only. Purpose: give the V1.7 recovery model its state definition, its outcome categories, and the data behind its probabilities. This audit does not change the simulator.

## Question

When a fumble leaves the ball at or past the offense's goal line, what happens next?

Three results are possible, and they must not be merged:

| Situation | Official result | Next play |
|---|---|---|
| Defense recovers in the offense's end zone | Defensive touchdown, 6 points, then the try | Scoring team kicks off |
| Offense recovers and the ball is dead in its own end zone, with offensive impetus | Safety, 2 points for the defense | Safety free kick |
| Ball goes out of bounds in the offense's end zone | Safety | Safety free kick |

A recovery in the offense's own end zone does not always end the play. The ball can stay live. The 2024 CAR at CHI play (Dalton) is an example: the offense recovered at its own CAR -9 spot and the play continued, with no safety. The model therefore has to separate who recovers, where the recovery happens, and whether the ball goes dead.

## Sources

| Era | Source files | Notes |
|---|---|---|
| 1999 to 2009 | `/root/lp-snapshots/nfl-backfill-2026-10-27/raw/pbp/play_by_play_YYYY.parquet` | Same nflverse field set. Parse coverage is about the same as later eras (see Parse coverage). |
| 2010 to 2021 | Same backfill folder | Same field set. |
| 2022 to 2025 | `/root/nflverse-raw/play_by_play_YYYY.parquet` | The 2022 to 2025 rows match the earlier audit (2,582 fumble plays). |
| 2026 | Not used | Season is partial. |

Fields used: `desc`, `fumble`, `fumble_lost`, `sack`, `touchdown`, `safety`, `touchback`, `td_team`, `posteam`, `defteam`, `yardline_100`, `yards_gained`.

Official outcome means the nflverse flags (`touchdown`, `safety`) plus the `Touchback` text in the description. Reversed scores are judged by the flags, which reflect the replay result.

Recovery location is read from the play description, not from an independent source. This is the main evidence limit. Section "Open items" lists the rows I have not read by hand.

## Eras

The sample is split into three eras. The split follows rule and data changes, not a fitted break point.

- 1999 to 2009: earlier replay and kick rules. Used as a sensitivity prior, not the primary estimate.
- 2010 to 2021: the modern replay era. Primary sample.
- 2022 to 2025: the most recent era. Only 8 fumble plays reach the denominator, so it is shown but not used alone.

The primary estimate uses 2010 to 2025 (68 plays in the denominator). The pooled 1999 to 2025 estimate (128 plays) is a sensitivity check.

## Classification

Each fumble play is classified from its description and flags:

- Recovery team and recovery spot. Parsed from "RECOVERED by TEAM-... at TEAM n", "and recovers at TEAM n", or "at 50" for midfield. A muffed punt or kick is credited to the receiving team.
- Spot convention. A spot "TEAM n" becomes nflverse yardline_100: `100 - n` if TEAM is the offense, `n` if TEAM is the defense. Yardline 100 or more is past the offense's goal line. Yardline 0 or less is past the defense's goal line.
- Goal line rule. A spot exactly on the goal line (yardline 100) is not in the end zone. A recovery on the goal line can still become a safety if the carrier is tackled in the end zone, so the outcome is judged from the play result, not the spot alone.
- Denominator. Fumble plays where the fumble spot is at or past the offense's goal line before the recovery. Fumble spot comes from "touched at" or "FUMBLES at" in the description. If that is absent, the pre-play yardline minus yards gained is used. The second method is approximate.

## Parse coverage

| Era | Rows with a recovery spot read | Fumble plays | Coverage |
|---|---|---|---|
| 1999 to 2009 | 8,160 | 8,878 | 91.9% |
| 2010 to 2021 | 7,373 | 8,141 | 90.6% |
| 2022 to 2025 | 2,342 | 2,582 | 90.7% |

The unparsed rows are mostly out-of-bounds plays and plays with no recovery text. Across all years, unparsed rows carry these official flags: 57 safeties, 70 touchbacks, 10 touchdowns. Of the 57 safeties, 29 are out-of-bounds plays inside the denominator. The other 28 are outside it. None of the unparsed rows has been read by hand.

## Denominator: fumble spot at or past the offense goal line

| Era | n | Touchdown | Safety | Continues (none) | Touchback |
|---|---|---|---|---|---|
| 1999 to 2009 | 60 | 25 | 31 | 3 | 1 |
| 2010 to 2021 | 60 | 25 | 25 | 10 | 0 |
| 2022 to 2025 | 8 | 5 | 3 | 0 | 0 |
| 1999 to 2025 pooled | 128 | 55 | 59 | 13 | 1 |
| 2010 to 2025 modern | 68 | 30 | 28 | 10 | 0 |

## Denominator by recovery category

| Category | n | Touchdown | Safety | Continues | Touchback |
|---|---|---|---|---|---|
| Defense recovers in offense end zone | 27 | 27 | 0 | 0 | 0 |
| Defense recovers in field or its own end zone, then runs it back | 32 | 28 | 1 | 3 | 0 |
| Offense recovers in its own end zone | 23 | 0 | 19 | 4 | 0 |
| Offense recovers in field or opponent end zone | 17 | 0 | 10 | 6 | 1 |
| Out of bounds, no recovery text | 29 | 0 | 29 | 0 | 0 |
| **Total** | **128** | **55** | **59** | **13** | **1** |

The 28 touchdowns in the "field" row are returns that start from the fumble spot. They are not end-zone recoveries. The model must keep them separate, because they need a return path and not a recovery-in-end-zone path.

Two rows in the "field" group need care. The 10 offense safeties in "offense recovers in field" are cases where the offense recovered on the goal line and the ball carrier was tackled in the end zone. The 29 out-of-bounds safeties have no recovery text; they are safeties by the out-of-bounds rule.

## Own end zone recoveries, by era

These are recoveries whose spot is past the offense's goal line.

| Era | Category | None | Safety | Touchback | Touchdown | n |
|---|---|---|---|---|---|---|
| 1999 to 2009 | Defense recovers in offense end zone | 2 | 0 | 1 | 9 | 12 |
| 1999 to 2009 | Offense recovers in its own end zone | 2 | 7 | 2 | 0 | 11 |
| 2010 to 2021 | Defense recovers in offense end zone | 1 | 0 | 0 | 19 | 20 |
| 2010 to 2021 | Offense recovers in its own end zone | 8 | 14 | 0 | 0 | 22 |
| 2022 to 2025 | Defense recovers in offense end zone | 0 | 0 | 0 | 7 | 7 |
| 2022 to 2025 | Offense recovers in its own end zone | 1 | 2 | 0 | 1 | 4 |

The one 2022 to 2025 "offense recovers" touchdown is the 2024 LA at SEA play. It is an interception return, not a fumble recovery, and the parser read a later recovery on that play. It should be removed from the recovery counts. Other eras may contain the same parser artifact; this audit has not checked them.

The rows with "none" for a defense recovery in the offense end zone are returns or continued plays that were not dead at the spot. The rows with touchback are a separate dead-ball path.

## Estimates

Priors are Dirichlet with one pseudo-count per outcome. The posterior mean is (count + 1) / (n + 4).

Outcome given fumble at or past the goal line:

| Sample | Touchdown | Safety | Continues | Touchback |
|---|---|---|---|---|
| 1999 to 2009 | 0.406 | 0.500 | 0.062 | 0.031 |
| 2010 to 2021 | 0.406 | 0.406 | 0.172 | 0.016 |
| 2022 to 2025 | 0.500 | 0.333 | 0.083 | 0.083 |
| 1999 to 2025 pooled | 0.424 | 0.455 | 0.106 | 0.015 |
| 2010 to 2025 modern | 0.431 | 0.403 | 0.153 | 0.014 |

Recommended model structure. These are the probabilities the simulator should draw from, and what each one rests on:

1. Recovery category, drawn from the denominator mix. Pooled counts are 27, 32, 23, 17, 29 out of 128. Use the modern 2010 to 2025 mix as primary, with the 1999 to 2009 counts as a half-weight prior. The modern mix is not yet computed by category; it must be computed before the model is fitted.
2. Outcome given category. Some of these are rules, not estimates:
   - Defense recovers in offense end zone: touchdown. This is a rule.
   - Out of bounds in offense end zone: safety. This is a rule.
   - Defense recovers in its own end zone and the ball is dead: touchback. This is a rule. Runs out of the end zone are returns.
   - Offense recovers in its own end zone: safety or continued play. This is an estimate: 19 of 23 pooled, with 4 continuing.
   - Defense recovers in the field: touchdown by return, or continued play. This is an estimate: 28 of 32 pooled.
   - Offense recovers in the field: safety, continued play, or touchback. This is an estimate: 10, 6, and 1 of 17 pooled.
3. Continued play. The 13 pooled continued plays need an endpoint model: where the ball goes next, and the next snap. The audit does not cover endpoints. This is a design gap, not a data gap, and must be closed before the continued-play branch can complete a game.

## Open items

1. Four unclear rows from the first pass. Their IDs are in `fumble_audit_1999_2025.csv.gz`, filter on `game_id`:
   - 2024_05_CAR_CHI (Dalton): offense recovered in its own end zone, play continued. Read and accepted as continued play. Not yet reconciled to a film or gamebook source.
   - 2024_09_LA_SEA: an interception play where the parser read a later recovery. Not a fumble recovery. It appears in the own-end-zone table as an offense touchdown and should be removed from the recovery counts.
   - 2022_03_GB_TB and 2023_18_TB_CAR: a field recovery with touchback text, and a play with a reversed touchdown. Not yet read.
2. Unparsed rows with official flags: 57 safeties, 70 touchbacks, 10 touchdowns across all years. Only 29 of the safeties are classified (out of bounds in the denominator). The rest are untested.
3. The out-of-bounds rule: a safety for ball out of bounds in the offense's end zone. The rulebook text and the question of which team touched the ball last must be checked before the rule is coded. Not verified in this audit.
4. The fumble spot fallback (pre-play yardline minus yards gained) is approximate. Its effect on the denominator has not been measured. Parsing the fumble spot for every play would remove this.
5. 2026 excluded: partial season.

## What this audit does not establish

- It does not give a recovery probability by player, team, weather, or down. The sample is too small for those splits.
- It does not give return yardage. The model does not need it for touchdowns or safeties. It does need it for continued plays.
- It does not validate the descriptions against official scoring records or gamebooks. The nflverse flags are the official proxy.
- The NFL rule statements in the table above come from the rule check in the project notes. They were not re-read from the rulebook in this audit.

## Files

- `build_audit.py`: reads the 1999 to 2025 play-by-play, classifies each fumble play, writes one row per fumble play. Paths are fixed to the snapshot and nflverse-raw folders on this box.
- `summarize_audit.py`: produces the denominator, category, era, prior, and reconciliation tables from the classification file.
- `audit_summary.txt`: the full output of `summarize_audit.py` for this run.
- `fumble_audit_1999_2025.csv.gz`: classified rows, 19,601 fumble plays, one per row, with `desc` truncated to 220 characters.
