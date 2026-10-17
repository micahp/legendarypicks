# Plan: NFL receiver target-share distribution v1

Branch `nfl-receiver-target-share-dist-v1`, worktree `/root/lp-target-share`,
branched from `scratch/spec-b-rebase` (37682186). Read
`docs/HANDOFF-player-projections-2026-10-16.md` and
`docs/RESULTS-nfl-marcel-and-calibration-2026-10-16.md` first.

## Why this next

Spec B's player opportunity allocation has a concrete weakness: projected targets
are allocated to players who will not participate, based on the final injury
report. This damages every downstream receiving market (targets, receptions,
receiving yards, receiving TDs) even when the team's overall volume estimate is
reasonable.

The plays x pass-rate decomposition from
`feat/nfl-props-opportunities-propensity` closed as NOT_ADOPTED does not address
this. The fix belongs in player-level target-share allocation, not in the
team-volume layer.

## What is already built

- Team passing volume: `nfl_player_projection_v2.team_volume` (Spec B 4.1),
  regressed own-versus-allowed blend with K_T. This is the incumbent and is used
  unchanged as the team total.
- Player share priors: `nfl_player_projection_v2.raw_share` (Spec B 4.2),
  recency-weighted season-to-date share regressed to the prior.
- Availability signal: `player_game_availability` with `report_status` (Out,
  Doubtful, Questionable, or null). 2024 rates:
  - null/empty: 89.9% play rate
  - Questionable: 63.4%
  - Out: 0.0%
  - Doubtful: 0.0%
- Downside simulation: `nfl_player_projection_v2.simulate` (NegBin targets,
  binomial receptions, gamma yards per reception).

## Three candidate models

All three use the existing Spec B team volume (`team_volume('tgt', K_T)`) as the
team total, then differ in how shares are allocated among players.

### Candidate 1: Baseline (Spec B as-is)

`share_v20` from the engine. Availability is handled by the v2.0 rule: remove
Out/Doubtful players, redistribute shares proportionally, observed share blended
at n / (n + MIN_TOGETTER). No probabilistic adjustment.

### Candidate 2: Availability-adjusted

Remove Out/Doubtful players from the candidate set and redistribute their share
to the remaining players proportional to base share, scaled to 1 - OTHER. But
rather than a hard cutoff, use `report_status` to estimate each player's play
probability before kickoff:

- Out/Doubtful: p_play = 0.0
- Questionable: p_play = 0.5 (to be fitted or calibrated)
- null/empty: p_play = 0.9 (to be fitted or calibrated)

Each available player's *effective* share = base_share / p_play, then
renormalized among available players. This prevents shares from being allocated
to players who won't play while not over-allocating to the remaining players.

### Candidate 3: Probabilistic shares (Dirichlet-multinomial)

Model the full team's target allocation as a Dirichlet-multinomial: the team's
total targets T are distributed among N players where the share vector follows
Dirichlet(alpha), with alpha_i derived from each player's base share scaled by a
concentration parameter.

The key parameter is the concentration phi: low phi means shares are volatile
and concentrated on one player; high phi means shares are close to the prior.
Fit phi on 2024 to match the observed variance of per-game target shares around
their priors.

Each player-game receives a simulated draw from the resulting Dirichlet over
total targets, which then feeds into the existing simulate() function for the
downstream stat distribution.

## Data sources

- `player_game_logs` (nflverse): targets, receptions, rec_yds, rec_td per
  player-game, seasons 2010 to 2026
- `player_game_availability`: report_status, played — the pre-kickoff signal
- `nfl_hist_snap_counts`: snap share for role/context
- `nfl_player_projection_v2.History`: existing loaded view, reused as-is

## Evaluation

All evaluation is walk-forward on 2026, with parameters frozen from 2024
fit (matching Spec B's protocol). 2026 games are reserved for prospective
confirmation.

### Primary test: target-count distribution quality

For each candidate, simulate K=4000 draws of (targets, receptions,
rec_yds, rec_td) for each player-game. Evaluate:

1. **CRPS** on target counts against the incumbent, with paired clustered 95%
   intervals (clustered by player-game). The new candidate must improve CRPS
   with the interval excluding zero.

2. **Interval coverage** at 50%, 80%, 90%: the fraction of actuals within the
   corresponding simulated quantiles. Report for targets, receptions, and
   receiving yards.

### Secondary tests

3. **MAE** on targets, receptions, receiving yards, receiving TDs — report
   with the incumbent.

4. **Market comparison**: compare the prop probabilities implied by each
   candidate's simulated distribution against the sportsbook market, both
   market-only and market-plus-model. Test separately.

### Acceptance criteria

- Primary: CRPS on targets improves over the incumbent with paired clustered
  95% interval excluding zero.
- Secondary: coverage at 50/80/90% is within [-5%, +5%] of nominal for targets
  and receptions (receiving yards allowed up to [-10%, +10%]).
- If neither the availability-adjusted nor the Dirichlet model meets the CRPS
  gate, the experiment is NOT_ADOPTED and all three remain on the branch as a
  read-only record.

## Constraints

- Availability must be determined using only information known before kickoff.
  The `report_status` column in `player_game_availability` is filed before the
  game; `played` is the realized outcome and is used only as the label.
- No use of 2026 data in fitting. Parameters frozen from 2024.
- The experiment script is read-only on the DB (mode=ro connection).

## Reproducing

```bash
cd backend
export LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db
python3 nfl_receiver_target_share_dist_v1.py --season 2026
```
