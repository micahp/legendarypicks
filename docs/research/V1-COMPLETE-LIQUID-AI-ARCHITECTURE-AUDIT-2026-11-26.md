# V1 Complete: Liquid AI architecture audit

**Audit date:** 2026-11-26
**Specification:** Original design at `68a019dbe2f5a0d74d29bf25efe7db525ccd9714`; restored and reconciled at LP commit `9dfdf4bfab3943de98a35cae360ebbd40d041af0`
**LP implementation inspected:** `feat/slc-v1-complete-implementation-2026-11-24`, code pin `eccd0c52fb2846ecf2398ec1a9313c06854a0e1b`
**GridIron implementation:** `feat/v1-complete-autonomous-execution-2026-11-24`, `058571b5f23c43418d3cbb5a202214b1b99b8f55`

This is a source audit and controlled-experiment proposal, not a declaration that V1 Complete has passed its gates. The LP and GridIron branches were clean of tracked edits before this note; GridIron already had four untracked input artifacts, which were left untouched. No simulation batch was run for this audit.

## Reconciled design

The updated LP specification calls for autonomous 11-on-11 play whose live outcomes follow from player-specific abilities, coach decisions, eligible personnel, assignments, movement and local interactions. Each player needs a small role- and assignment-specific read process, driven by current observable cues. No controller may inspect a private opponent call, future outcome or unobserved future ball position. Keep football rules and statistics in the existing SLC layer. Advanced animation, perception and collision physics are explicitly not V1 requirements.

That maps cleanly to four runtime responsibilities:

1. **Action selection:** play/personnel/coaching decisions before the snap; then a player's assignment and situational state transition.
2. **Steering:** choose a bounded movement intent toward the assignment target or current reactive target.
3. **Locomotion:** convert that intent into position and velocity through the shared movement model.
4. **Football interaction resolution:** evaluate eligible contact, blocks, throws, catches, tackles, fumbles and recoveries from the current geometry; emit facts for SLC rules/statistics to apply.

The first three layers follow Reynolds's action/steering/locomotion separation; football interaction resolution is an additional domain layer. The current code has reusable pieces for each, but decisions, steering and some interaction outcomes remain interleaved in the play controllers.

## Implementation gap matrix

