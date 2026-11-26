# Week 10 participation arms: leave hazards, snap counts, PBV1

Status: campaign complete for arms H, HS, HP and HSP. Advance-log re-runs of arms B and C are still running. The SLC v2 arm (PBV1 with V1.5 season weighting) has a passing 2-seed smoke test on KC_ATL only. LA_ARI cannot run in the v2 arm yet.

## Question

Does the lead RB get too little time on the field because of the leave step, the entry step, or both? Do player leave hazards and current-season snap counts fix it? Does PBV1 change it?

## Arms

All arms use the same 14 Week 10 snapshots and seeds 300001 to 300020. Each arm is the existing command for its base arm with only the listed changes.

| Arm | Base | Change |
|---|---|---|
| B | field only (existing) | none |
| C | field plus PBV1 (existing) | none |
| H | B | field with player leave hazards (leave_power 1.5) |
| HS | B | H plus 2026 snap counts through week 9 |
| HP | C | H |
| HSP | C | HS |

Inputs:
- Field with leave power: `field_lp15.json`, sha256 `2f7b870f8872d6b4`. Built by `export_field.py --leave-power 1.5` from the same tables as the existing field, which rebuilt exactly.
- Snap counts: `snapcounts_2026_w9.json`, sha256 `57807d58597563e7`. Built from the 2026-11-11 capture, weeks 1 to 9 only. Week 10 counts are not used, because they show the games being forecast.

## Results (14 games, 280 paired seeds)

| Arm | Lead RB on-field rate | Lead RB in 11 personnel | Departures per 100 on-field plays | Mean plays off before return | Lead RB carries per game |
|---|---|---|---|---|---|
| B | 0.358 | 0.338 | 28.7 | 4.9 | 9.0 |
| C | 0.370 | 0.365 | 27.6 | 4.7 | 9.5 |
| H | 0.460 | 0.447 | 24.3 | 3.8 | 11.4 |
| HS | 0.510 | 0.505 | 17.1 | 4.7 | 12.6 |
| HP | 0.452 | 0.452 | 24.7 | 3.6 | 11.2 |
| HSP | 0.526 | 0.526 | 16.5 | 4.7 | 13.2 |
| Actual | about 0.64 | not measured | not measured | not measured | 14.7 |

Margin differences (final home margin, paired by seed, 95% interval from 14 game clusters):

| Comparison | Mean difference | Interval |
|---|---|---|
| H minus B | -1.35 | -2.18 to -0.42 |
| HS minus B | -0.25 | -1.68 to 1.23 |
| HP minus B | -0.75 | -3.28 to 1.59 |
| HSP minus B | -0.22 | -2.28 to 1.92 |
| H minus C | 0.13 | -1.85 to 2.15 |
| HSP minus C | 1.27 | -0.15 to 2.71 |

Margin is not accuracy. These numbers show that the arms differ. They do not show which arm is closer to the actual result.

## Reading

- Player leave hazards raise the lead RB on-field rate from 0.36 to 0.46 and his carries from 9.0 to 11.4 per game.
- Current-season snap counts give the largest gain: 0.51 on-field and 12.6 carries. They also cut departures by about a third.
- PBV1 adds little. HSP and HS are close.
- Every arm is still below the actual lead RB carry total of 14.7 per game.
- The on-field rate uses simulated on-field plays over simulated team plays. The actual rate uses snap counts over play-by-play plays. The denominators differ, so the actual figure is approximate.

## Caveats

- Departures and return times come from consecutive on-field lineups. They do not separate forced departures from hazard departures. The advance-log re-runs of B and C (`B2`, `C2`) will allow that split. They are queued after the campaign.
- SLC v2 arm: `--slc-v2` requires the snap counts, turns on V1.5 season weighting and RNG v2, and loads a default kicker table. The kicker table for Week 10 is built from the roster published 2026-11-11 at 07:04 UTC, before every Week 10 cutoff. Its sha256 is `7d53cda1cd27774e`. LA has two active kickers in Week 10, so LA gets no row and LA_ARI is refused in the v2 arm.
- Team-code fix: the kicker table uses nflverse codes (`WAS`, `LA`). The lookup now converts the schedule codes (`WSH`, `LAR`). This fix is not committed yet.
- Cutoff rule: the snapshot check now judges nflverse inputs by publisher last-modified time, not download time. Committed in `c14f0f88`.

