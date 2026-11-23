# Retro Madden football AI: reference for SLC V1 Complete

**Date:** 2026-11-23  
**Scope:** Legendary Picks NFL simulation and its future playable/sprite-rendered counterpart  
**Status:** Engineering reference and proposed implementation sequence; not a claim of reverse-engineered EA source code, model adoption, or production readiness.

## 1. Product direction

The historical reference is the original computer John Madden Football (1988–89) through the 16-bit Genesis era, with Madden NFL 98 (released 1997) as the upper bound of this retro phase. We do not need Madden 98 graphics or every feature of that game. Choose a satisfactory 1990s visual style independently of the simulation's behavior.

The simulation-first philosophy matters. In a [2007 Sega-16 interview](https://www.sega-16.com/2007/11/interview-michael-knox/), Park Place founder Michael Knox recalled starting with a team/matchup simulator, visualizing its execution with Xs and Os, and then introducing interactive player control. This is a retrospective developer recollection, not independent validation of the accuracy or throughput figures he reported.

Our corresponding milestones:

| Milestone | Scope | Status / gate |
|---|---|---|
| V1 Pure / statistical simulation | Existing SLC play/drive/game simulation and box scores | Substantially achieved; retain as a reproducible statistical benchmark, not a claim that every game/variant is valid or forecasts beat the market |
| Retro presentation | Display generated football using 2D sprites, a scoreboard, camera and animations | Separate presentation milestone; label reconstructed playback if underlying outcomes were sampled |
| V1 Complete / live execution | Assigned players make football reads, act, interact and produce legal outcomes | In development; bounded live dropback demonstrated, not full-game live execution |
| Retro playable game | Human controller and AI controller operate the same live engine | Target: authentic basic 11-on-11 football, without modern visual fidelity |
| Later retro refinements | Broader playbooks, smarter reactions, better animations; Madden 95–98 as optional reference | Advance only once fundamentals work |
| Phase 3 / later generation | Madden 06-era complexity, sophisticated vision/animation/physics | Explicitly outside current scope |

The engine and reducer are shared where applicable. Headless Monte Carlo and interactive play differ in controller, rendering and pacing, not the football rules. Sprite rendering must not change outcomes, and it does not by itself prove autonomous live gameplay. Never substitute a historical whole-play result in a mode advertised as live execution.

## 2. What historical documentation actually says

### Original John Madden Football (computer edition, 1988–89)

[Original manual scan](https://mirrors.apple2.org.za/ftp.apple.asimov.net/documentation/games/misc/John_Madden_Football.pdf), printed pp. 25–26, 32–41, 45–47. Printed page numbers differ from PDF indices.

The roster editor describes position-dependent attributes on a 0–9 scale. One is explicitly named **coverage reading**, the quarterback's ability to identify an available receiver (p. 25). The primary-receiver task on p. 36 says, "Good QBs don't need a primary; they see the whole field." This is evidence of differentiated QB recognition and a first-read assignment in the original game. It does not disclose a vision cone, sensor system, decision frequency, or algorithm.

The Chalkboard play editor assigns formations, group tasks, individual tasks and routes with up to three directional changes. It documents a mixture of scripted movement and contingent behavior:

| Manual task / concept | Documented behavior, paraphrased | Printed page |
|---|---|---|
| DAYLIGHT | Runner selects a path through available space at reduced speed | 35 |
| DRAW | Runner waits for the handoff before advancing | 35 |
| RUN FAKE / PLAY ACTION PASS | Simulate a handoff without transferring possession | 35–36 |
| PRIMARY | Initial intended receiver in the QB progression | 36 |
| CHECK SWING | Protect against a free rusher before releasing | 36 |
| BLOCK AND GO | Brief blocking assignment followed by a route | 36 |
| PASS BLOCK | Drop into protection and engage a nearby opponent | 36 |
| MOTION | Assign pre-snap movement followed by a post-snap task | 36 |
| GAP CONTROL | Cover or penetrate a designated rushing lane | 40–41 |
| READ | Hold alignment until offensive movement warrants a reaction | 40–41 |
| MAN TO MAN | Assign a specific receiver to a defender | 40–41 |
| SHORT / LONG ZONE | Cover an area; deep coverage adjusts to route depth | 41 |

These are task descriptions, not evidence that EA used any particular software pattern (FSM, behavior tree, utility scoring, etc.). The manual also describes a practice/play-diagram workflow, an excellent precedent for a testable playbook editor. The coaching advice on printed pp. 54–55 discusses responding to alignments and offensive changes; advice about real football should not be mistaken for proof of an implemented CPU mechanic.

### John Madden Football '92 (Genesis)

[Genesis manual scan](https://bdjogos.com.br/manuais/542-john-madden-football-92-mega-drive-manual-usa.pdf), printed pp. 46–47 (PDF index 24).

The manual describes zone defenders as responsible for an area and maintaining a five-yard cushion relative to a receiver; man defenders follow an assigned receiver more closely. It also explains jam and prevent coverage and shows defensive alignments. This gives a concrete retro reference for positional rules. Five yards is a documented game-design reference, not a universal NFL-optimal separation or a requirement to fit all zone behaviors to that value.

### Madden NFL 98 (1997)

The [August 1997 Game Informer preview, issue 52](https://www.scribd.com/document/433155823/Game-Informer-Issue-052-August-1997) describes Liquid AI as defensive positioning responsive to other players and the evolving play. Treat this as period reporting about the advertised system, not source-code verification. The various platform builds must not be assumed identical. We do not need to reproduce Liquid AI precisely.

Further manual/reference reading:
- [Madden NFL 96 Genesis manual](https://segaretro.org/images/b/ba/Madden_NFL_96_MD_US_Manual.pdf).
- [Madden NFL 98 Genesis catalog entry](https://www.gamesdatabase.org/game/sega-genesis/madden-nfl-98.aspx), which links manuals for other ports; do not mistake these for a Genesis booklet.
- [Madden NFL 98 PlayStation manual transcription](https://manualzz.com/doc/6760695/ea-sports-ncaa-football-98-game-manual) (archive title is misleading; body identifies Madden NFL 98).
- [Madden NFL 98 SNES manual transcription](https://manualzz.com/doc/24869263/ea-sports-madden-nfl-98-video-game-instruction-booklet).

The computer and Genesis '92 pages above were inspected visually. The later links are additional references, not a claim that their internal AI algorithms have been recovered. We have not established that any 1990s Madden uses an individual geometric field of view or a modern QB vision cone. Do not import the Madden 06 feature as a current milestone requirement.

## 3. The missing layer: how a player makes a read

A player's state machine determines what actions are available, but a read determines which state/action is appropriate. In a retro game, we can implement this directly using football-specific geometric and event cues. No camera, image processing, tracking neural network or eye/neck simulation is necessary.

At each fixed simulation tick:

1. Freeze the current authoritative world: player IDs, positions, velocities, ball position/possession, contact, clock and phase.
2. Construct a role-specific observation for each player: own assignment, known teammates, relevant nearby opponents, current ball cues and recent observed movement. Start with a simple relevant-object filter. Explicitly define what can be observed and when.
3. Interpret the cues into football reads (free rusher, open receiver, gap closing, handoff apparent, ball released).
4. Transition the player's behavior state and choose a movement/action intent. Resolve ties with deterministic ordering or named seeded draws.
5. Apply all player intents simultaneously to shared bounded kinematics; resolve ball and contacts with a documented deterministic order.
6. Emit actual football events; reducer owns rule transitions, score, clock and statistical accounting.

The engine can know the complete state for collision/rules purposes. That does not mean every AI gets unrestricted strategic knowledge. The offense knows its called play, not the defense's private call; defense observes alignment and motion, not the offense's intent. Never give a defender the future target, catch, tackle or final ball spot. A QB may have a planned first read without having a preselected pass recipient. An early baseline may use current geometric coordinates of relevant actors with explicitly simplified perception; avoid claiming human-realistic vision or reaction times.

Suggested interfaces (design sketch, not existing API):

    WorldSnapshot -> observe(player_id, assignment) -> Observation
    Observation + PlayerMemory -> interpret_reads() -> ReadSet
    ReadSet + BehaviorState -> decide() -> ActionIntent
    All ActionIntents + WorldSnapshot -> advance(dt) -> WorldSnapshot + Events
    WhistleEvent -> existing reducer + game_stats -> next football state

Separate movement heading from attention if/when necessary. Store last-seen relative position and time only when a specific behavior needs memory. Full occlusion, head orientation, gaze, peripheral vision and cognition are deferred, not required for retro acceptance.

## 4. Retro behavior primitives and example state machines

Use small position/assignment state machines (hierarchical if useful), shared interrupts and steering. These are our implementation proposals inspired by the manuals, not claims about Madden's source architecture.

| Assignment | Relevant reads | Minimal states / actions |
|---|---|---|
| QB dropback | Route availability, defender proximity, clear passing lane, pressure | DROPBACK -> SCAN -> THROW / SCRAMBLE / THROWAWAY; contact may terminate as sack |
| WR route | Own waypoint, depth, defender leverage, visible ball | RELEASE -> RUN_ROUTE -> CUT -> TRACK_BALL -> CATCH_ATTEMPT -> CARRY |
| RB daylight | Handoff confirmed, gap width, blocker and defender positions | WAIT_HANDOFF -> READ_GAP -> ATTACK_GAP -> CUT / EVADE -> CARRY |
| RB/TE check-release | Free approaching pass rusher | CHECK -> BLOCK or RELEASE_ROUTE |
| OL pass protection | Assigned threat, rush direction, free nearby threat | SET -> IDENTIFY -> ENGAGE -> SUSTAIN / RECOVER |
| DL/LB gap control | Assigned gap, blocker, apparent carrier | HOLD / ATTACK_GAP -> ENGAGE -> SHED -> PURSUE |
| LB read | Initial line/backfield movement, possession evidence | HOLD_READ -> FILL_GAP / DROP_ZONE / PURSUE |
| CB man | Assigned receiver position and direction; release/ball cues | ALIGN -> MIRROR -> TRACK_BALL -> CONTEST / PURSUE |
| DB zone | Zone area, receiver threats, apparent pass direction | DROP_TO_ZONE -> MAINTAIN_LEVERAGE -> BREAK_ON_BALL |
| All live players | Whistle, possession change, ball loose, boundary | Stop; switch pursuit/return/block roles as applicable |

Example reads (initial heuristics to test, not measured parameters):
- QB: evaluate scheduled eligible receivers using reachability and defender arrival time around a candidate pass window; move to another read if it closes. Resolve an actual throw and contest after the decision, not by sampling its final outcome beforehand.
- RB: score a small set of legal candidate lanes by local clearance, forward progress and reachable acceleration; follow the best feasible lane. Do not know which historical gap succeeded.
- LB: observe early backfield and blocking cues; maintain the assigned responsibility until enough evidence favors run or pass. Similar first movements for play action and run should yield similar early decisions.
- DB: maintain relative leverage in man; defend the assigned zone in zone. Break toward the actual ball only after release is observable.

State machine = what the player is doing; read = what they infer; steering = where they want to move; kinematics = how they get there. Start with simple ordered rules. Add utility scoring only if competing legal actions require it. Do not label arbitrary utility numbers as fitted probabilities.

## 5. Data and modeling: do not repeat the movement experiments

Our earlier competition research is an explicit constraint on this plan, not a reason to launch another fitting sweep.

- [53-play NFL inside-zone autonomous benchmark](https://github.com/micahp/gridiron-physics/blob/main/docs/evidence/autonomous-acceptance/bdb53-tracking-perimeter-fix.json): +1 s mean position error 0.9918 m constant velocity versus 2.1885 m autonomous engine. More elaborate execution had roughly 2.2 times the error.
- [Separate broader all-player historical benchmark](https://github.com/micahp/gridiron-physics/blob/main/docs/research/PART-B-HISTORICAL-RESULTS-2026-10-28.md): +1 s error 1.138 m constant velocity versus 0.939 m constant acceleration, 206,536 player tracks. Do not compare these numbers directly to the 53-play cohort.
- [NHL movement study](https://github.com/micahp/legendarypicks/blob/e43c09fe7d1f955794717099f53be3392ee8e6ea/docs/research/NHL-MULTI-AGENT-MOVEMENT-REPORT-2026-10-23.md): interaction-aware movement failed the frozen short/long-horizon criterion and degraded joint geometry despite some longer-horizon individual endpoint gains.
- [Movement materiality decision](https://github.com/micahp/gridiron-physics/blob/main/docs/research/MOVEMENT-POLICY-MATERIALITY-DECISION-2026-10-24.md) and [LP simulation learnings](https://github.com/micahp/legendarypicks/blob/dev/docs/SIMULATION-LEARNINGS.md): a new challenger must clear the recorded practical and statistical thresholds against the best kinematic baseline; preserve holdouts.

Use existing bounded kinematics first. Constant velocity/acceleration with observed initial conditions are short-horizon prediction baselines, not complete autonomous football strategies. The rule-based policy generates initial assignments, intended motion and reactions without actual future positions. Use tracking to evaluate behavior, not as a compulsory training prerequisite. If a specific deficiency requires new fitting, preregister it, use time-honest data and identical inputs, and demand incremental value. The 53-play failure does not prove all learned policies fail; it does establish the danger of assuming complexity improves prediction.

Reuse current SLC personnel/formation and play-call priors, roster eligibility, player usage, and appropriate existing strategic/clock models. Never use a legacy sampled target role to secretly predetermine the live pass. Use PBP/participation to estimate supported tendencies and player opportunity; aggregate PBP cannot identify exact unobserved spatial trajectories. Existing target/carry/outcome models are benchmarks, not automatic live execution inputs.

For the retro prototype, shared baseline attributes and explicit authored parameters are acceptable as **design/fixture** inputs. No invented individual NFL ratings or fabricated data provenance. Label input classes observed, estimated, authored/synthetic, unsupported. The [historical Madden ratings dataset spec](https://github.com/micahp/legendarypicks/blob/dev/docs/MADDEN-RATINGS-DATASET-1992-2027.md) and [ratings research report](https://github.com/micahp/legendarypicks/blob/dev/docs/research/MADDEN-RESEARCH-REPORT-2026-10-23.md) are references, not authorization to import unvalidated ratings as ground truth. Distinguish gameplay attributes from calibrated predictive parameters.

## 6. Current V1 Complete integration

At the reported 98-test checkpoint, the research branch contains:
- [Personnel-first and deferred receiver selection](https://github.com/micahp/legendarypicks/blob/c4c388f7/scripts/nfl_sequence/pre_event.py).
- [Live QB decision](https://github.com/micahp/legendarypicks/blob/c4c388f7/scripts/nfl_sequence/live_qb.py), [live dropback](https://github.com/micahp/legendarypicks/blob/c4c388f7/scripts/nfl_sequence/live_dropback.py), ball flight and reducer/stat integration.
- [Bounded field implementation](https://github.com/micahp/legendarypicks/blob/research/slc-v1-complete-2026-11-23/scripts/nfl_sequence/live_field.py) and synthetic tests: two supplied roster-validated eleven-player lineups, constant assigned velocity, supplied QB and catch decisions, reproducible result.

This proves a limited execution path, not automatic legal formations, complete player behavior or NFL forecasting. The fixture's provenance-shaped fields alone do not establish real measurements. Blocking assignments currently do not implement meaningful blocking interaction. The original full-game hook at c4c388f7 still fails closed after a live QB decision; a later branch revision must explicitly integrate the execution result. Unsupported catch continuations, returns, tackles, field boundaries and clock transitions remain important gaps. Do not quietly substitute historical outcomes.

The separate legacy interception/timeout blocker is a timing/rules problem: insufficient matching historical runoff samples and no reusable interception snap-timing model were reported. Keep it separate from the behavior baseline; do not invent runoff to complete a game.

## 7. Implementation order and acceptance gates

1. **Retro playbook and lineup:** minimal legal offensive/defensive formation pairs and 22 distinct eligible players; explicit player tasks, route waypoints, man IDs, zone bounds and gap assignments. Generate from roster and appropriate existing priors. Validate assignment/formation compatibility, coordinate conventions and snapshots.
2. **Read-and-react baseline:** implement role observations, state transitions and shared kinematics. Begin with a simple pass concept vs man/zone and a simple run concept vs gap/read defense; use deterministic fixtures and bounded authored inputs first. Add a slow-motion overhead/Xs-and-Os debug viewer with read, state and assignment labels. Retain prior failure evidence.
3. **Complete play:** use generated motion/decisions, resolve pass/handoff, block, catch/drop/deflection, tackle, boundary and possession events through the reducer. Separate live-ball duration and dead-ball timing. Emit auditable play and stat records.
4. **Complete drive and game:** integrate the live path in the game loop, legal next snap, drive endings, scoring, turnovers, period transitions, special teams and normal kickoff policy. Preserve explicit unsupported-event failures during development; full-game mode must not claim completion if blocked. Verify deterministic replay and team/player reconciliation.
5. **Retro presentation and human control:** render shared world frames with original/appropriately licensed sprites and animation states, camera and scoreboard. A human-controlled player submits action intents through the same interface. AI vs AI must continue headless. Presentation can progress in parallel as a separate milestone.
6. **Evaluation:** tracking is a measurement tool. Test comparable initial-state trajectory error, spacing, read/response behavior, plausible conditional football outcomes and legal full-game distributions; compare to frozen V1 Pure and simple baselines. Forward forecast skill is separate and requires held-out game/prop scoring with as-of inputs.

Acceptance fixtures must cover, at minimum: no receiver selected before snap, QB changes read when coverage changes, man mirrors assigned target, zone maintains area and depth, RB responds to a changed lane, LB does not know a concealed play call, blocker reacts to a free rusher, dropped pass continuation, possession change interrupts, whistle halts motion, iteration order does not change deterministic results, and rendering does not affect headless output. Show failure traces with seed, tick, observation, read, state transition and result.

Keep authored gameplay tuning separate from predictive calibration. No new broad player-tracking fitting project, modern vision cone, GPU/3D rigging requirement, or full-body physics requirement in this retro phase. No promotion of a forecast model based on how convincing a rendered play looks.

**Bottom line:** Build the football intelligence that a retro game needs: assignments, observable reads, reactive decisions, simple movement and legal consequences. The graphics are a presentation choice; movement complexity is justified by measured improvements, not by the year printed on the reference game.
