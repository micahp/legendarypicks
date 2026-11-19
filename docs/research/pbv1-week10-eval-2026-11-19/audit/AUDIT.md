# Week 10 PBV1 allocation audit

Scope: 14 Week 10 games, 20 seeds per game, three arms. Box scores cover arms A, B and C. Per-play choice records cover arms B and C only. Records and code are on the fast host under `/root/tnf-batch/audit/`. Output: `results/analysis.json`. Code: `code/audit_analysis.py`.

Carries and targets below are per game, averaged over 20 seeds. Actual values come from the frozen database (`player_game_logs`, 2026 REG). Simulated values are the box-score `rushing.att` and `receiving.tgt`.

## Short answer

- The field arms do change who gets carries. Among players who have an actual log row, the share error falls about 7% in both field arms.
- About a quarter (22 to 27%) of simulated carries go to players with no log row in the real game. Only one cause is confirmed: Achane's pregame snapshot has no availability status. Most of the others have no published source either way (section 11a).
- The field arms cut carries to high-volume runners by much more than the MAE shows. Their signed error goes from -68 to about -190 carries per 14 games.
- Scores do not differ measurably between arms. Every confidence interval includes zero.

## 1. Every simulated carry and target

Per arm, totals over the 14 games. Each row is one player-game.

| Category | A player-games | A sim carries | B sim carries | C sim carries | Actual |
|---|---|---|---|---|---|
| Matched, actual touches | 264 | 642.4 | 583.0 | 595.5 | 735 |
| Matched, no actual touch | 38 | 17.4 | 35.8 | 32.3 | 0 |
| Sim player with no log row | 228 | 186.9 | 232.0 | 220.1 | 0 |
| Roster omission (actual touches, not in sim) | 14 | 0.0 | 0.0 | 0.0 | 7 |
| **Total** | | **846.7** | **850.7** | **847.9** | **742** |

Targets follow the same pattern. Simulated targets were 1029.7, 1020.5 and 1018.5 (A, B, C). Actual targets were 881. Players with no log row took 267.5, 292.9 and 297.2 of them. Roster omissions account for 27 actual targets.

The actual totals reconcile exactly with the logs: 742 carries and 881 targets, all in the rows above.

**Players with no log row are not an ID mismatch.** I checked the names. None of these players appears in the game's logs under another ID. The example is De'Von Achane (MIA, MIA_IND, seed 300001). He is in the simulated box score with 12 carries, but has no log row for that game. His entry in the pregame snapshot (`rosters/away/players[6]`) comes from `nflverse_depth_charts`, and the snapshot has no injury or availability field. The box score's roster status fields are null, so the output cannot show why he was included.

**Roster omissions:** 14 player-games had actual touches that the simulation never listed. I did not trace these individually.

## 2. Errors by position (carries, signed = simulated minus actual)

All rows, including players with no log row:

| Pos | A sim / act | A signed | A MAE | B sim / act | B signed | B MAE | C sim / act | C signed | C MAE |
|---|---|---|---|---|---|---|---|---|---|
| RB | 719.6 / 607 | +112.6 | 5.23 | 691.1 / 607 | +84.1 | 4.94 | 690.5 / 607 | +83.5 | 4.80 |
| QB | 95.8 / 115 | -19.2 | 2.40 | 113.6 / 115 | -1.4 | 2.55 | 112.1 / 115 | -3.0 | 2.54 |
| WR | 19.1 / 16 | +3.1 | 0.21 | 30.2 / 16 | +14.2 | 0.28 | 29.7 / 16 | +13.7 | 0.27 |
| TE | 12.3 / 3 | +9.3 | 0.14 | 15.8 / 3 | +12.8 | 0.18 | 15.6 / 3 | +12.6 | 0.19 |

Players with a log row only:

