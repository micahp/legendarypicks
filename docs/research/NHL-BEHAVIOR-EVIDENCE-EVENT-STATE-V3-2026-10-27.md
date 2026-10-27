# NHL Behavior Evidence Audit: Event-State Attribution v3

- **Date:** 2026-10-27
- **Branch:** `research/nhl-roster-behavior-audit-2026-10-26`
- **Base:** `9501768f1410484d8be235fe0700f710f5ec189e`
- **Purpose:** research-only corrected source audit and conditional behavior diagnostics; no adoption or gate decision.
- **Preserved prior audit:** `research/nhl/behavior-evidence/results/nhl-behavior-evidence-2026-10-26.json` (SHA-256 `fcd045826d2b1770fb19471bd83fd0a4672d79953a1c323127738ab8bff42f4f`).

## Population and provenance

| Population | Listed | Eligible | Excluded/quarantined |
|---|---:|---:|---:|
| 2019 start season | 1082 | 1064 | 18 reason records |
| 2020 start season | 868 | 857 | 11 reason records |
| 2021 start season | 1312 | 1292 | 20 reason records |

PBP manifest: 4876 bodies, all listed HTTP statuses 200: True. Shift manifest: 4876 bodies, all listed HTTP statuses 200: True. The source-origin breakdown is retained in the JSON because most bodies were reused from a cache whose original retrieval provenance was not recorded.

The independent box-score manifest listed 4876 records; the validated corpus reports source counts `{"official_gamecenter": 4576, "prior_official_audit_cache": 300}`. PBP and box-score bodies, game/team identity, clocks, score, and SOG were checked by the frozen v0.1 loader.

## Existing Legendary Picks NHL data

Read-only inventory of `picks.dev.db`; these current-season tables were not used to fit the 2019/20 or 2021 historical models:

| Table | NHL rows | Seasons / range | Source evidence |
|---|---:|---|---|
| `players` | 1431 | `"current roster snapshots"` | `"\u2014"` |
| `player_source_ids` | 2014 | `"current roster snapshots"` | `{"nhle.com": 1318, "rotowire": 696}` |
| `player_stats` | 1833 | `{"2026": 1038, "2027": 795}` | `{"nhle.com": 1833}` |
| `player_game_logs` | 54727 | `{"2026": 51143, "2027": 3584}` | `{"nhle.com": 51143, "nhle.com:gamecenter/boxscore": 3584}` |
| `team_game_results` | 2812 | `{"2026": 2624, "2027": 188}` | `{"espn_site_api:scoreboard+summary": 2624, "nhle.com:club-schedule-season+gamecenter/boxscore": 188}` |
| `team_game_stats` | 2812 | `"current roster snapshots"` | `{"espn_site_api:scoreboard+summary": 2624, "nhle.com:gamecenter/right-rail+landing": 188}` |
| `roster_snapshots` | 816 | `{"2027": 816}` | `{"espn_site_roster": 1, "nhle.com:roster": 815}` |
| `roster_memberships` | 644497 | `"current roster snapshots"` | `"\u2014"` |
| `game_context` | 3 | `"current roster snapshots"` | `"\u2014"` |

The database contains useful current pregame roster/player/team inputs, but its NHL player logs and team outcomes begin in 2025–26; it does not supply the historical training/development population. The official GameCenter archive remains the behavior-evidence source. All database reads used URI `mode=ro` and `PRAGMA query_only=ON`.

## Behavior evidence

The full event, field-coverage, shift, player, goalie, transition, and uncertainty tables are in the generated JSON. Selected counts:

| Measure | 2019/20 training | 2021 development |
|---|---:|---:|
| Eligible games | 1921 | 1292 |
| Faceoffs | 108660 | 73027 |
| Shot attempts | 213396 | 146319 |
| SOG events | 118203 | 81660 |
| Penalty events | 13630 | 9556 |
| Stoppages | 84104 | 56243 |

### Event-to-shift timestamp attribution

PBP events are ordered by `sortOrder`; both PBP clocks and shift start/end values resolve only to whole seconds. The event's situation code is retained as the source-reported state snapshot, not presumed to mean pre-event for every event type. When a later event record has the same clock second, its situation code is recorded separately as the next same-clock observation; otherwise a post-event state is not inferred. Independently, the extractor constructs the shift left-limit state (ending intervals still active, starting intervals not yet active) and right-limit state (the reverse), then reconciles the source snapshot against both. A source code matching neither state, or a missing code at a changed boundary, is marked uncertain and excluded from conditional event-rate fitting. The next-record state is evidence, not an inferred continuous transition, and this does not claim subsecond timing.

