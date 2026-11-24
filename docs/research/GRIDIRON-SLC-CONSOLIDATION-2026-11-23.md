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