| Pos | A sim / act | A signed | B sim / act | B signed | C sim / act | C signed |
|---|---|---|---|---|---|---|
| RB | 563.1 / 607 | -44.0 | 495.3 / 607 | -111.8 | 505.6 / 607 | -101.5 |
| QB | 76.3 / 115 | -38.7 | 90.5 / 115 | -24.5 | 89.7 / 115 | -25.3 |
| WR | 13.3 / 16 | -2.8 | 22.4 / 16 | +6.4 | 21.6 / 16 | +5.6 |
| TE | 7.2 / 3 | +4.2 | 10.6 / 3 | +7.6 | 11.0 / 3 | +8.0 |

Among players with a log row, RB absolute error falls from 450 (A) to 397 (B) and 392 (C). The field arms under-allocate RB carries to these players. The gap moves to players with no log row, and to WRs and TEs.

**High-volume runners** (29 player-games with 10 or more actual carries):

| Arm | Sim | Actual | Signed | MAE |
|---|---|---|---|---|
| A | 377.1 | 445 | -67.9 | 8.84 |
| B | 248.2 | 445 | -196.8 | 7.43 |
| C | 262.8 | 445 | -182.2 | 6.95 |

**Starters** (actual snap share at least 0.5, log row present, 158 player-games):

| Arm | Sim | Actual | Signed | MAE |
|---|---|---|---|---|
| A | 449.5 | 489 | -39.5 | 1.83 |
| B | 337.5 | 489 | -151.5 | 1.67 |
| C | 357.9 | 489 | -131.1 | 1.57 |

**Why starter MAE falls while starter volume falls.** MAE is an average over player-games. Starter rows are mostly low-volume. The field arms pull the high-volume runners' carries down, so errors on those rows shrink in absolute terms. The signed total gets worse because those runners are now under-allocated by about 180 to 200 carries. Starter MAE does not show this.

## 3. Who lost and gained starter carries

Summed over 14 games, simulated carries for starters. Actual in brackets.

Lost carries from A to B:

- Zach Charbonnet (SEA, RB): 29.2 to 11.8 [20]
- Christian McCaffrey (SF, RB): 25.1 to 10.9 [13]
- Derrick Henry (BAL, RB): 25.1 to 12.8 [10]
- Bijan Robinson (ATL, RB): 24.2 to 12.9 [16]
- Jahmyr Gibbs (DET, RB): 22.7 to 13.2 [22]
- Javonte Williams (DAL, RB): 21.2 to 13.0 [16]

Gained carries from A to B:

- Dak Prescott (DAL, QB): 2.7 to 7.9 [4]
- Justin Herbert (LAC, QB): 3.9 to 7.4 [7]
- Brock Purdy (SF, QB): 3.5 to 6.0 [2]
- Blake Corum (LA, RB): 8.2 to 9.9 [17]
- Dylan Sampson (CLE, RB): 6.7 to 8.3 [4]

From B to C, the lists partly reverse. Charbonnet rises from 11.8 to 17.4 [20], Jordan Mason (MIN) from 9.6 to 13.0 [16], and Bijan Robinson from 12.9 to 15.8 [16]. Javonte Williams falls from 13.0 to 9.8 [16] and Jonathan Taylor (IND) from 13.2 to 11.6 [16].

The field moves carries from high-volume RBs to QBs and to backups. Arm C partly reverses this.

## 4. Team opportunity shares

Per team-game, averaged over 28 team-games. Share error is the sum of |simulated share minus actual share| times actual team volume. Team total error is |simulated team total minus actual team total|.

Players with a log row only:

| Arm | Carry share error | Carry team total error | Carry player abs error | Target share error |
|---|---|---|---|---|
| A | 570.6 | 197.5 | 564.9 | 643.3 |
| B | 530.4 | 207.4 | 525.7 | 633.5 |
| C | 531.7 | 192.0 | 519.2 | 633.5 |

All players, including those with no log row:

| Arm | Carry share error | Carry team total error | Carry player abs error | Target share error |
|---|---|---|---|---|
| A | 648.9 | 200.7 | 751.8 | 799.9 |
| B | 681.2 | 215.6 | 757.7 | 811.7 |
| C | 663.0 | 197.1 | 739.3 | 805.0 |