| Population | Events at a shift boundary | Matches left limit | Matches right limit | Matches both | Conflicts at boundary | Missing source at boundary | Excluded from conditional fitting (all events) |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2019/20 training | 235034 | 22133 | 28451 | 169735 | 9979 | 4736 | 24428 |
| 2021 development | 160585 | 15983 | 20521 | 118839 | 4085 | 1157 | 5681 |

Selected same-second event fixtures from the source archive:

| Population | Game | PBP event | Clock | PBP situation code | Next same-clock code | Shift left limit | Shift right limit | Attribution |
|---|---|---|---|---|---|---|---|---|
| 2019/20 | `2019020001` | faceoff `9` (sort 10) | REG 1 00:00 | `1551` | `None` | H0vA0 (goalies 0/0) | H5vA5 (goalies 1/1) | source_matches_right_limit |
| 2019/20 | `2019020001` | goal `10` (sort 11) | REG 1 00:25 | `1551` | `1551` | H5vA5 (goalies 1/1) | H5vA5 (goalies 1/1) | source_matches_both_boundary_states |
| 2019/20 | `2019020001` | faceoff `11` (sort 14) | REG 1 00:25 | `1551` | `None` | H5vA5 (goalies 1/1) | H5vA5 (goalies 1/1) | source_matches_both_boundary_states |
| 2019/20 | `2019020001` | faceoff `13` (sort 19) | REG 1 00:38 | `1551` | `None` | H5vA5 (goalies 1/1) | H5vA5 (goalies 1/1) | source_matches_both_boundary_states |
| 2019/20 | `2019020001` | penalty `153` (sort 22) | REG 1 00:56 | `1560` | `1451` | H6vA5 (goalies 0/1) | H5vA4 (goalies 1/1) | source_matches_left_limit |
| 2019/20 | `2019020001` | faceoff `14` (sort 26) | REG 1 00:56 | `1451` | `None` | H6vA5 (goalies 0/1) | H5vA4 (goalies 1/1) | source_matches_right_limit |
| 2019/20 | `2019020001` | penalty `251` (sort 73) | REG 1 05:53 | `1551` | `1451` | H5vA5 (goalies 1/1) | H5vA4 (goalies 1/1) | source_matches_left_limit |
| 2019/20 | `2019020001` | penalty `169` (sort 105) | REG 1 08:05 | `1551` | `1451` | H5vA5 (goalies 1/1) | H5vA4 (goalies 1/1) | source_matches_left_limit |
| 2021 | `2021020001` | faceoff `52` (sort 9) | REG 1 00:00 | `1551` | `None` | H0vA0 (goalies 0/0) | H5vA5 (goalies 1/1) | source_matches_right_limit |
| 2021 | `2021020001` | faceoff `55` (sort 22) | REG 1 01:03 | `1551` | `None` | H5vA5 (goalies 1/1) | H5vA5 (goalies 1/1) | source_matches_both_boundary_states |
| 2021 | `2021020001` | faceoff `59` (sort 37) | REG 1 02:32 | `1551` | `None` | H5vA5 (goalies 1/1) | H5vA5 (goalies 1/1) | source_matches_both_boundary_states |
| 2021 | `2021020001` | faceoff `65` (sort 55) | REG 1 04:28 | `1551` | `None` | H3vA5 (goalies 1/1) | H5vA5 (goalies 1/1) | source_matches_right_limit |
| 2021 | `2021020001` | goal `260` (sort 227) | REG 2 00:12 | `1551` | `1551` | H5vA5 (goalies 1/1) | H5vA5 (goalies 1/1) | source_matches_both_boundary_states |
| 2021 | `2021020001` | goal `270` (sort 262) | REG 2 04:11 | `1551` | `1551` | H5vA5 (goalies 1/1) | H5vA5 (goalies 1/1) | source_matches_both_boundary_states |
| 2021 | `2021020001` | penalty `250` (sort 353) | REG 2 12:56 | `1551` | `1451` | H5vA5 (goalies 1/1) | H5vA4 (goalies 1/1) | source_matches_left_limit |
| 2021 | `2021020001` | penalty `406` (sort 383) | REG 2 16:09 | `1551` | `1541` | H5vA5 (goalies 1/1) | H4vA5 (goalies 1/1) | source_matches_left_limit |

### Evidence coverage and limits by mechanic

