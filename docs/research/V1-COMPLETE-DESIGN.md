# V1 Complete: football execution design

Starting point: `research/slc-v1-pure-2026-11-21` at `8a99925f`. This document defines acceptance gates, not completed features. V1 Complete has a distinct identity from V1 Pure and from participation/RNG V2 and semantic strength V2.

## Status and objective — 2026-11-26

This document restores the Liquid AI-inspired design from [LP 68a019db](https://github.com/micahp/legendarypicks/blob/68a019db/docs/research/V1-COMPLETE-DESIGN.md) to the implementation branch and records the research rationale and proposed experimental protocol. It is a design and acceptance contract, not a claim that all features are implemented. The ultimate goal is to test whether causal, physics-driven simulation can match or improve on statistical SLC baselines and sportsbook forecasts on cutoff-valid held-out games. Football plausibility, legality, computational cost and forecast skill are separate measurements. Early Madden is a behavioral reference, not statistical ground truth or a source of player ratings.

## Boundaries

V1 Complete is a simple, autonomous 11-on-11 football simulation in the spirit of early Madden: explicit player ratings, coach profiles, eligible personnel, playbook formations and individual assignments drive live execution rather than a sampled historical play outcome. A play proceeds through personnel selection, formation and play call, snap, live ball, whistle and next snap. Coaches choose personnel, calls and situational strategy using only information available at the decision; the quality of a decision is evaluated separately from its eventual execution and outcome. All 22 players, not just the quarterback, have a Liquid AI-inspired read layer implemented with small, role- and assignment-specific finite-state machines: observe relevant current field and ball cues, interpret the situation, maintain or change behavior, and move toward the appropriate assignment or reaction target using simple bounded 2D movement. Ratings affect specific abilities and decisions, including movement, recognition, blocking, throwing, catching and tackling. The ball has x, y and height; outcomes emerge from player movement, reachability, local interactions and seeded uncertainty, not from a preselected result, target, final spot or historical play. The shared football rules and statistics engine resolves the resulting events. Animations, sophisticated perception and full-body collision physics are not prerequisites.

Participants must come only from the cutoff-valid resolved roster. Exclude Out, inactive, reserve, and unelevated practice-squad players, including provisional projected elevations without an actual elevation. Preserve IDs, cutoff, sources and hashes. Missing eligibility or a required role blocks the affected run with a named reason. Use the existing roster resolver and preflight from `fix/roster-preflight-2026-11-22` after reconciling its dependencies; its provisional projected-elevation behavior must not override this stricter rule. Validate all selection paths, including special teams and substitutions.

Player inputs must be derived from actual observations, with source, as-of cutoff, sample support and uncertainty recorded. Never use video-game ratings. Missing or weak evidence must be explicit; a default is not a measured player rating. Do not use future observations in historical simulations. Preserve full-game rules and overtime, and keep football validity separate from evidence verification.

## Historical and technical evidence

Liquid AI is EA's product terminology, not a recovered algorithm or a claim that EA used our exact state machines. The following sources motivate the architecture; distinguish documented behavior, independent techniques and proposed implementation.

| Source | Documented or useful contribution | Limit |
| --- | --- | --- |
| Tom Netsel, interview with original Madden programmer Robin Antonick, [COMPUTE!'s Gazette, May 1990, pp. 22–24](https://www.commodore.ca/gallery/magazines/gazette/Compute-Gazette-Issue-83.pdf) | Individual assignments, player skill ratings, local matchups and conditional running-back behavior (check a blitz, otherwise release into a route). | Contemporary interview, not engine source. Page images were not successfully inspected in the prior research session. |
| Madden NFL 98 (1997) contemporary product descriptions and previews; Madden Football 64 descriptions | Liquid AI terminology, relative positioning, reactive defensive adjustments, receiver leading and timing. | Marketing and press descriptions; no recovered proprietary decision logic. Original preview bibliography remains to be independently recovered and archived. |
| [Madden NFL 2004 developer interview, August 2003](https://www.tweaktown.com/gaming/1805/madden_nfl_2004_interview/index.html) | CPU QB scrambling when receivers are covered, improved defensive movement, rating-sensitive interaction and catch retention. | Developer descriptions, not formulas or proof of NFL realism. |
| Craig Reynolds, [Steering Behaviors for Autonomous Characters, GDC 1999](https://www.red3d.com/cwr/papers/1999/gdc99steer.html) | Separates action selection, steering and locomotion; reusable seek, pursuit, path-following, arrival and evasion primitives. | Independent game-AI architecture, not evidence that EA used this implementation. |
| [Rush 2005 open-source distribution](https://sourceforge.net/projects/rush2005/) and Rush 2008 research | A simplified football simulation suitable for studying assignments, local interactions, player skills and multi-agent behavior. | Rush 2008 used an eight-player variant; source audit and license verification are outstanding before any reuse. |
| [Learning Hierarchical Skills for Game Agents from Video of Human Behavior, IJCAI 2009](https://www.cs.cmu.edu/~nli1/Published%20Papers/IJCAI09%20StrucK-LiN_Learning%20Hierarchical%20Skills%20for%20Game%20Agents%20from%20Video%20of%20Human%20Behavior.pdf) | Football behavior learning from video with Rush as an execution environment. | Not demonstrated NFL forecasting skill. |
| [Improving Offensive Performance Through Opponent Modeling, AIIDE 2009](https://ial.eecs.ucf.edu/pdf/Sukthankar-AIIDE2009.pdf) | Recognizing opposing plays from movement, adapting offensive decisions. | Later-stage research reference, not required for initial baseline. |
| [A Monte Carlo Approach for Football Play Generation, 2010](https://stars.library.ucf.edu/scopus2010/405/) | Coordinated football play generation and focusing computation on consequential players. | Do not import search complexity without measured benefit. |
| [A Real-Time Opponent Modeling System for Rush Football, IJCAI 2011](https://ijcai.org/proceedings/2011/412) | Online play recognition and plan modification. | Simulator results are not NFL validation. |

Research conclusion: authored assignments + reactive individual decisions + simple bounded movement + local skill-dependent interactions are a credible starting point. We do not have EA's original Liquid AI source, patents establishing its exact design, or measured emulator traces. No claim of faithful EA reproduction is warranted.

Reference games for future black-box experiments: early John Madden Football, Madden 98, Madden 2003, Madden 2004 and Madden 2005. Use legally acquired games and reproducible CPU-controlled scenarios. Record platform/version, rosters, settings, play diagrams, seed or save-state where available, and video/frame timing. Measure route timing, QB release timing, receiver and defender reaction, pursuit angles, blocking duration and skill sensitivity. Use NFL observations separately to calibrate/validate realism. Do not transfer proprietary game ratings into forecasts.

## Proposed executable architecture

1. Coaching layer: eligible personnel -> formation -> authored play and defensive scheme -> validated per-player assignments. A coach evaluates a decision before its outcome; no realized-result inputs. Team tendency priors may guide calls, but a run/pass rate alone is not a team playbook.
2. Player read layer: each of 22 controllers observes relevant present or past cues, interprets them in the context of its assignment and phase, and maintains or changes its state. Small role-specific finite-state machines are the proposed baseline, not a recovered EA algorithm. No future positions, realized results, or privileged exact landing point unless explicitly labeled as a diagnostic oracle.
3. Steering: shared seek, arrive, follow route, mirror, pursue, evade, contain, protect and intercept primitives translate intent into bounded motion commands. Separate decisions from steering updates and physics integration. Preserve distinct assignment and reaction targets.
4. Locomotion/world: shared position, velocity, bounded acceleration and ball trajectory with height. Start with the minimum sufficient interaction model; rendering and full-body contact physics are not prerequisites. Numerical step size must not create extra probability trials.
5. Interaction resolver: local reach, timing and player skills govern attempts. Track a player's continuous ball-contact episode independently of other candidates. Re-arm only after a genuinely distinct interaction; explicitly test exit/re-entry and tips. Use seeded draws for distinct decisions/interactions, not per-frame outcome sampling.
6. LP rules and statistics: authoritative clock, possession history, downs, scoring, penalties in supported scope, and statistical attribution. Gridiron produces causal facts; LP validates and applies them. Maintain versioned contracts, exact engine pin, separate raw geometry and rounded stat yards, and named failures rather than silently falling back to historical results.

Controller trace contract (proposed): player ID and role, assignment, phase, decision time, permitted observations and provenance, current state, guard/transition reason, chosen action, target, relevant ratings, next decision time, and interaction/event IDs. A decision should be reproducible from information available at that instant. Record full traces only for bounded diagnostics; use compact summaries for batches.

### Position-level controller baseline

These are proposed state/guard families, to be refined against football evidence. Implement shared primitives rather than 22 unrelated controllers.

| Role | Initial task | Relevant live cues | State transitions / behaviors | Ability dimensions to validate |
| --- | --- | --- | --- | --- |
| QB | Snap, handoff or dropback | Route progress, pressure, coverage, legal throw state | receive -> handoff or drop/read -> wait, throw, scramble, throwaway; sack is an external interaction | throwing accuracy, recognition, movement, release timing |
| RB | Run, protection or route | Gap availability, assigned rush threat, ball, pursuit | mesh -> carry/read/cut; check -> block or release -> catch opportunity | burst, change of direction, vision, carrying, blocking, catching |
| WR | Route | Landmark, leverage, ball release and trajectory | stem -> break/settle -> adjust to ball -> contest -> run/block | speed, acceleration, cuts, recognition, catching |
| TE | Route or block | Rush, route, ball, assignment | protect/engage/release or route -> catch/block | movement, blocking, catching |
| C | Snap and block | Assigned defender, gap and pocket | snap -> engage -> anchor/assist/recover | snap, strength, footwork, blocking |
| G | Protection or run block | Gap, assigned threat, teammate leverage | step -> engage/seal/double/pull -> recover | strength, acceleration, blocking |
| T | Edge protection or run block | Edge rush, pocket, assignment | set -> mirror/anchor/engage -> recover | lateral movement, strength, blocking |
| DT | Rush or gap | Blocker, gap, backfield, ball | penetrate/hold -> shed -> pursue/finish | strength, block defeat, pursuit, tackle |
| DE/edge | Rush or contain | QB/RB movement, edge, blocker | rush/contain -> shed -> pursue/finish | burst, leverage, block defeat, tackle |
| LB | Gap fit, blitz or coverage | Backfield action, routes, ball | read -> fill/rush/cover -> break/pursue/contest | recognition, pursuit, movement, tackle |
| CB/NB | Man or zone | Receiver leverage, route break, throw | align -> mirror/zone -> break on ball -> contest/pursue | speed, cuts, recognition, ball skills |
| S | Deep or underneath zone/man | Routes, QB, ball, leverage | hold/rotate -> close -> contest/tackle | recognition, range, ball skills, tackle |
| Special teams | Kick, protect, cover, return | Ball flight, legal recovery state, blockers, return lanes | role-specific release/coverage/field/return/recovery/whistle | kicking, movement, catching, pursuit |

Every supported assignment needs a valid initial state, allowed transitions, terminal/refusal handling, and evidence for each ability mapping. Role-level tests must cover guard behavior, reaction timing, rating sensitivity, and no access to future events. Keep unsupported assignments explicit. Do not equate a decision trace label with actual execution.

## Gates and acceptance tests

1. **Clock.** No sampled clock runoff. Advance live time from the actual play timeline; advance dead time from rules and team decisions, including timeouts, tempo, the play clock, stops and warnings. Penalty scope is awaiting Micah's decision; without penalty clock rules this gate cannot fully pass. Test stopped and running clocks, boundary timing, a team timeout, warning, period expiration, overtime, special teams and penalties if included. Inject an RNG that raises on use and assert clock advancement never draws a duration. Test a full game and assert no sampled historical runoff reaches state transitions.
2. **Quarterback.** At successive live instants the QB observes current routes and pressure and chooses to wait, throw, scramble based on evidence and ability, or throw away; a defender reaching him can cause a sack. Test no receiver open followed separately by sack, scramble and throwaway, plus an open receiver and an interrupted decision. Assert the QB cannot inspect future positions or the final play outcome.
3. **Ball flight.** A throw creates a time-indexed trajectory with release position, target landing point, height and speed. Interceptions arise from defenders reaching an interceptable ball, not a separate outcome weight. Test trajectory endpoints and height over time, an unreachable defender, a defender arriving first and a trajectory that cannot be caught. Verify replay with identical inputs.
4. **Completion.** Use the throw trajectory, receiver's route and motion, defender's position and motion, and data-supported player inputs to determine contest and catchability. Test changing each input independently changes the reachable or catchable outcome in a controlled setup. An unreachable or uncatchable ball cannot be completed. Cover absent ratings and both receiver-first and defender-first arrivals.
5. **Causal play order.** Enforce the stage sequence above, then transition clock, possession, score and player statistics at the whistle. Test the complete emitted trace for all play types. Change a later-stage value and assert all earlier decisions remain unchanged. Attempt to read an unavailable later-stage field and require a named failure.

Roster invariant test: construct active, Out, inactive, reserve, unelevated and actually elevated players and assert every selected player on offense, defense, substitutions and special teams belongs to the resolved eligible set. Unknown membership must not silently become active. Validate distinct eligibility and evidence-status results.

Existing timeouts are team decisions in V1 Pure. Keep their behavior unless a gate identifies a concrete incompatibility. The implementation at LP 673981d uses measured live scrimmage time and zero dead-ball game-clock runoff after ordinary possession changes, but still samples same-possession dead-ball time from historical distributions. This does not satisfy gate 1. Distinguish game clock, play clock and wall time; possession history (including double turnovers), legal restarts, warnings, penalties and period boundaries must govern transitions. Do not relax the original no-sampled-runoff acceptance requirement.

## Rating data coverage checked 2026-11-22

The [nflverse Next Gen Stats release](https://github.com/nflverse/nflverse-data/releases/tag/nextgen_stats) exposes weekly passing, receiving and rushing aggregates, [documented by nflreadr](https://nflreadr.nflverse.com/reference/load_nextgen_stats.html). The files retrieved on 2026-11-22 contain the following row counts, including season aggregate rows where present:

| Data | 2022 | 2023 | 2024 | 2025 | 2026 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Passing | 603 | 620 | 614 | 605 | 342 |
| Receiving | 1466 | 1473 | 1435 | 1402 | 801 |
| Rushing | 617 | 623 | 601 | 648 | 347 |

The latest week present in each 2026 file is 11. Passing includes time to throw, air yards and completion above expected; receiving includes separation, cushion and yards after catch; rushing includes efficiency and time to line of scrimmage. These are aggregate statistics with eligibility thresholds, not observed 2D trajectories or full defender coverage. Season/week rows are not automatically cutoff-safe: only use observations whose publication was available at the pregame cutoff. Investigate supplementary real-data sources and missing-player handling before fitting any physical parameters; do not infer that every player has an individual rating from these files.

Retrieved SHA-256: passing `da2b955ac3204b51569582ddfd62a2318858fceaaa40f171c08b7ea29397a853`; receiving `69a9cf35c11f652677eece3b8f85cdae7cc4f821014290794b996c5f878fa5cc`; rushing `1e898de8de66a716251775f8ae55bceb99f61a22dce1941e4849e96dbb55a01a`. These mutable release files are observations, not frozen inputs for a future run.

## Research checkpoint and open blockers (2026-11-26)

Historical checkpoint: [Gridiron 5da5973](https://github.com/micahp/gridiron-physics/commit/5da59737d9019cd5d87575b3158dd261b0928d9b) and [LP 673981d](https://github.com/micahp/legendarypicks/commit/673981dcd552741c4d8972bf9403207c08bdab30). Independent source inspection confirmed the exact engine pin at that checkpoint, shared run/pass fumble geometry, per-player contact state, defender-indexing repair and ordinary turnover clock correction. Agent-reported tests: 80 focused LP tests, Gridiron passing/run/result/server suites, and live defensive run/pass fumbles through Node -> adapter -> CEG -> reducer in both directions. Ordinary offensive live recovery was not demonstrated. Tests were inspected, not independently executed by the reviewer.

Agent-reported passing experiments (raw artifacts not independently inspected):
- Paired authored cohort, 48 calls each: baseline 72640b1 -> candidate 5da5973, catches 43 -> 45, interceptions 2 -> 0, probability draws 66 -> 60.
- Saved 220 pass-call replay: original cohort 5 catches and 104 interceptions; candidate 5 catches and 12 interceptions, all calls completed execution. Original counts came from incomplete games; this is not the same controlled experiment as the 48 calls. Rates use called-pass denominators, not verified NFL pass-attempt denominators. The replay is diagnostic, not an NFL rate estimate.
- One fixed pass changed from catch at 60 Hz to incompletion at 120/240 Hz. No timestep-invariant behavior claim.
- Preserve exact calls, seeds, assignments, ratings, masses, outputs and failure artifacts; do not tune to either cohort's outcome percentages.

At documentation reconciliation the remote LP head was [eccd0c52](https://github.com/micahp/legendarypicks/commit/eccd0c52fb2846ecf2398ec1a9313c06854a0e1b), with engine pin [058571b](https://github.com/micahp/gridiron-physics/commit/058571b5f23c43418d3cbb5a202214b1b99b8f55). The intervening changes concern kick/muff touchback handling, contract/reducer support and pinning; they were not fully reviewed or executed here. Do not assume that historical named special-teams blockers remain identical at newer pins; maintain an explicit current refusal registry.

Source-based issues to verify or resolve at the current head:
- Actual LP passing uses assigned calls and defaults to retro mode; the live pass-fumble fixture at 673981d uses legacy slant_flat. Add integration through the real assigned-retro path, including named players and frozen inputs.
- LP constructs a Cover 1 label while the fallback assignment builder provides a zone diagram. Reconcile metadata and behavior; fixed singleback/right/inside-zone or assigned slant-flat is an initial experiment, not a complete playbook. See gridiron_bridge.py:266–276,367–372 at 673981d.
- Position-specific defensive rating validation uses the offensive role map at gridiron_bridge.py:239–255 at 673981d. Verify rating requirements against actual defensive slots and reject missing required data.
- In passing.js at 5da5973, linear target extrapolation (486–532), receiver pursuit of prescribed landing (1180–1234), defender ball prediction (1294–1303) and release/phase scheduling (1450–1504) deserve isolated tests; none has been proven to cause the low catch count.
- Check possession-history clock semantics beyond final-offense comparison in e1_drive.py:424–440 at 673981d. Verify offensive recovery and turnover-chain statistics, including original-offense recovery after interception.
- Receiver reachability, timestep sensitivity, complete rules/statistics reconciliation and actual predictive performance remain acceptance blockers absent fresh evidence.

## Proposed experiment sequence and stopping conditions

First establish configuration parity. Freeze the saved 220 calls and the 48-call authored cohort as separate development fixtures, recording exact engine/LP SHAs, input hashes, assignments, behavior mode, ratings, mass, field orientation, RNG streams and call IDs. Include pre-fix replay on the exact same input when supported; retain incompatibility reasons rather than changing calls to make them run.

### A. Diagnose the completion funnel before changing mechanics

Run the existing candidate control, then one-factor ablations: assigned retro vs detailed; synthetic standard ratings vs real profiles; standardized masses vs original; mirrored direction with equivalent local coordinates; alternate authored passing concept. Use isolated QB/receiver and QB/receiver/defender fixtures for no-pressure and no-defender scenarios; do not mislabel those as regulation 11-on-11. If necessary, use a separately labeled oracle aim/steering diagnostic to bound the error, never as an accepted model.

For each called pass, report actual legal throws, sacks, scrambles, throwaways, other terminal outcomes, viable reads, target and non-target receiver reachability per throw, defender reachability, catch attempts, catches, interceptions, and LP-recorded completions. Report mutually exclusive terminal categories separately from intermediate events (a catch can precede a fumble). Record predicted target vs actual location at arrival, realized trajectory and miss distance, reaction latency, timing of route breaks, pressure, separation, contact episodes and draw IDs. Measure in consistent units; per-frame counts alone are insufficient. Trace release and phase updates, and compare RNG-consuming decisions. Stratify by diagram, coverage, roster inputs, direction and failure reason.

Stopping condition: reproduce the discrepancy and identify which stage accounts for the lost completions, with a paired intervention that materially improves that stage without fabricating outcomes or regressing legal events. If no candidate explains the discrepancy, narrow the next test; do not add new playbooks, tune catch/INT rates, or launch a large game batch merely to accumulate output.

### B. Simple reference versus detailed execution

Use the existing engine and LP contracts where possible. The simple reference should have bounded movement, compact reactive assignment controllers, shared ball trajectory and local rating-sensitive interactions. Compare with current detailed mechanics at identical information, assignments, inputs and seeds; do not implement a separate second rules engine. Defer sophisticated perception/collision/learning layers unless a measured deficiency requires them.

Separate deterministic ball-flight and movement convergence from AI decision cadence and stochastic interaction timing. Check 60/120/240 Hz with fixed decisions and random opportunity IDs where appropriate, then complete stochastic plays. Report trajectory errors in physical units, event timing, contact episodes, terminal outcomes, replay parity, and wall/CPU cost. Define tolerances and materiality thresholds before running a candidate comparison, based on numerical precision, observed football evidence and forecast relevance. One identical outcome is not a convergence study; one different stochastic outcome is not automatically a numerical error.

Use same-information simple baselines first. Retain complex components only when a paired, reproducible comparison demonstrates materially better football fidelity or prediction for acceptable cost; if simpler mechanisms match or outperform them, prefer the simpler implementation. No wholesale rewrite before the mechanism-level evidence.

### C. Escalate through gates, not version increments

1. Audit Rush 2005 source and license, document file-level assignment, movement, pass and interaction mechanisms; compare against Gridiron. Do not copy code without verifying license and compatibility.
2. Establish isolated route/throw/contact correctness and role transitions.
3. Validate assigned 11-on-11 execution across a small authored matrix; verify actual player IDs, ratings, assignments, and both directions through the LP bridge.
4. Replay original failed game seeds (including 300015) against the same pinned pair, preserving every failure. Verify complete causal event history, legal clocks and possession, reconciled score/team/player stats, deterministic replay, regulation/OT and special teams. No resampling failed seeds.
5. Only after structural and full-game validity gates pass, measure play/drive/game distributions against appropriately scoped historical NFL data. Freeze evaluation and holdout before model selection.
6. Compare future forecast probabilities against V1 Pure, V2 Pure, other relevant SLC baselines, market probabilities and simple reference models on identical eligible games. Report proper scores (Brier/log loss), calibration, margin/total error, uncertainty, coverage/failures, and computational cost. No claim of improvement without held-out evidence.

Deliverables: authoritative design, source-grounded controller/assignment audit, explicit reusable component inventory, experiment manifests and compact reports, named blocker registry, exact cross-repository pins and reproducible commands. Preserve negative findings and previous experiments.

## Delivery

Implement and test each gate in scoped commits after this document. Proposed research steps do not authorize a rewrite, production promotion, large batch, or relaxation of existing acceptance gates. A component passes only when it is wired into real full-game execution and its acceptance tests pass. Keep unimplemented cases explicitly blocked rather than silently using old sampled outcomes or durations. No fast-host runs without Micah's approval.
