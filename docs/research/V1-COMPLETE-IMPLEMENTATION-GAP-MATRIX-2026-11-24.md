# V1 Complete implementation gap matrix

Audit base: `research/slc-v1-complete-2026-11-23` at `d250b3ab`. The requested
`68a019db` object is unavailable locally and from `origin`; the design in this
branch is the latest available copy. This matrix records the implementation
before the autonomous implementation milestones. The original audit-time gaps
are retained below; current implementation status is appended after the audit.

| Area | Existing work to reuse | V1 Complete gap |
| --- | --- | --- |
| Player data and ratings | Gridiron's `pipeline/ratings.py` and `data/ratings.json` build player profiles from nflverse identity, combine and prior NFL production. Gridiron maps SPD/ACC/AGI/STR to movement, AWR/PRC to decision cadence, THA to assigned-QB accuracy, PBK/RBK and BSH/PMV/FMV to blocking and shedding, TAK/BTK/ELU to tackle contests, CTH/CAR to catches, and PUR to pursuit. | The SLC bridge sends empty profiles. The 161 Gridiron profiles cover DEN/SEA, not the frozen MIN/SF roster, and do not preserve field-level source/as-of/uncertainty in the execution payload. Some accepted ratings are not used by assigned passing. There is no shared provenance-aware rating contract or live differentiated roster feed. |
| Madden ratings restriction | `derived-v6/madden_player_seasons.db` was queried read-only: 58,743 rows, releases 1992–2027, 1,531 rows for release 2027. `MADDEN-RESEARCH-REPORT-2026-10-23.md` records a failed strict audit, unverified release snapshots, unresolved within-release stints and unassessed source rights. | `V1-COMPLETE-DESIGN.md` says never use video-game ratings. Proposed revision: allow a Madden-derived value only as a clearly labeled gameplay input, never as an NFL measurement or calibrated forecast feature, and only after identity, release cutoff, stint and source-rights checks pass. The current rights and snapshot evidence do not pass, so the raw Madden database is not a V1 runtime source. |
| NFL-derived data | Gridiron's profile pipeline uses nflverse combine measures (including explicit imputed-drill flags) and production through 2025 plus 2026 weeks 1–5 for its DEN/SEA profile snapshot. The design inventories nflverse weekly Next Gen Stats passing, receiving and rushing aggregates for 2022–2026. | NGS are aggregate and eligibility-limited, not trajectories or complete individual coverage. Existing live inputs do not carry player-specific NFL evidence to the executor. Combine/production estimates need field-level provenance and cutoff validation before use. |
| Personnel and eligibility | `roster_preflight.py`, `v1_complete_roster.py`, `live_participation.py`, `pre_event.py`, and `formation_layer.py` select cutoff-valid players and personnel before call selection. SLC has roster and participation artifacts. | Current Gridiron bridge is a frozen MIN offense / SF defense, 11-personnel example. No two-team game roster rotation or validated special-teams/substitution path is connected to live execution. |
| Coaching and playcalling | `slc_playcall.py`, `playbook_prior.py`, `formation_layer.py`, `timeout_decision.py`, `game_state.py`, and existing playcall research contain team/season run-pass, personnel, formation, timeout, fourth-down, tempo and try decisions. | These decisions primarily feed the statistical sampler. No live coach profile selects executable concepts and clock actions. Tendencies are not separated from decision quality, and decision quality is not yet evaluated against the expected value of the alternatives available at that moment. |
| Playbooks and assignments | Team-season playbook manifests and hashes are available. Gridiron has route geometry, `gridiron.assignments.v1`, 22-role validation and executable assigned passing with route, block, man, zone, rush and read tasks. Its inside-zone executor also assigns all 22 internally. | Team playbook evidence is not an executable diagram. Only inside-zone and a narrow set of pass concepts execute; custom 22-player assignments are not accepted for runs. Passing assignments do not yet cover the whole SLC game. No executable punt, kick, return, try or field-goal play exists. |
| Situational reads and movement | Gridiron `passing.js`, `autonomous-run.js`, `perception.js` and `retro-cadence.js` provide live reads, role behavior, bounded movement, route/block/tackle interactions and event traces. Input validation rejects supplied final outcomes and future tracking. The existing overhead viewer replays actual frames. | These behaviors are scoped to individual run/pass executors. SLC's Python live-field path uses assigned constant velocity and supplied QB/catch policies. Read coverage and assignment execution are not verified across every role and event, and play outcomes are not yet integrated into a game loop. |
| Rules, clock and statistics | SLC already has `reducer.py`, `game_state.py`, `game_stats.py`, `e1_drive.py` and `e2_reference.py`. The game-state engine covers possessions, down/distance, scoring, kickoffs, periods, timeouts, tries and overtime; reducers/statistics reconcile play, player and team records. | The full-game engine obtains plays, clocks, kicks, tries and several transitions from historical samples. `gridiron_bridge.py` handles one live play and rejects fumbles, safeties, defensive touchdowns, boundary/clock crossings and other events. `gridiron_drive.py` accepts caller-supplied next-snap clocks and is not autonomous. Penalties fail closed. Live events need to enter the existing rules/accounting path without sampling historical outcomes or duplicating rules. |
| Shared event contract | The V2 event-expansion worktree is preparing the shared event contract and rule/stat expansion; see its uncommitted inventory and `ceg_contract.py`. | Contract version and enforcement behavior are still under coordination. V1 integration must use the agreed `ceg-play-2` event, turnover geometry, defensive-score and penalty semantics. |

