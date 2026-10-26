# NHL 2021 As-Of Roster Reconstruction and v0.2 Evaluation Audit Plan

**Date:** 2026-10-25  
**Status:** Research plan; no validation or adoption claim  
**Repository:** `micahp/legendarypicks`  
**Branch at drafting:** `research/nhl-team-player-sim-2026-10-25` (`888a956734e4066f124d06f65cefbc0dcd84fa75`)  
**Scope:** 2021 *start season* (2021–22), NHL regular-season development population  
**Purpose:** Establish whether the verified GameCenter boxscore archive supports historically plausible player and goalie inputs for a paired v0.1/v0.2 development evaluation, without retrospective lineup leakage.

## Decision and boundary

Proceed with a **sequential, single-process, read-only source audit**. The NHL database's recent-season player logs and roster snapshots cannot supply a genuine 2021 as-of roster. The verified historical GameCenter boxscore archive contains player appearances and game statistics that may support a **prior-appearance roster proxy**, derived only from games strictly before each target date.

A roster reconstructed this way is **not** a verified pregame roster, actual active lineup, injury report, confirmed starter, or a historical provider snapshot. Label all historical outputs as **chronological reconstructed-input research**, not as historically issued predictions. An archive downloaded later may contain retrospective corrections; without original publication vintages, game-date filtering proves chronological isolation but not perfect historical data availability.

Do not use any target-game or later boxscore, PBP, shift chart, opponent outcome, participant list, goalie starter, or final score to construct that target's features.

## Frozen populations and source eligibility

Reuse the pinned, hash-verified GameCenter PBP and independent boxscore archives established by the v0.1 research report.

- Training source: eligible start-season **2019–2020** games (1,064 and 857 games, respectively).
- Development: start-season **2021** (1,312 listed, 1,292 eligible under the current v0.1 checks; recompute and report rather than assuming this remains unchanged).
- Start-season **2018** stays quarantined for demonstrated PBP chronology failures.
- Start-season **2022** is previously exposed and partial; not an untouched holdout.
- No future 2021 records may enter a historical target's input feature computation.
- Preserve the existing v0.1 and alpha2 source hashes, model artifacts and evaluation splits.

Eligibility for player reconstruction is **separate** from eligibility for event simulation and shift ledgers. Track these flags separately rather than discarding or silently repairing games.

## Sequential reconstruction algorithm

1. Verify the raw manifest entries and compressed-body hashes before including source data.
2. Extract only compact per-game facts from each eligible historical boxscore: game ID, date, regular-season designation, team IDs, player NHL-native IDs, team/position evidence, game participation, TOI, goalie appearances and starts when explicitly supported, and the subset of player stats needed by the simulator.
3. Process input history in ascending **game date**, with all games on one date grouped together.
4. **Before ingesting any outcomes from target date D**, construct a frozen pregame feature snapshot for every eligible D game using only observations with `game_date < D`. This conservative same-day exclusion avoids uncertain intraday publication timing.
5. Score or prepare all target games on D against those frozen snapshots. Only after every D snapshot is frozen may D's observations be appended to historical state for subsequent dates.
6. Accumulate compact rolling player/team and goalie history keyed by stable NHL player/team IDs. Handle team changes explicitly; never collapse the same player into two IDs or attach a player's new team to old appearances.
7. Do not infer that a player with no prior NHL appearance must be unavailable. Record **unseen/debut/call-up uncertainty** and the resulting coverage deficiency.
8. For each team, create an explicit *projected-eligible player pool*, not an actual confirmed lineup. Compute counts of usable forwards, defenders and goalies and document fallback rules. Do not silently backfill from the target-game roster.
9. Construct goalie starter probabilities only from previous-game evidence and available historical team/goalie associations. Mark every unconfirmed starter **uncertain**. No target-game starter may inform selection.
10. Persist compact, deterministic features, source hashes, sample counts, coverage and failure reasons. Keep the full source documents out of retained memory and out of Git.

### Leakage assertions

For every `PregameGameSnapshot` require:

- `target_game_date`, `feature_max_game_date`, roster mode (`prior_appearances_proxy`), source hashes and explicit uncertainty flags.
- `feature_max_game_date < target_game_date`; raise a hard error on violation.
- No target-game ID in supporting player, goalie, team or roster evidence.
- No later game or 2021 future-derived rate estimates, normalizations, trained hyperparameters or fitted parameters.
- No historical feature assembled from the current 2026 roster snapshot, recent-only NHL tables, or the current 2026 B3 feature ledger.
- Historical prior-game final boxscores used as past observations are distinguished from authentic, vintage pregame availability records.

If the as-of eligibility criteria cannot be met, mark the game ineligible for that analysis and retain it in the coverage denominator.

## Team-strength and model reconstruction

Reconstruct **historical team-strength/Elo state as of each 2021 target** from appropriate earlier results; the current 2026 prospective B3 feature ledger must not be replayed into 2021. Freeze the fitting window and the update rule before evaluation.

