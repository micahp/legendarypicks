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