| Mechanic | Exact observed fields | Deterministic rule work | Empirical behavior supported | Remaining unobserved |
|---|---|---|---|---|
| Penalties and manpower | PBP play type/eventId/sortOrder/timeInPeriod/timeRemaining/periodDescriptor/situationCode; penalty details typeCode/duration/descKey/committedByPlayerId/servedByPlayerId/eventOwnerTeamId; shift playerId/teamId/period/startTime/endTime/duration | Applicable rulebook penalty service, duration, release, coincidence and manpower tables | Penalty frequency/type by observed state; overlap candidates from assessment clocks and nominal duration; shift return proxies | PBP has no explicit Rule 19 adjudication label or canonical expiration/release event; nominal duration endpoint is not a verified service interval |
| Faceoffs and post-faceoff sequence | PBP winningPlayerId/losingPlayerId/eventOwnerTeamId/zoneCode/xCoord/yCoord/timeInPeriod/situationCode; rosterSpots playerId/teamId/positionCode | Restart placement when the source records the location and the applicable rule specifies it | Team/player faceoff win rates; next event; winner-team attempt before next faceoff and within 30 game-clock seconds | Continuous possession, unrecorded passes and puck control between event records |
| Shifts and substitutions | Shift data rows: gameId/playerId/teamId/period/startTime/endTime/duration/typeCode/eventDescription; PBP rosterSpots playerId/teamId/positionCode | Clock arithmetic, interval ordering and eligible personnel constraints under the applicable rules | Shift duration, observed start/deployment rates and interval overlap; context is nearest preceding PBP state | Forward line/defensive pair labels, coaching intent, fatigue, and why a change was selected |
| Goalie presence, pulls and returns | PBP situationCode goalie/skater digits and shot goalieInNetId; shift playerId/teamId/period/startTime/endTime; PBP score and clock | Personnel-count legality and rules for substitution/re-entry when all state is observed | Empty-net intervals and goalie-presence transitions by pre-event score/time, subject to shift reconciliation | A shift endpoint alone does not prove a pull; actual target-game starter is not a valid pregame input here |
| Shooting and scoring | PBP event type goal/shot-on-goal/missed-shot/blocked-shot; shootingPlayerId/scoringPlayerId/goalieInNetId/xCoord/yCoord/zoneCode/shotType/situationCode; independent box-score team SOG and goals | Score and SOG accounting; shootout goals separated from player regulation/OT goals | Attempt-event rate, attempt-to-SOG, SOG-to-goal, and recorded type/zone/strength/goalie conditional diagnostics | Attempts with no recorded PBP event and true release location for many blocked shots |
| Stoppages and restarts | PBP stoppage details.reason, event order/clock, following faceoff details.zoneCode/xCoord/yCoord; penalty and goal records | Restart consequence where event cause, zone and applicable rule inputs are explicit | Recorded stoppage reason frequency and ordered next-faceoff/restart sequence | Unrecorded whistles and geometric evidence to independently adjudicate icing/offside or other spatial calls |
| Overtime and shootouts | PBP periodDescriptor/timeInPeriod/event type/team owner; official final box score and shootout events/attempts | Season-applicable OT clock, sudden-death termination, shootout paired attempts and early-clinch rules | Tie-to-OT, OT duration/goal and shootout occurrence/attempt/outcome distributions | Decision policy for tactics and personnel unless identifiable from the observed event sequence |

### Shot-field availability by recorded outcome

| Population | PBP outcome | Events | shotType present | zoneCode present | x/y present | goalieInNetId present |
|---|---|---:|---:|---:|---:|---:|
| 2019/20 training | `blocked-shot` | 51409 | 0/51409 (0.0%) | 51409/51409 (100.0%) | 51409/51409 (100.0%) | 0/51409 (0.0%) |
| 2019/20 training | `goal` | 11638 | 11637/11638 (100.0%) | 11638/11638 (100.0%) | 11638/11638 (100.0%) | 11058/11638 (95.0%) |
| 2019/20 training | `missed-shot` | 43961 | 43961/43961 (100.0%) | 43961/43961 (100.0%) | 43961/43961 (100.0%) | 43485/43961 (98.9%) |
| 2019/20 training | `shot-on-goal` | 107451 | 107448/107451 (100.0%) | 107450/107451 (100.0%) | 107450/107451 (100.0%) | 107451/107451 (100.0%) |
| 2021 development | `blocked-shot` | 34851 | 0/34851 (0.0%) | 34851/34851 (100.0%) | 34851/34851 (100.0%) | 0/34851 (0.0%) |
| 2021 development | `goal` | 8213 | 8213/8213 (100.0%) | 8213/8213 (100.0%) | 8213/8213 (100.0%) | 7747/8213 (94.3%) |
| 2021 development | `missed-shot` | 29933 | 29933/29933 (100.0%) | 29933/29933 (100.0%) | 29933/29933 (100.0%) | 29680/29933 (99.2%) |
| 2021 development | `shot-on-goal` | 74024 | 74024/74024 (100.0%) | 74024/74024 (100.0%) | 74024/74024 (100.0%) | 74024/74024 (100.0%) |