Use the 2019–2020 PBP/boxscore training pool for static fitted shot/event parameters, with chronological previous-game observations allowed only under an explicitly labeled **online prior-history update** rule. Never train on later 2021 games when predicting earlier 2021 dates.

Version the exact team means, roster estimates, player rates, goalie priors, simulation seed, and model/source checksum per evaluated matchup. Report how many target games have valid historical team strengths independently of roster readiness.

The current v0.2 alpha2 uses donor events and remapped shift periods and is **not** a fully state-conditioned simulator. Evaluation must retain this limitation and not present player/shift totals as validated forecasts.

## Resource and operational constraints

- Read-only: no production or development DB writes, remote requests, server restarts, or model promotion.
- One scanning process; iterate archive sequentially. With reported **2.9 GiB** memory headroom, do not load the entire decompressed PBP or boxscore corpus at once.
- Immediately release each raw document after extracting minimal fields. Maintain compact per-player/per-team aggregations and optionally checkpoint deterministic derived summaries outside Git.
- Explicitly report peak resident memory, processed game counts, failed hashes/parses, elapsed runtime and resume behavior.
- Do not relax previously frozen hash, event-order, SOG or complete-game quarantine checks to improve coverage.
- The first step is an audit of eligible source coverage, not a full 500-draw simulation for every historical game.

## Required audit report

Report the following **by season, month, team, and when relevant position/goalie role**:

| Measure | Required output |
| --- | --- |
| Source coverage | Listed games, verified boxscores, eligible event/boxscore joins, quarantine reasons |
| Historical pregame proxy | Target games with usable **both-team** prior-appearance player pools; total target-game denominator |
| Player history | NHL ID resolution, games of exposure, missing/debut/call-up players, team changes, projected pool size |
| Lineup feasibility | Count with sufficient forward/defense/goalie candidates; percentage requiring fallback; reason codes |
| Goalie history | Candidate goalie count, prior starts/TOI/shot evidence, share with unresolved or weak starter priors |
| Team priors | Exact historical Elo/goal/SOG feature readiness and oldest/newest permitted evidence |
| Shift source | Separate eligible donor-game/period and remapping coverage; no claim of target-game projected shifts |
| Survivorship/selection | Eligible-versus-excluded team, date and matchup distribution; reasons and denominators |
| Audit reproducibility | Source and output checksums, deterministic sort/order, peak memory, repeated-run parity |

Coverage must be reported on **all 1,312 listed 2021 games** (and separately the 1,292 event-eligible population), not only on games where the simulation completes. If counts differ after fresh audit, explain why before proceeding.

**Stop/go criterion for historical development comparison:** both teams' proxy rosters and goalie distributions must be reconstructible without target/future-game information; all missingness, fallbacks and game exclusions must be counted. If coverage is unrepresentative, publish the audit but do not make broad model-performance claims.

## Paired development evaluation after coverage passes

For identical eligible 2021 games, run and compare:

1. Frozen **v0.1** league-level period bootstrap.
2. Existing, date-correct **team-strength/score-only** baseline(s).
3. Frozen **v0.2 alpha2** with chronological reconstructed historical player and uncertain-goalie inputs.

Use identical target-game IDs and outcomes; predeclare comparison population, evaluation time, seed budget, metric definitions and model version. Use matched-game paired differences with game-cluster uncertainty.

Required metrics:

- Home-win Brier and log loss.
- Regulation/OT team-goal CRPS and official final-score CRPS; joint score and margin diagnostics.
- SOG CRPS, period-level shot and goal counts, event-count means/variance and timing distributions.
- OT and shootout rates, power-play/special-teams diagnostics, and player/goalie/TOI coverage.
- Calibration/selection analysis by month, team, history depth and projected-roster quality.

Where an **exact regular-season game join** exists, include the normalized SBR no-vig closing moneyline as an **external market benchmark**. Reconcile date, teams, game type and final-score settlement. Do not join by matching a similar team/date string without verifying identity. SBR close is not a timestamped T−90 quote or proof of a historically tradable price.

Treat Monte Carlo confidence bounds as **sampling uncertainty** only; do not conflate them with uncertainty from unknown lineup, reconstructed eligibility, or model error.

Use paired and coverage-controlled diagnostics to determine whether conditioning adds value over the frozen v0.1 and team-only baselines. Document any player-level evaluation as exploratory if authentic historical pregame eligibility is unavailable.

## Promotion rule

**2021 is development only.** Improvements there can motivate another preregistered candidate but cannot establish adoption or betting profitability. Require an independently frozen later-season or truly prospective cohort with historically available rosters and goalie evidence before promoting the simulator to Legendary Picks forecasts.

No code changes, production writes, or forecast promotion are authorized by this document. The next deliverable is the coverage/leakage/memory audit report and its pinned derived data manifest.
