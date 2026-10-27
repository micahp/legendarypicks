# NHL Behavior Evidence and Rules Coverage Audit

- **Date:** 2026-10-26
- **Branch:** `research/nhl-behavior-evidence-2026-10-26`
- **Base:** `9501768f1410484d8be235fe0700f710f5ec189e`
- **Purpose:** research-only source audit and conditional behavior diagnostics; no adoption or gate decision.

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
| `game_context` | 3 | `"current roster snapshots"` | `"\u2014"` |
| `player_game_logs` | 54727 | `{"2026": 51143, "2027": 3584}` | `{"nhle.com": 51143, "nhle.com:gamecenter/boxscore": 3584}` |
| `player_source_ids` | 2014 | `"current roster snapshots"` | `{"nhle.com": 1318, "rotowire": 696}` |
| `player_stats` | 1831 | `{"2026": 1038, "2027": 793}` | `{"nhle.com": 1831}` |
| `players` | 1431 | `"current roster snapshots"` | `"\u2014"` |
| `roster_memberships` | 638869 | `"current roster snapshots"` | `"\u2014"` |
| `roster_snapshots` | 809 | `{"2027": 809}` | `{"espn_site_roster": 1, "nhle.com:roster": 808}` |
| `team_game_results` | 2812 | `{"2026": 2624, "2027": 188}` | `{"espn_site_api:scoreboard+summary": 2624, "nhle.com:club-schedule-season+gamecenter/boxscore": 188}` |
| `team_game_stats` | 2812 | `"current roster snapshots"` | `{"espn_site_api:scoreboard+summary": 2624, "nhle.com:gamecenter/right-rail+landing": 188}` |

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
| Situation-code/shift matches among unambiguous decodable rows | 533863/573676 (93.1%) | 372415/390867 (95.3%) |
| Situation-code rows excluded (unknown positions / duplicate active tracks) | 0 / 4892 | 0 / 4942 |

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

### Conditional scoring diagnostics

Parameters were fit on 2019/20 only, with 20 parent-equivalent observations for shrinkage and a parent fallback below 100 training opportunities. The 2021 score table is a once-scored development diagnostic. Shot-type/location/goalie scores condition on recorded target events and are not full-game simulation inputs.

| 2021 event model | N | Mean Brier / log loss | Paired 95% CI of loss difference vs parent |
|---|---:|---|---|
| `faceoff:league_50` brier | 73027 | 0.25000 | — |
| `faceoff:league_50` log_loss | 73027 | 0.69315 | — |
| `faceoff:team_rate` brier | 73027 | 0.24954 | — |
| `faceoff:team_rate` log_loss | 73027 | 0.69222 | — |
| `faceoff_shot:parent` brier | 73027 | 0.23195 | — |
| `faceoff_shot:parent` log_loss | 73027 | 0.65661 | — |
| `faceoff_shot:strength` brier | 73027 | 0.22025 | — |
| `faceoff_shot:strength` log_loss | 73027 | 0.63030 | — |
| `goal_all` brier | 81660 | 0.08841 | — |
| `goal_all` log_loss | 81660 | 0.32071 | — |
| `goal_by_goalie` brier | 81660 | 0.08377 | — |
| `goal_by_goalie` log_loss | 81660 | 0.30770 | — |
| `goal_by_shot_type` brier | 81660 | 0.08783 | — |
| `goal_by_shot_type` log_loss | 81660 | 0.31773 | — |
| `goal_by_strength` brier | 81660 | 0.08366 | — |
| `goal_by_strength` log_loss | 81660 | 0.30647 | — |
| `goal_by_zone` brier | 81660 | 0.08829 | — |
| `goal_by_zone` log_loss | 81660 | 0.31994 | — |
| `sog_all` brier | 146319 | 0.24664 | — |
| `sog_all` log_loss | 146319 | 0.68642 | — |
| `sog_by_shot_type` brier | 146319 | 0.14665 | — |
| `sog_by_shot_type` log_loss | 146319 | 0.43628 | — |
| `sog_by_strength` brier | 146319 | 0.24581 | — |
| `sog_by_strength` log_loss | 146319 | 0.68466 | — |
| `sog_by_zone` brier | 146319 | 0.15855 | — |
| `sog_by_zone` log_loss | 146319 | 0.48236 | — |
| `faceoff_shot_strength` paired delta | — | Brier [-0.01242617136473595, -0.011022984157202764]; log loss [-0.02793141145444189, -0.02473123618126738] | game-cluster percentile bootstrap |
| `faceoff_team_rate` paired delta | — | Brier [-0.00057028792345451, -0.0003559059543315479]; log loss [-0.0011406932537547654, -0.0007068164178684055] | game-cluster percentile bootstrap |
| `goal_by_goalie` paired delta | — | Brier [-0.005030983401939276, -0.0042360701783642485]; log loss [-0.014167608072927107, -0.01183306183476468] | game-cluster percentile bootstrap |
| `goal_by_shot_type` paired delta | — | Brier [-0.0006897084289797101, -0.000466126867745123]; log loss [-0.003513052495885627, -0.002428935597330373] | game-cluster percentile bootstrap |
| `goal_by_strength` paired delta | — | Brier [-0.00513357434556698, -0.0043612640155949595]; log loss [-0.015418993905385647, -0.013137519347743376] | game-cluster percentile bootstrap |
| `goal_by_zone` paired delta | — | Brier [-0.00015216917296942412, -7.84946666944758e-05]; log loss [-0.0010455730272868613, -0.00047029735247994253] | game-cluster percentile bootstrap |
| `sog_by_shot_type` paired delta | — | Brier [-0.10110274324357585, -0.09892691485333951]; log loss [-0.2528035501776702, -0.2475052548555866] | game-cluster percentile bootstrap |
| `sog_by_strength` paired delta | — | Brier [-0.0009667097713350614, -0.0007116450918388251]; log loss [-0.0020361798237262807, -0.0014947600464159105] | game-cluster percentile bootstrap |
| `sog_by_zone` paired delta | — | Brier [-0.08919536228187, -0.08697505168131597]; log loss [-0.20677584965126938, -0.20106758385085755] | game-cluster percentile bootstrap |

