# NHL Game Rules and Validity Specification

Date: 2026-10-26
Branch: `research/nhl-game-rules-validity-2026-10-26`
Base: Legendary Picks `60c428ada77a643d9560af60f1f971f7f7575664`
Scope: validation contract for the statistical full-game event generator and later hockey event consumers

## Purpose

Define what an NHL simulation must prove before it can be described as a valid game. This is a rule and validation specification, not an implementation or a claim that the current generator is a complete hockey simulator.

The current v0.2b generator samples historical period templates, retaining donor event slots, clock locations, and shift intervals. Its transition model conditions event-family samples on recent event family, known/unknown possession, manpower, and score state. It does not independently create all live play opportunities, enforce post-goal faceoffs, model rink geometry, or select substitutions with an autonomous coaching policy. Its event and accounting validator checks useful invariants, but passing it does not establish compliance with all NHL playing rules.

The rules document must therefore support two different conclusions:

- **Structurally valid:** clocks, periods, score, penalty state, personnel, restarts, and special game endings satisfy every deterministic check that the record can support.
- **Fully rule-assessed:** every potentially applicable playing rule has enough state evidence to assess the call and its consequences. Without puck/player positions and declared officiating decisions, a statistical event record cannot earn this status.

Never turn missing evidence into a pass. A game with a confirmed illegal state is invalid; a game with important unassessed rules is only partially assessed.

## Authoritative rule sources and versioning

Use the official NHL rulebook for the season and game type being simulated. Do not apply today's book retroactively to a historical game without checking the applicable edition and amendments.