Among players who played, the field arms reduce carry share error by about 7%. That is an allocation change, not a shift of volume between teams. Team totals change little.

Once players with no log row are included, the share error rises in both field arms. The gain among players who played is offset by carries to players who did not play. Total player absolute error is 751.8 (A), 757.7 (B) and 739.3 (C). Arm C is 1.7% below A. Arm B is above A.

## 5. Mechanism or reshuffling

To separate the two, compare the share error and the team total error:

- A better allocation mechanism lowers the share error for the same team total. Among players who played, the field arms do that (570 to 530).
- Reshuffling moves volume without improving shares. The no-log-row carries are reshuffling of this kind. They add 33 to 45 carries per 14 games over A, and they are not a gain.
- High-volume runners lose volume in both field arms, and that loss is not a share improvement.

So the field arms show a real change in the shape of allocation among players who played. That change is mostly offset by volume going to absent players and by lower volume for high-volume runners. Arm C is slightly better than A on total player error, and the scores do not move.

## 6. Lineup eligibility (per play)

Checked each play's non-QB rusher and each play's receiver against that play's `on_field` list.

| Arm | Plays | Checked | Violations | QB rushes not checked | Lineup status |
|---|---|---|---|---|---|
| B | 38,036 | 35,764 | 0 | 2,272 | ok 37,939, short 97 |
| C | 37,936 | 35,695 | 0 | 2,241 | ok 37,892, short 44 |

No play used a player who was off the field. Short lineups (on-field size 2 to 4) are included in the check.

## 7. Box score reconciliation

- Rush picks equal box carries exactly: 17,013 (B) and 16,957 (C), in every seed.
- Receiver picks exceed box targets by 613 (B) and 609 (C). These equal the receiver picks on sack plays plus the receiver picks on lost-fumble plays: B 531 + 82 = 613, C 526 + 83 = 609. Sacks and lost fumbles are not counted as box targets. Interceptions are counted.

This reconciles on totals. I have not checked it play by play.

## 8. Paired score differences (final margin, home minus away)

Paired by seed (280 seeds per pair). Mean difference, with a 95% interval from a bootstrap over the 14 game clusters.

| Pair | Mean margin diff | 95% CI | Seeds with a different margin |
|---|---|---|---|
| A minus B | -1.19 | [-2.94, +0.75] | 235 / 280 |
| B minus C | +1.49 | [-0.73, +3.74] | 247 / 280 |
| A minus C | +0.29 | [-1.29, +1.73] | 237 / 280 |

Total points and home-win differences also have intervals that include zero.

The arms differ in most individual seeds, but the average difference is small and not distinguishable from zero.

## 9. First divergence (B vs C, 280 seeds)

- **Lineup group label:** is the first field to differ in all 280 seeds, at play 0 to 9. This is by design. The PBV1 package sets the grouping label, so C's label differs from B's from the first play that draws a package.
- **Player choice (rusher or receiver):** first differs at play median 1, range 0 to 11.
- **Outcome (yards, event):** the earlier draw diagnostic found the first outcome difference at play 20 or later. Both are correct for what they measure. In the example of seed 300002, play 1 has different receivers in B and C, and both plays gain 27 yards. Outcome records can match when the player differs, so the earlier diagnostic understates when the decisions start to differ.

## 10. Shared draws and candidate lists (B vs C, first call per key)

- 65,119 draw keys appear in both arms.
- 27,629 give the same chosen value. 37,490 give a different chosen value.
- Of the different ones, 36,112 have a different candidate list. 1,369 have the same list but different weights.
- 73,535 keys occur more than once within one run. The comparison uses the first call only.

Most shared draws select a different player because the candidate list differs. That is expected once the lineup differs.

## 11. Follow-up: unlogged carriers and high-volume starters

Scripts: `code/investigate.py`. Output: `results/investigation.json`.

### 11a. Players with no log row who got carries (arm C)

Checked against published week 10 sources: `nfl_snap_counts` and `injury_reports`.