| Area | Existing and reusable | Gap against the updated design |
|---|---|---|
| Player ratings | NFL-derived, named-player profiles exist; the live bridge rejects missing required player ratings. Gridiron maps a subset to movement, reads and contacts. | Evidence classes and calibration support are mixed across artifacts. Some engine fallbacks and authored archetypes remain. Each rating needs a named behavior contract and isolated effect test. |
| Personnel and eligibility | LP roster/participation resolution and preflight supply eligible player IDs; GridIron validates player profiles and lineups. | Continue applying the same resolved eligibility to every substitution and special-teams role. Do not infer from position archetypes. |
| Coaching | `autonomous_game.py` separates coach decisions from player execution; fourth-down alternatives have explicit expected-value estimates and decision quality changes choice sharpness, not execution. Timeouts and two-point choices have decision models. | Auditing EV coverage and inputs remains necessary for every choice. Some policies use simple authored EV curves, a 70 default quality, or quality-scaled probability; these are decision models, not established NFL coaching-quality measurements. |
| Team playbooks | Checked-in season profiles and manifest provide aggregate team tendencies. LP's playbook prior is used to select run/pass tendencies. | Tendencies are not executable diagrams. The bridge currently sends singleback 11 personnel and a fixed call; `GridironSession.play` fills missing assignments with generic inside-zone or slant-flat/zone examples. Use season play evidence to inform tendencies, but maintain separately reviewed authored executable diagrams. |
| Assignments | `assignments.js` validates complete offense/defense role maps. Executors emit `assignment_executed` for 22 players. `example-assignments.js` defines executable generic diagrams. | Schema validation is not proof of assignment execution. Current run/pass brains reinterpret some assignments and choose live targets in code. Build scenario tests that verify each player's assigned route, block, gap, man/zone or special-teams task and allowed reactions. |
| Reads / Liquid-AI layer | Run, pass and special-teams controllers already contain role-conditioned reads; assigned retro execution uses an Awareness/recognition-dependent decision interval. | `Player.ai` is an ad hoc mutable bag, not an explicit FSM contract. State, observation, interpretation, transition and intent are not uniformly separated or auditable across all players. Some decisions run in sequential player order. |
| Steering and locomotion | Shared `World`, `Player.locomote`, bounded desired velocity, engagement, wrap/tackle and ball integration are already reused by run/pass/special teams. | `seek`, target selection and policy details are duplicated across controllers. `World.step` calls each brain sequentially, then integrates everyone, so action callbacks can have order-dependent side effects. Separate snapshot-based intent selection from integration incrementally. |
| Pass/contact outcomes | Live ball flight, route motion, catch contests, interception reachability, tackling and fumbles exist. Current pass code tracks attempted contacts by player while the opportunity remains active. | The saved 220 replays predate that contact guard. Current behavior is not replay-validated. Receivers in `passing.js` still steer toward the ball model's exact `landing` field (around line 1201), leaking an unobserved future location. Recovery and block-shed randomness also needs opportunity/timestep audits. |
| Rules, lifecycle and statistics | LP owns game state, rules/event adapters, lifecycle, clock and stat reconciliation. GridIron returns execution facts; it should not duplicate SLC rules. | End-to-end event coverage and full-game validation remain separate acceptance gates. Any unsupported emitted fact must reject with a named blocker. |
| Observation complexity | A delayed-memory/FOV module is available in detailed pass behavior. Retro mode can read current relevant positions and cues. | Rich perception is not a V1 requirement. Keep it optional for paired evaluation; do not make it a prerequisite or let it reveal exact future ball state. |

The restored research checkpoint at LP `9dfdf4bf` identifies additional source-based checks that remain relevant at the reviewed pins: the bridge labels defense `cover_1` while its fallback assignment builder supplies a zone diagram; the saved 220-call records do not preserve reachability/trajectory metrics; ordinary offensive live fumble recovery was not demonstrated in the cited end-to-end tests; and pass target extrapolation, defender ball prediction, and release/phase scheduling need isolated tests. The cover/assignment mismatch is visible in `gridiron_bridge.py:270-275,366-372`. It must be resolved as metadata/diagram parity, not mistaken for a team-season playbook.

One older checkpoint concern appears fixed in the reviewed bridge: required player ratings now branch separately for offensive roles, defensive line, and linebacker/defensive back roles (`gridiron_bridge.py:245-252`). Preserve this fail-closed role-specific validation when assignments or formations are expanded.

Primary implementation references: GridIron `engine/autonomous/simulator.js:52-125`, `assignments.js:1-103`, `example-assignments.js`, `autonomous-run.js:231-245,481-548,655-882`, `autonomous/passing.js:460-525,618-672,780-841,1201,1363-1397`, `autonomous/special-teams.js:117-152,191-223,252-299`, `retro-cadence.js:3-6`, and `engine/world.js:62-160,164-372`; LP `scripts/nfl_sequence/gridiron_bridge.py:235-282,366-376`, `autonomous_game.py:312-395`, `game_state.py:740-792`, `event_expansion_rules.py`, and `game_stats.py`.

## Player ratings: available evidence and behavior contract

### Inventory and provenance