| Rule set | Official source | Locally verified PDF SHA-256 |
|---|---|---|
| 2021–22, the season represented by the paired development evaluation | [NHL Official Rules 2021–2022](https://media.nhl.com/site/asset/public/ext/2021-22/2021-22Rules.pdf) | `17ef416dcb556f510df51efd45451e8d37da80da9e69488f78e3d8771228caa7` |
| 2026–27, the current season on this document date | [NHL Official Rules 2026–2027](https://media.d3.nhle.com/image/private/t_document/prd/i9yumvyaojps5kixzaxz.pdf) | `3c7a8cc932144565a798b57926e11f61d2686d8c9538d2a3f06c51c8380003f0` |

The [NHL Video Rulebook](https://www.nhl.com/info/video-rulebook) is an official visual aid for examples and enforcement. The written season rulebook controls. The [NHL historical rule changes page](https://records.nhl.com/history/historical-rule-changes) is a starting index for changes, not a substitute for comparing the editions that bracket the target season.

Before generating a game, freeze a `ruleset_id` containing at least:

- NHL season, regular-season or playoff game type, and scheduled puck-drop date.
- Rulebook edition, official source URL, PDF SHA-256, and any applicable published amendments.
- Regular-season/playoff overtime and shootout policy for that edition.
- Rink coordinate convention, dimensions, faceoff locations, home/away orientation, and clock conventions.
- The generator, validator, and event-schema versions.

The 2021–22 and 2026–27 editions both contain Rules 1–87, but that is not proof every intervening rule provision is identical. Build an edition-specific ruleset instead of assuming one timeless NHL rule configuration.

## Validation result vocabulary

Each rule check and each game-level summary must use one of these outcomes:

| Status | Meaning |
|---|---|
| `PASS` | Required evidence is present and the rule check passed. |
| `FAIL` | Evidence proves a rule violation or an invalid state transition. The game must not be emitted as valid. |
| `NOT_ASSESSED` | Required state or a rule decision is absent. This is not a pass. |
| `QUARANTINED` | Inputs conflict, the applicable rule edition is unknown, or the event cannot be reconciled safely. |
| `NOT_APPLICABLE` | The rule could not apply to this game or event, with a recorded reason. |

Game-level outcomes:

- `structural_valid=true` only when all required mechanical checks pass and none fail or remain unassessed in the supported structural scope.
- `full_rule_assessed=true` only when every applicable rule has been assessed from sufficient evidence or a recorded official ruling and all consequences pass.
- `valid_full_game=true` may be emitted only when both conditions hold. A game with an unassessed geometry-dependent or officiating-dependent rule must be labeled partial, even if its totals reconcile.

The current statistical simulator has no complete spatial-action record, so it cannot currently claim `full_rule_assessed=true` for a generated game.

## Required immutable event and state contract

The validator must consume an ordered event ledger, not just a final score or aggregate totals. Every event must preserve:

- Game identity, `ruleset_id`, game type, sequence number, period type/number, elapsed and remaining clocks, and state before/after.
- Event family and team ownership; participants by stable player ID; on-ice skaters, goalkeeper, extra-attacker state, and strength for each team.
- Active penalty ledger: infraction class, rule number when known, assessed player, serving player, duration/segments, start and expiry clocks, coincidental status, delayed status, and release reason.
- Stoppage cause and the required next faceoff location; faceoff spot and winner/loser; puck zone/position when the rule requires it.
- Goal ruling and evidence, including whether a goal is official, disallowed, awarded, penalty-shot, shootout, or an ordinary goal event.
- Substitution, injury, goalkeeper removal/return, penalty-box entry/exit, and shift intervals.
- For geometry-dependent rules: puck coordinates, player coordinates, attack direction, puck control/possession evidence, rink geometry, and the event observations needed to evaluate the rule.
- A rule-decision record identifying whether the call was observed in an official source, sampled by a statistical policy, computed by a geometry/rules engine, or manually adjudicated. The validator must not pretend these sources are interchangeable.

If a source reports only an official event label, preserve it as an observed call. Do not invent unseen passes, puck positions, offside status, player intent, or referee reasoning.

## Core game-state invariants

These are mandatory for every regular-season game unless the pinned rule edition says otherwise.

### Periods, game clock, and end state

1. Regulation consists of three ordered periods of 20:00. A period has one start and one terminal boundary, events remain inside its clock, and no event follows game end.
2. The canonical internal clock is integer seconds remaining or elapsed, with one documented conversion. Event order is nondecreasing within a period. An event at the horn or a delayed-whistle event that reaches 0:00 requires source timing/adjudication evidence; do not resolve second-level ambiguity by assumption.
3. Game start and each period restart begin with the required center-ice faceoff sequence. A regulation game does not enter overtime unless tied after the third period.
4. Regular-season overtime is a maximum five-minute sudden-death period. Its normal base strength is three skaters and a goalkeeper per side, subject to the edition's penalty-state tables and overtime rules. A valid overtime goal ends the game immediately.
5. A regular-season tie after overtime proceeds to a shootout. A playoff tie proceeds through successive 20-minute sudden-death overtime periods; it never enters the regular-season shootout path.
6. A completed regular-season game has one winner and a legal official final score. In a shootout decision, the official team score receives exactly one deciding goal beyond the overtime score. That shootout deciding goal is not a player goal and is not charged as a goal against to the losing goalkeeper.

### Roster, player eligibility, and on-ice strength

1. Every active player and participant belongs to the frozen pregame eligible list. Identity must be by stable NHL player ID, not display name.
2. Validate roster composition under Rule 5 for the pinned edition. Distinguish the submitted eligible list from the currently active on-ice lineup; do not treat every rostered player as dressed or available without evidence.
3. An on-ice player cannot also be serving an active penalty or be ejected/ineligible. Each team has at most one goalkeeper on the ice. A pulled goalkeeper is represented as absent and the extra skater is represented explicitly.
4. Derive skater counts from the active penalty ledger and game type, not from a donor strength label. Enforce the edition's limits, minimums, and overtime adjustment tables. Validate each event's strength label against the actual on-ice players.
5. A penalty expiration or early release changes eligibility only under the relevant penalty rule. If the player cannot legally return at that moment because of the team-strength floor or period/overtime transition rules, record the later legal return point.

### Penalty and manpower state machine

The penalty system must be one ordered state machine shared by event generation, personnel selection, and validation. A sampled penalty cannot be applied after a shift template has independently fixed illegal personnel.

- **Minor and bench minor:** two minutes. A bench minor names a legal serving skater. A minor may end early after a qualifying power-play goal against a shorthanded team, according to Rule 16 and its exceptions.
- **Double minor:** two sequential two-minute segments, not one opaque four-minute block. A qualifying goal can end the first segment; the second remains active.
- **Major and match:** their prescribed full time/ejection consequences are not cancelled by an ordinary power-play goal. A match penalty removes the player; its serving and manpower consequences follow its rule.
- **Misconduct/game misconduct:** distinguish a player's removal/eligibility from whether the team is shorthanded. A ten-minute misconduct, game misconduct, and match penalty have different shootout eligibility consequences.
- **Coincidental penalties:** apply the rulebook's coincidental pairing and manpower tables; equal penalties do not automatically create a power play.
- **Goalkeeper penalties:** the goalkeeper's rule-specific penalty is served by a legal skater when required; do not put the goalkeeper in the penalty box as an ordinary skater or remove the goalkeeper unless a separate substitution event is legal.
- **Delayed penalty:** preserve the delayed state until the legal whistle condition. If a goal occurs before the whistle, apply Rule 15's minor/major/match distinctions and required penalty washout/release logic.
- **Expirations:** use the game clock, correct penalty ordering, segment boundaries, simultaneous-expiry procedure, and stoppage requirement. Every expiry, release, and return must reconcile to the active ledger.
- **Penalty shots/awarded goals:** these are separate outcomes. A penalty-shot goal does not release an active minor penalty; a qualifying awarded goal is not a fabricated shot event.

Mandatory properties include: no negative penalty time; no missing expiry/segment event; no penalized player on ice; no early player return; legal serving player; legal manpower after each goal, expiry, stoppage, and period transition; and no more than one applicable early-release consequence for the same penalty segment.

### Stoppages, faceoffs, and goals

1. Every stoppage that resumes play has exactly one legal restart. The faceoff must be one of the nine marked spots, with location derived from the actual stoppage cause and the priority rules in Rule 76.
2. A goal normally requires a center-ice faceoff before play resumes. Exceptions are terminal game-ending goals and a period/game boundary where no play resumes. A score update without a corresponding restart or terminal state is invalid.
3. A goal increments the scoring team's score once and, for ordinary game play, counts as a shot on goal under the selected official scoring definition. A shootout attempt/decision uses separate accounting.
4. A goal event must be supported by an official/source ruling or a simulation geometry/rule decision. Without puck/goal-line and applicable illegal-goal evidence, the validator may check accounting but must mark goal legality `NOT_ASSESSED`.
5. The faceoff winner changes the next possession state in the simulator. Merely recording a winner while retaining a preselected unrelated next event is an attribution-only transition, not a causal faceoff model.

### Substitutions, goalkeepers, and shootouts

- Validate player-on/player-off transitions, line-change windows after stoppages, icing and other no-change exceptions, on-the-fly substitution boundaries, penalty-bench returns, and too-many-men consequences using Rules 68, 71, 74, and 82.
- Validate goalie pull/return as explicit personnel events. In regular-season overtime, a pulled goalkeeper cannot return on the fly before a stoppage. A goalie change during a shootout is permitted only under the applicable injury exception; it cannot be sampled as an ordinary substitution.
- A shootout occurs only in a regular-season game tied after overtime. Alternate the selected shooting order after the home team's permitted choice; stop as soon as the result is mathematically decided; after three attempts per side, use sudden death. No shooter repeats until every eligible shooter has attempted, subject to the rule's unequal-eligibility exception.
- Select shooters only from the game's submitted eligible-player list, then exclude players barred by Rule 84.4 (including players serving a ten-minute misconduct, players assessed a game misconduct or match penalty, and the player designated to serve a goalkeeper misconduct). Keep shootout attempts and goals out of ordinary player goal totals. Reconcile the official deciding goal and losing-goalie statistics separately.
- **Goalkeeper as shootout shooter:** Rules 5.1 and 84.4, in both inspected editions, define “player” to include goalkeepers and say all players are eligible subject to the listed exclusions. They do not categorically prohibit a goalkeeper from shooting. Do not label a goalie in the shooter pool a rule violation based on position alone. The implementation risk is that its pool comes from every player in a club roster snapshot, not a verified game-specific eligible list, and does not apply Rule 84.4 exclusions. Whether additional official interpretation narrows goalkeeper participation remains unverified.

## Rulebook coverage map: Rules 1–87

Every rule in the current NHL rulebook must be represented in the ruleset inventory. The categories below identify the evidence needed; they do not claim every rule can be decided from a statistical event stream.

Legend: **L** = deterministic event/ledger consequence; **G** = geometry/action evidence; **J** = referee, scorer, or league judgment; **S** = static configuration or roster evidence; **A** = administrative evidence.

| Rule | Subject | Validator coverage and evidence category |
|---:|---|---|
| 1 | Rink | Pin rink dimensions, markings, zones, and coordinate transforms; source/config check (**S/G**). |
| 2 | Goal Posts and Nets | Goal position, displaced net, and puck crossing evidence; goal legality cannot be inferred from a score label alone (**G/J**). |
| 3 | Benches | Pin bench locations and legal entry/exit boundaries for substitutions (**S/G**). |
| 4 | Signal and Timing Devices | Reconcile period clock, horn/end boundaries, and any timing correction evidence (**L/A**). |
| 5 | Team | Validate eligible list, roster roles, team membership, and goalkeeper constraints (**S/L**). |
| 6 | Captain and Alternate Captains | Validate submitted leadership if present; protests/official discussion require declared calls (**S/J**). |
| 7 | Starting Line-up | Starting players must be eligible and match the frozen submitted lineup; changes require the permitted approval path (**S/L**). |
| 8 | Injured Players | Injury, replacement, penalty-service, and return events require explicit availability evidence (**L/J**). |
| 9 | Uniforms | Uniform, number, and team-color requirements are pregame compliance inputs, not inferred from score events (**S/A**). |
| 10 | Sticks | Dimensions, materials, measurement requests, and illegal-stick rulings require equipment/call data (**S/J**). |
| 11 | Goalkeeper's Equipment | Equipment and goalkeeper-specific restrictions require equipment records and declared enforcement (**S/J**). |
| 12 | Illegal Equipment | Validate only recorded inspection/ruling and its penalty consequence (**J/L**). |
| 13 | Puck | Pin the official puck/configuration for the season; validate physical behavior only in a supported motion model (**S/G**). |
| 14 | Adjustment to Clothing or Equipment | Adjustment must occur at a legal stoppage or replacement event; otherwise require an official ruling (**L/J**). |
| 15 | Calling of Penalties | Validate delayed whistle, possession/whistle trigger, and goal-before-whistle consequences (**L/J**). |
| 16 | Minor Penalties | Validate two-minute duration, shorthanded status, legal early release, and penalty-shot exception (**L**). |
| 17 | Bench Minor Penalties | Validate team penalty, legal designated server, two-minute duration, and manpower effect (**L**). |
| 18 | Double-minor Penalties | Track two two-minute segments and any legal first-segment termination (**L**). |
| 19 | Coincidental Penalties | Pair events and apply the edition's coincidental penalty/manpower table (**L/J**). |
| 20 | Major Penalties | Validate full major time, serving player, ejection linkage, and no ordinary goal release (**L**). |
| 21 | Match Penalties | Validate player removal, serving assignment, manpower, and eligibility consequences (**L/J**). |
| 22 | Misconduct Penalties | Validate duration and player eligibility separately from team manpower (**L**). |
| 23 | Game Misconduct Penalties | Remove player from later events and apply any associated serving/manpower effects (**L**). |
| 24 | Penalty Shot | Validate award, designated shooter, attempt mechanics/result, clock exclusion, restart, and associated penalty handling (**L/G/J**). |
| 25 | Awarded Goals | Validate qualifying event and official scoreboard award without fabricating an ordinary shot (**L/G/J**). |
| 26 | Delayed Penalties | Preserve delayed state, legal whistle trigger, and expiration/release ordering (**L**). |
| 27 | Goalkeeper's Penalties | Validate goalkeeper treatment, substitute server, goalkeeper presence, and any ejection/replacement (**L/J**). |
| 28 | Supplementary Discipline | Apply known pregame suspensions/eligibility; postgame league discipline is outside the simulated game (**A**). |
| 29 | Signals | Preserve the called infraction and official signal when sourced; don't infer a penalty from a signal-free stat label (**J/A**). |
| 30 | Appointment of Officials | Validate official assignments when the artifact claims them; not an on-ice action model (**A**). |
| 31 | Referees | Treat referee decisions as declared adjudications; validate their resulting state changes (**J/L**). |
| 32 | Linespersons | Treat faceoff, icing, and offside calls as adjudications unless geometry and decision policy are modeled (**J/G**). |
| 33 | In-Arena Scorer | Reconcile official goal/player attribution to the game event ledger (**A/L**). |
| 34 | Game Timekeeper | Reconcile game-clock advancement, stoppages, period boundaries, and corrections (**L/A**). |
| 35 | Penalty Timekeeper | Reconcile penalty clocks, segments, releases, and penalty-bench returns (**L/A**). |
| 36 | Real Time Scorers | Reconcile shot, save, goal, hit, and other credited statistics under the selected definition (**A/L**). |
| 37 | Video Review | If modeled, validate review eligibility, ruling, score/time correction, and restart; otherwise mark unassessed (**J/A**). |
| 38 | Coach's Challenge | Requires challenge state, allowed window, outcome, and resulting penalty/clock/restart effects (**A/J/L**). |
| 39 | Abuse of Officials | Requires an observed or simulated infraction ruling; validate assessed penalty/ejection only (**J/L**). |
| 40 | Physical Abuse of Officials | Requires an observed or simulated infraction ruling; validate penalty/ejection only (**J/L**). |
| 41 | Boarding | Requires contact, player motion/location, and an officiating severity decision; validate penalty consequence (**G/J/L**). |
| 42 | Charging | Requires approach/motion/contact evidence and an officiating decision (**G/J/L**). |
| 43 | Checking from Behind | Requires relative orientation/contact evidence and an officiating decision (**G/J/L**). |
| 44 | Clipping | Requires contact height/body-position evidence and an officiating decision (**G/J/L**). |
| 45 | Elbowing | Requires contact/action evidence and an officiating decision (**G/J/L**). |
| 46 | Fighting | Requires actor/action chronology, entry/leave-bench state, and penalties/ejections (**G/J/L**). |
| 47 | Head-butting | Requires action evidence; validate the resulting penalty class and consequences (**G/J/L**). |
| 48 | Illegal Check to the Head | Requires contact location, force/action evidence, and official classification (**G/J/L**). |
| 49 | Kicking | Requires contact/action evidence and official classification (**G/J/L**). |
| 50 | Kneeing | Requires contact/action evidence and official classification (**G/J/L**). |
| 51 | Roughing | Requires action/context and official classification (**G/J/L**). |
| 52 | Slew-footing | Requires action/contact evidence and official classification (**G/J/L**). |
| 53 | Throwing Equipment | Requires equipment trajectory/context and official classification (**G/J/L**). |
| 54 | Holding | Requires stick/body contact and opponent-motion evidence (**G/J/L**). |
| 55 | Hooking | Requires stick contact/control evidence and official classification (**G/J/L**). |
| 56 | Interference | Requires puck possession, opponent eligibility, and contact/action timing (**G/J/L**). |
| 57 | Tripping | Requires action/contact evidence and official classification (**G/J/L**). |
| 58 | Butt-ending | Requires stick action evidence and official classification (**G/J/L**). |
| 59 | Cross-checking | Requires stick/contact evidence and official classification (**G/J/L**). |
| 60 | High-sticking | Requires stick/puck/player height and contact evidence; distinguish a foul from a legal follow-through (**G/J/L**). |
| 61 | Slashing | Requires stick action/contact evidence and official classification (**G/J/L**). |
| 62 | Spearing | Requires stick action/contact evidence and official classification (**G/J/L**). |
| 63 | Delaying the Game | Validate the specific trigger, required penalty/penalty-shot/awarded-goal consequence, and restart (**G/J/L**). |
| 64 | Diving / Embellishment | Requires actor behavior and an officiating judgment; do not infer from a penalty alone (**G/J**). |
| 65 | Equipment | Validate declared equipment infraction and resulting penalty/repair procedure (**S/J/L**). |
| 66 | Forfeit of Game | Treat only as an explicit league/official terminal ruling; never synthesize as a normal game outcome (**A/J**). |
| 67 | Handling Puck | Requires hand/body contact, zone, and faceoff-phase evidence; validate stoppage/penalty consequence (**G/J/L**). |
| 68 | Illegal Substitution | Validate roster eligibility, penalty-bench return, injured-player replacement, and goal consequences (**L/J**). |
| 69 | Interference on the Goalkeeper | Requires crease, contact, movement, possession, and referee judgment; validate goal/penalty/restart outcome (**G/J/L**). |
| 70 | Leaving the Bench | Requires bench-entry/exit and incident chronology; validate penalties and participation (**G/J/L**). |
| 71 | Premature Substitution | Validate goalkeeper/extra-attacker and line-change state from on-ice transitions (**G/L**). |
| 72 | Refusing to Play the Puck | Requires puck accessibility and player/official context; validate the declared delay ruling (**G/J/L**). |
| 73 | Refusing to Start Play | Validate restart deadlines and declared warning/penalty consequences (**A/J/L**). |
| 74 | Too Many Men on the Ice | Validate bench exchange timing, active skaters, extra-attacker state, and any resulting penalty/goal ruling (**G/L/J**). |
| 75 | Unsportsmanlike Conduct | Requires declared conduct ruling; validate penalty/ejection and eligibility (**J/L**). |
| 76 | Face-offs | Validate legal spot, restart reason, participants, faceoff procedure evidence, and possession update (**G/L/J**). |
| 77 | Game and Intermission Timing | Validate period length, intermission/timeout record where present, and legal clock transitions (**L/A**). |
| 78 | Goals | Validate goal event, score, scorer/assists, disallowed-goal conditions, and ensuing center-ice restart (**G/L/J**). |
| 79 | Hand Pass | Requires hand contact, zone, and teammate touch evidence; validate the correct whistle/restart (**G/J/L**). |
| 80 | High-sticking the Puck | Requires puck height, touch/goal context, and official decision; validate stoppage/goal consequence (**G/J/L**). |
| 81 | Icing | Requires rink coordinates, puck path, touch, goalkeeper state, and race-to-puck determination; validate stoppage, line-change restriction, and restart (**G/J/L**). |
| 82 | Line Changes | Validate stoppage line-change windows, icing restrictions, substitutions, and goalie changes (**G/L**). |
| 83 | Off-side | Requires puck/player positions at the blue line, possession/control, delayed offside, and any review ruling (**G/J/L**). |
| 84 | Overtime | Select regular-season or playoff branch; validate format, manpower, penalty transitions, sudden death, shootout, and official score (**L**). |
| 85 | Puck Out of Bounds | Requires puck path, last touch/origin, and arena boundary evidence; validate whistle, clock correction, and faceoff spot (**G/J/L**). |
| 86 | Start of Game and Periods | Validate center-ice start, period order, team ends, and intermission restart (**L/A**). |
| 87 | Time-outs | Validate one team timeout, duration, stoppage-only use, and no shootout timeout (**L/A**). |

The official reference tables are part of the ruleset, especially the penalty summaries, penalty-shot/awarded-goal summaries, short-handed goal-release table, coincidental-penalty table, goalie-interference examples, and regular-season overtime penalty tables. The validator must use the tables from the pinned edition instead of re-deriving them from a partial prose summary.

## Current v0.2b gaps confirmed by code inspection

These are immediate validation blockers, not a full legal audit of all 87 rules:

1. `generate_game()` selects donor regulation periods and retains source event slots and times. B2 samples a transition family at those slots; the model manifest itself describes the donor clock/count scaffold. This cannot let a trailing team's policy independently create new attack times.
2. The B2 transition context has prior event family, known/unknown possession, strength, and score state. It has no explicit zone, puck position, time remaining, faceoff cause, or tactic/action state. A goal is not an explicit transition family that forces the next center-ice faceoff.
3. `_live_on_ice()` reconciles donor candidates and fills missing skaters by usage/shot-rate ordering. That maintains a ledger but is not a substitution policy driven by a coach, fatigue, or tactical line matching.
4. `calibrate_fivevfive_offsets()` fits SOG/goal offsets on regulation 5v5 donor opportunities. B2 reuses those offsets when generating transition shots across event states. Require a separate calibration-validity analysis for non-5v5 strength states; rule-state validity does not validate this scoring calibration.
5. The shootout shooter pool is built from every player in the frozen club roster snapshot, rather than a verified game-specific submitted lineup, and does not filter Rule 84.4 ineligible players. Goalkeeper inclusion alone is not a rule violation under the inspected rule text; the unverified game-lineup eligibility and exclusion handling are the issues to resolve.
6. Existing `validate_generated_game()` checks sequence and clocks, score/SOG/player accounting, a subset of penalty/manpower transitions, regular-season overtime/shootout termination, roster membership, and shift-ledger reconciliation. It does not validate all rulebook topics, faceoff locations and mandatory goal restarts, offside, icing, goalie interference, or other geometry-dependent calls.

Relevant implementation: [`nhl_game_state_sim.py`](../../research/nhl/statistical-full-game-v0.2b/nhl_game_state_sim.py), especially `fit_event_transition_model`, `calibrate_fivevfive_offsets`, `_live_on_ice`, `_shootout`, and `validate_generated_game`.

## Acceptance gates before a game can be called valid

### Gate 1: Rule-state integrity

- Ruleset and game type are frozen and season-correct.
- Every emitted game has zero hard-invariant failures: legal roster IDs, clocks, periods, manpower, penalty expirations/releases, legal on-ice roles, stoppage/restart sequence, goal/score sequence, terminal state, and regular-season/playoff overtime policy.
- Any unsupported rule state (including an unhandled penalty class, unmodeled special state, contradictory roster, or unresolved terminal event) quarantines that game; the validator must not silently drop the event or repair personnel by arbitrary rank.
- Independent whole-game audit reports pass/fail/unassessed counts by rule and event family. The generated summary is not the independent validator.

### Gate 2: Gameplay causality

For fixed pregame inputs and seed, controlled changes must produce only rule-legal, explainable downstream effects:

- A different faceoff winner changes the next possession and can change subsequent opportunities.
- A penalty changes the manpower/penalty ledger immediately and affects legal event opportunities until expiration/release.
- A goal changes score, applies a legal qualifying penalty release if any, and creates a center-ice restart unless the game ends.
- A goalie change affects the defending goalie and saves only after a legal substitution transition.
- A line change changes the on-ice players through a legal stoppage/on-the-fly change policy, not donor re-mapping alone.

Passing accounting while all downstream event slots remain fixed is not sufficient evidence of causality.

### Gate 3: Gameplay realism and evidence coverage

- Compare generated event sequences, faceoff/restart causes, team possessions, penalties, manpower, shots, goals, overtime, shootouts, shifts, and player deployment against independent NHL GameCenter/box-score/shift evidence on identical eligible games.
- Report full population counts, quarantine and missing-state reasons, rule-assessment coverage, and uncertainty. A missing event field is unknown, not proof that the corresponding rule was satisfied.
- Keep statistical forecast metrics (Brier/CRPS) separate from legality and realism. Passing a scoring metric cannot waive a rule failure.
- Require genuinely unseen later-season or prospective games for adoption. The 2021 population is development-only and 2022 is exposed.

## Implementation order

1. Add the season/game-type ruleset manifest and status vocabulary to generated game artifacts.
2. Build an independent validator for clocks, periods, rosters, penalty ledger, manpower, goalkeeper presence, goals, stoppages, faceoff restarts, regulation/OT/shootout, and team/player accounting. Use official reference tables as the expected transition table.
3. Repair penalty state and post-goal restart generation before adding more statistical tuning. Make illegal state transitions fatal and preserve the failed seed and event sequence for diagnosis.
4. Add explicit substitution/goalie policies and validate lineup changes against Rules 68, 71, 74, and 82.
5. Extend the state representation with rink zones, puck/player positions, attack direction, and declared rule decisions before claiming automated offside, icing, goalie-interference, hand-pass, high-stick, or out-of-bounds validation.
6. Add real-source whole-game fixtures and counterexamples for each supported rule family. Hand-authored fixtures can supplement but cannot be the only oracle. Compare generated cases against independently sourced NHL events and record the source hash.
7. Re-run the paired development evaluation only after the rules gate passes. Do not tune Brier scores to compensate for an invalid or incomplete game process.

## Coverage limitation of this specification

This document inventories all 87 rule headings in the inspected official editions and specifies the evidence class and validation consequence needed for a full-game engine. It paraphrases the rules and does not reproduce the rulebook. It is not a clause-by-clause legal opinion, does not enumerate every reference-table exception, and does not replace NHL rule interpretations, official scoring guidance, or season-specific amendments. Before implementing a rule family, read that complete rule and its cited notes/tables in the exact edition pinned for the target game. Where those materials leave a case unresolved, keep the case unassessed until an authoritative NHL ruling or precedent resolves it.
