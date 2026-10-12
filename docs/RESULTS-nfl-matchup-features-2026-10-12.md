# Results: pressure, sack and touch-share features against frozen v1, 2026-10-12

Plan: [RESEARCH-nfl-model-inputs-2026-10-11.md](RESEARCH-nfl-model-inputs-2026-10-11.md), steps 1 to 4.
Harness: `backend/nfl_feature_backtest.py`, with the shared pre-registered keep rule. Read-only on the dev DB.

## Verdict

**None of the three is kept.** Each has a pooled 2011 to 2023 interval that includes zero, so none
meets the rule. In these specifications, the matchup stats from the stability test do not improve the stacked
game model on identical games, and the market gap is unchanged.

## Pre-registration

- The three features' docstrings, with their parameters, were written before any of them was run:
  `pressure_matchup`, `sack_matchup`, `share_absence`.
- Before the first run, one structural bug was fixed in the helper code, in a sanity check. The
  league-history lookup was calling a method that did not exist. No parameter changed.
- Parameters: dropback shrink 200 (the same as QBE); windows of 8 team games (pressure, sacks, the same
  as QBE) and 4 team games (shares, the same as AVAIL); league rate pooled over every earlier team-game.

## Results (win Brier, feature minus B, 5,000 paired bootstrap)

| Feature | 2011-2023 pooled | 2024 | 2025 (second look) | Margin MAE, pooled | Kept |
|---|---|---|---|---|---|
| `pressure_matchup` | -0.0002 [-0.0006, +0.0001] | +0.0002 [-0.0016, +0.0020] | -0.0020 [-0.0040, +0.0001] | -0.014 [-0.029, +0.000] | no |
| `sack_matchup` | +0.0001 [-0.0003, +0.0005] | +0.0006 [-0.0010, +0.0023] | -0.0013 [-0.0032, +0.0006] | +0.003 [-0.013, +0.019] | no |
| `share_absence` | -0.0000 [-0.0003, +0.0002] | -0.0011 [-0.0029, +0.0006] | +0.0010 [-0.0007, +0.0028] | -0.003 [-0.014, +0.007] | no |

Reference: B (recalibrated v1) is 0.0125 worse than the de-vigged moneyline on 2011 to 2023 (the
`B-mkt` column). None of the three closes any of that gap.

Keep rule: the pooled interval must lie entirely below zero, and the 2024 and 2025 point estimates
must not be above zero.
- `pressure_matchup` fails on the pooled interval, and 2024 is positive.
- `sack_matchup` fails on the pooled interval, and 2024 is positive.
- `share_absence` fails on the pooled interval, and 2025 is positive (+0.0010).

## What each one was

- **`pressure_matchup`:** expected QB-hit rate per dropback. For each side, the offense's hit rate
  taken and the opposing defense's hit rate generated, both shrunk, then compared home minus away.
  Expected sign negative.
- **`sack_matchup`:** the same construction with sacks. Expected sign negative.
- **`share_absence`:** touch share (targets plus carries over pass plus rush attempts) of each non-QB
  player listed Out or Doubtful, summed per team, then home minus away. Expected sign negative. The
  listing is the same one AVAIL uses. The feature is offense only. AVAIL also counts defensive snap
  shares, so the two are not identical.

## Checks

- **Team codes:** play-by-play, schedule and injuries use the same codes in every season. Every
  scheduled REG team appears in play-by-play.
- **Windows:** verified on one team-game (KC, 2016 week 5): the window reaches back into 2015 and
  holds 8 games, 303 dropbacks.
- **League history:** the only base row without league history is 2010 week 1 (column 0). Both matchup
  features report 0 such rows in their output; the 2010 week 1 games are training rows only.
  This is a count of `league_before == 0`, not a check of the training set.
- **Join rate for shares:** of listed Out or Doubtful players, 99% of WR (2303 of 2328), 99% of RB
  (1551 of 1555) and 99% of TE (1227 of 1243) have a play-by-play id.
- **Unmatched listings:** 12,215 listings have no touches anywhere in play-by-play. These are mostly
  linemen, linebackers, cornerbacks and safeties, who correctly contribute no offensive touches. A
  small number of skill players (25 WR, 4 RB, 16 TE) never got a target or carry in the data.

## Caveats

1. **Multiple looks.** Eight features have now been run through this harness, plus one combined run.
   With that many, one interval excluding zero is expected by chance. The pre-registered rule guards
   against this, and none of the three clears it.
2. **AVAIL comparison is not like-for-like.** The AVAIL row in the backfill results uses the same
   win-Brier scoreboard and the same B, but its stack came from a different script
   (`nfl_backfill_features.py`). Its values are close to `share_absence`'s (pooled -0.0001, 2024
   -0.0017, 2025 +0.0008), so the snap-based and touch-based absence measures look alike here.
3. **Share feature has blind spots.** A player out for the whole 4-game window has zero share, so the
   measure is weakest exactly when a starter has been injured for weeks. Doubtful players who played
   recently are the cases it handles best.
4. **Margin MAE for `share_absence` in 2024** was -0.073 [-0.144, -0.004], the one interval in these
   runs that excludes zero. It is a single season, 2025 reversed it (+0.022), and the keep rule does not
   use MAE. It is not a finding.

## Not run

- **The combined run** was in the plan after the three singles. No single feature was kept, so there is
  no kept set to combine. The `kept_combined` slot stays as it was.
- **Player-prop use of shares** belongs to Spec B. This result is about the game model only.

## Next

1. Record the null: under the keep rule, none of the three enters the game model. Shares stay in the plan for player props
   (Spec B), where the stability result (target and carry share r about 0.7) is what matters.
2. The threshold-free share rerun and noise baseline from the stability doc are still open. They
   matter for Spec B, not for this game-model verdict.
