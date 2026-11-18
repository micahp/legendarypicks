# PBV1 package sampler: what we have and why on and off did not change

Status: partial. Two week 10 games are still running (WAS at NYG, LA at ARI). This report will be updated when they finish.

## What ran

- Model: the v2 code on the v1 full-stack profile, with no v2 flags. Off: no package sampler. On: `--playcall-pbv1-package`
  with the frozen training table `pbv1_training_plays.csv` (sha256 ab875384...).
- TNF, IND at HOU, 2026-11-19, 100 seeds per run (seeds 300001 to 300100). Both runs completed.
- Week 10 slate, 10 seeds per game. Both models completed 12 of the 14 games. The two remaining games are running.

## Results

- TNF: on and off give identical points in every one of the 100 seeds.
- Week 10 (12 games): on and off give identical grades. Brier 0.2467, log loss 0.6879, mean absolute margin error 10.83.
- Corrected v1 on the same 12 games: Brier 0.1917, log loss 0.5645, mean absolute margin error 11.23.

## Why on and off did not change anything

- The sampler runs. The PBV1-on run records package draws (134 in the first TNF game record, mostly package 11).
- The draw sets `chosen['personnel']` in `pre_event.py` (around line 366).
- The formation layer also writes `personnel`, but only to count tables.
- A search of the drive, game-state, play-call, and single-play code found no reader of the personnel label that affects
  a result. The search was not exhaustive, so this is the likely cause, not a confirmed one.
- Next step: trace every reader of `personnel` in the outcome path, and confirm whether the label changes any draw.

## Caveats

- Ten seeds per game is shallow. Differences this small would not show up at this size.
- The two-game gap in the week 10 slate is due to the streak-file code bug, which is now fixed.