- LP documents an external Madden ratings bundle scraped from nfldraftbuzz: 58,743 player-release rows, 1992–2027, with 60 attributes plus identity/provenance columns. It is not checked into either implementation worktree. LP's current specification explicitly says “Never use video-game ratings.”
- Gridiron's legacy `data/ratings.json` is a mixed NFL-derived profile artifact; its audit notes a Madden-derived speed conversion and weak identity overlap for the MIN–SF example. Treat it as unsuitable for production calibration until its conversion and per-player evidence are isolated.
- The game-specific `data/ratings-2026_12_GB_LA.json` identifies itself as `nfl_derived`, includes 8,968 combine athletes and 2,321 statistical players in its input metadata, and reports 1,679 calibrated league players. The pinned bridge maps a subset of ratings as runtime requirements. It is the right provenance direction, but the labels (for example `AWR`, `PRC` and `THA`) are latent gameplay constructs, not directly observed combine measurements.
- The LP V1 design records weekly Next Gen Stats passing, receiving and rushing aggregates through Week 11 as of its documented cutoff. They can support player estimates such as throw timing, separation or rushing efficiency; they are not full trajectories, complete coverage labels or universal player measurements. Combine measurements are useful for physical priors, but event times/measurements need provenance and uncertainty.
- Classify every value as **NFL-observed**, **NFL-derived estimate**, **authored gameplay parameter**, or **unsupported**. Madden-derived values may be retained for a clearly separated historical comparison, never silently relabeled as NFL measurement.

No single normalized evidence-and-effect schema currently spans the NFL-derived profile, legacy GridIron profile, authored archetypes and coaching profile. Proposed common player record:

```json
{
  "player_id": "canonical-id",
  "position": "role-at-cutoff",
  "as_of_utc": "pregame-cutoff",
  "ratings": {
    "physical": {"SPD": {"value": 0, "class": "NFL-derived estimate", "source_ids": [], "support": 0, "uncertainty": 0}},
    "technical": {"TAK": {"value": 0, "class": "NFL-derived estimate", "source_ids": [], "support": 0, "uncertainty": 0}},
    "awareness": {"PRC": {"value": 0, "class": "NFL-derived estimate", "source_ids": [], "support": 0, "uncertainty": 0}},
    "behavioral_tendencies": {"risk_choice": {"value": null, "class": "unsupported", "source_ids": [], "support": 0, "uncertainty": null}}
  },
  "effects": [{"rating": "SPD", "behavior": "top_speed_cap", "mapping_version": "v1"}]
}
```

Physical measures include speed, acceleration, agility, strength, and (when evidenced) jumping/endurance. Technical skills cover role interactions such as throw, catch, tackle, block, coverage, and kick. Awareness/recognition is distinct from motor skill. Behavioral tendencies are observed choices, not coaching quality or a relabelled skill rating. Every rating needs provenance, support and uncertainty; an authored value must never masquerade as a measured player value. The `effects` list links every active rating to its specific interaction.

### Existing live mappings and missing contracts

| Rating/input | Existing behavior in Gridiron | Required independent verification |
|---|---|---|
| `SPD` | Top speed / pursuit reach | Change only top-speed cap; verify bounded reach and equal starting state. |
| `ACC` | Force-limited acceleration | Vary acceleration with identical top speed; compare time-to-space, not just endpoint. |
| `AGI` | Lateral acceleration / cut response | Controlled direction change at fixed speed and geometry. |
| `STR` | Engaged drive and parts of block/tackle interaction | Matched contact with strength varied on one participant. |
| `AWR` / defensive `PRC` | Decision cadence, read delay/quality, recovery response | Hold cues constant and measure read/transition latency; isolate recovery separately. |
| `BCV`, `AGI`, `ELU` | `BCV` affects RB lane scoring; `AGI` changes lateral cut cost; `ELU` is currently combined with `BTK` as tackle resistance. | Controlled lane choice, lateral cut and tackle resistance are separate tests; do not describe `ELU` as an evasion controller until one exists. |
| `RBK`, `IBL`, `PBK` vs `BSH`, `PMV`, `FMV` | Block engage/drive and defender shedding/rush interactions | Fixed pair and geometry, separate engagement from shed outcome, one rating at a time. |
| `THA` | Assigned QB throw placement | Same release/receiver geometry; isolate placement error. `THP` has no direct live mapping in the inspected pass controller and needs one before it can be treated as implemented. |
| `CTH`, `CAR` | `CTH` affects the catch contest; `CAR` affects catch fallback/loose-ball security and fumble resistance. | Catch, retention and fumble are separate controlled interactions. `CIT`, `THP` and `TRK` have no direct live mapping in the inspected controllers. |
| `TAK` vs `BTK`, `ELU`, `STR` | Tackle attempt/completion and resistance | Fixed local tackle eligibility; report attempt and completion independently. |
| `PUR` | Pursuit path/speed contribution | Fixed target motion and geometry; evaluate path and arrival time. |
| `KPW`, `KAC` | Kick launch power and placement dispersion | Live kick geometry, same wind/ball setup; validate distance and lateral error separately. |
| `CIT`, `THP`, `TRK` | No direct live mapping identified in the inspected controllers. | Keep unsupported until each has a named behavior and an independent effect test. |

