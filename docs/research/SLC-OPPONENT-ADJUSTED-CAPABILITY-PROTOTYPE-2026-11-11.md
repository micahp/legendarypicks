# Opponent-adjusted conditional strength, research prototype (2026-11-11)

**Branch:** `research/slc-opponent-adjusted-mechanisms-2026-11-11`  
**Status:** Implemented, synthetic regression-tested; **NOT yet evaluated on the pinned full historical 2025 holdout and NOT adopted**. No production, database, SLC profile, or simulation default changes.

## Why a different model

SLC's current event and joint-transition models multiply offense and defense frequency ratios derived separately for each team. Their proper scoring has been weaker than a league situation-cell baseline on observed 2025 plays, while the V1.5 full-game ablation also shows that removing the existing weights did not improve winner forecasts. Neither finding proves that team strength is useless: the ratio architecture can miss relative matchup capability, and the simulator's generated pre-play state mix changes the effect of a component.

This prototype fits one coherent conditional distribution per pass or run intent:

```text
logit_event_k = log P_league(event_k | down, distance, field, intent)
                + adjusted_offense(team, intent, event_k)
                + adjusted_defense(opponent, intent, event_k)

P(event_k) = softmax_k(logit_event_k)
```

Both team effects are learned **jointly**, conditioning on the observed opponents, not estimated as independent team win rates or multiplied onto a sample afterwards. Effects are separately regularized by event and intent (L2), centered to avoid identifiability drift, and shrink toward zero when support is sparse. A missing team/context has an explicit league fallback. This is a first statistical capability profile, **not a physics-based protection-vs-pass-rush execution model** or a full context interaction.

This is a coherent **multinomial** model rather than independently fitted sacks/turnover/first-down Bernoulli outputs. Pass events include sacks, sack fumbles, interceptions, other fumbles lost, incompletions, short completions, conversions, and 20+ yard completions. Designed run events cover lost fumbles, negative/zero gains, short/chain gains, and 10+ explosive gains. Sack fumbles count correctly in both sack and turnover marginals. Separate run/pass models allow defense capability differences by intent. It does **not** synthesize a penalty or an offensive touchdown classifier.

## Fixed first evaluation: 2025 holdout

```bash
python3 scripts/nfl_sequence/evaluate_matchup_capability.py \
  --source-dir /root/lp-snapshots/nfl-backfill-2026-10-27/raw/pbp \
  --output /tmp/slc-opponent-capability-2025.json
```

The evaluator reads only source Parquet from **2022–2024** (training) and **2025** (unseen test). It refuses training on target season, duplicate game/play keys, missing required PBP columns, overwritten outputs, and penalty/unknown-status rows. Evaluation uses 2025 observed *pre-play* contexts. The model does not use 2025 EPA tiers or observations as features. Fixed constants, before seeing 2025: 40 pseudo-observations per situation, L2 penalty 60, minimum situation support 20, 16 coordinate sweeps. These are starting values, not empirically optimized hyperparameters.

**Evaluation caveat:** 2025 is a chronological holdout *relative to this new model's fit*, not a pristine family-wide holdout. Prior SLC experiments have already inspected 2025 football outcomes. Treat it as development-exposed research and retain future games/2026 as separate time-safe confirmation. No score is claimed until the command runs and the output is inspected.

Per intent and group, it writes:
- League situation baseline, offense-only, defense-only, and joint model on **identical plays** with multiclass log loss and multiclass Brier.
- Binary Brier/log loss for sack, INT, fumbles lost, turnovers, chain-advance, and explosive event categories.
- All nine historical-training-only EPA offense/defense strength bins, team-level losses, source SHA-256, fit hashes, fallback counts, and a game-clustered 95% paired log-loss interval.
- Source/excluded-row counts, reproducible scorer/model SHA-256s; no edits to source files.

**Promotion policy:** Joint capability must beat the league baseline *and* incumbent event/transition models on exactly matched held-out observed plays with meaningful team/strength subgroup support, calibration, clustered uncertainty, and measured chain/yardage quality. Then and only then integrate behind a distinct opt-in flag replacing the old event-team layer, validate probability contracts and physical NFL transition legality, and run a bounded paired full-game ablation. Preserve 2026 for cutoff-safe walk-forward confirmation; do not fit on target/future games.

**Known limitations:** Uses one situation-conditional residual vector per team rather than varying team effects across situations; no formation, coverage, roster personnel, QB identity, pressure tracking, specific TD conversion, possession/clock model, or new penalty mechanism. The evaluator scores labels extracted from clean PBP; confirm exact event-label parity with existing E1 and exclusions before promoting. Training-only EPA quartiles stratify evaluation; they do not directly enter model predictions. A strong league baseline can still beat this candidate.

## Tests

```bash
python3 -m unittest discover -s scripts/nfl_sequence -p 'test_matchup_capability.py' -v
python3 -m unittest discover -s scripts/nfl_sequence -p 'test_matchup_capability_evaluator.py' -v
```

The CI workflow runs these without historical data. The read-only 2025 holdout run is *not* run in CI because pinned NFL parquet is not available in Actions. Until scored, this is engineering progress, not predictive performance evidence.
