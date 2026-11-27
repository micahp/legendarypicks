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
| Shared event contract | Versioned `ceg-play-2` and additive `ceg-play-3` define typed scrimmage, possession, kick, scoring, return and penalty facts. The V1 adapter maps live Gridiron outcomes into these contracts and the existing SLC reducer/statistics path. | Some event families and rule details remain unsupported. The adapter must continue to reject missing or contradictory facts with named blockers rather than infer an unobserved outcome. |

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

## Current implementation status — 2026-11-27

| Area | Reused and now integrated | Remaining V1 gap |
| --- | --- | --- |
| Player ratings | The LP bridge supplies game-specific, provenance-checked estimated ratings for the frozen game rosters; mapped ratings affect movement, reads, throwing, blocking, catching and tackling. | Rating quality and behavioral calibration remain open. Madden data remains excluded under the documented restriction pending identity, cutoff and rights review. |
| Personnel and coaching | Both frozen teams use eligible rosters; team-season tendencies inform live run/pass selection, fourth-down EV, timeouts and tries. Punt and kickoff units now select eligible specialists, returners and ten-player support units. | Other substitution and formation variants remain. Decision quality still needs calibration against expected value of the live alternatives. |
| Plays and assignments | Supported inside-zone, assigned pass, punt and kickoff plays execute all 22 roles through bounded movement and live interactions; generated outcomes flow to SLC. The overhead viewer receives the same live trajectory frames. | More executable formations and team concepts remain. Field-goal/try and blocked-kick execution do not yet run 22 assigned players. |
| Rules and statistics | Typed scrimmage and kick events flow through the SLC reducer and reconciled statistics. Quarter 5 is explicitly represented as overtime in the Gridiron request schema. Timeout watchdog diagnostics retain the exact call, result and terminal state; the 19 saved timeout plays completed after the GridIron progress and loose-ball pursuit fixes. Fumble geometry keeps continuous displacement separate from rounded statistical yards. Goal-line interception returns, defensive fumble return touchdowns and retained offensive fumble touchdowns now use the event's possession and dead-ball facts. | The 30-game replay did not exercise overtime or every special-teams branch. Broader kick and penalty coverage remains a separate acceptance gate; field-goal and try execution still lack complete 22-player trajectory evidence. |
| Acceptance | 257 focused LP tests pass. The final retrospective seed cohort covers 2026_12_CHI_DET, 2026_12_PHI_DAL and 2026_12_KC_BUF with seeds 300021–300030. All 30 unique games completed legally with reconciled player/team statistics; KC–BUF seed 300030's initial contract failure is preserved alongside its passing replay on the corrected contract. Runtime pins: LP `e0efbaad` for the corrected seed, preceding runtime `71108ff7` for the other 29; GridIron `f1adc6777fa415abf72c29df96ca2e3c7d90b942`. Exact artifacts and hashes are in `V1-COMPLETE-THANKSGIVING-SEED-FAILURES-2026-11-26.jsonl`. | This retrospective cohort proves completion and accounting for these inputs only. It does not establish broad football realism, overtime completion, event coverage beyond exercised cases, or forecasting readiness. |

Punts and kickoffs use live 22-player Gridiron execution and typed facts through
the SLC lifecycle. Unsupported outcomes remain explicit blockers; they are not
silently replaced with sampled outcomes. The previously observed full-game
timeouts and goal-line/fumble transition blockers are resolved for the replayed
cases. Full-game try/field-goal execution and broader event coverage remain open.