GridIron's synthetic `ratingProfile` maps `SPD`, `ACC`, `STR`, and `AGI` into `vmax`, `f0`, `drive`, and lateral acceleration through authored sandbox multipliers. Those coefficients are not calibrated NFL force measurements. The bridge's strict required-rating list is a useful fail-closed boundary; remaining `??` defaults inside low-level formulas should be unreachable for production players or produce explicit evidence blockers.

### Specification restriction and proposed revision

The current spec's categorical ban protects against treating game-balancing numbers as real measurements, but it also prevents a controlled test of whether historical Madden attributes provide useful player differentiation. Do not bypass that text. Proposed replacement for Micah's review:

> Production V1 player profiles use cutoff-valid NFL observations and explicitly labeled NFL-derived estimates. Madden ratings are prohibited as production measurements or execution inputs. If rights and data provenance permit, a separate, non-production benchmark may map Madden attributes to candidate behaviors and compare paired results; it must remain isolated from NFL-derived profiles and cannot establish NFL calibration.

This retains the production safeguard while allowing a falsifiable ablation on Madden's player differentiation. It requires a spec change before any Madden-derived gameplay input is used.

## Coaching and playbook boundary

`autonomous_game.py` already contains the right separation: `coaching_quality()` feeds fourth-down choice temperature, timeout-call probability, penalty choice and try choice; it does not modify GridIron player ratings or execution chances. Fourth down estimates go/punt/field-goal alternatives from current down, distance, field position, score and clock. Playbook pass-rate is a separate prior. Two-point and DPI choices also calculate alternative values before the decision. This is directionally aligned with the design.

Remaining issue: EV and “quality” are authored models, not audited ground truth. For each coach choice, persist the options, information set, EV model version, estimated values, choice and quality; score regret against the best available alternative at decision time. Never score a coach by the realized play outcome. Review the default quality of 70 and any flat/legacy tendency for hidden effects. Verify personnel, formation, tempo, timeout, kickoff options and try decisions through the same pre-decision information rule.

For playbooks, preserve two datasets: (a) observed team-season frequencies/concepts, with source and cutoff; (b) authored executable diagrams with explicit personnel, alignment, all 22 assignments, reads and conditionals. The existing bridge currently uses (a) as a tendency prior and (b) only as generic authored examples. Do not label generic examples as historically observed plays.

## Role-specific reactive controller specifications

These are the required FSM contracts assembled from existing behavior, not claims that formal FSMs already exist. “Keep” means retain as a state/assignment; transition only on a relevant current cue or an assignment interrupt. Slot groups reflect the current runtime, not every NFL package.

