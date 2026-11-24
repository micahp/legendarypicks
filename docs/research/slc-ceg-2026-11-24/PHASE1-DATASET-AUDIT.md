# SLC-CEG Phase 1: canonical NFL event dataset

Date: 2026-11-24. Branch `research/slc-ceg-2026-11-24`. No model fitted. No frozen SLC version, V1 Complete or Gridiron
changed. No simulation batch.

Code: `scripts/nfl_sequence/ceg_event_tables.py` (tables, views, reconciliation, audits), `ceg_waterfall.py`
(raw -> v2 -> CEG), `ceg_contract.py` (GeneratedPlay contract), `test_ceg_contract.py` (11 tests pass).
Outputs in `phase1/`: `phase1_manifest.json` (inputs, tables, views, reconciliation, audits, periods),
`schema_registry.json`, `missingness.json`, `waterfall.json`. Tables (not in git):
`/root/slc-ceg-data/phase1-2026-11-24/` on this machine, sha256 in the manifest.

## Result

1. **Phase 0 gate passes.** All five frozen packs (v1, v1.5, v1.6, v2, pbv1) reproduce the week 11 batch exactly on CIN
   at WAS seeds 300001 to 300003: identical outcomes, identical player box scores, same pack hashes
   (`baseline_reproduction.json`).
2. **The dataset is built from the raw play-by-play, before any SLC filter.** 225,829 rows over 2022 to 2026 (2026
   through week 11, Monday night included), 209,564 snaps, no duplicate keys.
3. **It reconciles with nflverse's own totals.** Over 2,900 team-weeks: pass attempts match exactly in 2,898, carries in
   2,896, targets in 2,900; every difference is 1. All 1,250 completed regular-season final scores in `games.csv` match.
4. **The v2 pool drops more than the audit said, in different places.** Corrections are in section 3.

## 1. Inputs

nflverse releases fetched 2026-11-24 into `/root/slc-ceg-data/raw-2026-11-24/`: play-by-play, snap counts, weekly
rosters and weekly player stats for 2022 to 2026; participation for 2022 to 2025; `games.csv`. sha256 of every file is in
`phase1_manifest.json`.

**2026 personnel and formation (corrected 2026-11-24).** Two sources, checked by listing every nflverse release and our
database tables:

- *Personnel groupings, offense formation and defensive coverage per play* (nflverse `pbp_participation`, our
  `nfl_hist_participation`): both end at 2025. Not published for 2026.
- *FTN charting* (nflverse `ftn_charting_2026.parquet`, sha256 `bb72c788f63b...`, pulled 2026-11-24 00:01 UTC): published
  for 2026. Every completed game through week 10 (151 of 163); the 12 week 11 games were not pulled yet. Per play: QB
  location (shotgun or under center), backfield count, box count, no huddle, motion, play action, screen, RPO, trick
  play, throwaway, interception-worthy, drop, blitzers, pass rushers. It joins to 18,488 of 19,968 2026 scrimmage plays;
  every miss is a week 11 play. It also gives a throwaway label that the play-by-play does not have.
- *Snap counts* per player and game are published for 2026 (`snap_counts_2026.parquet`).

So 2026 has formation-level charting but no personnel grouping (11, 12, 21 and so on) per play.

## 2. Tables and timing

One physical row per play, keyed by (game_id, play_id), split by timing so a model cannot read the wrong side of the snap.
`schema_registry.json` gives every column's table, dtype and timing class.

| table | timing classes | examples |
|---|---|---|
| decision | pre_snap | clock, down, distance, field, score, timeouts, weather, xpass |
| labels | offense_choice, realized_event | shotgun, run location; play class, sack, turnover, penalty, try result |
| post | intermediate, realized_event, transition | air yards, YAC, return, kick distance; yards; next snap, runoff, clock-stop class |
| people | identity | passer, rusher, receiver, kicker, punter, returners |

