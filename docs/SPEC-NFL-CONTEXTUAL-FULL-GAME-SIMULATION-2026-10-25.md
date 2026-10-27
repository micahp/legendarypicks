# Legendary Picks: Contextual NFL Full-Game Simulation

**Specification:** NFL-CONTEXT-SIM-V1  
**Status:** Research specification, not approved for production  
**Date:** October 25, 2026  
**Repositories:** `micahp/legendarypicks` and `micahp/gridiron-physics`  
**Primary research branch:** `feat/statistical-full-game-e2-2026-10-25`

## 1. Objective

Build an NFL simulation engine that generates thousands of plausible outcomes for **a specific matchup at a specific moment in the season**.

A Chiefs–Seahawks matchup in Week 1 should not have the same underlying probabilities as one in Week 7 or the playoffs, even if both teams have similar rosters.

The simulator must account for what was known before kickoff:

- How each team has performed against its opponents.
- How each team's performance has changed recently.
- Which players are expected to play and their current roles.
- Each team's record, standings position, and postseason situation.
- How the current simulated game develops, including score, clock, workload, and fatigue.

The goal is to improve the accuracy of projected team scores, win probabilities, spreads, totals, and eventually player props.

**Success is not generating football-looking games. Success is generating better predictions for the games that actually occur.**

---

## 2. Core Design Principle

### One matchup, one frozen context, thousands of different possible games

Before running simulations:

1. Collect all eligible information available before the matchup's cutoff.
2. Create a versioned **Pregame Context Snapshot**.
3. Build a matchup-conditioned play-sampling model from the eligible historical archive.
4. Freeze that model for the batch.
5. Run independently seeded simulations.
6. Aggregate the resulting scores, player statistics, and outcomes.

Each simulation shares the same pregame information but can develop differently because of random play outcomes, possessions, turnovers, field position, game plans, and in-game decisions.

### The historical database must continuously evolve

As NFL games finish, their eligible observations become available for future matchups.

The dataset should grow naturally throughout the season. After a new NFL week, the eligible pool may contain another 10–16 or so games, depending on the schedule.

**Do not freeze the historical dataset permanently.**

However, indexing the eligible pool once for a particular matchup is encouraged. We should not repeatedly sort and rebuild an unchanged sampling cell for every play in that matchup's 10,000 simulations.

Caching must be scoped to the exact input dataset, game, as-of cutoff, and model configuration.

---

## 3. Current Architecture

Extend the existing research system rather than replacing it.

Primary implementation points:

| Existing component | Responsibility |
|---|---|
| `pregame_snapshot.py` | Frozen schedule and roster information |
| `e1_drive.py` | Historical play classification and sampling |
| `e2_reference.py` | Historical reference data and sampling pools |
| `game_state.py` | Complete-game orchestration |
| `reducer.py` | Authoritative football state transitions |
| `simulate_pregame_batch.py` | Multi-seed simulation and reporting |
| `pregame_batch.py` | Distribution aggregation |

Add the following research components:

- `pregame_context.py`: as-of-safe matchup context.
- `contextual_pool.py`: historically grounded, matchup-conditioned sampling.
- `game_context.py`: in-game variables such as fatigue, score pressure, and offensive/defensive workload.
- `contextual_evaluation.py`: chronological comparisons, calibration, ablations, and diagnostic reports.

Names may change if existing modules offer a cleaner integration point.

The shared football rules reducer remains authoritative. Do not create a separate implementation of downs, possession, scoring, or clock rules.

---

## 4. Pregame Context Snapshot

Extend the existing snapshot with a versioned context object.

### 4.1 Required context

| Category | Fields | Priority |
|---|---|---|
| Game identity | Game ID, season, week, kickoff, regular season/playoffs, home/away | Required |
| Team record | Wins, losses, ties, games played before kickoff | Required |
| Team performance | Points scored/allowed, yards per play, offensive and defensive efficiency where available | High |
| Recent form | Last 3 and last 5 eligible games, with opponent quality | High |
| Personnel | Expected starting QB, roster, position roles, verified availability | High |
| Game situation | Division matchup, standings position, postseason phase | High |
| Stakes | Playoff qualification/seeding implications where mathematically supported | Experimental |
| Environment | Venue/home field | Required |
| Weather | Not included in V1 | Deferred |

