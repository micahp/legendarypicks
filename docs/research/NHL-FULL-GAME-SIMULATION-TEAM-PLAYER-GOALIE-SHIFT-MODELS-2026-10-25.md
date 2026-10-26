# NHL Full-Game Simulation: Team, Player, Goalie and Shift Models

**Projects:** Legendary Picks + Gridiron Physics
**Starting branch:** `research/nhl-statistical-full-game-2026-10-25`
**Status:** Research implementation specification
**Target:** Statistical simulation v0.2 and v0.3, with a later physical execution integration.

## 1. Objective

Extend the existing NHL statistical full-game generator so that a simulated matchup reflects the actual participating teams, eligible players, goaltenders, strengths, and decisions made during the game.

Today v0.1 samples complete historical period templates. Team names do not affect the generated results.

The target system should answer:

- Which team is more likely to control play?
- Which players are on the ice and how are they deployed?
- Who is most likely to create a shot?
- Where does the shot come from, and who is defending it?
- How likely is the goalie to save it?
- When do teams substitute, change tactics, or pull their goalie?
- How do these decisions change the remainder of the game?

The simulator must produce an internally consistent chronological game record and allow many seeded games to be sampled from one frozen pregame matchup.

It must not use the actual outcomes, lineups, goalie starts, or substitutions from the target game as prospective inputs.

## 2. Existing systems and data

Preserve and reuse the current work where appropriate:

| Component | Current status | Next action |
|---|---|---|
| NHL GameCenter PBP | 4,876 archived games | Reuse verified source |
| NHL box scores | Verified against PBP | Reuse |
| Statistical v0.1 | Complete event stream | Freeze as baseline |
| Team-strength models | Existing research candidates | Benchmark and adapt |
| NHL player identities | NHL-native ID ingestion exists | Audit historical coverage |
| Current NHL rosters | Existing ingestion | Add as-of-game snapshots |
| NHL player game logs | Existing ingestion | Audit historical depth |
| NHL shift charts | Not in verified v0.1 corpus | Audit, acquire separately |
| Goalie save model | Not established | Build |
| Gridiron hockey movement | Isolated research adapter | Integrate only after validation |

The current Gridiron hockey adapter is available in research commit `c35d1ba7e395f2a0a93f493b441cfe40ed21ba1f`. Do not assume it is already part of Gridiron main.

Historical PBP time splits remain:

- 2019–2020 start seasons: initial training.
- 2021: development.
- 2018: chronology quarantine until repaired.
- 2022: previously exposed, partial historical diagnostic only.
- Later unseen seasons: required for independent evaluation and adoption.

If new training data are introduced, freeze an updated chronological evaluation design before model selection.

## 3. v0.2: Team-specific decisions and outcomes

### 3.1 Pregame team model

Build a team-strength snapshot strictly from information available before puck drop.

For each team estimate:

| Attribute | Model purpose |
|---|---|
| Even-strength shot creation | Frequency of generating attacks and shots |
| Even-strength shot suppression | Opponent shooting opportunities |
| Shooting quality | Probability and quality of dangerous attempts |
| Faceoff strength | Initial possession advantage |
| Penalty generation/taking | Power-play exposure |
| Power-play effectiveness | Man-advantage shot creation and scoring |
| Penalty-kill effectiveness | Suppression while shorthanded |
| Score-state tendencies | Adjustments when leading or trailing |
| Home advantage | Venue effect on matchup probabilities |
| Tempo and event rates | Expected number and spacing of events |

Estimate parameters per team using rolling, chronological evidence with league-average shrinkage.

Keep separate attacking and defensive effects. Avoid adding unverified team-specific attributes as arbitrary numeric ratings.

Initially omit rest, travel, coaching, or other contextual inputs unless their historical availability and incremental predictive value are independently established.

### 3.2 State-conditioned event generator

Replace independent whole-period template sampling in the new candidate with a state-conditioned event process.

Maintain the game state:

- Period and remaining clock.
- Current score.
- Strength state: 5v5, 5v4, 4v5, 4v4, 3v3 and supported exceptional states.
- Penalties and expiration times.
- Faceoff and event zone.
- Probabilistic possession state, including unknown.
- Current on-ice personnel when v0.3 is enabled.
- Goalie presence and empty-net status.
- Team tactical mode.

At each event transition:

1. Sample elapsed game-clock time from a fitted, state-dependent distribution.
2. Calculate the competing probabilities of eligible next event types.
3. Sample the next event.
4. Assign team ownership and supported event details.
5. Process outcomes and rule-driven state changes.
6. Recalculate the conditional distribution for the next event.

