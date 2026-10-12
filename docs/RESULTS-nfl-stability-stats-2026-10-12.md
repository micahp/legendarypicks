# Results: first-half vs second-half stability of matchup stats and player shares

Date: 2026-10-12. Step 2 of the plan in [RESEARCH-nfl-model-inputs-2026-10-11.md](RESEARCH-nfl-model-inputs-2026-10-11.md).
Read-only on the dev DB.

## Question

Does a rate measured in the first half of a season predict the same rate in the second half? A stat
that does not carry over cannot predict next week, so it is dropped before any predictive test.

## Instrument

- Table: `nfl_pbp` in `picks.dev.db`, seasons 2010 to 2025 (2026 excluded, season in progress).
- The stored table holds regular-season plays only (max week 17 or 18, 272 games in 2025, no playoff
  weeks). It has no `season_type` column, so none was used.
- Half cut per season: weeks up to half of the season's max week are half 1, the rest half 2.
- Team-season unit: one team's rate in each half. 32 teams x 16 seasons = 512 team-seasons.
- Shares are recomputed from play-by-play. The existing `player_game_shares` and `player_team_shares`
  tables only cover 2025 and 2026, too few seasons for a stability test.
- Script: `stability.py` in the session scratchpad (not committed). Pearson r is computed by hand.

## Team rates

| Rate | Denominator | Pooled r (half 1 vs half 2) | Per-season r, median (min to max) |
|---|---|---|---|
| Pressure generated (`qb_hit` on the defense) | dropbacks faced | +0.34 | +0.34 (+0.02 to +0.50) |
| Sack rate allowed | offense dropbacks | +0.39 | +0.35 (+0.11 to +0.61) |
| QB scramble rate | offense dropbacks | +0.70 | +0.69 (+0.49 to +0.89) |
| No-huddle rate | offense plays | +0.86 | +0.83 (+0.53 to +0.96) |

## Player shares

Share = player's count / team's total in that half. Each row keeps players meeting the threshold in both
halves.

| Share | Threshold (count in each half) | n player-season pairs | Pooled r | Per-season median (min to max) |
|---|---|---|---|---|
| Target share | 10 targets | 3,106 | +0.70 | +0.71 (+0.62 to +0.77) |
| Carry share | 10 carries | 1,559 | +0.74 | +0.75 (+0.65 to +0.83) |
| Receiving TD share | 1 TD | 1,845 | +0.31 | +0.30 (+0.16 to +0.47) |
| Rushing TD share | 1 TD | 911 | +0.42 | +0.46 (+0.26 to +0.56) |

## Reading the numbers

- **Carries and targets carry over.** Both are well above the TD shares. Target and carry share are the
  inputs Spec B needs.
- **TD shares are the weakest.** They are the Fant-type cases from before: a small number of touchdowns
  per half, so the share moves a lot from one half to the next. Do not weight TD shares as a stable
  signal.
- **Team rates split.** No-huddle and scramble rates are very stable, and they also look like team style
  rather than matchup information. Pressure generated and sack rate are moderate (r about 0.35 to 0.4).
  At around 8 to 9 games a half, sampling noise is a large part of that, so a moderate r does not show
  the stat is a clean signal. Step 3 has to test whether it predicts margin beyond EPA.

## Caveats

1. **Selection bias in player shares.** Requiring 10 targets or carries in each half keeps only the
   regular starters, which narrows the range and pushes r up. The shares are likely more stable than
   the cut shows for starters and less stable for backups. A threshold-free run would be needed to
   separate those.
2. **Noise is not measured.** No noise floor (a random-split or permutation baseline) was run. The r values
   above are not compared against what chance would produce at these sample sizes.
3. **These are stability results, not predictive results.** Nothing here shows a stat moves game
   margin. That is step 3.
4. **Pressure and sack rates are on dropbacks.** `qb_dropback` is null on about 1,400 plays per season,
   and those plays are excluded from the denominators. Rows where `qb_hit` is null but the play is a
   dropback are counted as no hit.

## Next

1. Step 3, predictive value over EPA, for the stats that held up: pressure generated, sack rate, and the
   target and carry shares as absence inputs. Use FTN only where it adds something (blitz rate, pass
   rushers), because it covers 2022 to 2025 only.
2. A threshold-free rerun of the share test, and a noise-floor baseline, before any of these is called stable.
3. Spec B: target and carry shares are the candidates for player volume, subject to step 2's rerun.