### Missing goalie identity versus empty-net state

This classification uses the source goalie ID and the event-state reconciliation above. `Expected empty net` means the reconciled situation code indicates no defending goalie; `missing ID with goalie present` is a source identity gap, not a goalie-performance observation. Unresolved states remain separate.

| Population | On-target event | Events | Goalie ID present | Expected empty net | Missing ID, goalie present | State unresolved |
|---|---|---:|---:|---:|---:|---:|
| 2019/20 training | `goal` | 11296 | 10716 | 547 | 8 | 25 |
| 2019/20 training | `shot-on-goal` | 106907 | 106907 | 0 | 0 | 0 |
| 2021 development | `goal` | 8003 | 7537 | 450 | 0 | 16 |
| 2021 development | `shot-on-goal` | 73657 | 73657 | 0 | 0 | 0 |

The preserved prior artifact reported all-attempt shotType Brier `0.14665190792563246` (n=146319) against all-attempt parent `0.24664238099282254` (n=146319). That apparent gain is invalid as a prospective shot-conversion comparison: shotType missingness differs by recorded outcome: `True`; blocked-shot events have 100% shotType missingness in both populations: `True`. Blocked attempts are negative SOG outcomes, so the missing-value category reveals the target. This version excludes missing shotType or zoneCode and compares each grouped diagnostic with a parent on the same feature-present attempts. Because the complete-case cohort can still be selected by target-dependent recording, these scores are retrospective conditional diagnostics, not prospective predictive evidence. Likewise, goalie-ID analysis excludes missing goalie IDs rather than treating missing as a goalie skill group; the old goalie-ID Brier `0.08377127733298244` (n=81660) is preserved only as a retrospective reference. The new output also reports goalie presence separately from goalie identity.

### Conditional scoring diagnostics

Parameters were fit on 2019/20 only, with 20 parent-equivalent observations for shrinkage and a parent fallback below 100 training opportunities. The 2021 score table is a once-scored development diagnostic. Shot-type/zone/goalie scores condition on recorded event attributes; complete-case cohorts may be selected by outcome-dependent recording and are not prospective skill estimates or full-game forecasts. A grouped attribute can be used prospectively only after it is generated or known before its conditional outcome; actual target-game goalie identities remain retrospective.