The builder asserts that the decision table holds only pre-snap columns. Shotgun and no huddle are offense choices at the
snap: targets for a formation model, never inputs to the play call.

Play classes, 2022 to 2026: designed run, dropback, scramble, kneel, spike, field goal, punt, kickoff, extra point,
two-point, no_play (a foul with no play), timeout and admin rows. nflverse files a timeout as a `no_play` row with
`timeout = 1`: 9,660 such rows are classed as timeouts, not snaps. A first build missed this and is kept as
`phase1-2026-11-24-superseded-timeouts`.

## 3. Waterfall: raw play-by-play, v2's pool, CEG

v2's population is recomputed with v2's own `e1_drive.classify` on the same nflverse rows, in v2's read order
(`waterfall.json`). v2 reads `nfl_pbp` from its frozen database, so its packs can differ slightly; the reasons are v2's.

| season | raw rows | reg, week <= 18 | scrimmage play types, down 1-4 | regulation | v2 pool | CEG snaps |
|---|---|---|---|---|---|---|
| 2022 | 49,434 | 47,157 | 36,911 | 36,576 | 35,553 | 45,860 |
| 2023 | 49,665 | 47,399 | 37,159 | 36,979 | 35,878 | 46,169 |
| 2024 | 49,492 | 47,274 | 36,496 | 36,305 | 35,215 | 45,919 |
| 2025 | 48,771 | 46,452 | 35,834 | 35,629 | 34,581 | 45,186 |
| 2026 | 28,467 | 28,467 | 21,889 | 21,694 | 21,034 | 26,430 |

CEG snaps include the postseason (8,413 snaps over 2022 to 2025); every view reports regular season and postseason
separately.

**Left out before v2's classifier (play type), 2025:** 4,538 `no_play` rows (pre-snap fouls and timeouts), 2,794
kickoffs, 1,268 extra points, 433 kneels, 79 spikes, 128 two-point tries, 1,378 admin rows. Kickoffs and tries are
handled by v2's other tables. **Pre-snap fouls are not modelled anywhere in v2.**

**Left out by v2's classifier, 2022 to 2026:**

| reason | plays | note |
|---|---|---|
| penalty on a live play | 3,075 | plus every pre-snap foul above; CEG: 15,900 penalty rows, 4,533 first downs by penalty |
| overtime play | 1,106 | regulation-only pool; overtime draws regulation rows |
| punt without a clean receiving-team snap | 1,099 | punt return touchdowns, muffs, punt penalties |
| turnover without a clean new-offense snap | 431 | |
| turnover returned for a touchdown | 220 | CEG: 160 pick-sixes and 85 fumble-return touchdowns, postseason included |
| negative derived clock runoff | 64 | data errors in the source clock |
| no same-quarter next snap | 33 | |

**Corrections to the Phase 0 audit and the review:**

- *Last plays of a quarter* are not dropped. v2's classifier measures their runoff against the end-of-quarter row, so only
  33 plays in five seasons lose a next snap.
- *Scrambles* are kept by v2. The QB-decision stack turns `include_qb_scrambles` on; only builds without it dropped them.
- *Penalties* are the largest exclusion: every pre-snap foul and 3,075 live-play fouls. In 2025, 2,583 no-play rows
  (nearly all fouls) and 687 live-play fouls, about 11 per game.
- *Overtime plays* (1,106) are a fourth exclusion that the audit did not list.

The breakdown of each exclusion by season, CEG play class, down, field zone, last snap of a quarter, and last two minutes of
a half is in `waterfall.json` (`breakdown`). For example, 2025 live-play penalties: 259 on dropbacks, 193 on designed runs,
176 on punts, 55 on scrambles; 71 inside the last two minutes of a half.

## 4. Opportunity views and denominators

The review's datasets are views over the tables: one filter and one denominator each (`VIEWS` in the builder; counts in
the manifest). No duplicated physical data.

