# P1 team play-calling component: results (SLC v2 Milestone 3), 2026-11-02

Status: research component result. Development seasons 2023 and 2024 only. No 2025 or 2026 result read. No SLC default change. No simulator run.

## What P1 predicts

The team's regular-season pass share in each game: pass plays over run plus pass plays, from the published play-by-play (`pbp_{season}`, regular season). The estimate shrinks the team's usable in-season pass shares toward a prior with K = 4 pseudo-games.

Prior, in order of preference:
1. The head coach's prior-season pass share across all team-games, if the coach had at least 8 prior-season team-games.
2. The team's prior-season pass share.
3. The league prior-season pass share.

The head coach is carried from the team's latest usable earlier game. The target game's schedule row is never used (owner ruling P1). For a season opener, the carried coach is the last coach of the prior season.

The availability lag is 10 hours after kickoff, as in P2. Publication timing for play-by-play is not stated by the publisher, so this lag is an assumption.

## Results (squared error on team pass share; positive improvement means the component is better)

| Season | Team-games | Component MSE | League baseline MSE | Improvement over league baseline (95% CI) | Team prior only MSE | Improvement over team prior only (95% CI) | Coach-era prior only MSE | Improvement over coach-era prior only (95% CI) |
|---|---:|---:|---:|---|---:|---|---:|---|
| 2023 | 544 | 0.009534 | 0.009821 | +0.000287 (-0.000485 to +0.001030) | 0.010403 | +0.000870 (+0.000290 to +0.001468) | 0.010189 | +0.000655 (+0.000131 to +0.001180) |
| 2024 | 544 | 0.010072 | 0.011167 | +0.001095 (+0.000399 to +0.001812) | 0.010865 | +0.000793 (+0.000234 to +0.001379) | 0.010951 | +0.000879 (+0.000308 to +0.001473) |

Intervals are game-clustered, 10,000 draws, seed 20261102.

Prior sources used: coach-era for 464 of 544 team-games in 2023 and 430 of 544 in 2024. The rest used the team prior. No team-game fell back to the league prior.

## Reading

1. **In-season updating adds a real gain on top of the coach-era prior in both seasons.** The improvement over the coach-era prior with no in-season update is +0.00066 (2023) and +0.00088 (2024). Both intervals exclude zero. This is the robust result.
2. **Against the league baseline, the gain is significant in 2024 but not in 2023.** The 2023 interval includes zero. This is a weak comparator, and the result is reported as it is.
3. **The coach-era prior does not reliably beat the team prior.** In 2023 the coach-era prior has lower error than the team prior (0.010189 against 0.010403). In 2024 it has higher error (0.010951 against 0.010865). The sign flips, so the claim that a coach's history improves the prior is not supported by these two seasons. Reported as found.
4. Null pass shares: none in the development seasons.

## Leakage and availability checks

- The target game is never an input: the usable rule excludes it.
- The coach used for the forecast comes from usable earlier games only. The target game's schedule row is not read for the coach.
- Every forecast row carries a manifest entry (`outputs/p1_forecast_manifest.csv`, 1,088 rows). Each row records the coach used and its source, the prior and its source, the games used, the latest used kickoff, and the check that it plus the lag is at or before the cutoff. All rows pass (`late_violations` 0).

## What P1 does not yet cover

- **Tempo** (plays per game, time of possession) and **fourth-down aggression** are not yet evaluated. They are planned P1 features and remain open.
- **Personnel usage** is not an in-season input. Participation for 2023 onward is published after the postseason (publisher text), so personnel is usable only as a prior-season input, and only from 2024 forward for these development seasons. Not evaluated.
- **Coordinators and play caller** are not identified. The coach-era prior is a head-coach prior. Owner ruling P1 says team tendencies, not the head coach, are the primary signal, and this result is a head-coach-era result.
- **Coaching changes** are not modelled as structural breaks yet. The carried coach changes only when a new game is usable, so a mid-season change is picked up after the first game under the new coach.

## Outputs

- `p1_team.py`: the component (carried coach, prior fallbacks, shrinkage, team-game loader).
- `p1_eval.py`: the development evaluation and manifest.
- `test_p1_team.py`: 11 passing tests (coach carry-forward, target coach excluded, opener rule, lag boundary, prior fallbacks, shrinkage, leakage, null handling).
- `outputs/p1_results.json`, `outputs/p1_forecast_manifest.csv`.
