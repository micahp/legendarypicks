# Playcall M3 freeze (2026-11-02)

Purpose: freeze the definitions, denominators, folds, numerical gates and input hashes before any 2026 file is opened.
Governing record: `PLAYCALL-DECISIONS-2026-11-02.md` (commit `dbac437c`). Source inputs are pinned below as of that
commit. Arm functional forms are NOT frozen here; they are frozen after development folds A and B, as the ruling requires.

## 1. Definitions (2022-2025 pre-2026 data; same definitions for every season)

- Scope: season in {2022, 2023, 2024, 2025}, season_type REG, posteam present.
- Scrimmage play: play_type in {run, pass}, excluding qb_kneel = 1 and qb_spike = 1.
- Run: play_type == run. Dropback: play_type == pass (includes sacks). Sack: sack == 1.
- Drive: distinct (game_id, drive) per posteam containing at least one scrimmage play.
- Plays per drive: scrimmage plays / drives.
- Per-game quantities: divided by the number of distinct REG game_ids for the team in that season.
- Carries: rusher_player_name on run plays. Targets: receiver_player_name on dropbacks with a receiver recorded.
- Shares: player count / team total for the same team and season.
- Personnel code: count of RB followed by count of TE in offense_personnel (formation_layer.personnel_code). Overall
  personnel is never counted from raw strings, which list the linemen.

## 2. Metric denominators

- Run/pass predictive log loss: mean over scrimmage plays of -log(p) for the observed run/pass label.
- Brier: mean over scrimmage plays of (p - y)^2, y = 1 for run.
- Uncertainty: paired, game-clustered bootstrap over game_id, 10,000 resamples, seed 20261102.
- Share variance ratio: variance of player share across games / the same quantity observed, per position.
- Team opportunity bias: |simulated - observed| / observed for team-season run count, dropback count and drive count.
- Zero rate: fraction of team-games with zero carries (or zero targets) for a given player role.
- Tails: P95 and P99 of per-game player lines, reported with support counts.

## 3. Folds

- Development fold A: train on 2022, validate on 2023.
- Development fold B: train on 2022-2023, validate on 2024.
- Retrospective fold R (previously exposed, labelled as such): train on 2022-2024, evaluate once on 2025. No tuning on 2025.
- Reconciliation (read-only): 2026 observed sources only, for the ARI-DAL audit numbers. Not used for fitting,
  tuning, features, thresholds or arm ranking.
- Prospective: future 2026 games, predictions locked before kickoff. Not started.

## 4. Numerical gates (from the ruling, unchanged)

Play-calling alternatives:
- Log loss improves by at least 0.001 absolute over the corresponding baseline.
- Paired, game-clustered 95% CI supports the improvement.
- Brier does not increase by more than 0.001 absolute.

Player-share and participation alternatives:
- RB and WR share-variance ratios within 0.80 to 1.20 of observed, for adequately supported cohorts.
- At least 10% reduction in absolute variance-ratio error versus baseline.
- No more than 5% relative worsening of team opportunity-count absolute bias.

All arms:
- Zero new football legality or accounting failures.
- Full effect sizes, bootstrap intervals, coverage, zero rates, P95/P99 and subgroup regressions reported.
- Multiple candidate-arm comparisons accounted for before any statistical claim.
- Insufficient support is inconclusive, not passed.
- Passing gates qualifies an arm for prospective validation only.

## 5. Input hashes (sha256, at commit dbac437c)

Play-by-play and participation (`/root/gridiron-playbooks-research/data/raw/`):

- pbp_2022.csv.gz 0c69a71eb39498956c7b1d5c1ca52ce7fe679934a95d1af249facb5ea9829ea4
- pbp_2023.csv.gz 4649804ee0f0a40b41e51ec75a1ce921949d7fab5459213488656b92f78560e8
- pbp_2024.csv.gz 23370d5d10f8104d80d46a1fc5e61f4f6f5a3263fe96fe2dd629913cfcb08c06
- pbp_2025.csv.gz 2f135887790a013fd004e609e37096bb4816d5cc80b9f19122e1bad478961978
- pbp_participation_2022.csv 37eae0a8c388d0974c6df9a1f9a1d01f09f63a21440d3b03d7f208c1438c51e4
- pbp_participation_2023.csv ad01aeb4045ee19a4f086ff38b52b14c8f427d3401e529c3078a4545921650a9
- pbp_participation_2024.csv b1f436a98b2a7759eb4ed1181e072a35c2666f9aeb356a49c943d28d6be6b0b9
- pbp_participation_2025.csv 59069adfee7b0f464befba8a5e8be331e523633cc6a7ab403d37bcbcdfbe66ac

Baseline tables (`docs/research/playcall-baseline-2022-2025/`):

- team_season.csv ca86d81da08a016a22527a4a65f0016fc9b85cc86e82ebbba60377c56efad224
- player_season.csv 615ea8a7d53a783bfeef9ce2364eeeb9eec8c03b1bf90b2cf0727aa6076aeba4
- personnel_by_team_season.csv 85513f41c8fc74713725932a06cf1c68b7fa27e2bdba4a481879726c5da68d98
- build_baseline.py e15ad2bc1e3d6cdd6295d7d151431a407180d246f99fbaf18a8323accdb2a390

SLC code files the arms depend on (`scripts/nfl_sequence/`):

- slc_config.py 64c23cc336aecfa89ddc0518d970d14ec3ba518b7421e50eda2996bda49dc3c1
- decision_layer.py 6900696a6ba246d45e76e299d0ebb4ca9dc32157921067c96bb30305b7509ce8
- playbook_prior.py 837e6de9ea6816725d64db30ddec31daf66db0cdd8e81b455d7918bdb240b6a0
- formation_layer.py 34ad0f35c1d2921d1caff421d1eed43001d1243d0a1d6524e10257e1ae9c3412
- defense_layer.py d25574f41a314ad6670baa96629f37d29d3e4d3cf1cd9b171a64bb242bceb4b3
- pre_event.py 635c92864287903027ea02477c5c7b004f8ffa843ffaaeddf612495d796058f8

## 6. Q1 verification requirement (for any arm that uses the playbook prior)

The resolved profile manifest must show: playcall_playbook enabled, the enabled-layer flags, the source hashes above,
and nonzero playbook-prior usage counts. A prior that is enabled but unused is a diagnostic failure. The profile is not
edited.