Event types should include faceoffs, shots, goals, misses, blocks, hits, giveaways, takeaways, penalties, stoppages and supported boundary events.

**Important limitation:** Standard NHL play-by-play does not record every pass or continuously identify possession. Treat possession and unobserved tactical actions as latent model states with explicit uncertainty. Do not claim they are directly observed training labels.

### 3.3 Team tactical policies

Introduce a versioned policy interface with actions such as:

- Attack or defend conservatively.
- Generate or suppress shooting opportunities.
- Clear the defensive zone.
- Pursue loose pucks.
- Dump and chase versus controlled entry, once supporting data exist.
- Change deployment based on score, strength and clock.
- Pull the goalie in late-game situations.

Early policies should influence the statistical event probabilities. Do not claim that a sampled tactical action succeeded because of simulated physical skill.

Different teams must demonstrably produce different probability distributions for the same frozen context.

### 3.4 Shot and scoring process

Split the existing goal-generation process into conditional stages:

**Opportunity → shot attempt → shot result → goal or no goal**

Include:

- Attempt generation by attacking team and strength state.
- Shot type and location or danger-zone distribution.
- Miss and block probabilities.
- Shot-on-goal probability.
- Conditional scoring probability against the defending goalie or a documented team-average replacement in v0.2.
- Rebound and continuation probabilities where supported.

Use verified source definitions for shot attempts and shots on goal. Do not assume blocked-shot coordinates represent the original shot-release point.

Generated goals must arise from valid scored shot events, not be inserted independently to force a predicted final score.

### 3.5 NHL rules and time

Implement explicit rule handling for regulation, penalties, delayed penalties where supported, manpower changes, three-on-three regular-season overtime, and shootouts.

Examples:

- A goal during an eligible minor-penalty power play can release a penalized player under the applicable NHL rules.
- A major penalty does not end merely because a goal is scored.
- A tied regulation score triggers overtime.
- An overtime goal ends the game immediately.
- Shootout attempts do not become ordinary player goals.
- Pulled-goalie situations must change both personnel and scoring exposure.

Rule handling must be versioned by season where relevant.

## 4. v0.3: Player-specific behavior

### 4.1 Pregame roster and identity

Create a frozen **PregameGameSnapshot** with:

- Game ID, scheduled start and capture cutoff.
- Home and away NHL team IDs.
- Eligible NHL player IDs and positions.
- Availability and lineup evidence.
- Verified or projected lineup status.
- Known or uncertain starting goaltender.
- Team and player parameter versions.
- Input hashes, source timestamps, seed and model version.

Historical game participants obtained from final box scores are ground truth for retrospective validation, not permissible pregame availability inputs.

If a pregame historical lineup cannot be established, report the coverage gap. A reconstructed or oracle-lineup diagnostic must be visibly distinguished from a deployable pregame simulation.

### 4.2 Player attributes

Build player attributes from prior games, with position and exposure normalization.

| Player attribute | Initial effect |
|---|---|
| Shot attempts per 60 | Shot participation |
| Shot selection/quality | Shot type and danger |
| Finishing ability | Scoring probability adjustment |
| Primary/secondary assists | Attribution and involvement |
| Faceoff win rate | Faceoff outcomes |
| Penalty rate | Penalty exposure |
| Hits and blocks | Relevant event participation |
| Even-strength TOI | Deployment probability |
| PP/PK TOI | Special-teams deployment |
| Position and role | Eligible lineup assignments |

Use empirical Bayes or comparable shrinkage for limited samples, with uncertainty and sample counts retained.

Ratings must never be invented simply to make a familiar player perform better. When data are insufficient, use a documented positional or league-average distribution.

### 4.3 Player event selection

Once a team creates an opportunity, choose the involved player or players conditional on:

- Who is currently on the ice.
- Their role and location/zone context.
- Their individual rates and uncertainty.
- The current strength state.
- Team tactical state.
- Prior simulated fatigue and deployment.

Examples:

A first-line winger may receive a larger share of offensive shot opportunities than a defensive specialist.

A defenseman may be more likely to generate shots from the point.

A center with stronger faceoff evidence may receive a higher faceoff probability.

These are probabilities, not guaranteed actions.

Track simulated player totals, including goals, assists, shots, attempts, faceoffs, penalties, TOI and applicable goalie stats. Attribute assists consistently, with no more than two per goal and no unsupported retrospective claims about exact passes.

## 5. v0.3: Goaltender model

### 5.1 Starter selection

Support three separate scenarios:

1. **Verified starter:** Confirmed before the pregame cutoff.
2. **Uncertain starter:** Sample a starter from an evidence-based distribution.
3. **Unresolved:** Use a documented fallback with uncertainty; do not silently mark anyone confirmed.

Do not use the real game's final box-score starter to select a pregame goalie.

Previous goalie-start heuristics were not sufficiently reliable, so their results must not be represented as confirmation.

### 5.2 Per-shot save model

Estimate the probability of a save using:

- Goalie identity and prior save evidence.
- Shot location or danger zone.
- Shot type.
- Strength state.
- Rebound context where observable.
- Shooter quality with regularization.
- Supported goalie/team defensive context.

The model should shrink toward appropriate population priors and report uncertainty for goalies with limited minutes or few shots faced.

Do not treat every shot as an independent identical save-percentage trial.

### 5.3 Goalie gameplay behavior

Model starting, relief, pulling and returning the goalie as explicit personnel events.

Handle:

- Saves and goals against.
- Shots against.
- Goalie TOI.
- Empty-net goals and shots.
- Valid goalie substitutions.
- Shootout outcomes, accounted for separately from regulation/OT goalie statistics.

A future physical goalkeeper may choose stance, depth, lateral movement and save actions. Until movement has an independently validated timebase and mechanics, physical goalie movement must not be described as causing a statistically scripted save.

## 6. v0.3: Shifts, lines and fatigue

### 6.1 Shift-chart acquisition

Audit the NHL shift-chart source:

`https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={game_id}`

Collect a representative, stratified sample of regular-season games before bulk acquisition. Verify response structure, historical availability, player identity coverage, start/end times, overlaps, and reconciliation to box-score TOI.

Measure complete-game coverage by season and by team. Record failures rather than repairing undocumented inconsistencies silently.

Keep raw records and derived shift data outside Git, with checksums, provenance, and a legal-use review.

### 6.2 Lineup and substitution engine

Represent the following at each point in the game:

- Active skaters on both teams.
- Active goalie, or empty net.
- Strength state and penalized players.
- Player position/role.
- Time since entering the ice.
- Accumulated TOI.
- Simulated fatigue.
- Line and defensive-pair assignment.
- Available bench personnel.

Estimate substitution rates from prior verified shift charts, conditioned on shift duration, stoppages, score, strength, period and player role.

Allow legal changes during play and during stoppages.

Penalty-box players must not be reintroduced early except under a valid rules transition.

### 6.3 Line combinations

Estimate likely forward lines, defensive pairs, power-play units and penalty-kill groups only where historical pregame evidence supports them.

For incomplete historical lineup evidence:

- Use an uncertainty-aware projected lineup.
- Preserve player eligibility and legitimate positional roles.
- Mark projected combinations as projections.
- Report the proportion of simulations using fallback assignments.

Do not copy the actual target-game shift sequence into a pregame simulation.

### 6.4 Fatigue model

Use simulated exposure, not unobserved physical tracking, for the initial fatigue proxy.

Fatigue may influence substitution propensity and, only after evidence-based calibration, event performance.

Do not assign real skating speed, acceleration, reaction time, or physiological fatigue constants from ordinal tracking observations.

Use the existing Gridiron movement adapter for isolated research until an independently validated timing and identity join exists.

## 7. Interfaces between Legendary Picks and Gridiron

Legendary Picks remains responsible for:

- Pregame inputs and eligibility.
- Statistical model parameters.
- Tactical/event generation.
- Game-clock and rules state.
- Player/goalie selections.
- Event outcomes and statistical records.
- Immutable simulation artifacts.

Gridiron Physics remains responsible for:

- Reading the NHL-specific record.
- Rendering event timelines and scoreboards.
- Visualizing players and the puck.
- Producing generated movement frames.
- Executing hockey-specific motion constraints.
- Reporting physical movement diagnostics.

Define separate immutable schemas for:

**PregameGameSnapshot**
As-of inputs, available players, model versions, parameters, uncertainty and source hashes.

**NhlSimulationEvent**
Sequence, clock, strength, active players, participating players, action, sampled result, state before/after, responsible model and provenance.

**NhlSimulationGame**
Seed, snapshot hash, simulation mode, full event stream, final score, team totals, player totals, source/model hashes and validation report.

**NhlMovementFrame**
Timestamp or explicitly ordinal step, entity positions, puck position, role/action intent, coordinate system, physical-model version and observed-versus-generated provenance.

The statistical event record must be immutable to the visualization.

The existing NFL `GRIDIRON-CONTRACT-v1` is not an NHL event schema. Define a hockey-specific contract rather than changing NFL field semantics.