| 2021 event model | N | Mean Brier / log loss | Paired 95% CI of loss difference vs parent |
|---|---:|---|---|
| `faceoff:league_50` brier | 73027 | 0.25000 | — |
| `faceoff:league_50` log_loss | 73027 | 0.69315 | — |
| `faceoff:team_rate` brier | 73027 | 0.24954 | — |
| `faceoff:team_rate` log_loss | 73027 | 0.69222 | — |
| `faceoff_shot:parent` brier | 73027 | 0.23195 | — |
| `faceoff_shot:parent` log_loss | 73027 | 0.65661 | — |
| `faceoff_shot:strength` brier | 73027 | 0.22026 | — |
| `faceoff_shot:strength` log_loss | 73027 | 0.63030 | — |
| `goal_all` brier | 81660 | 0.08841 | — |
| `goal_all` log_loss | 81660 | 0.32071 | — |
| `goal_by_goalie_present` brier | 81194 | 0.08426 | — |
| `goal_by_goalie_present` log_loss | 81194 | 0.30935 | — |
| `goal_by_shot_type_complete` brier | 81660 | 0.08783 | — |
| `goal_by_shot_type_complete` log_loss | 81660 | 0.31773 | — |
| `goal_by_strength` brier | 81222 | 0.08287 | — |
| `goal_by_strength` log_loss | 81222 | 0.30411 | — |
| `goal_by_zone_complete` brier | 81660 | 0.08829 | — |
| `goal_by_zone_complete` log_loss | 81660 | 0.31994 | — |
| `goal_goalie_present_all` brier | 81194 | 0.08421 | — |
| `goal_goalie_present_all` log_loss | 81194 | 0.30905 | — |
| `goal_state_valid_all` brier | 81222 | 0.08749 | — |
| `goal_state_valid_all` log_loss | 81222 | 0.31817 | — |
| `goal_type_complete_all` brier | 81660 | 0.08841 | — |
| `goal_type_complete_all` log_loss | 81660 | 0.32071 | — |
| `goal_zone_complete_all` brier | 81660 | 0.08841 | — |
| `goal_zone_complete_all` log_loss | 81660 | 0.32071 | — |
| `sog_all` brier | 146319 | 0.24664 | — |
| `sog_all` log_loss | 146319 | 0.68642 | — |
| `sog_by_shot_type_complete` brier | 111468 | 0.19250 | — |
| `sog_by_shot_type_complete` log_loss | 111468 | 0.57260 | — |
| `sog_by_strength` brier | 145688 | 0.24584 | — |
| `sog_by_strength` log_loss | 145688 | 0.68470 | — |
| `sog_by_zone_complete` brier | 146319 | 0.15855 | — |
| `sog_by_zone_complete` log_loss | 146319 | 0.48236 | — |
| `sog_state_valid_all` brier | 145688 | 0.24671 | — |
| `sog_state_valid_all` log_loss | 145688 | 0.68655 | — |
| `sog_type_complete_all` brier | 111468 | 0.19591 | — |
| `sog_type_complete_all` log_loss | 111468 | 0.58069 | — |
| `sog_zone_complete_all` brier | 146319 | 0.24664 | — |
| `sog_zone_complete_all` log_loss | 146319 | 0.68642 | — |
| `sog_by_strength` paired delta | — | Brier [-0.0010299981310807615, -0.0007277980086576596]; log loss [-0.002188225402377064, -0.001513337638873069] | game-cluster percentile bootstrap |
| `sog_by_shot_type_complete` paired delta | — | Brier [-0.003755412070897829, -0.0030519197915488128]; log loss [-0.008965544022102145, -0.0072736634069073824] | game-cluster percentile bootstrap |
| `sog_by_zone_complete` paired delta | — | Brier [-0.08919536228187, -0.08697505168131597]; log loss [-0.20677584965126938, -0.20106758385085755] | game-cluster percentile bootstrap |
| `goal_by_strength` paired delta | — | Brier [-0.005006573751091481, -0.0042323896178422665]; log loss [-0.015250356198628245, -0.012953652253556991] | game-cluster percentile bootstrap |
| `goal_by_shot_type_complete` paired delta | — | Brier [-0.0006897429988827336, -0.0004661591175346147]; log loss [-0.003513244834256468, -0.002429095639549017] | game-cluster percentile bootstrap |
| `goal_by_zone_complete` paired delta | — | Brier [-0.00015216917296942412, -7.84946666944758e-05]; log loss [-0.0010455730272868613, -0.00047029735247994253] | game-cluster percentile bootstrap |
| `goal_by_goalie_present` paired delta | — | Brier [2.032565513496176e-06, 8.205512218169286e-05]; log loss [5.2422989580858115e-05, 0.000566389731561423] | game-cluster percentile bootstrap |
| `faceoff_team_rate` paired delta | — | Brier [-0.00057028792345451, -0.0003559059543315479]; log loss [-0.0011406932537547654, -0.0007068164178684055] | game-cluster percentile bootstrap |
| `faceoff_shot_strength` paired delta | — | Brier [-0.012452089140357087, -0.010963375945301501]; log loss [-0.028028801699678474, -0.024606906667026585] | game-cluster percentile bootstrap |

### Event rates by observed game state

Train-only rates use shift-derived team-minute exposure. Event conditioning uses the PBP situation code only when reconciled against the shift left/right limits; ambiguous/conflicting event states are excluded. The listed conditional rates use one context axis at a time; groups under 100 training events fall back to the unconditioned parent. The 2021 comparison conditions on observed shift exposure and in-game state, so it is a diagnostic and not a pregame game forecast. Full support, sparse cells, state exclusions, and cluster intervals are in the JSON.