### 4.2 Example schema

Illustrative values, not a claim about an actual game:

```json
{
  "schema": "lp-nfl-pregame-context-1",
  "game_id": "example_KC_SEA",
  "as_of": "2026-10-25T18:00:00Z",
  "season": 2026,
  "week": 7,
  "game_type": "REG",
  "home": {
    "team": "SEA",
    "record": {"wins": 3, "losses": 3},
    "recent_games": 5,
    "starting_qb_id": "verified-player-id",
    "offensive_form": {},
    "defensive_form": {},
    "personnel": {},
    "stakes": {}
  },
  "away": {
    "team": "KC",
    "record": {"wins": 5, "losses": 0},
    "recent_games": 5,
    "starting_qb_id": "verified-player-id",
    "offensive_form": {},
    "defensive_form": {},
    "personnel": {},
    "stakes": {}
  },
  "source_manifest": [],
  "context_hash": "sha256-of-canonical-context"
}
```

The actual schema must define typed fields and support missing data explicitly. Do not replace unavailable facts with fabricated values.

Every input must carry sufficient provenance to establish that it was available at the requested cutoff.

---

## 5. Historical Data Eligibility

### 5.1 Chronological eligibility

For each game being simulated, the engine may use only observations from completed games whose results were available before the simulation cutoff.

This applies to:

- Play-by-play data.
- Team season records.
- Player game logs.
- Depth charts.
- Injuries and availability.
- Historical projections and market information.

For historical backtests, the database's current contents are not proof that a fact was available before a historical kickoff.

Where historical publication or ingestion timing cannot be established, label that source unverified for as-of evaluation.

### 5.2 Growing the pool

The existing historical E1 archive currently uses seasons 2022–2025.

Extend its eligibility process to incorporate subsequent completed games from 2026 and later seasons without hard-coded season lists.

Keep the full historical archive available, but allow the model to assign different weights to recent and older examples.

Do not automatically make all 2026 plays more important than older plays. Determine weighting through chronological validation.

### 5.3 Sparse data

A team may have no current-season games in Week 1, only one by Week 2, and many by December.

Use a hierarchical fallback:

1. Same team and relevant situation, when sufficient evidence exists.
2. Broader team or opponent-adjusted estimates.
3. Comparable teams and historical situations.
4. Position-, event-, and league-level distributions.

Shrink small samples toward broader populations.

Never treat one unusual game as the definitive identity of a team.

Report sample sizes, effective sample sizes, and fallback decisions.

---

## 6. Matchup-Conditioned Play Generation

This is the main modeling change.

Today, the play generator primarily samples historical outcomes from down, distance, and field-position cells.

In V1, the same football situation must produce different probabilities depending on the teams and current matchup.

### 6.1 Offensive and defensive strengths

Estimate separate, pregame-frozen characteristics for each offense and defense.

Initial candidates:

**Offense**

- Pass/run tendency.
- Passing efficiency.
- Rushing efficiency.
- Sack avoidance.
- Turnover frequency.
- Explosive-play frequency.
- Red-zone scoring.
- Pace and clock consumption.

**Defense**

- Passing efficiency allowed.
- Rushing efficiency allowed.
- Sack/pressure production.
- Explosive plays allowed.
- Turnover production.
- Red-zone defense.
- Pace faced and defensive workload.

Prefer opponent-adjusted or shrinkage-based estimates where the data permits.

### 6.2 Conditional sampling

The model should produce something conceptually equivalent to:

`P(play event | down, distance, field position, offense, defense, pregame context, current game state)`

Separate:

1. **Play selection:** run, pass, punt, field-goal attempt, etc.
2. **Play outcome:** completion, sack, yards, turnover, touchdown, etc.
3. **Rules transition:** authoritative reducer applies the result.

Do not use a single modifier to boost everything for a stronger team.

For example, a good passing offense facing a weak pass defense might have better passing outcomes, but that should not automatically make its rushing game, fourth-down decision-making, or defensive performance better.

### 6.3 Historical sampling method

Use the existing observed play pool as the foundation.

Research approaches include:

- Weighted empirical sampling.
- Hierarchical probability models.
- Opponent-adjusted team effects.
- Context-specific mixture distributions.

Any proposed adjustment needs to be identified, measured, and compared with the unconditioned model.

Avoid arbitrary multipliers like “undefeated teams receive 10% better offensive efficiency.”

### 6.4 Within-batch diversity

Allow individual simulations to sample a bounded latent game-plan or game-level performance variation, so two seeds do not necessarily have identical strategic tendencies.

Such variation must be learned or validated from historical game-to-game variation, not invented solely for variety.

Different seeds should produce meaningful different games without changing the frozen pregame facts.

---

## 7. Season Situation and Stakes

A team's record matters as information, but it does not prove greater motivation.

A 5–0 team and a 3–3 team may approach a game differently. That could reflect team strength, performance consistency, strategic choices, or actual postseason incentives.

We need to distinguish them.

### Phase 1: descriptive context

Include:

- Current wins and losses.
- Division record.
- Position in division.
- Remaining schedule and games remaining.
- Regular season versus postseason.
- Divisional versus non-divisional opponent.

### Phase 2: measurable stakes

Research additional features:

- Change in playoff probability with a win versus a loss.
- Change in division-title probability.
- Change in seeding probability.
- Elimination or clinching scenarios.
- Playoff elimination-game status.

Only compute these where the data and rules support them.

### Modeling constraint

**Do not directly improve a team's simulated performance because it “needs the win more.”**

First test whether high-stakes situations historically correlate with measurable changes in play-calling, pace, fourth-down decisions, or efficiency *after controlling for team strength and opponent*.

Records may also be redundant with team-strength estimates. Ablations must measure whether they add independent predictive information.

---

## 8. In-Game Adaptation

Pregame context is frozen. The simulated game state is not.

The engine should respond to what happens during each simulation.

Potential inputs:

- Current score differential.
- Quarter and remaining time.
- Timeouts.
- Down and distance.
- Field position.
- Possession history.
- Offensive and defensive snap counts.
- Time since last possession.
- Drives and plays since substitutions or rest.

### Examples

A team trailing by 17 points in the fourth quarter should not necessarily use the same play-selection distribution as it did in a tied first quarter.

A team leading late may run more often, but the size and timing of that change must be supported by historical observations.

A game with repeated three-and-outs should produce a different defensive workload than one with multiple long drives.

**The simulation must evolve based on its own generated events, not borrow future facts from the actual historical game.**

---

## 9. Fourth-Quarter Defensive Fatigue

### Hypothesis

Defenses can become less effective late in games due to accumulated physical workload.

The user-level football intuition is that, by the fourth quarter, defenders can be **half a step slower**.

Treat this as a research hypothesis, not an established universal numerical penalty.

### 9.1 Statistical simulator

Track available proxies:

- Defensive snaps played.
- Consecutive defensive plays.
- Time spent on the field.
- Length of the previous possession.
- Rest between defensive possessions.
- Pace faced.
- Player rotation, when supported.
- Offensive workload as a comparison/control.

Test whether those variables explain late-game changes in:

- Passing and rushing efficiency allowed.
- Explosive-play rate.
- Sack rate.
- Yards after catch.
- Defensive stops.

Do not implement an unconditional Q4 defensive-efficiency penalty.

### 9.2 Gridiron Physics

A later physical interpretation may reduce or alter:

- Acceleration.
- Recovery speed after direction changes.
- Pursuit efficiency.
- Reaction timing.
- Repeated-effort capacity.