| view | denominator | 2025 rows | targets |
|---|---|---|---|
| play_decisions | scrimmage snap with a call | 38,216 | run, dropback, punt, FG, kneel, spike |
| dropbacks | dropback (incl. scramble) | 20,788 | attempt, sack, scramble, no attempt |
| pass_attempts | attempt, sacks excluded | 18,287 | complete, incomplete, interception; receiver; air yards |
| pass_completions | completion | 11,749 | YAC, fumble |
| designed_runs | designed carry | 13,714 | yards, fumble |
| scrambles | scramble | 1,149 | yards, fumble |
| turnovers | interception or fumble | 976 | recovering team, return, defensive TD |
| penalties | every snap incl. no_play | 45,186 | penalty, type, team, yards, first down |
| special_teams | kickoff, punt, FG, extra point | 7,439 | result, distance, return, touchback, block |
| clock_events | snap with a next snap | 45,186 | runoff, clock-stop class, timeout before next snap |
| strategic_decisions | 4th down with a call, or a try | 5,457 | go, punt, FG; extra point or two-point |

### Conditional dependency graph

Pre-snap inputs at each node are the decision table plus the outputs of the nodes above it. Arrows are conditioning, not
causation.

```text
state (decision table)
 -> timeout decision (at the opportunity before the snap)          [clock_events]
 -> play call: run | dropback | punt | FG | kneel | spike           [play_decisions; 4th down: strategic_decisions]
 -> pre-snap foul? (voids the play)                                 [penalties]
 dropback -> sack | scramble | attempt | no attempt                 [dropbacks]
   attempt -> receiver -> air yards -> complete | incomplete | interception     [pass_attempts]
     complete -> YAC (given air yards and receiver) -> fumble?      [pass_completions]
     interception -> return -> defensive TD?                        [turnovers]
   sack -> yards lost -> fumble?
   scramble -> yards -> fumble?                                     [scrambles]
 run -> carrier -> yards -> fumble?                                 [designed_runs]
 fumble -> recovering team -> return -> dead-ball spot or TD        [turnovers]
 live-play foul? -> accept or decline -> enforcement (rules core)   [penalties]
 kick -> result, distance, return, block, recovery                  [special_teams]
 -> clock: live seconds; dead-ball seconds if the clock runs        [clock_events]
 -> next state (reducer)
```

## 5. Audits

**Yardage support, no cap** (2022 to 2026, plays with no penalty): designed runs -34 to +93 (0.1% below -8, 7 plays at -15 or
less, 87 at +60 or more); dropbacks -24 to +98 (123 at -15 or less, 218 at +60 or more); scrambles -1 to +62; kneels -7 to
0. The support is wide; a fixed floor or cap would cut real plays.

**Field-boundary censoring.** 6,094 offensive scrimmage touchdowns; 6,084 have yards gained equal to the yards to the goal
line. A touchdown gain is right-censored at the goal line: the underlying gain distribution is observed only up to it. A
yardage model must treat a touchdown as censored at yardline_100, not as a draw of exactly that value. 43 plays reach the
own goal line (safety or touchback by rule).

**Turnovers and returns.** 1,924 interceptions (160 pick-sixes), 2,969 fumbles: 1,345 lost, 1,624 recovered by the
offense, 85 returned for a touchdown. The recovering team is missing for 257 fumbles (8.7%); a recovery model must count
those as unknown, not as offense recoveries. Return yards are present on every turnover.

**Penalties.** 15,900 penalty rows: 11,770 on no-play rows, 4,130 on live plays. Type and yards are never missing. The
play-by-play gives occurrence, type, team, yards and first down by penalty, but not the enforcement spot. Enforcement
must come from the rules core (the V1.7 penalty core), and the next snap (`post.next_yardline_100`) checks it.

