# SLC v2 research plan: historical realism and weekly matchup intelligence

Status: proposed research roadmap, 2026-11-02. Research only. Not an approved production change. No 2026 result was used to write this plan.
Repository: micahp/legendarypicks, branch slc-v1.

Relation to earlier plans. This plan replaces the linear A to G workflow in `docs/STRATEGY-GRANULAR-PREDICTION-MODELS-2026-10-26.md` (section 13) for SLC v2, with two coordinated tracks. The M3 freeze (`PLAYCALL-M3-FREEZE-2026-11-02.md`) and its thresholds still govern M3 as written.

Naming. HPV1 remains the historical project identifier and the name of the data contract (`HPV1-DATA-CONTRACT-2026-11-02.md`). The historical sampling experiment is named PBV1 from here on. Existing files keep their names; the rename applies to new documents only.

## 0. Current state

- **A0** (production score-clock play-calling model): the control.
- **A2** (situation cell model, K = 20): does not advance. It is worse than A0 on log loss in both development folds (fold A 2023: +0.0166; fold B 2024: +0.0116). The adopt, revise or reject decision is not yet recorded.
- **A1** (drive and possession volume): no frozen functional form. No result.
- **Gate 3** (2022 to 2024 shotgun source reconciliation): not passed. Fifteen 2022 team-seasons fail R1. TB 2024 stays open on R3 (five plays).
- **HPV1 data contract** (2022 to 2025 personnel, play classes, observed joint records): written and tested. Owner decisions in its section 12 are open.
- **2026 holdout**: exposure-uncertain. The 2025 season was previously exposed. No 2026 read for fitting, tuning, selection or evaluation.

## 1. Two objectives, evaluated separately

**Track R, simulation realism.** Make the simulator produce realistic drives, play selection, personnel, workloads, targets, substitutions and scoring distributions.

**Track P, weekly predictive improvement.** Predict the next game by capturing how this offense (current coaching staff, current players) matches up against this defense, using what both have shown so far this season.

Realism does not imply accuracy. Track R is judged on realism diagnostics and Track P on proper scores. Each layer is validated before the two are combined.

Principle: historical seasons teach the model how football works. Recent weeks update what we believe about the teams playing now. Historical priors plus weekly updates are more defensible than replacing history with the last three games.

### Architecture

- **Historical football model**: 2022 to 2025 playbooks, team styles, personnel, workloads and outcomes.
- **Current-season weekly updates**: coaching tendencies, player roles, injuries, usage trends, defensive tendencies.
- **Offense**: play calls, tempo, personnel, QB decisions, targets, carries.
- **Defense**: coverage, rush, positional allowances, pressure, explosive plays.
- **Matchup-conditioned SLC simulation**: decisions and outcomes simulated with the two teams interacting.
- **Calibrated predictions**: win probability, point distributions, player props, uncertainty.

## 2. Phases

| Phase | Realism track | Prediction track |
|---|---|---|
| A. Define targets | What is a realistic game, drive and workload? | What improves next-week winner, score and prop forecasts? |
| B. Audit inputs | Historical playbooks, personnel, participation | Cutoff-safe weekly coaching, roster, opponent and player data |
| C. Build simple models | Historical play-family and participation priors | Previous-season prior plus current-season updates |
| D. Walk-forward testing | Train through year N, test year N+1 | Recalculate features before each week from earlier games only |
| E. Integrate behind flags | Personnel and workload mechanisms | Coaching and opponent-conditioned mechanisms |
| F. Global ablation | Are game and player distributions more realistic? | Did Brier, log loss, score distributions and props improve? |
| G. Adopt or reject | Promote independently validated realism changes | Promote only changes that improve forecasts |

The prediction track does not wait for every realism issue to close. The 2022 shotgun reconciliation is not a prerequisite for evaluating current-season coaching or defensive positional tendencies.

## 3. Evaluation protocol: year-forward and week-forward

Expanding-window development.

| Fit period | Evaluation |
|---|---|
| 2022 | 2023 |
| 2022 to 2023 | 2024 |
| 2022 to 2024 | 2025 (previously exposed; retrospective only) |
| Through an authorized 2026 pregame cutoff | Future 2026 games, prospective only after forecast lock |

Inside each evaluation season, a forecast for Week W uses only information available before Week W's forecast cutoff. Example: a 2024 Week 8 forecast uses seasons through 2023 plus 2024 games from earlier weeks, provided their data was published before the cutoff. No Week 8 or later outcome is used.

Model parameters, current-season statistics, injury data and coaching information obey the same as-of rule.

Keep separate early-week and final pregame forecasts where source coverage allows. Do not backfill late injury or inactive information into earlier horizons.

The 2026 holdout-exposure record applies. Previously examined 2026 games are exploratory evidence, not an untouched test. New prospective snapshots are authorized and logged explicitly. No historical guard is bypassed.

## 4. Track R: historical realism baseline

**R1. Keep A0.** The existing score-clock play-calling model stays as the control. A2 does not advance in its present form.

