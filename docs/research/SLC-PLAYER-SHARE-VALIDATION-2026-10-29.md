# SLC player-share validation, 2026-10-29

Status: research only. The validation fits on 2024 regular-season player counts and scores the next season, 2025. No 2026 game outcome was used. The results do not establish player projections or team-score calibration.

## Method

The Dirichlet-multinomial MLE v2 model in scripts/nfl_sequence/share_distributions.py fits each team's player opportunity shares from 2024 and estimates one concentration parameter per role by maximum likelihood. For each 2025 team-game, the fixed-share model uses the same 2024 shares. The Dirichlet-multinomial model allows those shares to vary between games around the same mean.

The held-out score includes only players with 2024 history on the same team. Shares are renormalized across those players. Team-games with zero total opportunities for that returning-player group are skipped. The result therefore describes returning players, not the full 2025 rosters.

## Cohort and log score

Each role had 544 2024 fit team-games. The 2025 season has 544 team-games. The score includes 543 receiver team-games and 526 carry team-games after applying the returning-player restriction. It covers 494 receivers and 329 rushers.

| role | fitted concentration | fixed-share log score per team-game | Dirichlet-multinomial log score | improvement with 95% interval |
|---|---:|---:|---:|---:|
| targets | 24.406 | -21.4356 | -17.1322 | +4.3034 [3.9726, 4.6565] |
| carries | 7.542 | -13.9681 | -8.4250 | +5.5431 [4.9028, 6.2299] |

Higher log scores are better. The intervals are percentile bootstrap intervals from 2,000 resamples of team-game differences. The resampling treats team-games separately and does not cluster both sides of the same NFL matchup, so the interval is exploratory.

## Opportunity dispersion

| role | observed mean player variance | fixed-share predicted variance | Dirichlet predicted variance | observed zero rate | fixed-share predicted zero rate | Dirichlet predicted zero rate |
|---|---:|---:|---:|---:|---:|---:|
| targets | 2.7741 | 1.1413 | 2.1893 | 0.6837 | 0.4948 | 0.5562 |
| carries | 4.8394 | 1.1161 | 3.9906 | 0.7614 | 0.5864 | 0.6730 |

The Dirichlet-multinomial moves the predictions toward the held-out variance and zero rate for both roles. It remains underdispersed.

## Full-game score check

I reran the player-share control on the same current source state as the saved Dirichlet arm. Both runs used the frozen 2026 Week 8 CAR-GB snapshot, the same play-call artifact and reference frame, and seeds 1 to 100. Each completed 99 full games; seed 32 was blocked in both. Every paired valid seed had exactly the same final score, home margin, and total points. Mean total points were 39.99 and mean home margin was -0.43 in both arms.

This confirms that per-game share variation changes who receives credit without changing team scores on this snapshot. The layer is off by default. The output hashes and exact input fingerprints are in docs/research/SLC-RESULTS-PIN-2026-10-29.json.

## Limits

The held-out comparison is conditioned on returning players with same-team history. The bootstrap does not cluster by actual matchup. The full-game score comparison is one matchup and 99 valid seeds. Neither result supports a default change or a scoring-calibration claim.