## Not done

- Advance-log re-runs of B and C.
- Full 13-game SLC v2 run.
- Accuracy against actual margins for each arm.

## Files

- `results/final_six_arms.json`: metrics and margin comparisons from `code/camp_report.py`.
- `code/campaign.py`: the four new arms and the check run.
- `code/choice_harness_v2.py`: records advance calls. Only logs. Box scores match the original KC_ATL run.
- `code/campaign_v2.py`: the SLC v2 arm (smoke test on KC_ATL).
- `code/build_w10_kicker.py`: builds the Week 10 kicker rows from the 07:04 UTC roster.
- Raw run outputs stay on the fast host at `/root/tnf-batch/camp/`, not in git.

## Follow-up: departures, first-play entry, and the lead RB's weight

Scripts are in `code/`. Results are in `results/advance_analysis.json`, `results/entry_weights.json` and `results/entry_group.json`. Arms B and C use the advance-log re-runs (`B2`, `C2`). Arms H, HS, HP and HSP use the campaign runs.

### Departures: hazard or forced

Per 100 on-field plays, for the lead RB:

| Arm | Hazard departures | Forced removals |
|---|---|---|
| B | 24.5 | 4.3 |
| C | 24.1 | 3.4 |
| H | 21.6 | 2.8 |
| HS | 14.3 | 2.8 |
| HP | 22.7 | 2.1 |
| HSP | 14.3 | 2.1 |

Almost all departures are hazard departures. Forced removals are small in every arm.

### First play: entry by bench weight

At each team's first offensive play, an RB slot is almost always filled (99% or more). The lead RB enters in about half the cases:

| Arm | Lead RB enters at first play |
|---|---|
| B | 50.1% |
| C | 50.4% |
| H | 50.6% |
| HS | 45.3% |
| HP | 50.9% |
| HSP | 49.0% |

The entry draw follows the weights. In every weight band, the lead RB's pick rate matches his average weight share. So the first-play gap comes from the weights.

### First play by personnel group

Mean lead RB weight share, and how often he was picked, for the most common groups:

| Group | Arm | Cases | Lead weight share | Lead picked |
|---|---|---|---|---|
| 11 | B | 220 | 0.47 | 0.47 |
| 11 | HSP | 308 | 0.51 | 0.46 |
| 12 | B | 200 | 0.53 | 0.55 |
| 12 | HSP | 183 | 0.50 | 0.52 |
| 21 | B | 51 | 0.42 | 0.35 |
| 21 | HSP | 21 | 0.40 | 0.29 |

Group 11 is the main case. The lead RB gets under half the bench weight.

### Why the lead's weight is low in group 11

The weight formula reproduces all 933 logged RB weights in arm B exactly (`group11_rates.py`). The weight is the rate built from 2022 to 2025 history.

- The lead RB's average rate is 0.28. A backup's average is 0.09.
- But the lead has the highest rate in only 116 of 220 group-11 cases (53%).

Current-season snap share (weeks 1 to 9, `current_share.py`) says something different:

- The lead RB's share is 0.50. A backup's share is 0.16.
- The lead has the highest share in 151 of 220 cases (69%).

So the 2022 to 2025 history puts a backup ahead of the lead in about half the cases. The current season does not.

### Open item

In arm HS, the lead's group-11 weight share is still about 0.48. The snap-count update should move the weight toward the lead, but it does not do so enough. The next check is how `snap_update.apply()` changes the weights for these same cases. That check has not been run yet.

### Limits

- The lead RB is the player with the most actual Week 10 carries. This is used only to score. The simulation does not use it as an input.
- Current-season shares use weeks 1 to 9 only.
- Twenty seeds per game is exploratory.

### What the snap-count update does to the weights

`snap_update.player_weights()` sets each player's weight to his current-season snap share blended with his history rate, divided by that history rate. `Field.rate()` multiplies the rate by this weight. (`PLAYER_N0 = 1.0`, `WEIGHT_RANGE = (0.02, 50)`.)

