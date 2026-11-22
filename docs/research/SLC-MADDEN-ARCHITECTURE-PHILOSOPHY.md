# SLC football architecture: Madden reference philosophy, V1-Pure, and V1 Complete

**Status:** Design principles and acceptance contract, **not an implementation or a certification of Madden behavior**.  
**As of:** 2026-11-22.  
**Primary current context:** [CONTEXT-2026-11-22.md](../CONTEXT-2026-11-22.md), especially §§6–7.  
**Related design/audit:** [SLC-V1-PURE-2026-11-21.md](SLC-V1-PURE-2026-11-21.md), [SLC-V1-PURE-INTRAPLAY-ORDER-AUDIT-2026-11-21.md](SLC-V1-PURE-INTRAPLAY-ORDER-AUDIT-2026-11-21.md), and the [Gridiron Physics end-to-end delivery plan](https://github.com/micahp/gridiron-physics/blob/main/docs/END-TO-END-FOOTBALL-SIMULATOR-DELIVERY-PLAN-2026-10-24.md).

## 1. The reference, and what it means

**Design reference: early-PS2-era Madden, roughly Madden NFL 2001–2002.** This is the intended *level and structure of football decisions*, **not** a request to recreate EA code, copyrighted plays/assets, exact per-edition AI behavior, ratings or gameplay probabilities. These titles/years were established as design references in prior discussion; the November 22 context file does **not** independently document or verify particular features of those editions.

The desired Madden-like philosophy is:

1. **Actual football intent:** a coach calls an actual offensive/defensive concept with personnel, formation and assignments rather than only drawing a marginal run/pass probability.
2. **Situational decisions:** down, distance, score, clock, field position, personnel and timeouts inform coaching behavior. The player/coach makes a decision *before* the resulting action is known.
3. **Players execute differently:** speed, movement, decision tendency, ability and uncertainty affect how a call unfolds. Ratings express abilities; tendencies express choice behavior. Do not turn a 0–99 game rating into physical force or directly copy EA ratings.
4. **The opponent matters:** defensive positioning, reads, pressure, pursuit, coverage and the competition for the ball change the result. A pass completion or interception is not an independent post-hoc label.
5. **Football happens in causal order:** call → pre-snap look/possible adjustment → snap → movement, blocking, QB decisions and ball action → catch/run/defense/contact → whistle → legal next-snap state.

This is a **simulation** rather than a human-controlled Madden game: the teams and players make their own choices. Forecast accuracy and event-frequency calibration remain separate evaluation goals. A more sophisticated simulation may still predict worse; do not assume increased mechanical detail automatically beats a statistical baseline.

### Presentation and complexity budget

- **V1 Complete field model:** top-down **2D** with players as dots, positions and speeds. The ball has horizontal position and **a height value along its flight path**. The height is modeled even though the field display is 2D.
- A defender reaching the ball carrier can stand in for a tackle initially. An intended target, receiver reach, catchable trajectory and opponent reach can determine a pass outcome. **Do not represent proximity as verified realistic collisions, blocks, or catches.**
- **Not required for V1 Complete:** 3D character animation, full rigid-body contact, limb-level physics, sophisticated visual presentation or an autonomous Madden-equivalent 22-player physics engine. If an interaction is simplified, label the mechanism.
- Reuse the authoritative SLC rules/game-state reducer; do not construct a competing clock/referee or conceal sampled fallbacks as physically caused results.

## 2. Names and version boundaries: do not confuse them

| Name | What it means | What it does **not** mean |
| --- | --- | --- |
| **Historical V1 / V1 full-stack** | Frozen reference model with accumulated play-call, outcome and historical-conditioning layers. The V1-Pure work began from frozen V1 `6895c2e3`. | **Not** “V1 Complete,” and not proof of Madden-like within-play execution. |
| **V1-Pure** | A deliberately simplified, legal statistical game generator based on V1. Keeps score-clock call, historical event pool, roster/participants, Dirichlet shares, rules/blocker fixes, plus later timeout decisions and a partial rule-based snap clock. | **Not** a snap-to-whistle causal simulator, even if game-state, stats, or clocks reconcile. |
| **V1 Complete** | **Next branch, starting from the end of V1-Pure.** This is where the missing football realism mechanisms and their acceptance gates are implemented. | **Not** the old V1 with every historical filter re-enabled. Not already complete merely because its name says “Complete.” |
| **PBV1** | Separate playbook experiment/workstream; a bridge toward actual named calls and assignments. | A personnel/formation label alone is **not** a validated full playbook or physical execution. |
| **V2 / personnel-first V2** | Separate model family with personnel → formation → call work; compare against V1 Complete after its gates. | Do not silently import V2's assumptions or measured improvements into V1 Complete. |

### V1-Pure: where it ends

On the context date, V1-Pure is the **base/control arm**, not the place for more realism features. Historical event-row filters, A–N pass labels/lifts, team and player outcome multipliers, coverage/formation-conditioned weights, streak adjustments and QB overrides are off by design. It avoids the documented pass-label sack suppression in the legacy V2/PBV1 path.

V1-Pure added:
- Independent offensive/defensive **timeout decisions after the whistle** based on actual situational rates.
- A **snap clock** that separates approximate live-ball time from rule- and tempo-governed dead-ball time for possession-retaining runs/passes.
- Legal game-state/rules enforcement and reproducible baseline checks.

**Limits:** It still samples **whole-play** historical events and outcomes. At the November 22 context cutoff, turnovers, scores and kicks still used sampled runoff, and penalties, injuries and reviews were missing. Thus “no sampled clock runoff” and football-ordered intra-play behavior were **not achieved**. The WAS–NYG week-10 diagnostic reported about **118 plays, 17.6 drives, 32.2 combined points** vs nflverse 2022–2025 references of **137, 21.7 and 44.5**. These are a scoped diagnostic, not universal calibration results.

The local commits `fa2438e8`, `db4f7d53`, `114c9323` cover the clock changes, with 7 snap-clock and 232 game/drive tests reported passing. The context said they were **local and unpushed**; do not assert publication or merge without a fresh repo check. **Freeze V1-Pure here** and put new realism work on V1 Complete.

### V1 Complete: what “complete” must require

The following are the initial gates supplied by the November 22 context, expanded here into explicit observations **without claiming they are implemented**.

| Gate | Requirement | Evidence needed |
| --- | --- | --- |
| **1. Clock and football stoppages** | **No sampled next-snap clock runoff** masquerading as gameplay. Derive live-ball time, dead-ball time, play clock and stoppages from legal rules and team decisions. Penalties are a dependency to resolve. | Per-play timeline, stop/restart reason, timeout count, boundary parity and held-out distributions of snaps/drive, timeouts, plays/game and points. |
| **2. QB in the pocket** | QB makes sequential decisions as protection, route development and defensive pressure evolve: wait/read, throw, scramble, sack, or throwaway. Do not select a terminal outcome up front and replay its appearance. | Deterministic traces: “wait, nobody open, sack”; “wait, nobody open, scramble”; “wait, nobody open, throwaway”; legal QB/ball states and decision information at each time. |
| **3. Ball in flight** | After release, a pass has a location, velocity, height/arc and arrival time. The ball is not just a `complete` or `intercepted` label. | Reproducible release, sampled/derived throw parameters, continuous flight and catchability checks; clear uncertainty about what is observed vs generated. |
| **4. Pass outcome from interaction** | Throw placement, defender, receiver route/movement, arrival timing, catch reach and **data-grounded** abilities govern completion, breakup or interception. | Trace of both receiver and defender reach/arrival; catch/ground/out-of-bounds legality; matched-condition tests. No independent interception weight applied after the fact. |
| **5. Football execution order** | Personnel and formation/called play are established before snap; the play call precedes the visible pre-snap look, which may provoke a defensive response or audible. Snap and live play precede whistle, rules and next snap. | Ordered causal event log; prohibited reads of future outcome; exact game-state invariants and source-tagged mismatch reports. |
| **6. Timeout decisions** | A team chooses its timeout based on observed state and legal availability, not whether the historical source row happened to be followed by one. | Carry forward V1-Pure's dedicated timeout decisions and tests; verify integration with complete clock/penalty mechanics. |

**Required ordering, as a contract:** select legal context → coaching intent/call, personnel and alignment → allow pre-snap observation/response/audible/timeout when modeled → snap and start live ball → player movement and developing reads → ball transfer/throw/flight and competing actions → contact/terminal result → whistle, score/possession/downs/fouls → dead-ball clock/timeout/substitution → next legal snap. The offensive **called play** must exist before its *visible execution*, and the generated play outcome must not be fed backward to earlier decisions. The order within the coaching/package selection should follow the actual model's explicit contract rather than an undocumented shortcut.

**Do not conflate two distinct tests:** a reducer can reconstruct the correct next-play state from an *externally fixed historical event* (boundary-transition parity) while the simulator still fails to generate the event in causal football order (intra-play fidelity). See the V1-Pure order audit.

## 3. Ability inputs: real football data, not Madden ratings

The context explicitly requires **data-grounded ratings/traits**, not importing abilities from a video game. Potential inputs to audit include nflverse/Next Gen Stats-style **QB time to throw, air yards and completion above expected**, and **receiver separation/cushion**. Their 2022–2026 coverage was **not yet checked** in the source context.

For every player ability or tendency, record source, observed season/window, identity, denominator, measurement/uncertainty, prediction-time cutoff and fallback. Do not claim a QB's observed mean time to throw dictates a fixed release time. Do not silently use post-snap data from the play being simulated to decide earlier actions. If a value is missing, use an explicit prior or label the capability unmodeled.

## 4. Reality checks: mechanics, statistics and predictive value differ

1. **Football integrity:** legal state transitions, downs/spot/possession/score, clock rules, permitted player identities, causally ordered actions and no future-event lookahead.
2. **Mechanics/coherence:** actual continuous decision traces, credible movement and ball geometry, correct catch/tackle ordering, coherent players/roles, and honest labels on abstractions.
3. **Game distribution:** chronological held-out snaps, runs/dropbacks, sacks, interceptions, drives, red-zone scoring, penalties/timeouts, total points, tails and relevant player stats; compare against actual eligible games and the cheap V1-Pure baseline.
4. **Forecasting:** score-based metrics such as Brier/log loss and market comparison where the product needs forecasts. A realism pass is not market outperformance, and a statistical improvement is not proof of causal simulation.

Avoid changing multiple mechanisms just to make point totals match. Preserve matched snapshots and source provenance. For cross-commit model comparisons, **same seed ID is insufficient**: the share-model reference fingerprint includes the source commit, is resealed into the snapshot, and changes stream initialization. Pin identical snapshot bytes, code/data refs and report precisely which randomness can or cannot be paired.

## 5. Architecture boundaries with other work

- **SLC V1 Complete owns** the game/drive state and 2D causal football sequence for the selected supported play families.
- **PBV1 owns** research into realistic named-play representation, calls and assignments; adapt explicitly only after its support and correctness are established.
- **Gridiron Physics owns** optional later 3D/physical execution and viewing, not a hidden precondition to V1 Complete's 2D MVP. A physical result requires a versioned authority handoff to SLC's rules reducer.
- **V2 and other arms** are comparison candidates, not mechanisms automatically enabled to make V1 Complete's gate labels green.
- **Original V1** remains unchanged as a historical control. **V1-Pure** remains the minimal baseline.

No change to production forecasts, model-pack publication, live picks, grading, or app releases follows from this design. The November 22 context records the decision that **a model is released only when it beats the market as a reproducible experiment**; SLC model packs are not app release assets, and no per-model Git tags are desired.

## 6. Open decisions and explicit unknowns

- **Penalties in V1 Complete:** **user decision remains open.** They are needed for the proposed no-sampled-runoff clock gate. V1.7 reportedly has a 16-foul engine, but its clock behavior has **not** been audited. Evaluate reuse and rules integration before inclusion. Do not claim the gate passed while penalty-driven stoppages remain unmodeled.
- **Reference titles:** Madden NFL 2001–2002 is a design-era reference from discussion, **not verified evidence of exact EA feature internals**. If comparing individual historical editions, independently document what they actually supported; do not backfill imagined capabilities.
- **2D representation:** player-dot proximity and ball height are deliberate simplifications. They support a causal model but do not by themselves certify physical catches, tackles, blocking or locomotion.
- **Ratings coverage:** 2022–2026 candidate player measurements are unverified; obtain actual coverage/rights/cutoff evidence before relying on them.
- **V1 Complete build status:** at the source cutoff, it was the **next branch** to start from V1-Pure, not an implemented or passing simulator.
- **Missing work remains missing:** injuries, reviews, expanded play families and realistic contact may be explicitly deferred, but must not be silently treated as handled.

## 7. Immediate handoff to the V1 Complete agent

1. Preserve V1-Pure and its timeout/clock tests as a frozen, runnable comparison baseline. Branch V1 Complete from the correct final V1-Pure commit once accessible, not from old historical full-stack V1.
2. Begin with a **phase-separated executable event schema and trace** for a minimal supported run and pass. Explicitly record what the coach knew before snap, what the QB knew while reading, ball flight and the whistle/next-snap boundary.
3. Show one legal complete run sequence and one pass each for completion, breakup/incompletion, interception, QB sack, scramble and throwaway where implemented; mark unsupported families accurately.
4. Audit V1.7 penalties against stoppage/clock rules and raise the inclusion decision rather than papering over missing time with sampled runoff.
5. Only then expand matchups, calibrate abilities and compare held-out game distributions against unchanged V1-Pure. Do not substitute a successful box score or test total for evidence of intra-play causality.

**Bottom line:** Madden is a reference for the *organization of football decisions*, not for source probabilities or graphics. V1-Pure is the clean statistical control. **V1 Complete is the first attempt to make the game happen in football order**, within a deliberately simple 2D world.