Fatigue should accumulate and recover through the simulation's events and rest periods.

Do not arbitrarily reduce all defenders' maximum speeds at the start of Q4.

### 9.3 Validation

Compare models with:

1. No fatigue variables.
2. Quarter-only variables.
3. Workload-based fatigue.
4. Workload and rest/rotation effects, if available.

Use offense and defense controls to distinguish defensive fatigue from broader late-game strategy changes.

Adopt fatigue effects only when they add out-of-sample value and behave plausibly across game states.

---

## 10. Legendary Picks Pregame Headlines

Legendary Picks already has generated matchup stories in `backend/core_stories.py`.

Those stories are grounded in records, streaks, player form, and matchup context. `backend/stakes.py` supports stakes calculations for some sports, but not NFL yet.

### Proposed integration

Use the same underlying facts that generate a story to populate the Pregame Context Snapshot.

Example:

**Generated headline:**

“Seattle enters the matchup looking to stay above .500 against unbeaten Kansas City.”

**Underlying structured context:**

- Seattle record: 3–3.
- Kansas City record: 5–0.
- Matchup date and phase.
- Standings information available before kickoff.
- Any verified qualification or seeding implications.

The headline is useful for explaining what makes the matchup distinctive.

The structured facts are the simulation inputs.

### Restrictions

- Do not assign numerical modifiers from the wording or emotional tone of an AI-generated headline.
- Do not use generated text that may incorporate post-cutoff information.
- Do not allow the simulator's own prediction to feed back into its pregame feature calculation.
- Keep the original source facts and generation timestamps.
- Do not rely on a current standings endpoint to reconstruct a previous week's standings.

Later research may evaluate grounded, pregame news features, but raw text-driven performance adjustments are outside V1.

---

## 11. Batch Simulation and Performance

Extend the existing `simulate_pregame_batch.py`.

### Required behavior

For one matchup:

1. Build and validate its context snapshot once.
2. Load eligible historical observations.
3. Compute team/opponent estimates.
4. Construct and index matchup-specific sampling structures.
5. Run independently seeded complete games.
6. Preserve every requested seed's result and status.
7. Aggregate distributions.
8. Save hashes of context, inputs, code, and parameters.

### Performance requirements

- Reuse immutable sampling structures within one frozen batch.
- Do not recompute historical cell counts or sort historical candidates for each simulated play.
- Permit reproducible independent seed shards.
- Support checkpointing and resume.
- Require merged shards to produce the same result as a contiguous run over identical seeds and inputs.
- Report simulation throughput and memory consumption.

Do not force every test to use 10,000 simulations.

Start with smaller cohorts to measure correctness, runtime, distribution stability, and blocker rates.

Increase simulation count when Monte Carlo uncertainty materially affects the projected outputs.

---

## 12. Forecast Outputs

Each batch should provide:

### Team forecasts

- Mean points for both teams.
- Median points and 10th–90th percentile intervals.
- Mean scoring margin.
- Mean total.
- Win probability.
- Probability of covering an offered spread.
- Over/under probabilities and pushes.
- Most frequent exact scores, clearly separate from projected mean score.

### Player forecasts

- Passing attempts, completions, yards, touchdowns, interceptions.
- Rushing attempts and yards.
- Receptions, targets, receiving yards.
- Player-stat distributions where available.

Player projections must remain labeled as role-based allocations until the model has genuine player-specific predictive components.

### Coverage and validity

- Total attempted seeds.
- Valid full games.
- Ties requiring unresolved overtime.
- Games blocked before the end of regulation.
- Games with unsupported special-teams or rules transitions.
- Simulation and validation errors.
- Valid-game coverage percentage.
- Conditional versus regulation-end score distributions.

**Never silently discard invalid games or describe their exclusion-adjusted mean as an unconditional forecast.**

---

## 13. Model Evaluation

The existing Legendary Picks NFL v1 points model remains the baseline.

The contextual simulator must outperform meaningful reference models before promotion.