`code/snap_effect.py` compares arm B2 (no update) with arm HS (update). At each team's first play, both arms start from the same empty lineup, so the candidates are the same. The comparison uses the 189 group-11 cases where both arms have the same candidates:

| Measure | Value |
|---|---|
| Lead RB share of bench weight, B2 | 0.44 |
| Lead RB share of bench weight, HS | 0.48 |
| Lead RB weight ratio, HS to B2 (median) | 2.04 |
| Backup RB weight ratio, HS to B2 (median) | 1.78 |

Every RB weight roughly doubles. The lead gains little against the backups, because each player's weight is scaled by his own share-to-history ratio, and those ratios are similar for the lead and the backups. The update does not change the ranking enough to fix group 11. The mean ratio is skewed, so the medians are the reliable figures.

This is a finding, not a fix. The update has not been changed or tuned.

### Arm HE: current-season entry weight (one change from HS)

Change: the bench draw weights each player by his current-season share of team snaps (weeks 1 to 9). Players with no earlier active game keep the table rate. Leave hazards still use the table rate. The flag is `--participation-entry-current-season`, off by default. Code: `participation_field.entry_weight()`, `snap_update.apply()`, `slc_engine`, `simulate_pregame_batch`. Driver: `code/he_campaign.py`. Results: `results/he_report.json`, `results/entry_group_he.json`.

Check: for players with earlier games, the HE weight equals the current snap share (for example Kenneth Walker III: weight 0.743, share 0.743).

| Measure | HS | HE |
|---|---|---|
| Lead RB on-field rate | 0.510 | 0.522 |
| Lead RB in 11 personnel | 0.505 | 0.507 |
| Departures per 100 on-field plays | 17.1 | 18.4 |
| Lead RB carries per game | 12.6 | 12.9 |

Paired margin, HE minus B: -0.18 (interval -1.53 to 1.21). HE minus C: 1.30 (interval -0.52 to 3.12).

First play, group 11 (`results/entry_group_he.json`):

| Arm | Lead RB weight share (all candidates) | Lead RB picked |
|---|---|---|
| HS | 0.48 | 0.44 |
| HE | 0.43 | 0.45 |

Among RB candidates only (`code/rb_only_share.py`, 198 cases): the lead's share is 0.49 in HS and 0.46 in HE. The current-season share did not favor the lead on the first play.

Likely reasons, not yet tested:
- The lead RB is the player with the most actual Week 10 carries. In many cases a backup has a higher current share.
- Players with no earlier game use the table rate. That mixes two scales in one draw.

Conclusion: the current-season entry signal works as coded but does not fix the lead RB's first-play share. It changes the lead RB's on-field rate only slightly.

### Where the lead RB's exits come from (all arms)

`code/exit_split.py` counts each time the lead RB goes from on-field to off-field. The cause comes from that play's advance calls: a hazard leave (`leavers`) or a forced personnel removal (`count_removed`). Results: `results/exit_split.json`.

| Arm | Exits per 100 on-field plays | Hazard share | Forced share | Hazard per 100 on-field plays | Forced per 100 on-field plays |
|---|---|---|---|---|---|
| B | 28.8 | 85% | 15% | 24.5 | 4.3 |
| C | 27.6 | 88% | 12% | 24.1 | 3.4 |
| H | 24.3 | 89% | 11% | 21.6 | 2.8 |
| HS | 17.1 | 83% | 17% | 14.3 | 2.8 |
| HP | 24.8 | 92% | 8% | 22.7 | 2.1 |
| HSP | 16.5 | 87% | 13% | 14.3 | 2.1 |
| HE | 18.4 | 84% | 16% | 15.5 | 2.9 |

Most exits are hazard leaves in every arm. HE raises total exits from 17.1 to 18.4 per 100 on-field plays, almost all from hazard leaves. So HE's gain on entry is partly cancelled by more exits.

We cannot yet say whether about 15 hazard exits per 100 on-field plays is too high. The database has no real stint data to compare against.