### Event rates by observed game state

Train-only rates use shift-derived team-minute exposure. The listed conditional rates use one context axis at a time; groups under 100 training events fall back to the unconditioned parent. The 2021 comparison conditions on the observed shift exposure and in-game state, so it is a diagnostic and not a pregame game forecast. Full support, sparse cells, and cluster intervals are in the JSON.

| Event family | Context | Train events / team-minutes | Frozen train rate / 60 team-min | 2021 observed / expected | Observed/expected | 2021 mean game Poisson deviance delta vs parent |
|---|---|---:|---:|---:|---:|---|
| `attempt` | `all=all` | 213396 / 233368.7 | 54.8649 | 146319 / 143373.5 | 1.021 | 0.0000 |
| `attempt` | `period=OT` | 2776 / 2848.7 | 58.3127 | 1750 / 1703.2 | 1.027 | -0.0428 |
| `attempt` | `period=REG` | 210620 / 230520.0 | 54.8209 | 144569 / 141657.1 | 1.021 | 0.0036 |
| `attempt` | `score=tied` | 73874 / 80469.3 | 55.0801 | 51668 / 50669.0 | 1.020 | -0.0067 |
| `attempt` | `strength=4v5` | 4587 / 18077.8 | 15.6329 | 3184 / 3078.0 | 1.034 | -5.7827 |
| `attempt` | `strength=5v4` | 26596 / 18077.8 | 87.9276 | 17858 / 17312.2 | 1.032 | -2.9678 |
| `attempt` | `strength=5v5` | 171369 / 186341.6 | 55.1758 | 117653 / 115600.0 | 1.018 | -0.0208 |
| `attempt` | `time=<=1m` | 12986 / 10511.7 | 73.9249 | 8726 / 8776.5 | 0.994 | -0.5248 |
| `attempt` | `time=>10m` | 105321 / 116627.7 | 54.1902 | 72066 / 70808.2 | 1.018 | 0.0157 |
| `faceoff_win` | `all=all` | 108660 / 233368.7 | 27.9369 | 73027 / 73005.0 | 1.000 | 0.0000 |
| `faceoff_win` | `period=OT` | 1131 / 2848.7 | 24.0006 | 724 / 701.0 | 1.033 | -0.0361 |
| `faceoff_win` | `period=REG` | 107529 / 230520.0 | 27.9872 | 72303 / 72319.0 | 1.000 | -0.0001 |
| `faceoff_win` | `score=tied` | 36516 / 80469.3 | 27.2346 | 25182 / 25053.5 | 1.005 | -0.0076 |
| `faceoff_win` | `strength=4v5` | 8623 / 18077.8 | 28.6127 | 5678 / 5633.6 | 1.008 | -0.0041 |
| `faceoff_win` | `strength=5v4` | 10344 / 18077.8 | 34.2658 | 6881 / 6746.6 | 1.020 | -0.2467 |
| `faceoff_win` | `strength=5v5` | 84058 / 186341.6 | 27.0748 | 56382 / 56725.0 | 0.994 | -0.0602 |
| `faceoff_win` | `time=<=1m` | 5795 / 10511.7 | 33.0246 | 3980 / 3920.7 | 1.015 | -0.0957 |
| `faceoff_win` | `time=>10m` | 56268 / 116627.7 | 28.9371 | 37775 / 37810.9 | 0.999 | -0.0338 |
| `goal` | `all=all` | 11296 / 233368.7 | 2.9042 | 8003 / 7589.4 | 1.054 | 0.0000 |
| `goal` | `period=OT` | 290 / 2848.7 | 5.9688 | 183 / 174.3 | 1.050 | -0.3044 |
| `goal` | `period=REG` | 11006 / 230520.0 | 2.8651 | 7820 / 7403.3 | 1.056 | 0.0077 |
| `goal` | `score=tied` | 3722 / 80469.3 | 2.7765 | 2617 / 2554.2 | 1.025 | 0.0003 |
| `goal` | `strength=4v5` | 325 / 18077.8 | 1.0975 | 210 / 216.1 | 0.972 | -0.2349 |
| `goal` | `strength=5v4` | 227 / 18077.8 | 0.7756 | 163 / 152.7 | 1.067 | -0.3164 |
| `goal` | `strength=5v5` | 10200 / 186341.6 | 3.2804 | 7274 / 6872.8 | 1.058 | -0.1514 |
| `goal` | `time=<=1m` | 910 / 10511.7 | 5.1706 | 637 / 613.9 | 1.038 | -0.1523 |
| `goal` | `time=>10m` | 5264 / 116627.7 | 2.7101 | 3721 / 3541.2 | 1.051 | 0.0058 |
| `penalty` | `all=all` | 13630 / 233368.7 | 3.5043 | 9556 / 9157.5 | 1.044 | 0.0000 |
| `penalty` | `period=OT` | 100 / 2848.7 | 2.1670 | 66 / 63.3 | 1.043 | -0.0528 |
| `penalty` | `period=REG` | 13530 / 230520.0 | 3.5214 | 9490 / 9099.4 | 1.043 | -0.0031 |
| `penalty` | `score=tied` | 4111 / 80469.3 | 3.0698 | 3004 / 2823.9 | 1.064 | -0.0032 |
| `penalty` | `strength=4v5` | 10154 / 18077.8 | 33.3898 | 6801 / 6574.2 | 1.035 | -14.6578 |
| `penalty` | `strength=5v4` | 289 / 18077.8 | 0.9854 | 277 / 194.0 | 1.428 | -0.2242 |
| `penalty` | `strength=5v5` | 790 / 186341.6 | 0.2879 | 697 / 603.1 | 1.156 | -7.7351 |
| `penalty` | `time=<=1m` | 941 / 10511.7 | 5.3519 | 724 / 635.4 | 1.139 | -0.1350 |
| `penalty` | `time=>10m` | 6182 / 116627.7 | 3.1837 | 4288 / 4160.0 | 1.031 | -0.0116 |
| `sog` | `all=all` | 118203 / 233368.7 | 30.3905 | 81660 / 79416.6 | 1.028 | 0.0000 |
| `sog` | `period=OT` | 1796 / 2848.7 | 37.5048 | 1140 / 1095.5 | 1.041 | -0.2301 |
| `sog` | `period=REG` | 116407 / 230520.0 | 30.2995 | 80520 / 78293.9 | 1.028 | 0.0098 |
| `sog` | `score=tied` | 41038 / 80469.3 | 30.5968 | 28891 / 28146.5 | 1.026 | -0.0088 |
| `sog` | `strength=4v5` | 3390 / 18077.8 | 11.4487 | 2334 / 2254.2 | 1.035 | -2.2512 |
| `sog` | `strength=5v4` | 13947 / 18077.8 | 46.1261 | 9516 / 9081.9 | 1.048 | -1.3535 |
| `sog` | `strength=5v5` | 95121 / 186341.6 | 30.6255 | 65774 / 64164.2 | 1.025 | -0.0221 |
| `sog` | `time=<=1m` | 6981 / 10511.7 | 39.7497 | 4751 / 4719.2 | 1.007 | -0.2544 |
| `sog` | `time=>10m` | 58702 / 116627.7 | 30.2016 | 40295 / 39463.3 | 1.021 | 0.0068 |

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

The simulator’s regulation manpower calculation now counts active noncoincidental penalties per team. Equal opposing counts do not cancel merely because the net difference is zero. Matching penalties classified coincidental remain excluded. Overtime retains its separate manpower table. The independent Gate 1 validator remains separate and unchanged.

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
  --output research/nhl/behavior-evidence/results/nhl-behavior-evidence-2026-10-26.json \
  --report docs/research/NHL-BEHAVIOR-EVIDENCE-AND-RULES-COVERAGE-2026-10-26.md
```

Elapsed audit time: 890.7 seconds. JSON and report content are emitted by the script; raw data are not copied into Git.