### 13.1 Research ladder

| Model | Description |
|---|---|
| S0 | Current statistical full-game simulator |
| S1 | S0 + updated historical archive and pregame team context |
| S2 | S1 + offense/defense matchup conditioning |
| S3 | S2 + current in-game score/time behavior |
| S4 | S3 + season situation and standings |
| S5 | S4 + workload/fatigue candidates |
| S6 | Best validated combination of adopted features |

Each step must be tested separately.

If S4 or S5 makes predictions worse, discard the feature rather than retaining it for realism alone.

### 13.2 Evaluation metrics

**Win probability**

- Brier score.
- Log loss.
- Reliability/calibration.
- Discrimination against the v1 and market baselines.

**Team scores, spread, and total**

- Mean absolute error.
- RMSE.
- Proper distributional scoring, such as CRPS.
- Prediction interval coverage.
- Margin and total calibration.

**Simulation quality**

- Average drives and plays per game.
- Team points distribution.
- Run/pass rates by game state.
- Turnovers and sacks.
- Pace and possession balance.
- Fourth-quarter efficiency patterns.
- Full-game validity coverage.
- Error and unsupported-transition rates.

### 13.3 Backtest methodology

Use chronological, walk-forward evaluation.

For every historical matchup:

- Freeze the relevant historical cutoff.
- Rebuild only the context legitimately available then.
- Use historical plays and rosters eligible at that time.
- Generate predictions before accessing the target game's outcome.
- Compare results against the actual score and baseline forecasts.

Do not use a complete 2022–2025 play pool when simulating a game within that window. That would leak future games into historical forecasts.

Use paired seeds for controlled ablations and game-level comparisons across the evaluation set.

Keep a final untouched holdout or prospective cohort separate from tuning.

### 13.4 Promotion gate

A model may be considered for promotion only when:

- Its information provenance is sound.
- Its game validity and selection bias are acceptable.
- Its scores and probabilities are demonstrably calibrated.
- Its performance against v1 is competitive on unseen games.
- Gains are not limited to one team, one week, or a small number of unusual results.
- Its cost and latency are practical for Legendary Picks.

Realistic-looking game traces are useful diagnostics, not evidence of predictive superiority by themselves.

---

## 14. Acceptance Scenarios

The following deterministic and historical tests are required.

### A. Same matchup, different season context

Construct or retrieve two matchup contexts with the same teams:

- Week 1: both 0–0.
- Later regular season: different records and additional completed games.

Verify that the historical eligibility, team estimates, and context fingerprints differ appropriately.

The model must not require an arbitrary direct record-based bonus for the distributions to differ.

### B. Quarterback change

Change the verified expected starter while keeping other inputs fixed.

Confirm that relevant passing and participation assumptions respond where supported, without changing unrelated defensive or special-teams attributes.

### C. Playoff game

Verify that postseason rules and context are distinguished from regular-season ones.

Do not call a game complete if an overtime or playoff transition is unsupported.

### D. Late defensive workload

Compare two otherwise equivalent in-game states with different accumulated defensive workloads.

A workload-sensitive model should produce a measurable change only when an adopted fatigue component supports it.

### E. Historical archive growth

Add newly eligible completed games and rebuild the matchup pool.

Verify:

- Updated input hash.
- Updated sample eligibility.
- Updated estimates where appropriate.
- Deterministic reproduction for the same archived snapshot.

### F. Generated headlines

Compare the same structured context with two differently worded headlines.

Forecasts must remain unchanged unless an independently verified structured input differs.

### G. Future-data leakage

Insert an outcome, roster update, or news item timestamped after the historical cutoff.

The pregame snapshot and resulting simulations must not change.

### H. Sharded reproducibility

Run identical seeds in a single batch and as independent shards.

All per-seed results, aggregate statistics, and input fingerprints must match.

---

## 15. Implementation Order

### Phase 0: Data inventory and feasibility audit

Inspect the current NFL database, source tables, roster coverage, timestamps, and historical availability.