**Clock.** The play-by-play has the game clock only at snaps. Of snaps with a next snap in the same quarter, 81,049 are
followed by a stopped clock (incomplete, score, change of possession, timeout, late out of bounds, kicks): runoff median 5 s,
p90 10 s. That is the live-play duration. 123,188 are followed by a running clock: median 38 s, p90 44 s. That is live time
plus dead-ball time. Live duration is fitted on stopped plays and dead-ball runoff on running plays minus live time. 37
snaps have a negative runoff (source clock errors) and are flagged, not used.

**Timeouts.** 9,660 timeout rows; 9,163 snaps are followed by a timeout before the next snap. A timeout is a decision at the
dead-ball opportunity between two snaps, by the team that called it, not a flag on the play before.

**Missingness** (`missingness.json`, by table and season). Inside the right view the key fields are complete: air yards
are present on every pass attempt and YAC on every completion; air yards plus YAC equals yards gained on 99.8% of
completions. Weather (temp, wind) is missing on 34% to 73% of rows (domes and unreported); a weather term must treat
missing as its own level.

## 6. Evaluation periods

| period | data | use |
|---|---|---|
| development | 2022 to 2024 | fit and model selection |
| confirmation | 2025 | one pre-registered check of the selected models |
| examined 2026 | weeks 1 to 11 | already read by the week 11 batch and opportunity step 1; reported, never used to select |
| prospective 2026 | week 12 on | forecasts frozen before kickoff |

## 7. Arms B and C

- **Arm B, league level:** each event model conditions only on what the football rules require (the play class at its
  node, and the field for legality). No down, distance, score or clock terms. It is the unconditional baseline.
- **Arm C, situation conditioned:** arm B plus down, distance, field, score differential, time and timeouts, at league
  level. No team, player or matchup terms.

Team, player and matchup terms (arms D and E) are added only when they beat arm C on the development seasons and are
confirmed once on 2025.

## 8. Opportunity candidate for arm D (review of step 1)

`research/slc-v1-conditional-opportunity-2026-11-23`, log loss per opportunity 1.614 against 1.910 on 2026 weeks 1 to 11.

- **Denominators:** targets (pass with a receiver) and designed carries (run, not scramble), regular season, two-point
  tries out. These match the views above.
- **Cutoff safety:** in-season counts use only weeks before the game's week; priors use the prior season. Safe.
- **Caveat 1, candidates:** the candidate set is the players with at least one opportunity in that game. That uses who
  played, which a pregame forecast knows only through the injury report. The sim's eligible set is larger, so the gain
  may shrink in the sim.
- **Caveat 2, periods:** k was tuned on 2025 and scored on 2026 weeks 1 to 11. Under the periods above, 2025 is
  confirmation and 2026 weeks 1 to 11 are examined. Before arm D uses it, k is retuned on 2022 to 2024 and confirmed once
  on 2025.

It stays the arm D candidate.

## 9. GeneratedPlay contract

`ceg_contract.py` defines `PlayCall`, `TimeoutDecision`, `GeneratedPlay`, `Clock` (live and dead-ball seconds apart),
`Penalty` (occurrence and acceptance; enforcement by the rules core), `Possession` (dead-ball team, spot, how, return
yards) and `Provenance` (generator, version, manifest hash, components, draw ids). No historical row. `validate()` refuses
an event that the intent cannot produce, air yards and YAC that do not sum, a sack with a target, a fumble with no
recovery, a stopped clock with dead-ball time, and a ball past an end line; it reports a goal-line boundary instead of
capping yards. 11 tests pass.

## 10. Before Phase 2

Phase 2 (the scrimmage generator, arms B and C) starts only after this is reviewed. Open items it needs:

- An enforcement-spot check for penalties, comparing the rules core with `post.next_yardline_100`.
- Whether formation models use FTN charting (2022 to 2026, through week 10 for 2026) in place of participation
  personnel, which stops at 2025. FTN is not yet in the tables; it joins on (game_id, play_id).
- The censored-likelihood form for touchdown gains.