| Supported role / slots | Relevant observations | Minimal states and transitions | Rating dependencies |
|---|---|---|---|
| QB | Snap/mesh possession, assigned concept, current route progress and visible coverage estimate, pressure/contact, current ball state | Receive/drop → read; read → hold, throw to an assignment-compatible reachable read, scramble on pressure/space, or throw away under configured situation; contact → sack/loose ball; phase change interrupts cadence | `AWR` cadence/read, `THA` placement, `SPD`/`ACC` scramble locomotion; `THP` currently unmapped |
| RB | Handoff/mesh, declared track/gap, current lane leverage, nearby defenders, live ball and contact | Mesh → press track; read lane → press/cut; threat at lane → rescore/switch lane; contact → tackle/break/fumble; loose ball → pursue/recover; recovery → return/escort | `BCV` lane choice, `AGI` cut cost, `SPD`/`ACC`, `CAR`, `BTK`/`ELU` tackle resistance, `AWR` recovery cadence; `TRK` unmapped |
| OL: LT/LG/C/RG/RT | Blocking assignment/track, current leverage and contact, defender disengagement, ball phase | Set → assigned zone/target; approach → engage; engaged → drive/maintain; defender shed or ball phase change → redirect/recover | `RBK`/`PBK`/`IBL`, `STR`, `AGI`; matchup defender `BSH`/`PMV`/`FMV` |
| TE and WR1–WR3 | Route landmark and progress, assignment, current defender leverage/zone, live ball, contact | Release/route → landmark/break; coverage cue → maintain route/conditional adjustment if assigned; throw → reach/catch/contest; run assignment → stalk/edge block; live carrier → support | `SPD`/`ACC`/`AGI`, `CTH`/`AWR`; `CIT` is not mapped in the inspected controllers; `RBK`/`IBL` when blocking |
| DL: LEDGE/LDT/RDT/REDGE | Assigned rush/gap, OL engagement, mesh/carrier/QB currently visible, shed/contact | Align → gap/rush; engage → power/finesse shed; run cue → close assigned gap; live carrier → pursue/wrap; loose ball → recover | `PMV`/`FMV`/`BSH`, `STR`, `PUR`, `TAK`, `PRC`/`AWR` cadence |
| LB: MLB/WLB/NB | Assigned fit, backfield/line movement cues, coverage role, carrier and pursuit geometry | Read key → hold/fit; recognized run → flow/force/alley; pass assignment → carry man/zone; close leverage → tackle; loose ball → pursue/recover | `PRC`/`AWR` read delay, `PUR`, `TAK`, `BSH`, `SPD`/`AGI` |
| DB: LCB/RCB/SS/FS | Assigned receiver or zone landmark, receiver's observed movement, QB/ball cues, leverage, current carrier | Backpedal/hold leverage → follow/zone landmark; route break/ball airborne → break only when observable and reachable; catch/turnover → tackle or recover/return | `PRC`/`AWR` recognition, `PUR`, `SPD`/`AGI`, `CTH`, `TAK` |
| Specialists and unit roles: K/P, snapper, holder, returner, coverage/protection | Assigned kick/snap/hold/coverage role, live ball trajectory and current bounce, return lane/threats, contact | Align → snap/hold/kick; kick flight → cover/track; returner → catch/fair-catch/muff then return; loose ball → recover; contact → block/tackle | `KPW`/`KAC`, `CTH`/`CAR`/`AWR`, `PUR`/`TAK`, `RBK`/`IBL`/`BSH`, movement ratings |

For every transition, store the assignment, observed cue and timestamp, rating(s) used, chosen state and resulting intent. Keep intent selection at the rating-dependent decision cadence; continue locomotion between decisions. Shared interrupts (snap, possession, ball phase, contact, whistle) should wake affected players without letting them read unavailable state.

## Rush 2005 source inspection

