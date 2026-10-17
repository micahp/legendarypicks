# Legendary Picks: FBS Game Prediction Research Plan

**Repository:** `micahp/legendarypicks`
**Working branch:** `feat/fbs-data-audit`
**Scope:** NCAA Division I FBS
**Primary objective:** Predict each team's probability of winning a game before kickoff.

## Core direction

The FBS research starts with game-winner prediction. The earlier audit tested player-prop predictions; preserve that work and its results, but do not treat it as the intended first experiment. Player props are a downstream product of a future game simulator, not the initial modeling target.

Build a probabilistic college-football game model, starting with game winners and later expanding to score distributions, totals, spreads, and full play-by-play simulation. The eventual simulation should produce correlated team and player statistics.

Complete Phase 1 before historical expansion. After Phase 1, acquire the complete available historical datasets before advanced modeling experiments. Player-prop history is not required to evaluate a game-winner model.

## Phase 1: Establish the FBS game-winner baseline

Use data already available. Existing audits document downloaded datasets. Do not limit the experiment to games with player props: evaluate the historical population of FBS football games.

### 1. Establish the evaluation population

- Use FBS-vs-FBS games as the primary evaluation population.
- Include FBS-vs-FCS games as separately identified observations where useful for training.
- Report regular season, conference championship, bowl, and playoff games separately.
- Respect each season's historical FBS membership and conference alignment.
- Confirm unique game IDs, dates, final scores, venues, neutral-site status, and opponents.
- Count completed games available in each season.
- Start with downloaded 2022–2025 data and available 2026 results, plus any other historical seasons already present locally. Do not needlessly redownload data for this phase.

### 2. Build simple game-winner models

The target is `P(home_team_wins)`. Start with a deliberately small ladder:

1. Home-field and historical base-rate model.
2. Chronologically updated Elo model.
3. Simple team-strength model using only prior game results, scoring margins, and opponent adjustments.
4. An incremental team-statistics model using already available pregame information, only if the simpler models justify it.

Neutral-site games must not receive normal home-field advantage.

Do not start with player statistics, player usage shares, passing yards, rushing yards, or player prop lines. Those belong in later phases.

### 3. Backtest chronologically

Generate every prediction using only information available before kickoff. Use rolling-origin, season-by-season evaluation. Prefer 2025 as a complete holdout and 2026 as the current forward-testing season. Earlier available seasons can provide development data and additional walk-forward holdouts. Do not randomly split games in a way that leaks future information into training.

For every game, record:

- Game ID, date, season, home team, and away team.
- Pregame data cutoff.
- Predicted home-win probability.
- Actual winner and final score.
- Model version and available feature set.

### 4. Evaluate probability accuracy

Brier score is the primary metric. Also report log loss, calibration, reliability, resolution, and simple winner-pick accuracy. Compare each candidate to the baselines on exactly the same games. Use paired, game-level uncertainty intervals; do not claim improvement based only on a slightly lower pooled Brier score.

If timestamped pregame moneyline odds exist, compare against no-vig implied market probabilities. If historical odds are unavailable, state that limitation and continue with the independent baselines. Do not invent prices or treat closing lines as available before an earlier prediction cutoff.

Report metrics by season, conference, favorite/underdog status, and available pregame strength differences. Also report the requested slices:

- Saturday kickoffs versus kickoffs on other days.
- SEC and Big 12 games versus lower-conference games without Top-10 or playoff teams.

For these slices, record the day-of-week convention and define the ranking/playoff source, cutoff, and conference-group assignment before evaluating results. Use only information available by the relevant pregame cutoff to classify teams; do not use later season outcomes to form the groups. Show sample counts and uncertainty for each slice.

### Phase 1 deliverables

Produce a reproducible report containing:

- Number of evaluated games per season.
- Historical data coverage and missingness.
- Model definitions.
- Brier scores, log losses, calibration, and accuracy.
- Saturday/non-Saturday and conference-tier breakdowns, with sample counts.
- Paired comparisons and uncertainty intervals.
- Identified weaknesses and the next recommended experiment.

**Stopping condition:** A reproducible, leakage-controlled game-winner benchmark exists, and we understand how well the simplest model performs. Superiority over sportsbooks is not required to proceed with the research.

Do not substitute player-prop scores for game-winner results.

## Phase 2: Acquire the complete historical FBS data

After establishing the initial game-winner baseline, expand the historical database as far back as available publishers allow. Do not arbitrarily cap ingestion at 2018 or 2022. Use each dataset's actual published historical coverage. Schedules and final results extend farther back than modern play-by-play and player-usage data; preserve those differences instead of forcing all sources into one date range.

### Required historical data categories

**Games and outcomes**

- Complete schedules and final scores.
- Opponents, venues, conferences, and divisions.
- Regular season and postseason.
- Historical FBS membership.
- Game moneylines, spreads, and totals where available.

**Team performance**

- Offensive and defensive statistics.
- Scoring, turnovers, and penalties.
- EPA, success rates, and explosiveness.
- Pace, play volume, possession, and drive efficiency.
- Situational efficiency, red-zone and third-down performance.
- Opponent-adjusted statistics.

**Play-by-play**

- Every available historical play.
- Down, distance, field position, and game clock.
- Drives, possessions, scoring events, and turnovers.
- Play type and player attribution.
- Passing, rushing, and receiving outcomes.
- Special-teams and defensive events.

**Players and rosters**