| Event family | Context | Train events / team-minutes | Frozen train rate / 60 team-min | 2021 observed / expected | Observed/expected | 2021 mean game Poisson deviance delta vs parent |
|---|---|---:|---:|---:|---:|---|
| `attempt` | `all=all` | 206724 / 233368.7 | 53.1496 | 145688 / 138890.9 | 1.049 | 0.0000 |
| `attempt` | `period=OT` | 2560 / 2848.7 | 53.8865 | 1694 / 1573.9 | 1.076 | -0.0130 |
| `attempt` | `period=REG` | 204164 / 230520.0 | 53.1401 | 143994 / 137314.1 | 1.049 | 0.0018 |
| `attempt` | `score=tied` | 71758 / 80469.3 | 53.5009 | 51481 / 49216.3 | 1.046 | -0.0248 |
| `attempt` | `strength=4v5` | 4192 / 18077.8 | 14.3177 | 3104 / 2819.0 | 1.101 | -5.5460 |
| `attempt` | `strength=5v4` | 26577 / 18077.8 | 87.8475 | 18806 / 17296.5 | 1.087 | -4.0623 |
| `attempt` | `strength=5v5` | 165472 / 186341.6 | 53.2789 | 115765 / 111625.8 | 1.037 | -0.0161 |
| `attempt` | `time=<=1m` | 12466 / 10511.7 | 70.9697 | 8633 / 8425.7 | 1.025 | -0.5891 |
| `attempt` | `time=>10m` | 102302 / 116627.7 | 52.6354 | 71835 / 68776.6 | 1.044 | 0.0410 |
| `sog` | `all=all` | 114406 / 233368.7 | 29.4142 | 81222 / 76865.5 | 1.057 | 0.0000 |
| `sog` | `period=OT` | 1654 / 2848.7 | 34.6016 | 1101 / 1010.7 | 1.089 | -0.1965 |
| `sog` | `period=REG` | 112752 / 230520.0 | 29.3479 | 80121 / 75835.0 | 1.057 | 0.0147 |
| `sog` | `score=tied` | 39845 / 80469.3 | 29.7064 | 28762 / 27327.4 | 1.052 | -0.0240 |
| `sog` | `strength=4v5` | 3113 / 18077.8 | 10.5288 | 2282 / 2073.0 | 1.101 | -2.1318 |
| `sog` | `strength=5v4` | 14739 / 18077.8 | 48.7176 | 10555 / 9592.1 | 1.100 | -2.3661 |
| `sog` | `strength=5v5` | 90696 / 186341.6 | 29.2053 | 63878 / 61188.7 | 1.044 | 0.0273 |
| `sog` | `time=<=1m` | 6717 / 10511.7 | 38.2483 | 4693 / 4540.9 | 1.033 | -0.2843 |
| `sog` | `time=>10m` | 56959 / 116627.7 | 29.3041 | 40125 / 38290.5 | 1.048 | 0.0102 |
| `goal` | `all=all` | 10889 / 233368.7 | 2.7996 | 7868 / 7316.0 | 1.075 | 0.0000 |
| `goal` | `period=OT` | 266 / 2848.7 | 5.4808 | 169 / 160.1 | 1.056 | -0.2534 |
| `goal` | `period=REG` | 10623 / 230520.0 | 2.7653 | 7699 / 7145.6 | 1.077 | 0.0097 |
| `goal` | `score=tied` | 3612 / 80469.3 | 2.6943 | 2570 / 2478.5 | 1.037 | 0.0026 |
| `goal` | `strength=4v5` | 260 / 18077.8 | 0.8829 | 196 / 173.8 | 1.127 | -0.2346 |
| `goal` | `strength=5v4` | 1925 / 18077.8 | 6.3521 | 1384 / 1250.7 | 1.107 | -0.6741 |
| `goal` | `strength=5v5` | 7465 / 186341.6 | 2.4077 | 5329 / 5044.5 | 1.056 | -0.0270 |
| `goal` | `time=<=1m` | 871 / 10511.7 | 4.9492 | 614 / 587.6 | 1.045 | -0.1465 |
| `goal` | `time=>10m` | 5097 / 116627.7 | 2.6240 | 3676 / 3428.7 | 1.072 | 0.0134 |
| `penalty` | `all=all` | 11885 / 233368.7 | 3.0557 | 8156 / 7985.1 | 1.021 | 0.0000 |
| `penalty` | `period=OT` | 81 / 2848.7 | 3.0557 | 54 / 89.3 | 0.605 | 0.0000 |
| `penalty` | `period=REG` | 11804 / 230520.0 | 3.0722 | 8102 / 7938.5 | 1.021 | -0.0015 |
| `penalty` | `score=tied` | 3641 / 80469.3 | 2.7183 | 2582 / 2500.6 | 1.033 | -0.0128 |
| `penalty` | `strength=4v5` | 524 / 18077.8 | 1.7527 | 359 / 345.1 | 1.040 | -0.0884 |
| `penalty` | `strength=5v4` | 629 / 18077.8 | 2.0976 | 498 / 413.0 | 1.206 | -0.0020 |
| `penalty` | `strength=5v5` | 9175 / 186341.6 | 2.9553 | 6295 / 6191.7 | 1.017 | -0.0001 |
| `penalty` | `time=<=1m` | 750 / 10511.7 | 4.2683 | 549 / 506.7 | 1.083 | -0.0612 |
| `penalty` | `time=>10m` | 5452 / 116627.7 | 2.8074 | 3744 / 3668.3 | 1.021 | -0.0111 |
| `faceoff_win` | `all=all` | 104891 / 233368.7 | 26.9679 | 72161 / 70472.7 | 1.024 | 0.0000 |
| `faceoff_win` | `period=OT` | 1040 / 2848.7 | 22.1251 | 688 / 646.2 | 1.065 | -0.0379 |
| `faceoff_win` | `period=REG` | 103851 / 230520.0 | 27.0298 | 71473 / 69845.0 | 1.023 | -0.0061 |
| `faceoff_win` | `score=tied` | 35413 / 80469.3 | 26.4106 | 24914 / 24295.5 | 1.025 | 0.0117 |
| `faceoff_win` | `strength=4v5` | 8084 / 18077.8 | 26.8322 | 5619 / 5283.0 | 1.064 | 0.0025 |
| `faceoff_win` | `strength=5v4` | 9711 / 18077.8 | 32.1765 | 6801 / 6335.3 | 1.074 | -0.2722 |
| `faceoff_win` | `strength=5v5` | 82142 / 186341.6 | 26.4542 | 55797 / 55424.8 | 1.007 | -0.0049 |
| `faceoff_win` | `time=<=1m` | 5519 / 10511.7 | 31.4554 | 3862 / 3734.5 | 1.034 | -0.0955 |
| `faceoff_win` | `time=>10m` | 54493 / 116627.7 | 28.0233 | 37430 / 36617.0 | 1.022 | -0.0896 |