| Class | Player-games | Carries | Share of carries |
|---|---|---|---|
| No snap row and no injury row | 81 | 142.1 | 65% |
| Injury report: Out, Doubtful or IR | 22 | 36.8 | 17% |
| Injury report: other status (for example Questionable) | 11 | 14.7 | 7% |
| Snap count file shows snaps, but no log row | 24 | 12.8 | 6% |
| Snap count file shows zero snaps, no injury row | 4 | 13.6 | 6% |

Arm B shows the same pattern.

- The Out, Doubtful and IR rows should have been removed by the availability rule. The rule only acts when the snapshot carries a designation. The snapshot has none, so the rule never fired.
- The snaps-but-no-log rows point to gaps in the log table. The simulation may be right for those players.
- The 142 carries with no published source either way are not explained by these checks.

### 11b. High-volume starters: snap share and carries per snap

Six starters, one game each, from the log rows. Snap share is the player's snaps over team snaps. Carry share is carries over team carries. Relative rate is carry share divided by snap share. A value of 1.0 means carries in proportion to snaps.

| Player | Actual snap % | B snap % | C snap % | Actual carry % | B carry % | C carry % | Actual rel. | B rel. | C rel. |
|---|---|---|---|---|---|---|---|---|---|
| Bijan Robinson | 8.0 | 8.0 | 8.9 | 80.0 | 44.3 | 52.7 | 10.0 | 5.5 | 5.9 |
| Jahmyr Gibbs | 10.5 | 8.7 | 9.0 | 64.7 | 50.6 | 48.7 | 6.1 | 5.9 | 5.4 |
| Derrick Henry | 7.0 | 7.1 | 7.8 | 66.7 | 36.5 | 38.8 | 9.5 | 5.2 | 5.0 |
| Christian McCaffrey | 10.1 | 7.6 | 8.0 | 44.8 | 38.7 | 41.2 | 4.5 | 5.1 | 5.2 |
| Jonathan Taylor | 8.8 | 8.7 | 9.0 | 47.1 | 46.0 | 43.8 | 5.4 | 5.3 | 4.9 |
| Zach Charbonnet | 12.6 | 7.3 | 8.6 | 57.1 | 36.1 | 46.6 | 4.5 | 5.0 | 5.4 |

Control (A) carry share for the same six is 76% to 89%. That is above the actual 45% to 80%. Arm B is 36% to 51%. The control overshoots and the field arm undershoots.

Arm A's box score has snap data for only 2 of 39 players in one game I checked. The snap split therefore cannot compare A with the field arms.

Readings:

- **Snap share.** Arm B matches the actual snap share for Robinson, Henry and Taylor. It is lower for Gibbs, McCaffrey and Charbonnet. Arm C is closer on all six.
- **Carries per snap.** Actual relative rates run from 4.5 to 10.0. Both field arms give every player 4.9 to 5.9. The simulation does not separate the high-volume runners from the others once they are on the field.
- **Selection on the field.** In arms B and C, the six are picked as rusher on 0.88 to 0.95 of run plays while they are on the field. So the shortfall is not in choosing among on-field players.
- **What is left.** The low carries per snap probably come from how often runs are called while the player is on the field. The records do not yet split that out. Splitting it needs one more pass over the choice records.

## Limitations

- Choice records cover arms B and C only. Arm A's allocation comes from box scores only.
- Shared-draw comparison uses the first call per key. 73,535 keys repeat within a run.
- The no-log-row cause is established for Achane only. I did not trace the causes for the other players, which may include injuries, inactives, or depth-chart entries.
- Starter means snap share at least 0.5 in the actual logs.
- Twenty seeds per game is exploratory. The intervals are wide.
- Roster omissions were not traced.

## Reproduce

On the fast host:

    cd /root/tnf-batch/audit && python3 audit_analysis.py

Writes `/root/tnf-batch/audit/analysis/analysis.json`. This copy is in `results/analysis.json`.

Scratch checks run on the host while building this report (`check3.py` to `check6.py` in `/root/tnf-batch/audit/`) are not committed.
