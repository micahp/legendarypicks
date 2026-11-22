# V1 Complete: football execution design

Starting point: `research/slc-v1-pure-2026-11-21` at `8a99925f`. This document defines acceptance gates, not completed features. V1 Complete has a distinct identity from V1 Pure and from participation/RNG V2 and semantic strength V2.

## Boundaries

A play proceeds in this order: eligible personnel, formation, call, snap, live ball, whistle, next snap. A stage reads only information available at that stage. The field is top-down 2D: each player has position and speed, and the ball has x, y, and height. A defender reaching the runner makes a tackle. Pass outcomes depend on who can reach the ball at a catchable height and time. There are no animations or player collisions.

Participants must come only from the cutoff-valid resolved roster. Exclude Out, inactive, reserve, and unelevated practice-squad players, including provisional projected elevations without an actual elevation. Preserve IDs, cutoff, sources and hashes. Missing eligibility or a required role blocks the affected run with a named reason. Use the existing roster resolver and preflight from `fix/roster-preflight-2026-11-22` after reconciling its dependencies; its provisional projected-elevation behavior must not override this stricter rule. Validate all selection paths, including special teams and substitutions.

Player inputs must be derived from actual observations, with source, as-of cutoff, sample support and uncertainty recorded. Never use video-game ratings. Missing or weak evidence must be explicit; a default is not a measured player rating. Do not use future observations in historical simulations. Preserve full-game rules and overtime, and keep football validity separate from evidence verification.

## Gates and acceptance tests

1. **Clock.** No sampled clock runoff. Advance live time from the actual play timeline; advance dead time from rules and team decisions, including timeouts, tempo, the play clock, stops and warnings. Penalty scope is awaiting Micah's decision; without penalty clock rules this gate cannot fully pass. Test stopped and running clocks, boundary timing, a team timeout, warning, period expiration, overtime, special teams and penalties if included. Inject an RNG that raises on use and assert clock advancement never draws a duration. Test a full game and assert no sampled historical runoff reaches state transitions.
2. **Quarterback.** At successive live instants the QB observes current routes and pressure and chooses to wait, throw, scramble based on evidence and ability, or throw away; a defender reaching him can cause a sack. Test no receiver open followed separately by sack, scramble and throwaway, plus an open receiver and an interrupted decision. Assert the QB cannot inspect future positions or the final play outcome.
3. **Ball flight.** A throw creates a time-indexed trajectory with release position, target landing point, height and speed. Interceptions arise from defenders reaching an interceptable ball, not a separate outcome weight. Test trajectory endpoints and height over time, an unreachable defender, a defender arriving first and a trajectory that cannot be caught. Verify replay with identical inputs.
4. **Completion.** Use the throw trajectory, receiver's route and motion, defender's position and motion, and data-supported player inputs to determine contest and catchability. Test changing each input independently changes the reachable or catchable outcome in a controlled setup. An unreachable or uncatchable ball cannot be completed. Cover absent ratings and both receiver-first and defender-first arrivals.
5. **Causal play order.** Enforce the stage sequence above, then transition clock, possession, score and player statistics at the whistle. Test the complete emitted trace for all play types. Change a later-stage value and assert all earlier decisions remain unchanged. Attempt to read an unavailable later-stage field and require a named failure.

Roster invariant test: construct active, Out, inactive, reserve, unelevated and actually elevated players and assert every selected player on offense, defense, substitutions and special teams belongs to the resolved eligible set. Unknown membership must not silently become active. Validate distinct eligibility and evidence-status results.

Existing timeouts are team decisions in V1 Pure. Keep their behavior unless a gate identifies a concrete incompatibility. The current `snap_clock.py` samples live and dead times, and `e1_drive.py` can use historical runoff for other plays. Neither satisfies gate 1 as it stands.

## Rating data coverage checked 2026-11-22

The [nflverse Next Gen Stats release](https://github.com/nflverse/nflverse-data/releases/tag/nextgen_stats) exposes weekly passing, receiving and rushing aggregates, [documented by nflreadr](https://nflreadr.nflverse.com/reference/load_nextgen_stats.html). The files retrieved on 2026-11-22 contain the following row counts, including season aggregate rows where present:

| Data | 2022 | 2023 | 2024 | 2025 | 2026 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Passing | 603 | 620 | 614 | 605 | 342 |
| Receiving | 1466 | 1473 | 1435 | 1402 | 801 |
| Rushing | 617 | 623 | 601 | 648 | 347 |

The latest week present in each 2026 file is 11. Passing includes time to throw, air yards and completion above expected; receiving includes separation, cushion and yards after catch; rushing includes efficiency and time to line of scrimmage. These are aggregate statistics with eligibility thresholds, not observed 2D trajectories or full defender coverage. Season/week rows are not automatically cutoff-safe: only use observations whose publication was available at the pregame cutoff. Investigate supplementary real-data sources and missing-player handling before fitting any physical parameters; do not infer that every player has an individual rating from these files.

Retrieved SHA-256: passing `da2b955ac3204b51569582ddfd62a2318858fceaaa40f171c08b7ea29397a853`; receiving `69a9cf35c11f652677eece3b8f85cdae7cc4f821014290794b996c5f878fa5cc`; rushing `1e898de8de66a716251775f8ae55bceb99f61a22dce1941e4849e96dbb55a01a`. These mutable release files are observations, not frozen inputs for a future run.

## Delivery

Implement and test each gate in a separate commit after this document. A component passes only when it is wired into real full-game execution and its acceptance tests pass. Keep unimplemented cases explicitly blocked rather than silently using old sampled outcomes or durations. No fast-host runs without Micah's approval.