I retrieved and inspected the BSD Rush 2005 0.4.12c source archive (SHA-256 `eaeea661a1a0020c039f4b12807f124c432ee2780101a4b722fbbc1c99548d5f`), focusing on `src/ai.c`, `src/main.h`, `src/plays.c`, `src/setsgets.c`, and `src/collisions.c`. The [project describes itself as an arcade-style, BSD football game](https://rush2005.sourceforge.net/) and the [SourceForge release archive](https://sourceforge.net/projects/rush2005/files/) provides the source.

What the code actually does:

- `main.h` has two enumerations: a player `STATE` (waiting, tackling, shadowing, pass/run blocking, route running, covering, recovering, chasing/returning, etc.) and a separate `MOVELOGIC` (wait, run/pass block, charge/sweep, handoff, recovery, route, shadow/chase variants). This is a practical precedent for assignment/mode distinct from motion instruction.
- `GetAIAction` in `ai.c` branches on possession and state. A ball carrier charges or tests rectangular lanes, then chooses left/right or a random fallback. The QB selects a wide-open receiver, then a more permissive fallback when the pocket is blocked; if no receiver is available it may pick one randomly.
- `ApplyMoveLogic` interprets assigned move types; authored `plays.c` diagrams establish formations and per-player movement logic. This is scripted role assignment with conditional local reactions, not a general-purpose learned policy.
- `PassBall` projects a receiver using current velocity and adds skill-dependent random placement error. `OpenLane` tests axis-aligned collision rectangles. `ZoneWatch` changes from zone to chase when an offensive player overlaps the authored zone.
- `CheckForFumbleRecovery` in `collisions.c` selects the first overlapping eligible offensive player, then the first defensive one. This is simple deterministic overlap resolution, not nearest-player or awareness-based selection.
- The project issue list itself flags poor pursuit/evasion, return and special-teams limitations. Its author also describes Rush as fast arcade play rather than high-fidelity simulation.

Rush 2008 research is a later extension, not a description of Rush 2005's own AI: it uses an eight-player football variant, authored formations/plays and role goals or tick-level actions, with ICARUS hierarchical skills acquired from video. See the [primary IJCAI workshop paper](https://www.cs.cmu.edu/~nli1/Published%20Papers/IJCAI09%20StrucK-LiN_Learning%20Hierarchical%20Skills%20for%20Game%20Agents%20from%20Video%20of%20Human%20Behavior.pdf). The transferable lesson is represent assignments and local conditional reactions explicitly; do not copy its 8-player scale or introduce learned skills into V1. For the motion split, see Reynolds's [original GDC 1999 paper](https://www.red3d.com/cwr/papers/1999/gdc99steer.html). The [May 1990 Antonick interview scan](https://www.commodore.ca/gallery/magazines/gazette/Compute-Gazette-Issue-83.pdf) supports individual ratings/assignments as historical inspiration. A [Madden NFL 2004 developer interview](https://www.tweaktown.com/gaming/1805/madden_nfl_2004_interview/index.html) describes covered-receiver scrambling and defensive reaction to QB runs; it is evidence for those behaviors as design goals, not their internal algorithm. The existing `RETRO-MADDEN-PLAYER-AI-V1-COMPLETE-2026-11-23.md` correctly treats proprietary implementation details as unknown.

## Saved 220-call completion failure

Evidence: `/root/runs/week-12/v1-complete/replay-evidence/bounded-three-seed-pass-attempt-and-clock-audit-300015-300017.json`, SHA-256 `42943a12da5b7d10e3b9dc0f871bcc93528d104d5b7ea37e7f1fdfb9ccb2fe99`. It contains 220 isolated saved pass calls across seeds 300015–300017 and one separate seed-300017 post-score kickoff replay. No full-game batch was part of this evidence.

- All 220 saved pass event hashes matched the saved baseline. This establishes replay/instrumentation stability for that baseline; it does not validate the outcome model.
- The 220 throws generated 104 interception events, 111 incompletions and 5 catches (3 touchdowns). The summary recorded 1,324 contact-candidate ticks and 1,319 defender interception-probability draws over 220 player-contact opportunities: about 6 draws per continuous opportunity. One saved throw had the same defender draw 17 times in 0.133 seconds while the ball remained in its catchable envelope.
- The mechanism is repeated Bernoulli sampling during one continuous geometry opportunity, which compounds chance: six independent 5% draws yield `1 - 0.95^6 = 26.5%`, rather than one 5% opportunity. The exact contribution of this defect to the 104 historical interception events cannot be inferred from aggregate counts.
- The reconciled design at LP `9dfdf4bf` reports an agent-run replay of the saved 220 calls on a later candidate: 5 catches, 12 interceptions, and execution completed for all calls. It also reports a distinct 48-call authored cohort (43→45 catches, 2→0 interceptions, 66→60 probability draws) and one fixed pass that was a catch at 60 Hz but incomplete at 120/240 Hz. These are agent-reported results; their call-level candidate artifacts were not present in the saved evidence directory inspected for this audit, so hashes, inputs, and event-by-event changes were not independently verified here. The 48-call cohort is not the same input population as the saved 220.
- GridIron commit `3618bd2` added per-player contact-attempt latching and removes the latch after leaving the envelope; `5da5973` further changed return geometry/airborne contact. These commits postdate baseline `ddd19cf`. The reported candidate results are encouraging for interception draw counts but do not show improved completions (the reported catch count remains five), do not establish causality, and do not pass timestep invariance.
- The saved compact records omitted full trajectories and per-player reachability metrics. Therefore receiver reachability, catchable-frame count, time-to-ball and trajectory error are not recoverable from this JSON alone. The seed-300015 fumble endpoint quantization and seed-300017 muff-touchback evidence are unrelated special-teams/contract failures and must not be conflated with the completion defect.

Do not tune aggregate completion/interception rates until the one-opportunity mechanics are verified. The first experiment should preserve one random draw per uninterrupted player/ball reachability opportunity; leaving and re-entering creates a new opportunity. Audit whether the same rule is needed for fumble recovery, kick recovery and block shedding. For continuous hazards, use a timestep-invariant event-time method rather than a new Bernoulli draw on every numerical integration step.

## Simplification plan and controlled protocol

No wholesale rewrite is indicated. Keep the shared `World` and all existing play executors. Simplify around them in this order:

1. **Write down behavior contracts:** explicit states, allowed observations, assignments, transition triggers, intent output and rating dependencies per role above. Keep a small `state` plus role controller; avoid a generic planning framework.
2. **Close information leaks:** replace receiver steering toward exact `ball.landing` with current ball observation or a bounded estimate from observed position/velocity. Ensure QB and defenders do not read hidden live coordinates in detailed mode. Add an assertion/test seam for unavailable future fields.
3. **Make decisions order-independent:** capture a read-only tick snapshot; calculate one intent per player; then resolve engagements, locomotion, contact and ball integration. This can be introduced behind existing controller interfaces, not as a new physics engine.
4. **Make randomness opportunity-based:** contact entry/re-entry and block-shed/recovery have explicit IDs and one decision event (or a documented timestep-invariant hazard). Compare 60/120/240 Hz with identical event-addressed random streams.
5. **Reduce unneeded perception complexity:** use assigned `retro` behavior as the simple reference. Keep detailed FOV/delayed memory as a challenger only if it improves an observable metric without leaking information or harming stability.
6. **Retain shared rules/statistics:** GridIron emits live execution facts; LP applies the frozen V3 contract, rules, clock and player/team statistics. Any emitted but unmappable fact remains a named failure.

Paired experiment gates, following the updated LP design's diagnosis sequence:

| Stage | Setup and controlled change | Measures / pass condition |
|---|---|---|
| A. Isolated completion funnel | Run QB/receiver with no pressure/defender, then QB/receiver/defender fixtures. Keep route, throw, geometry and RNG fixed; vary reachability, catchability, and one rating independently. Include receiver-first, defender-first, unreachable and uncatchable trajectories plus one contact that persists, exits and re-enters. These are isolated fixtures, not 11-on-11 results. | Legal throws, viable reads, receiver/non-target reachability per throw, catchable frames, catch attempts, interceptions and sacks; verify one attempt per uninterrupted opportunity. |
| B. Numerical stability | Replay the same isolated setups at 60/120/240 Hz, with random stream keyed to play/player/opportunity rather than loop iteration. | Same opportunity/event ordering and comparable continuous trajectories; no growth of attempts merely from more integration ticks. |
| C. Saved 220 controlled ablations | First independently verify the reported candidate control against the exact stored calls and pinned inputs. Then vary one factor per comparison: assigned `retro` vs `detailed`; synthetic baseline vs named NFL-derived profiles; standardized vs original masses; mirrored direction in equivalent local coordinates; alternate authored pass concept; and contact-attempt ownership. Do not combine changes. Use event-addressed random streams where supported and preserve stream divergence otherwise. | Per throw: legal terminal category, viable reads, target/non-target reachability, catch attempts, catches, INTs, sacks, scrambles, throwaways, release/route timing, miss distance at arrival, pressure/separation, contact episode and draw IDs, velocity/trajectory, movement stability and runtime. Expect causal event hashes to differ after a fix; inspect each difference. |
| D. Controlled 11-on-11 plays | Only after A–C pass. Add one authored play diagram/front at a time; verify all 22 assignments and reaction rules. | Assignment execution, local interactions, decision latency, outcome distribution and reproducibility. |
| E. Full game / forecast batch | Only after play and rules integration gates. Use cutoff-valid rosters/ratings, immutable inputs, compact events and deterministic replay. | Reconciled score, clock, possession, penalties, player/team stats and execution coverage. Evaluate predictive quality separately from legal simulation. |

Trajectory error needs a timestamped observed trajectory target; aggregate Next Gen Stats cannot supply it. If no all-22 tracking or suitable event-level tracking is available, mark trajectory error unavailable instead of substituting final play outcome. Report confidence intervals clustered by source game, because the saved plays come from only three source-seed groups. Preserve only compact failing inputs, event IDs, controller decisions, positions around the event and hashes; do not write full-play trajectories for all successful calls.

## Acceptance status at audit time

| Gate | Status |
|---|---|
| Identify existing reusable architecture and gaps | **Reviewed**; matrix above. |
| Inspect Rush 2005 implementation and Rush 2008 distinction | **Reviewed** from source archive and primary research paper. |
| Baseline replay integrity for saved calls | **Passed for baseline**: 220/220 event hashes. |
| Candidate 220-call replay | **Agent-reported in LP `9dfdf4bf`; raw candidate artifacts and per-call hashes were not independently verified in this audit.** |
| Correct repeated interception attempts | **Code change present; reported draw reduction needs trace-level verification; timestep sensitivity remains open.** |
| Isolated and one-factor rating/interaction ablations | **Not run in this audit.** No fast-host execution was started. |
| Full paired retro-vs-detailed and other 220-call ablations | **Not run in this audit.** |
| All 22 role FSM contracts executed and verified | **Not yet demonstrated by this audit.** |
| Full autonomous-game acceptance gates | **Not assessed/passed here.** |

## Source notes

- LP V1 design: `docs/research/V1-COMPLETE-DESIGN.md` at `68a019dbe2f5a0d74d29bf25efe7db525ccd9714`.
- Player AI source: GridIron `engine/autonomous-run.js` (run state/read, lane selection, block and tackle behavior); `engine/autonomous/passing.js` (QB reads, contact latches, ball flight and pass execution); `engine/autonomous/special-teams.js`; `engine/autonomous/retro-cadence.js`.
- Shared movement/interaction: GridIron `engine/world.js` (`Player.locomote`, `World.engage`, `wrap`, contact/ball integration and sequential `World.step`).
- Assignment interface and generic diagrams: GridIron `engine/autonomous/assignments.js`, `example-assignments.js`, `simulator.js`; LP `scripts/nfl_sequence/gridiron_bridge.py`.
- Coaching, lifecycle and accounting: LP `scripts/nfl_sequence/autonomous_game.py`, `game_state.py`, `event_expansion_rules.py`, `game_stats.py`.
- Ratings provenance: LP `docs/MADDEN-RATINGS-DATASET-1992-2027.md`; LP `docs/research/RETRO-MIN-SF-RATINGS-AUDIT-2026-11-23.md`; GridIron `data/ratings.json` and game-specific ratings JSON; LP design's Next Gen Stats coverage table.