- Season and game rosters.
- Player game logs and season statistics.
- Player usage and position groups.
- Recruiting rankings and team talent.
- Transfer-portal activity.
- Returning production and experience.
- Injuries and availability where historically verifiable.

**Coaching and systems**

- Head coaches and coordinators where available.
- Coaching changes and tenure.
- Historical offensive tendencies.
- Scheme and formation information where available.
- Tempo, run/pass tendencies, and substitutions.

**Ratings and context**

- Historical Elo, FPI, and other rating systems.
- Weekly ratings and rankings.
- Conference strength.
- Home field, rest, travel, and neutral-site context.
- Weather where historically available and usable.

### Sources and archive

Use the existing SportsDataverse inventory rather than repeating its discovery work. The prior audit identified 25 `cfb_*` releases and 68 additional college-football releases under `espn_cfb_*` and `ncaa_mfb_*`. Review the full inventory along with CFBD and identify the complete historical range of each relevant category.

Download available raw and reference datasets, plus useful derived datasets stored separately, subject to verified access and licensing rights. Record the exact limitation when a source cannot be obtained. Use Parquet for the historical archive; avoid repeated API calls when bulk historical releases exist.

For every dataset, record its source URL, available seasons, row count, file size, schema, missingness, checksum, provenance, and update date. Keep source data separate from normalized tables and generated model features. Do not commit large historical data files to Git; preserve them in the research storage layer.

### Data safeguards

- Reconcile games and player identities across CFBD, ESPN, and NCAA sources.
- Validate scores and play totals between publishers.
- Never silently convert unknown statistics to zero.
- Prevent duplicate games and duplicate player records.
- Preserve differences in historical statistical definitions.
- Treat published ratings and model outputs as derived features, not original observations.
- Never use season-end ratings to forecast earlier games.
- Weekly `through_week` snapshots that include week W cannot predict week W.
- Do not use retrospectively fitted outcome-based statistics, such as the Paper Index's `paper_share`, as pregame features.
- Record historical coverage gaps instead of estimating missing information without disclosure.

### Phase 2 deliverables

Produce a historical coverage matrix for all datasets and available seasons, a normalized data dictionary, reproducible ingestion scripts, and a complete storage-size report. Show which seasons support game-winner models, team-stat models, play-level models, and eventual player-level simulation. Establish the full usable history rather than relying only on the eight seasons in the initial storage estimate.

## Phase 3: Improve game-winner predictions incrementally

Use the expanded archive to test which additional information improves forecasts. Introduce feature families one at a time. Retain the prior model as the control, evaluate on identical held-out games, and record whether each addition meaningfully improves results. Reject complexity that does not improve out-of-sample results. Do not assume a feature helps because it makes football sense; measure it.

- **A — Opponent strength:** Compare baseline ratings with schedule-adjusted opponent efficiency, conference strength, and defensive performance.
- **B — Play-level efficiency:** Add EPA, success rate, explosive-play rates, turnovers, and situational performance, using prior games only.
- **C — Game environment:** Add pace, possessions, scoring opportunities, field position, rest, home field, neutral-site effects, and other supported context.
- **D — Roster and coaching continuity:** Test coaching changes, returning production, team talent, transfers, and injuries for preseason estimates and in-season forecasts.
- **E — Temporal weighting:** Compare full-history, recent-form, rolling-window, and hierarchical models. Determine how quickly team ratings should adjust during a season.

## Phase 4: Predict full-game outcomes

After establishing a credible game-winner model, expand to joint final-score distributions. Predict and evaluate:

- Probability each team wins.
- Expected scores and scoring margin.
- Expected total points.
- Probability of covering a spread.
- Probability of exceeding a game total.

Outputs must be coherent: the simulated score distribution should imply the model's winner, margin, and total probabilities rather than producing incompatible predictions. Evaluate margins and totals using MAE, probabilistic scoring rules, calibration, and historical market lines where available. Success predicting winners does not imply success predicting totals or spreads.

## Phase 5: Full play-by-play simulation

Develop the simulator using validated team and game-environment models. Simulate possessions, play calls, down-and-distance states, player participation, yards, turnovers, scoring, substitutions, and complete game chronology. Run repeated simulations per matchup to produce distributions of final scores and full-game statistics; validate simulated outcomes against actual historical games.

Player statistics should come from this same game simulation, rather than unrelated predictions. Begin a separate player-prop modeling and market-calibration project only after simulated player statistics are demonstrably useful.

## Execution rules

1. Start with Phase 1. Do not spend another cycle building or optimizing player-prop models.
2. Preserve existing audit reports, scripts, and results. They remain useful prior work even though the previous modeling target was wrong.
3. Work from `feat/fbs-data-audit`. Inspect existing files before writing new ones.
4. Reuse downloaded datasets and existing infrastructure wherever possible.
5. Give each modeling experiment a chronological backtest, explicit control, consistent evaluation sample, and written keep/reject decision.
6. Keep experiments and research data isolated from production.
7. Do not implement advanced models just because they appear in this plan. Prove each preceding layer first.
8. If an experiment fails, document why and proceed based on evidence rather than tuning until the result appears favorable.

## Immediate next action

Inspect the existing FBS audit branch, identify historical game-result and team-level datasets already available, and implement the first chronological game-winner baseline. Produce its report before starting Phase 2.

The first question is: **How accurately can we predict which FBS team wins, using only information available before kickoff?** Everything else builds on that answer.