**R2. Complete PBV1.** Season-correct historical play-family and personnel distributions, built on the HPV1 data contract.

- Cross-season package comparisons use the normalized RB+FB code, proposed as HPV1 owner decision 12(a). Until the owner decides, report both the RB-only (SLC) code and the RB+FB code.
- SLC's original RB-only representation is retained for the simulator.
- Preserve formation labels, UNKNOWN values and source provenance.
- Sample only observed joint combinations, or explicitly declared and statistically supported fallback distributions.

**R3. Add player participation.** Learn participation and role rotation from historical player IDs, personnel, game situation and workload. Participation from the game being predicted never becomes a pregame input.

Where pregame roster evidence is unavailable, evaluate package-level behavior on its own and report the eligibility limitation.

**R4. Evaluate realism.** Compare team opportunities, drives, play families, package frequencies, player zero rates, share variance and P95/P99 workloads with held-out games.

No arbitrary carry caps, target caps or invented injuries.

M3 A1 (drive and possession volume) remains a separate experiment. Its functional form is frozen before fitting.

## 5. Track P: weekly matchup feature store

One versioned feature snapshot per team and upcoming game, with an explicit `as_of` timestamp and source provenance.

### P1. Coaching identity and tendencies

- Effective-date joins for head coach, offensive coordinator, defensive coordinator and verified play-caller responsibility.
- Tendencies conditioned on score, down, distance, field position, quarter and available personnel.

Initial features:
- Neutral-situation pass rate
- Early-down run and pass rate
- Pass rate when leading or trailing
- Tempo, no-huddle and clock consumption
- Fourth-down aggression
- Red-zone choices
- Formation and personnel preferences
- Target and carry concentration by role

Use team and league priors where coach-specific samples are small. Do not attribute all team behavior to the head coach.

### P2. Current player workload and usage

For each eligible player, estimate:
- Snap and route participation, where available
- Carries, targets and QB dropbacks
- Target share and targets per route
- Red-zone and end-zone opportunity shares
- Role in relevant personnel packages
- Short-term usage changes, with historical shrinkage
- Pregame availability and depth-chart effects

Model team opportunities first, then participation, then player allocation and outcomes. Do not impose desired final carry or target totals.

### P3. Opponent-adjusted defensive matchup profiles

The target shape is the position-versus-defense breakdown (for example, the CBS WR-versus-BUF team page). That page is a reference for the shape only. Build the internal version from NFL data already on hand. Do not scrape or ingest third-party pages.

For each defense, position group and historical week:
- Attempts and targets allowed
- Receptions and completion rate allowed
- Rushing and receiving yards allowed
- Yards per opportunity
- Touchdowns and red-zone outcomes allowed
- Explosive plays allowed
- Coverage, pressure and front proxies, when reliably observed

Keep the opponent team and individual player contributions, not only season averages.

Adjust for opponent strength and opportunity volume. A defense that faced several elite passing offenses is not automatically weaker than one that faced low-volume passing attacks.

Model opportunity allowed separately from efficiency allowed. Do not use raw fantasy points allowed as an extra feature beside the component statistics it is built from.

Treat positional touchdowns as sparse events needing strong shrinkage.

Use sub-position distinctions (slot WR, boundary WR, TE alignment, receiving RB) only when alignment and role data support them.

### P4. Separation and defensive execution

Audit the tracking and charting coverage that is verified to exist before modeling receiver separation, pressure timing, coverage matchup or defender position.

If coverage exists, test separation and pressure as conditional efficiency features. Do not infer measured separation from a Gridiron Physics animation, and do not assume tracking coverage exists for current-season games.

If coverage is insufficient, defer this component explicitly. It must not block coaching, usage or positional-defense tests.

## 6. Weekly opponent-conditioned simulation

Offense tendencies and opponent defensive tendencies act together. For each snap:

1. Read legal game state and available players.
2. Sample offensive intent from the validated policy, adjusted by supported coaching tendencies.
3. Select a historically supported play family and personnel package.
4. Select eligible participants, carrier or target, and QB behavior.
5. Sample the defensive response from supported opponent information.
6. Draw a conditional outcome from calibrated offense-versus-defense effects.
7. Update clock, score, field state and player workload.

No outcome may be overwritten afterward to match an expected stat line.

Keep decision and outcome models separate, so a gain or failure can be attributed to one component.

## 7. Ablation matrix

Each arm is an independently switchable research flag.

| Arm | Change from A0 |
|---|---|
| A0 | Frozen existing full-stack baseline |
| R1 | Historical playbook and personnel sampler (PBV1) |
| P1 | Weekly coaching tendencies |
| P2 | Weekly player usage and participation |
| P3 | Opponent-adjusted defense-versus-position model |
| P4 | Verified separation and pressure features, only if supported |
| P5 | Combined offense-versus-defense interaction, after component evaluation |

Test each arm before any combination. Preserve common game inputs and matched seeds. Record blocked games and rule failures; do not discard them silently.