For eventual physics-driven mode, create a separate versioned outcome contract that explicitly identifies which outcomes physics is authorized to determine. Do not simultaneously sample a statistical goal and independently permit physics to override the goal without a formally defined hybrid model.

## 8. Evaluation and acceptance gates

### Team-specific model

Compare v0.2 on identical historical games against the frozen v0.1 baseline, existing team-strength baselines, and the matched SBR closing-moneyline benchmark where available.

Evaluate:

- Winner Brier and log loss.
- Home and away goal CRPS.
- Joint score distribution and margin.
- Shots-on-goal CRPS.
- Period goal/shot distributions.
- Event frequencies and time intervals.
- Power-play opportunities and conversion distributions.
- Calibration by team-strength and score-state strata.
- OT and shootout frequencies.
- Full-game event/goal variance.

Calculate paired uncertainty by game and preserve chronological evaluation.

Do not declare adoption from the 2021 development set. Require a frozen later-season or prospective population for independent evaluation.

### Player, goalie and shift models

Measure:

- Player shot, goal and point distribution calibration.
- Skater TOI and shifts per game.
- Shift-duration distributions by role and strength.
- Line-combination and deployment frequencies where ground truth is available.
- Goalie shots-against and goals-against distributions.
- Goalie per-shot log loss/Brier and calibration by danger/strength.
- Power-play and penalty-kill deployment.
- Goal attribution and scorekeeping integrity.
- Missing identity, lineup and shift-data coverage.

Report matchup-level and player-level results separately. An improved game winner Brier cannot substitute for realistic or accurate player deployment.

### Mandatory invariants

Every generated game must:

1. Use only eligible, cutoff-valid inputs.
2. Reach a valid final result.
3. Have monotonic, legal event clocks.
4. Have legal on-ice personnel and penalty transitions.
5. Reconcile all goals and team shot counts.
6. Reconcile player goals, assists and on-ice exposure to the simulated event record.
7. Handle overtime and shootouts without double-counting goals.
8. Produce byte-identical outputs for the same fixed input, seed and runtime.
9. Preserve observed-versus-generated provenance.
10. Avoid changing production NHL forecasts or NHL/NFL physical code without a separate authorization and evaluation.

## 9. Delivery sequence

### A. Data-readiness gate

Audit historical player identities, rosters, shift charts, lineup timing, shot locations and goalie evidence.

**Deliverable:** Source manifest, completeness matrix, quarantine report, pregame-availability audit, and exact model-eligible population.

Stop features that depend on unverified source coverage.

### B. Team-conditioned simulation v0.2

Fit team attack/defense and state-conditioned event distributions; generate complete games with real team identities affecting outcomes.

**Deliverable:** Versioned event generator, pinned sample games, tests, and paired development comparison against v0.1 and existing team models.

### C. Player and goalie model v0.3a

Add verified roster membership, projected starting players, participation distributions, and conditional goalie save probabilities.

**Deliverable:** Complete team/player accounting plus calibration and coverage diagnostics.

### D. Shift/deployment model v0.3b

Build legal on-ice lineups and shift transitions. Condition events on actual simulated personnel and fatigue proxies.

**Deliverable:** Shift ledger, on-ice timeline, TOI reconciliation, special-teams deployment tests and independent shift-distribution evaluation.

### E. Gridiron integration v0.4 research

Render the statistical record with hockey-specific positioning and movement. Keep statistical results unchanged in read-only mode.

Separately prototype physics-informed outcomes where timing, entity identity, puck mechanics and tracking evidence support them.

**Deliverable:** Full-game NHL viewer, immutable-record checks, movement validation report and explicit physical-versus-statistical boundary.

## 10. Engineering restrictions

- Develop on isolated research branches/worktrees.
- Do not modify NHL production prediction models during this project.
- Do not overwrite frozen baseline or historical artifacts.
- Do not leak actual target-game player participation, goalie starts, game stats or shifts into pregame features.
- Do not use unresolved MoneyPuck-derived training data without an appropriate rights determination.
- Preserve source hashes, training windows, cutoff times and model versions.
- Never convert an ordinal movement index into seconds without independent validation.
- Do not claim independent evaluation using development or previously exposed games.
- Keep partial or failed data joins visible instead of inventing values.

**Definition of success:** Given two scheduled NHL teams and a pregame cutoff, the simulator can produce many reproducible, matchup-specific, player-attributed full games with plausible shifts, valid hockey rules, consistent team/player totals, and measurable predictive skill. The physical viewer can then represent those generated games without confusing animation with causal simulation.