Deliver:

- Available candidate features.
- Coverage by season and week.
- As-of provenance assessment.
- Missing-data and leakage risks.
- Feasibility of historical comparison.

No predictive behavior changes.

### Phase 1: Pregame Context Snapshot

Implement the versioned context object and source manifest.

Keep the current unconditioned simulator behavior available.

Acceptance: exact reproduction, cutoff safety, and matchup-specific snapshot differences.

### Phase 2: Dynamic historical pools

Remove the fixed-season eligibility assumption, add cutoff-safe eligibility, and construct context-specific indexed sampling structures.

Acceptance: new eligible games enter the pool; future games do not; seeded behavior is reproducible.

### Phase 3: Team and opponent conditioning

Start with a small set of offense/defense measures and recent-form features.

Run chronological ablations against the current simulator.

Acceptance: independently measured impact and a go/no-go decision for each feature.

### Phase 4: In-game score, clock, and pace behavior

Extend event selection using simulated score differential and time remaining.

Preserve the existing rules reducer.

Acceptance: conditional behavior is plausible and measured against historical game-state distributions.

### Phase 5: Fatigue research

Study defensive workload and fourth-quarter changes.

Implement workload-based effects only if historical evidence and backtests support them.

Acceptance: no unconditional or unexplained quarter-four speed adjustment.

### Phase 6: Stakes and headline context

Extend NFL structured stakes context and connect its source facts to the snapshot.

Use generated headlines for explanations, not arbitrary simulation modifiers.

Acceptance: no headline-driven feedback loop, fabricated input, or timestamp leakage.

### Phase 7: Large-batch evaluation

Run reproducible multi-game, multi-seed backtests.

Compare the best adopted configuration with NFL v1 points and appropriately timestamped market baselines.

Deliver an explicit adoption or rejection report.

---

## 16. Engineering Constraints

- All work begins research-only, on a separate branch.
- Do not merge, deploy, or modify production forecasting behavior without explicit approval.
- Database reads must remain read-only during research simulations.
- Preserve the current statistical simulator as a reproducible control.
- Preserve the shared reducer as the source of football rules.
- No hidden use of actual target-game outcomes.
- No hard-coded motivation boosts.
- No weather feature in V1.
- No fabricated injury, roster, or headline facts.
- No silent fallback to a broader pool without recording the fallback.
- No arbitrary NFL benchmark tuning to make simulated scores look realistic.
- No deletion or silent exclusion of failed seeds.

## 17. Deliverables

The agent should produce:

1. **Data audit:** feature availability, sources, timing, and coverage.
2. **Context schema:** versioned, validated, and hash-pinned.
3. **Context builder:** reconstructible for every supported cutoff.
4. **Conditional sampler:** clearly separated from the original sampler.
5. **In-game context model:** score, pace, workload, and approved factors.
6. **Updated batch runner:** reproducible, efficient, and shardable.
7. **Evaluation report:** model ladder, accuracy, calibration, and error analysis.
8. **Representative simulations:** contrasting matched Week 1, midseason, playoff, and late-game situations.
9. **Go/no-go recommendation:** whether any component has earned adoption.

Every report must specify the code commit, model version, historical cutoff, sample cohort, and input hashes.

---

## 18. Definition of Done

The research is successful when the engine can generate distinctly conditioned distributions for different NFL matchups and historical contexts, and we can explain those differences using verified pregame information.

The ultimate target is a simulator where:

- The teams matter.
- The starting players matter.
- Recent performance matters when supported.
- The season situation can matter when demonstrated.
- What happens earlier in a simulated game changes what happens later.
- Fatigue is an effect of accumulated workload rather than an automatic fourth-quarter penalty.
- More historical games improve the available evidence without creating leakage.
- Thousands of simulated games produce stable, interpretable forecast distributions.

**The final adoption decision is based on out-of-sample prediction quality, not simulation realism alone.**

The existing v1 points model stays in production until a challenger earns promotion.