## Rating record proposal

Store each player attribute as a typed record: `name`, `value`, `native_scale` or
`units`, `source_class` (`madden_derived`, `nfl_derived`, `estimated`,
`authored`), `source_id`, `source_row_hash`, `as_of`, `identity_confidence`,
`sample_support`, `uncertainty`, and the gameplay behavior that consumes it.
Keep measured combine values in their native physical units; do not disguise
them as 0–99 NFL skill ratings. Runtime validation must reject future-dated,
unresolved or unsupported values. Authored fallbacks remain explicit.

## Delivery focus

1. Execute explicit assignments for every player in each supported scrimmage
   play and test each intended rating effect.
2. Convert actual Gridiron events into the shared SLC event contract and reuse
   the existing reducer/game-state/statistics path.
3. Add live rules-backed outcomes for turnovers, returns, scoring, kicks,
   penalties, dead-ball clocks and overtime, with no historical outcome or
   caller-supplied next-snap state.
4. Run the existing headless engine and viewer from the same recorded events.

## Current implementation status — 2026-11-25

| Area | Reused and now integrated | Remaining V1 gap |
| --- | --- | --- |
| Player ratings | The LP bridge supplies player-specific estimated NFL ratings to Gridiron; mapped ratings affect movement, reads, throwing, blocking, catching and tackling. Special-teams execution requires named, rated players in all 22 unit roles. | The available ratings file has no matching profiles for the frozen MIN/SF roster, so production runs fail with named player IDs until a provenance-safe feed is provided. Runtime rating records still need typed source/as-of/uncertainty provenance and broader independent effect checks. Madden data remains excluded under the documented restriction pending identity, cutoff and rights review. |
| Personnel and coaching | Both frozen teams use eligible rosters; team-season tendencies inform live run/pass selection, fourth-down EV, timeouts and tries. Punt and kickoff units now select eligible specialists, returners and ten-player support units. | Other substitution and formation variants remain. Decision quality still needs calibration against expected value of the live alternatives. |
| Plays and assignments | Supported inside-zone, assigned pass, punt and kickoff plays execute all 22 roles through bounded movement and live interactions; generated outcomes flow to SLC. The overhead viewer receives the same live trajectory frames. | More executable formations and team concepts remain. Field-goal/try and blocked-kick execution do not yet run 22 assigned players. |
| Rules and statistics | `ceg-play-2` scrimmage outcomes, DPI, selected pre-snap/live fouls, live punts, kickoff returns, fair catches, muffs/recoveries, touchbacks, punt OOB and return scores pass through typed adapters into E1, game state and reconciled stats. Safety free kicks use the correct scoring/restarting teams and y100=80 spot. Non-counting penalties suppress play stats; terminal penalty outcomes reconcile flags and possession. | Named blockers remain for kickoff OOB/downed-ball enforcement, blocked punt/field goal outcomes, onside-kick generation, field-goal returns, end-of-period free kicks, and some kick fumble/return transitions. Autonomous field-goal and try outcomes still lack complete 22-player execution/trajectory evidence. |
| Shared kick geometry | The LP copy of `ceg-play-2` now uses the kicking team's frame consistently for punt catches, returns, touchbacks and recoveries. | The V2 branch maintainer has been notified; the shared branch contract still needs this correction before both branches freeze the same semantics. |
| Acceptance | 238 focused LP contract, rules, stats, autonomous-game and lifecycle tests pass. Gridiron special-teams/server/assignment/acceptance/contact/result checks pass. Generated punt-return TD and out-of-bounds punt events have been exercised through the real Gridiron session, SLC adapter and game lifecycle; lifecycle cases cover return scoring, safety restart, touchback clock, period expiry, and named refusal for blocked punts. | Still required: production roster ratings, real full-game autonomous 22-player evidence including tries/field goals, an autonomous game to completion with reconciled statistics, complete supported-event coverage, a larger all-role assignment sweep, and a behavioral/statistical batch. |

Punts and kickoffs now use live 22-player Gridiron execution and named
ceg-play-2 facts through the SLC lifecycle. Outcomes that lack a live executor
or a complete rules transition remain explicit named blockers; they are not
silently replaced with sampled outcomes. The frozen-roster rating coverage and
full-game try/field-goal execution are still release blockers.