Unconditioned event-type frequencies use eligible games as the denominator, with game-cluster intervals when support is at least 100. This includes stoppage types and shootout records; the full per-game table is in each season section of the JSON.

| Event type | Train count / mean per eligible game (95% CI) | 2021 count / mean per eligible game (95% CI) |
|---|---:|---:|
| `faceoff` | 108660 / 56.564 ([56.244143675169184, 56.88703800104113]) | 73027 / 56.522 ([56.121517027863774, 56.921052631578945]) |
| `penalty` | 13630 / 7.095 ([6.944299843831338, 7.2498698594482045]) | 9556 / 7.396 ([7.2105263157894735, 7.577399380804954]) |
| `stoppage` | 84136 / 43.798 ([43.49921915668922, 44.12024986985945]) | 56253 / 43.539 ([43.14938080495356, 43.914860681114554]) |
| `goal` | 11638 / 6.058 ([5.952108276939094, 6.158771473191046]) | 8213 / 6.357 ([6.225232198142415, 6.489164086687307]) |
| `shot-on-goal` | 107451 / 55.935 ([55.555960437272255, 56.30609057782405]) | 74024 / 57.294 ([56.81888544891641, 57.750773993808046]) |
| `missed-shot` | 43961 / 22.884 ([22.626756897449244, 23.14003123373243]) | 29933 / 23.168 ([22.876160990712073, 23.479876160990713]) |
| `blocked-shot` | 51409 / 26.762 ([26.46694429984383, 27.041124414367516]) | 34851 / 26.974 ([26.646284829721363, 27.312693498452013]) |
| `giveaway` | 36263 / 18.877 ([18.503904216553877, 19.239458615304528]) | 23120 / 17.895 ([17.424148606811144, 18.354489164086687]) |
| `takeaway` | 25872 / 13.468 ([13.22280062467465, 13.722540343571056]) | 18288 / 14.155 ([13.8328173374613, 14.486068111455108]) |
| `shootout-complete` | 160 / 0.083 ([0.07027589796980739, 0.09682457053617907]) | 96 / 0.074 (None) |

### Forward-only team-rate check

The simple pregame rate comparator uses 2019/20 team goals/SOG for and against, 20-game league shrinkage, then updates after each completed 2021 date. Same-date outcomes are held back until every game that date has a forecast. It is a diagnostic baseline, not a fitted full game generator.

- Goal-count MSE: team-rate 3.0606; league-only 3.1851; paired difference -0.1245 (95% CI [-0.15094966413135297, -0.09894138359567078]).
- SOG-count MSE: team-rate 44.7368; league-only 48.4914; paired difference -3.7545 (95% CI [-4.314275420920349, -3.2153258186612996]).

## Penalty/manpower correction

The simulator’s regulation manpower calculation now counts active noncoincidental penalties per team. Equal opposing counts do not cancel merely because the net difference is zero. Matching penalties classified coincidental remain excluded. Overtime retains its separate manpower table. The independent Gate 1 validator remains a separate checker; its follow-up v0.3 extends the exact penalty subset to validate the 600-second misconduct exclusion without changing manpower or the gate threshold.

