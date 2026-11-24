# Gridiron and SLC consolidation: single-play research bridge

This is a single-play integration, not a full-game engine or a validated NFL forecast. Gridiron owns the autonomous play outcome. SLC supplies an eligible lineup and pre-snap situation, then reduces the result. Neither historical whole-play outcomes nor observed future tracking are passed to Gridiron. The two existing executors accept inside zone and slant-flat only. Existing Python retro execution is retained as a separate research baseline, not chosen as a second production engine.

## Reused components

| Component | Source | Current integration and limit |
| --- | --- | --- |
| Autonomous execution | Gridiron `engine/autonomous/` | Versioned `gridiron.autonomous-play.v1` and `gridiron.autonomous-result.v1`; pinned research commit `1800e843ccc59edb5f40ff090a2b4806f5ea630f`. One play per Node process. |
| Historical route offsets | Gridiron `engine/routes.js` | Nine existing offsets extracted from `engine/play.js`; four complete historical replays retain exact hashes. They are not yet consumed by the two fixed autonomous concepts. |
| Assignment description | Gridiron `engine/autonomous/assignments.js` | Validates composable offensive and defensive descriptions without outcome inputs. Existing executors do not execute custom descriptions and reject them explicitly. |
| Roster and participation | `roster_preflight.py`, `live_participation.py` | Frozen MIN–SF roster, eligibility checks and fitted offensive field selection. Defense is selected by eligible nickel depth-chart roles. Limited to MIN offense, SF defense and 11 personnel. |
| Playbook | Existing MIN 2025 team-season profile | Its manifest and file hashes are verified. Optional seeded run/pass selection uses the prior-season pass rate; the two supported concepts and formation are explicit, not team-specific concept selection. |
| SLC reduction | `reducer.py`, `game_stats.py` | Supported terminal events are reduced to downs, possession and player lines. Unsupported cases fail rather than inventing results. Clock ends at whistle; no between-play clock, period changes, kickoffs or full game. |
| Viewer | `retro_viewer.py`, `gridiron_viewer.py` | Existing overhead renderer consumes actual Gridiron frames and logged decisions for both concepts. It is a replay, not a playable game. Ball height is converted from meters to yards. |

Profiles use Gridiron's authored archetype defaults, not observed player-specific ratings. The frozen snapshot's verification classification is incomplete, which is disclosed in the viewer. This is a test of integration, not a validation of football realism. No new model fitting was performed.

## Execution and audit

Snapshot SHA-256 `c0e8e8874db5f90f8d7ba05d5e7c3e5afd2445abb6079f426e962bf9d6302c95`; participation SHA-256 `a31fc7150c107b3c15b11e2e643ace88828c033f8da3576b51348e4b5a677107`; playbook manifest SHA-256 `9d4749f817e97f4e3da0b6c5170eae0fa922d8b1b59d608ab4ce9dd990c2e929`. The bridge validates the individual playbook hash against that manifest.

On this host, seed 300001 at first-and-10 on the 50 produced an inside-zone tackle at -0.976 yards and a slant-flat completion and tackle at +33.102 yards. SLC floors the spot to whole yards, yielding -1 and +33 respectively. Both exact result records, including frames and events, matched on a second execution with the same input. One process invocation took roughly 0.3–0.5 seconds, including Node startup and JSON exchange; a single Python retro pass took roughly 0.008 seconds. This is a small local timing observation, not a benchmark. The baselines use different personnel and concepts and cannot establish relative football quality.

Gridiron's `yardline_100` input is used by its executor as an absolute field x coordinate; for this bridge's +x direction, it is `100 - SLC yardline_100`. The adapter refuses the opposite direction, inconsistent spots and game situations. It uses SLC's turnover-relative spot, and rejects unclassified fumbles, safeties, defensive touchdowns, clock-boundary crossings, and other unsupported results. Whole-yard reduction, passer/receiver/rusher lines, interception possession and a fourth-down incompletion have focused checks. Clock runoff between plays, scoring sequences, tackles and defensive player stats, spot behavior near end zones and period boundaries require more work.

The Gridiron prototype test had asserted a 2026 comparison field after its data were intentionally replaced with 2025-only team profiles. The separate Gridiron commit `cabed5a` aligns the assertion with those existing artifacts. No historical playbook data were modified.

## Remaining work

The composable assignment contract must be connected to actual route and defensive execution. The extracted historical offsets need an outcome-independent autonomous route executor before they can replace fixed concept logic. Full-game call sites must use the bridge and handle both teams, field direction, all legal plays, clock, possessions, scores and reconciled team and player statistics. A persistent process or embedded runtime is needed before evaluating batch throughput. The playable retro game must consume the shared execution interface; the current viewer is read-only. Simple behavior modes on the shared engine are not yet implemented. These are prerequisites for claiming a single shared full-game runtime.