Use stable random substreams by mechanism, so adding a feature does not change unrelated draws.

## 8. Metrics and adoption

**Primary prediction metrics**
- Game-winner Brier score and log loss
- Calibration by probability bucket
- Team points and total-points distribution scores, including CRPS where available
- Player prop probability Brier and log loss, and count and yardage distribution scores
- Comparison with timestamp-valid market probabilities and lines

**Diagnostic metrics**
- Team drive counts, plays per drive, rushes and dropbacks
- Play-calling and personnel distributions
- Player target and carry likelihood, and share variance
- Positional opportunity and efficiency calibration
- Coverage, uncertainty and reliability by week and sample size

Uncertainty uses paired, game-clustered intervals, reported season by season. Props from the same game are not independent games.

Freeze the advance thresholds and the multiple-comparison procedure before the final retrospective evaluation. The M3 thresholds stay as frozen for M3; they are not replaced silently.

A prediction arm advances only if it improves the relevant proper scoring rules without unacceptable loss of football legality, calibration or key distribution diagnostics.

A realism arm may improve the simulator without improving prediction scores. Report that distinction explicitly.

## 9. Execution order

**Milestone 1: source and feature audit.** Inventory the weekly coaching, play-calling, player usage, defense-versus-position, separation, roster and injury fields. Record temporal coverage and as-of eligibility.

**Milestone 2: historical realism.** Complete PBV1 package-level evaluation. Test participation models independently. Keep the known Gate 3 limitations visible.

**Milestone 3: weekly coaching and opponent features.** Generate cutoff-safe historical snapshots per team and per player, with past opponents, support counts, fallbacks and source timestamps.

**Milestone 4: predictive ablation.** Evaluate P1, P2 and P3 on chronological historical weeks, each on its own, before any combination.

**Milestone 5: full-game integration.** Put successful components behind research flags in SLC. Run small verified smokes, then paired full-game simulations. Preserve A0 results and the immutable archived 10K batches.

**Milestone 6: retrospective and prospective testing.** Freeze the approved candidate before the previously exposed 2025 fold is evaluated. For prospective 2026 evidence, lock the model version, inputs, predictions and hashes before kickoff.

**Milestone 7: adoption.** For each component record ADOPT, REVISE, REJECT or INCONCLUSIVE, with measured effects and provenance.

No automatic production deployment. No use of sealed data without authorization.

## 10. First deliverable: Weekly Matchup Intelligence Data Inventory

Before any new model is fitted, produce an inventory covering:

- Available historical weeks and seasons for each feature family
- Source fields and joins
- Coaching identities and effective-date coverage
- Opponent-adjustment method candidates
- Week-by-week cutoff safety
- Missing injury, route, separation and defensive charting data
- Baselines and the frozen ablation protocol
- Small examples of how one offense and one defense are represented before kickoff

Then implement the simplest P1, P2 and P3 statistical baselines. Do not start with a large learned coaching agent or an unrestricted playbook generator.

Schema audit of 2026 files is allowed for the inventory. Reading 2026 values is not, beyond what an audit requires.

## 11. Priorities

1. **Weekly player usage and coaching tendencies.** The most direct route to fixing target-share and carry-allocation errors. Measurable on player opportunities before any full-game run.
2. **Opponent-adjusted positional defense.** Separate what a defense allows because of its own weaknesses from what it allows because of the offenses it faced.
3. **Combine inside the game simulator.** Let the offense-versus-defense matchup affect decisions and outcomes while keeping the existing game-state engine. Advanced tracking and persistent game-plan adjustments come after this.

Preferred first major experiment (pending Milestones 1 to 4): A0 versus A0 plus current-season coaching and player usage versus A0 plus opponent-adjusted defensive tendencies, evaluated with rolling weekly cutoffs. It tests the central thesis without waiting for every playbook or physics issue to be solved.

Caution: week-to-week information is more relevant to the current matchup but noisier. A team has played only a few opponents, and changes in quarterback, personnel or schedule difficulty can create misleading trends.

## 12. Owner decisions needed

1. Confirm the PBV1 name for new documents.
2. HPV1 contract section 12: (a) cross-season package code (RB+FB or RB-only); (b) pregame eligibility source with an as-of time; (c) formation mapping across 2022 and 2023 onward; (d) 2025 cross-side CB labels.
3. `playbook_prior.py` pin: amend the M3 freeze with the new hash, or revert the file for M3.
4. Bootstrap settings: the spec (2,000 draws, seed 20261028) and the freeze (10,000 draws, seed 20261102) disagree.
5. The A1 functional form, frozen before any fit.
6. The coaching identity source. No verified source is recorded yet.
7. Confirm that the 2025 fold runs only after the candidate is frozen.

## 13. Stop conditions for automated work

Stop and ask before:
- any read of 2026 values beyond a schema audit;
- any commit, push, merge, deploy or production default change;
- any change to a frozen threshold, hash or seed;
- any use of a third-party page or a scraped source;
- any decision listed in section 12.

Commits happen only when the owner asks.