This bounded correction is grounded in the [2021–22 NHL Official Rules](https://media.nhl.com/site/asset/public/ext/2021-22/2021-22Rules.pdf) (pinned SHA-256 `17ef416dcb556f510df51efd45451e8d37da80da9e69488f78e3d8771228caa7`). It is a direct reference for 2021 development rules; do not transfer edition-sensitive details to earlier training seasons without checking those editions.

Observed opposing-penalty overlap candidates and their pre/post situation-code and shift-count checks are included in the JSON. The feed does not contain an explicit Rule 19 adjudication label or exact penalty-expiration event; estimated duration endpoints and return-to-shift times are therefore identified as estimates, not official expiration timestamps.

Strict source-evidence transitions (faceoff-delimited asymmetric state, no intervening goal, new penalty by the previously full side, then 4v4 with shift-count agreement before the prior nominal duration endpoint): 407 in training and 330 in 2021 development.

| Population | Game | Period | Prior penalty group | New opposing penalty group | Situation code before → restart | Shift skaters home/away before → after |
|---|---|---|---|---|---|---|
| 2019/20 | `2019020004` | REG 1 | MIN 05:47 (event 81) | MIN 06:47 (event 84) | `1541` → `1441` | [4, 5] → [4, 4] |
| 2019/20 | `2019020004` | REG 1 | MIN 09:52 (event 96) | MIN 09:59 (event 99) | `1451` → `1441` | [5, 4] → [4, 4] |
| 2019/20 | `2019020005` | REG 3 | MIN 11:03 (event 556) | MIN 11:49 (event 559) | `1541` → `1441` | [4, 5] → [4, 4] |
| 2019/20 | `2019020010` | REG 2 | MIN 16:00 (event 467) | MIN 17:12 (event 470) | `1541` → `1441` | [4, 5] → [4, 4] |
| 2019/20 | `2019020015` | REG 1 | MIN 18:52 (event 212) | MIN 19:07 (event 215) | `1541` → `1441` | [4, 5] → [4, 4] |
| 2021 | `2021020004` | REG 3 | MIN 09:57 (event 500) | MIN 10:05 (event 554) | `1451` → `1441` | [5, 4] → [4, 4] |
| 2021 | `2021020005` | REG 2 | MIN 09:31 (event 551) | MIN 10:06 (event 300) | `1451` → `1441` | [5, 4] → [4, 4] |
| 2021 | `2021020009` | REG 3 | MIN 09:21 (event 702) | MIN 11:19 (event 708) | `1451` → `1441` | [5, 4] → [4, 4] |
| 2021 | `2021020010` | REG 2 | MIN 06:47 (event 454) | MIN 07:34 (event 458) | `1451` → `1441` | [5, 4] → [4, 4] |
| 2021 | `2021020010` | REG 3 | MIN 18:23 (event 762) | MIN 18:27 (event 766) | `1541` → `1441` | [4, 5] → [4, 4] |

## Limits and decision

- A faceoff winner and subsequent event are recorded; continuous possession and unrecorded passes are not. Follow-up shots are sequence proxies, not possession truth.
- Shift charts identify player IDs and intervals; they do not expose line identity, coaching intent, exact bench policy, or fatigue state.
- Situation-code/shift agreement is computed only when positions are known and no active player track is duplicated; excluded and mismatching rows remain visible in the JSON.
- Official shot-event coordinates and types support conditional conversion analysis, but blocked-shot coordinates are not treated as release locations. The source does not observe shot opportunities that produced no event.
- Goalie identity on a target shot is a retrospective condition. It was not used as a pregame starting-goalie input.
- 2021 is development evidence, not an independent adoption test; 2022 remains excluded. No candidate is selected and no validity gate is changed.
- Structural accounting does not establish autonomous puck possession, tactical decisions, physical movement, or complete rule adjudication.

## Reproduction

```bash
python research/nhl/behavior-evidence/audit_behavior.py \
  --data-root /root/lp-data/nhl-fullframe-event-audit-2026-10-21 \
  --boxscore-root /root/lp-data/nhl-official-outcome-backfill-2026-10-20 \
  --db /root/legendarypicks/backend/data/picks.dev.db \
  --output research/nhl/behavior-evidence/results/nhl-behavior-evidence-event-state-v3-2026-10-27.json \
  --report docs/research/NHL-BEHAVIOR-EVIDENCE-EVENT-STATE-V3-2026-10-27.md
```

Elapsed audit time: 919.3 seconds. JSON and report content are emitted by the script; raw data are not copied into Git.