## Executable assignments follow-up

The sections above describe the first bridge at commit `1800e843`. The follow-up pins Gridiron `62f6f6b0adeb588e4fc14b1ce5b89e295e876074`. `gridiron.assignments.v1` now executes on the existing passing executor when `concept` is `assigned`. Each eligible receiver consumes route geometry from `engine/routes.js`; offense assignments specify routes, protection and optional check-release, and defense assignments specify man, zone, rush or read. Executable calls require all 22 assignments. The caller's authored example compositions are slant-flat, curls and four verticals. They are examples assembled from shared primitives, not replacement team playbooks. Prior team run/pass selection remains available in the bridge; example concept selection is explicit.

Nine route tests hold the quarterback in the pocket with an explicit authored decision delay and use a non-rushing test defense. Each receiver reaches its first route break under live movement. Both man and zone are exercised against all three example compositions; a matched-seed check confirms different defender trajectories and QB read/throw records. These are behavioral fixtures, not evidence of NFL accuracy. The legacy unassigned `slant_flat` path and inside-zone remain intact as frozen regression baselines; their entire seed-1042 result hashes still match. Legacy slant-flat remains concept-specific code, so removal or translation of that baseline to assignments requires a separate parity decision.

Assigned calls default to `retro` observations of current relevant positions, with no gaze cone or delayed observation-memory requirement. The existing `detailed` mode remains available for comparisons. Neither mode is a fitted NFL perception model. `slc-server.js` provides a persistent sequential JSON-lines boundary; errors return named responses without stopping later requests. A warm 30-play local slant-flat/zone sample, including JSON transport and frame serialization but excluding rendering, completed in 1.989 seconds: approximately 15.1 plays per second. The reported engine portion was 1.293 seconds. This small single-host measurement is not a production throughput guarantee.

The overhead viewer generates all combinations of the three example concepts, both coverage sets, and supplied seeds in one persistent session. Its seed menu selects among the seeds supplied at generation time; it does not execute new seeds in the browser. It displays actual recorded frames and decisions. Full-game execution, period/clock handling, special teams, complete team and player statistics, opposite field direction, playable control, and SLC game-loop integration remain open. Fail-closed reducer limitations from the first bridge still apply.

### Profile and research audit

The frozen MIN–SF bridge supplies empty per-player profiles, so the physics engine uses authored positional archetypes. Those defaults are gameplay parameters, not player-specific NFL measurements. Source code and effects:

| Mechanism | Existing influence | Limitation |
| --- | --- | --- |
| Movement | `autonomous-run.js` maps SPD to maximum speed, ACC to propulsion, AGI to lateral capacity, STR to drive; `world.js` integrates the resulting physical parameters. | Mappings are authored sandbox rules, not measured player forces. The assigned-call test shows that changing SPD changes a receiver's route. |
| Decision speed and reading | Passing decisions run at a fixed 10 Hz in `passing.js`; assigned QB calls can specify an authored additional decision delay. PUR/AWR affect post-possession pursuit timing. | QB decision cadence and read quality are not fitted per player. Retro reads current relevant positions; detailed mode uses geometric visibility and delayed memory. |
| Throw and catch | Existing passer error uses `qb.R.ACC` before THN or AWR; receiver CTH/AWR and defender PRC affect catch and interception contests. | `ACC` is also the acceleration rating, so treating it as throw accuracy is a semantic collision. The contract does not accept THN. Preserve the legacy baseline and resolve this in a separately tested rating-contract change. |
| Blocking and contact | PBK/RBK, BSH/PMV/FMV and STR influence engagement or shedding; TAK, BTK/ELU and STR contribute to tackle resolution. | Authored rules and coefficients are uncalibrated. They are gameplay behavior, not inferred NFL physical forces. |
| Explicit physics fields | The input schema accepts mass, height, radius, vmax, f0, drive, alat and reach. | `scenarioFromCall` forwards only mass; the other accepted overrides are currently ignored. Do not claim they affect execution until implemented or rejected explicitly. |

See [retro Madden behavior research](RETRO-MADDEN-PLAYER-AI-V1-COMPLETE-2026-11-23.md), [Madden ratings research](MADDEN-RESEARCH-REPORT-2026-10-23.md), and [NHL multi-agent movement research](NHL-MULTI-AGENT-MOVEMENT-REPORT-2026-10-23.md). The latter is a movement comparison, not an NHL 95 game-code analysis. No NHL 95-specific research document was found in the searched local worktrees or commit subjects; no conclusions about that game's implementation are asserted here. The existing research cautions against treating complexity or historical video-game ratings as evidence of predictive NFL quality.
