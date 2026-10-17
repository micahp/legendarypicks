# NFL props: does more history help, and what full Marcel is worth

Measured 2026-10-16 on `picks.dev.db` (read-only for every grade), on `scratch/spec-b-rebase`. Three
questions, in the order they were asked: can v2's probabilities be repaired without new data, does a full
Marcel baseline beat Marcel-lite, and does a third season of history buy more than calibration does.

## What was added to the database

| item | rows | space |
|---|---:|---:|
| per-game logs, seasons 2010 to 2023 (`ingest_nfl_weekly_stats.py --year --all-positions`) | 248,485 | +95.9 MB (`player_game_logs` 91.5 to 187.4 MB) |
| birth dates (`ingest_nfl_player_ages.py`, new table `nfl_player_birth_dates`) | 24,854 | +2.8 MB |
| index and freelist growth | | about +35 MB |
| **total** | | **+134 MB** (dev DB 2,816 to 2,950 MB) |

NFL log coverage is now 17 seasons, 2010 to 2026, 292,415 rows. Load provenance for the 14 new seasons is
recorded in `nfl_hist_loads` with the artifact sha256, and `file_rows = stored_rows` for every one of them.
Birth dates resolve for 100% of skill-position player-seasons in every season 2010 to 2025 and 87% in 2026
(in-season rookies are not in the roster artifact yet); 23,707 of 24,854 rows join to a `players` row.
`players` was not altered: the ages live in their own table because an ALTER on a shared table is a change
other sessions did not agree to.

Scope note: the back-seasons were loaded with `--all-positions` so they match the existing 2024 and 2025
rows, which carry defensive and kicking lines. Mixing scopes across seasons would make a later coverage
claim false.

## 1. Calibration is nearly the whole measured gap, and it needs no new data

`calibrate_nfl_prop_probabilities.py`, leave-one-week-out over weeks 2 to 5: the map is fitted on the other
weeks only, so every number is out of sample. 33,519 items on 920 player-games.

| forecast | Brier | log loss | vs raw v2 (clustered 95%) |
|---|---:|---:|---:|
| raw v2 | 0.2747 | 0.7542 | |
| platt, 2 parameters | **0.2488** | 0.6905 | +0.02583 +/- 0.00933 |
| isotonic | 0.2493 | 0.6916 | +0.02543 +/- 0.00971 |
| isotonic, per market | 0.2494 | 0.6994 | +0.02525 +/- 0.00980 |
| market | 0.2460 | 0.6850 | +0.02868 +/- 0.01010 |

A constant 0.5 scores 0.2500. Per market, Platt wins everywhere except passing touchdowns, where raw v2 was
already fine (0.2410) and Platt slightly hurts. Per-market isotonic overfits on the 122-player-game markets
(pass attempts 0.2691, passing touchdowns 0.2569), so pooled Platt is the robust choice.

Murphy decomposition, Brier = reliability - resolution + uncertainty, uncertainty 0.2500:

| forecast | Brier | reliability | resolution |
|---|---:|---:|---:|
| raw v2 | 0.2747 | 0.0260 | 0.0016 |
| platt | 0.2488 | 0.0007 | 0.0019 |
| market | 0.2460 | 0.0001 | 0.0034 |

Read plainly: the entire excess over the floor was miscalibration. Reliability falls 37x; resolution barely
moves and stays about half the market's. The spread shows the same thing: raw v2 runs p10 to p90 of 0.227 to
0.545, Platt runs 0.464 to 0.543, so the repair works by shrinking toward 0.5 rather than by sharpening.
After calibration the model still disagrees with the market by more than 0.05 on 31% of items and hits only
42.5% of those sides. So this makes the number good without making the model better, and what remains
between v2 and the market is an information gap of about 0.003, not a calibration gap.

### Forward only: the same map, fitted only on earlier weeks

Leave-one-week-out trains on weeks *after* the held-out week, which a production fit could never do. The same
map fitted only on weeks strictly before the target week, which is all production would have:

| forecast | Brier | log loss | vs raw (clustered 95%) |
|---|---:|---:|---:|
| raw v2 | 0.2771 | 0.7598 | |
| platt | 0.2488 | 0.6904 | +0.02831 +/- 0.01075 |
| isotonic | 0.2497 | 0.6949 | +0.02732 +/- 0.01109 |
| market | 0.2462 | 0.6854 | +0.03086 +/- 0.01186 |

On the 25,390 items a forward map can score, weeks 3 to 5, Platt lands on **0.2488, the same number to four
decimals as the leave-one-week-out fit**. The gain is not an artifact of training on the future. Per market,
forward Platt beats the market on receiving yards (0.2474 against 0.2481) and improves every market except
passing touchdowns, 0.2434 to 0.2449 with the interval spanning zero, where raw v2 was already fine.

The fitted map is stable in shape and nowhere near the identity: slope +0.232 fitted on week 2, +0.193 on
weeks 2 to 3, +0.165 on weeks 2 to 4, with intercepts +0.071, +0.101 and +0.120. A slope near 0.2 means v2's
log-odds need shrinking by roughly a factor of five to be honest, and the estimate moves *away* from 1 as data
accumulates instead of converging on it. That is structural overconfidence, not sampling noise.

Two operational consequences. Week 2's 8,129 items, 24% of the population, have no earlier week to fit on, so
the map cannot be served in the first week of a season; every later week can. And the map cannot be
pre-fitted from prior seasons, because props exist for 2026 only, so it has to accumulate in season.

## 2. Full Marcel: regression pays, extra seasons and aging do not

`marcel_nfl_backtest.py` implements the full recipe: the target season's earlier weeks on weight 5 and
season k back on weight (5 - k), regression to the position mean with K pseudo-games, and an age multiplier,
all fitted on 2013 to 2021 and graded walk-forward on 2025. MAE on the 2,990 player-games every variant can
score:

| configuration | receiving yards | receptions |
|---|---:|---:|
| window 0, no regression (a plain current-season mean) | 19.722 | 1.411 |
| **window 0, regression fitted** | **19.494** | **1.396** |
| window 1 | 19.579 | 1.417 |
| window 2 | 19.780 | 1.436 |
| window 3 | 19.928 | 1.447 |
| window 5 | 20.013 | 1.452 |
| window 3, aging on | 20.446 | 1.512 |
| marcel-lite, what the site serves | 20.163 | 1.442 |
| position mean only | 22.608 | 1.700 |

Every added season makes the point estimate worse, monotonically, from window 0 through window 5. Regression
to the position mean is the one component that pays (19.722 to 19.494, 1.411 to 1.396). The aging curve hurts
badly (19.928 to 20.446, 1.447 to 1.512). Two things also worth noting: marcel-lite's own weighting is worse
than a plain current-season mean, and the best configuration here beats marcel-lite on both stats.

The aging curve as built is crude, a bucket multiplier on the ratio of the cell mean to the position mean
with a 30-game floor, and it is fitted on levels rather than on the residuals of the regressed prediction, so
it conflates age with role and survivorship. It is not evidence that aging does not exist in the NFL. It is
evidence that this version of it should not be shipped.

Full six-stat run at window 3 with aging, against marcel-lite on identical player-games: receiving yards
20.446 against 20.163, receptions 1.512 against 1.442, passing yards 66.652 against 63.395, pass attempts
7.675 against 7.862, completions 5.355 against 5.493. Marcel loses three of five.

## 3. But for the probability, history is worth a lot, and the first season is most of it

Marcel's P(over) is the share of games in the same window that beat the line: the direct analogue of
marcel-lite's `prob_over`, over more games. No fitted distribution, deliberately, so this isolates the
question of whether more history fixes the probability. Graded on 2026 sportsbook props.

| window | items | player-games | mean games behind each number | Brier | market |
|---|---:|---:|---:|---:|---:|
| 0 (current season only) | 14,315 | 349 | 3.4 | 0.3064 | 0.2463 |
| 1 | 31,853 | 832 | 15.4 | 0.2686 | 0.2460 |
| 3 | 32,093 | 842 | 36.0 | 0.2658 | 0.2461 |

Window 0 reproduces marcel-lite (0.3082) to within 0.002 on a near-identical population, which is the control
that says the harness is sound and the difference is the extra seasons. The first prior season is worth
0.0378 and the next two are worth 0.0028 together. History also fixes coverage: a model with prior seasons
can serve weeks 2 and 3, which the live route cannot, so it grades 842 player-games where the live route
grades 354.

## 4. Discrimination, and whether LP adds anything on top of the price

Brier cannot answer the milestone question on its own: a model that says 0.5 for everything scores a
respectable Brier with no information, and shrinking toward 0.5 improves Brier while losing discrimination.
`measure_nfl_prop_discrimination.py` (new) separates the three terms, out of sample and clustered by
player-game.

| forecast | Brier | reliability | resolution | AUC |
|---|---:|---:|---:|---:|
| v2 raw | 0.2747 | 0.0260 | 0.0016 | 0.5241 |
| market | 0.2460 | 0.0001 | 0.0034 | 0.5619 |

Our discrimination is 0.524 against the market's 0.562. Two corrections to how this was first written up, both
raised in review and both correct.

First, the pooled table above compares different samples: ours is scored on weeks 2 to 5 (33,519 items) while
the refit forecasts are scored on weeks 3 to 5 (25,390). Computing both on the same items and within each
week:

| forecast, 25,390 identical items | pooled | wk3 | wk4 | wk5 | weighted within week | clustered 95% on pooled |
|---|---:|---:|---:|---:|---:|---|
| market, raw | 0.5608 | 0.5589 | 0.5568 | 0.5679 | 0.5609 | [0.5486, 0.5710] |
| ours, raw | 0.5262 | 0.4979 | 0.5065 | 0.5760 | 0.5253 | [0.4901, 0.5571] |
| ours, refit | 0.5181 | 0.4979 | 0.5065 | 0.5760 | 0.5253 | [0.4810, 0.5448] |
| stack | 0.5587 | 0.5468 | 0.5496 | 0.5927 | 0.5621 | [0.5360, 0.5788] |

Refit minus raw on the same items is **-0.00813 with a clustered interval of [-0.02220, +0.00423]**, which
spans zero, so the earlier claim that calibration costs ranking power is **not established**. Note also that
the within-week AUCs for raw and refit are identical by construction: Platt is a monotone transform, so it
cannot reorder items inside a week. Only the pooled figure can move, and it moves because each week is fitted
with its own slope, which changes the scaling *between* weeks. Market minus ours is +0.03453 with
[+0.00027, +0.07589], so the market's discrimination advantage is established, though barely.

Second, the per-market AUCs need clustered intervals before any of them is called inverted, and with them the
picture changes:

| market | n | player-games | ours, clustered 95% | market, clustered 95% |
|---|---:|---:|---|---|
| passing yards | 6,693 | 122 | 0.4755 [0.4012, 0.5822] | 0.5679 [0.5459, 0.5892] |
| pass completions | 701 | 122 | 0.4450 [0.3526, 0.5600] | 0.5493 [0.4987, 0.6100] |
| pass attempts | 797 | 122 | 0.5216 [0.4419, 0.6255] | 0.4882 [0.4426, 0.5327] |
| passing touchdowns | 735 | 122 | 0.6319 [0.5317, 0.7211] | 0.6303 [0.5354, 0.7083] |
| receiving yards | 19,118 | 795 | 0.5207 [0.4960, 0.5569] | 0.5441 [0.5358, 0.5561] |
| receptions | 5,475 | 783 | 0.5383 [0.5023, 0.5744] | 0.5975 [0.5718, 0.6212] |

Ours spans 0.5 on passing yards, completions and attempts, so "ranks those players backwards" was overstated
and is withdrawn. The market's interval excludes 0.5 on passing yards, 0.5679 [0.5459, 0.5892], but includes
it on completions, 0.5493 [0.4987, 0.6100], so the strongest supported statement is that **the market
demonstrates positive discrimination for passing yards and the evidence on completions is inconclusive**, while
our passing-yard and completion probabilities are consistent with no discrimination at all. On passing
touchdowns and receptions ours does discriminate, and it beats the market on attempts and touchdowns and loses
on the other four. By position, ours beats the market on running backs (0.5591 against 0.5517) and loses on
quarterbacks (0.4893 against 0.5747), receivers (0.5101 against 0.5589) and tight ends (0.5334 against 0.5547).

**The increment test.** A forward-only logistic stack of the market's log-odds and ours, fitted on earlier
weeks and scored on the target week, asks whether our number carries anything the price does not. The fitted
coefficient on ours is positive every week and shrinks as data accumulates: +0.151 on week 3, +0.126 on week 4,
+0.109 on week 5, against the market's own +0.828, +0.860 and +0.846.

| forecast, out of sample on 25,390 items | Brier | log loss | AUC |
|---|---:|---:|---:|
| market, raw | 0.2462 | 0.6854 | 0.5608 |
| market, refit | 0.2464 | 0.6859 | 0.5556 |
| ours, refit | 0.2488 | 0.6904 | 0.5181 |
| stack (market + ours) | 0.2457 | 0.6843 | 0.5587 |

Clustered by player-game: log loss, market minus stack, +0.00153 with a 95% interval of [-0.00092, +0.00380];
Brier +0.00070 with [-0.00049, +0.00182]; AUC, stack minus market, +0.00307 with [-0.01668, +0.02288].

Read plainly: **the increment is not established.** Every interval spans zero. The point estimates all point
the right way, which is worth something, but on 2026 weeks 3 to 5 Legendary Picks does not demonstrably know
anything about a player's next performance that the market has not already priced. The market's own
probabilities also refit slightly worse than raw, 0.6859 against 0.6854, which is what a well-calibrated
forecast does when you re-estimate it from noise.

The acceptance test for the next milestone is two separate gates, not one, and not a Brier target:

1. **Against the incumbent.** Does the new model improve forward-only Brier or log loss over v2 plus forward
   Platt, with a paired clustered interval excluding zero, while keeping calibration and improving
   discrimination or resolution?
2. **Against the price.** Separately, does adding it to the market improve on the market-only model, with the
   clustered interval excluding zero?

They are distinct accomplishments and neither implies the other. A larger coefficient on ours is not evidence
by itself, because a larger coefficient can accompany worse predictions; the gate is the out-of-sample score
with its interval, not the size of the coefficient.

## 5. The passing audit: it is a volume problem, and the grader has a look-ahead

Two things were wrong with how the passing markets were being assessed.

**The grader selects the population with post-game information.** `grade_nfl_prop_probabilities.py` keeps the
quarterback who led his team in attempts *in the finished game*, `max(team_rows, key=lambda x: (x.att, -x.pid))`,
which reads the target week's box score. The research population is therefore partly selected on the outcome
and cannot represent pregame forecasting.

`audit_nfl_passing_projections.py` (new) rebuilds the population from pregame information only: a
quarterback-game qualifies when he led his team in attempts over the games *before* the target week. The
look-ahead turns out to be small and it was **not** flattering: 113 pregame quarterback-games against 124
post-game, and the passing-market Brier is 0.2713 on the pregame population against 0.2784 on the post-game
one. The post-game filter was selecting a harder population, so it made the model look worse rather than
better. It still needs fixing, because the population has to be defined without the outcome.

**The failure mode is volume, not efficiency.** Same population, decomposed:

| component | projected | actual | MAE |
|---|---:|---:|---:|
| attempts | 30.959 | 33.177 | 7.141 |
| completion rate | 0.651 | 0.641 | 0.075 |
| yards per completion | 11.088 | 11.104 | 1.881 |
| passing yards | 223.418 | 233.752 | 62.164 |

Completion rate and yards per completion are essentially unbiased, +0.010 and -0.016. Attempts are
under-projected by 2.218, which is 6.7%, and passing yards by 10.3. Decomposing the yards gap on those
numbers, the attempts shortfall accounts for about 15.8 of it, the completion-rate gap about -3.4 and the
yards-per-completion gap about 0.3, which reconciles with the 10.3 observed once the interaction is included.
So the passing-yard under-projection is a **volume** problem, and the efficiency layer is doing its job. The
fix belongs in projected attempts, not in the catch-rate or yards-per-completion constants.

That also explains the discrimination result without appeal to a distribution defect: if attempts are the
input that is wrong, the simulated distribution is being centred on too few opportunities, and no
recalibration of the distribution can recover the missing volume.

## 6. Where the attempt error actually is: dispersion, not level

The 6.7% shortfall explains the mean bias and cannot explain the poor AUC. A uniform correction moves every
forecast without reordering anything, so it cannot improve discrimination. `diagnose_nfl_qb_volume.py` (new)
locates the error, and it is not a per-quarterback effect.

| | projected | actual |
|---|---:|---:|
| mean attempts | 30.959 | 33.177 |
| sd across quarterback-games | **1.728** | **9.708** |

The projection is very nearly the same number for every quarterback while actual attempts vary more than five
times as widely. A predictor with that little dispersion cannot rank anyone, and an AUC near 0.5 is exactly
what it produces.

The decomposition puts the problem in the team-volume layer, since `project_qb` computes
`att = team_volume('att') * raw_share(QB, 'att')`:

| component | projected mean (sd) | actual mean (sd) |
|---|---:|---:|
| team attempts | 31.975 (1.116) | 34.088 (8.913) |
| quarterback share | 0.968 (0.041) | 0.972 (0.111) |

Share is fine and low-variance by nature, because the lead passer takes about 97% of team attempts either way.
Team volume is the problem: it projects roughly 32 attempts for every team. `team_volume` regresses a team's
own season-to-date attempts and its opponent's allowed attempts toward the league mean with `K_T` pseudo-games
and then averages the two 50/50. `K_T` is 8.0 and there is no quarterback override, so in weeks 2 to 5, where a
team has one to four games behind it, 67% to 89% of the projection is the league mean.

**The sweep.** Rebuilding the same projections across `K_T`:

| K_T | bias | MAE | sd projected | sd actual | AUC |
|---:|---:|---:|---:|---:|---:|
| 0.0 | -2.098 | 7.429 | 4.209 | 9.708 | 0.5701 |
| 1.0 | -2.148 | 7.137 | 2.933 | 9.708 | 0.5717 |
| 2.0 | -2.173 | 7.099 | 2.443 | 9.708 | 0.5699 |
| 4.0 | -2.198 | 7.106 | 2.015 | 9.708 | 0.5624 |
| 8.0, as fitted | -2.218 | 7.141 | 1.728 | 9.708 | 0.5500 |
| 16.0 | -2.231 | 7.170 | 1.583 | 9.708 | 0.5312 |

Three things follow, and they are separate problems.

1. **Discrimination rises monotonically as shrinkage falls**, from AUC 0.5312 at `K_T` 16 to 0.5717 at `K_T` 1.
   That is the lever for AUC, and it is not a per-quarterback correction.
2. **The MAE cost is negligible and the fitted value is not even MAE-optimal here.** The whole MAE range is
   7.099 to 7.170, about 1%, and the best is `K_T` 2.0 at 7.099, so the fitted 8.0 is slightly worse on its own
   objective. `K_T` was fitted on 2024 by minimising the MAE of projected *targets* for receivers and then
   reused for quarterback attempts.
3. **The bias is not a `K_T` problem.** It sits between -2.1 and -2.2 across the whole sweep, so the shortfall
   is in the level the shrinkage pulls toward, not in the amount of shrinkage. It needs a separate fix, in the
   league mean or in the 50/50 own-versus-allowed blend.

Two further cautions. Even at `K_T` 0 the projected sd is 4.209 against an actual 9.708, so shrinkage is not the
only source of compression: averaging a team's own rate with its opponent's allowed rate halves the variance of
two noisy estimates before any regression happens, and that is inherent to the blend. And the
per-quarterback table is not a finding at this sample, because each quarterback has three or four games and a
single game's attempts vary with sd 9.7, so a four-game mean error carries a standard error near 4.9 and the
rank order is noise.

**So the next modelling step is not a 6.7% level correction.** It is lowering `K_T` for attempts toward 1 or 2,
worth about +0.04 AUC at no MAE cost, and separately correcting the level. Both are testable on the fit seasons
before anything is published, and the passing markets stay out of any public claim of predictive advantage until
they are.

Section 7 does that and **corrects two of the claims above.** The AUC gain is real but smaller than it looks
here, the fitted `K_T` does turn out to be MAE-optimal once the fit is restricted to the right weeks, and the
6.7% shortfall is a 2026-specific level shift rather than a stable model bias.

## 7. Refitting the attempt shrinkage: real but small, and it does not create an increment

`refit_nfl_qb_volume.py` (new) fits `K_T` on the 2013 to 2021 seasons under two objectives and evaluates the
result on 2026, which neither fit saw. The first thing it established is that **the week regime dominates the
answer**, which corrects section 6.

### The regime has to match the evaluation

| K_T | MAE, all fit weeks | AUC, all fit weeks | MAE, fit weeks 2-5 | AUC, fit weeks 2-5 |
|---:|---:|---:|---:|---:|
| 0.25 | 6.658 | 0.6087 | 6.872 | 0.5732 |
| 1.0 | 6.604 | 0.6112 | 6.677 | 0.5755 |
| 2.0 | 6.584 | 0.6127 | 6.600 | 0.5774 |
| **4.0** | **6.581** | **0.6131** | 6.565 | **0.5779** |
| **8.0, as fitted** | 6.601 | 0.6106 | **6.563** | 0.5733 |
| 16.0 | 6.637 | 0.6031 | 6.577 | 0.5616 |

Over all weeks the two objectives agree and both pick 4.0. Restricted to weeks 2 to 5, the regime props exist
in, MAE picks 8.0 and AUC picks 4.0, and they disagree. So:

- **Section 6's claim that the fitted 8.0 "is not even MAE-optimal for attempts" is withdrawn.** It is not
  MAE-optimal over all weeks, but it *is* MAE-optimal in the early-week regime, 6.563 against 6.565. The earlier
  statement was a regime mismatch, which is the same instrument-versus-world error the rest of this document
  keeps running into.
- **The AUC lever is real but small.** In-regime it is 0.5733 at 8.0 against 0.5779 at 4.0, about +0.005, not
  the +0.04 the 2026 sweep in section 6 suggested. That sweep measured against settled prop lines on one season
  and overstated the general gain.
- The curves are flat in both regimes, so `K_T` is not a high-leverage parameter. It is worth moving because it
  is nearly free, not because it is decisive.

### The level is not a stable bias, and the correction does not transfer

| fit-seasons regime | mean projected | mean actual | ratio |
|---|---:|---:|---:|
| all fit weeks | 35.329 | 34.922 | 1.0117 |
| fit weeks 2 to 5 | 35.547 | 35.438 | **1.0031** |

Restricted to the same weeks as the evaluation, the model is **unbiased**: ratio 1.0031, shift +0.109 attempts.
The 2.2 attempt shortfall seen in 2026 is therefore a 2026-specific level shift, not a stable model bias, and
**section 6's framing of it as a volume defect to be fixed is corrected.**

Fitting a level correction on the fit seasons and applying it to 2026 makes things slightly worse, because the
fit-seasons correction is a factor of 0.9969 in the opposite direction: 2026 bias moves from -2.198 to -2.293 at
`K_T` 4.0, and the market scores all get worse. The correction is dropped.

### What the refit does on 2026, held out

| variant | bias | MAE | sd projected | AUC against the fixed threshold |
|---|---:|---:|---:|---:|
| `K_T` 4.0 | -2.198 | 7.106 | 2.015 | 0.5836 |
| `K_T` 4.0 + level | -2.293 | 7.119 | 2.008 | 0.5836 |
| `K_T` 8.0, as fitted | -2.218 | 7.141 | 1.728 | 0.5765 |
| `K_T` 8.0 + level | -2.313 | 7.155 | 1.722 | 0.5765 |

The refit improves the point estimate and the discrimination on held-out data, in the same direction the fit
seasons selected, and the level correction hurts both.

### The affected market, and the paired test

Pass attempts, 735 of the 1,207 posted items scorable, on 111 player-games:

| variant | Brier | log loss | AUC |
|---|---:|---:|---:|
| `K_T` 4.0 | **0.2568** | **0.7078** | **0.5421** |
| `K_T` 4.0 + level | 0.2587 | 0.7116 | 0.5395 |
| `K_T` 8.0, as fitted | 0.2595 | 0.7133 | 0.5310 |
| `K_T` 8.0 + level | 0.2607 | 0.7158 | 0.5249 |

Paired on the 735 identical items, clustered by player-game:

| metric | `K_T` 8.0 minus `K_T` 4.0 | clustered 95% |
|---|---:|---|
| Brier | +0.00267 | [-0.00187, +0.00824] |
| log loss | +0.00549 | [-0.00378, +0.01684] |

**Both intervals span zero**, so at 111 player-games the market-level improvement is **not established**. The
direction is consistent across three metrics, two populations and the held-out season, which is why it is worth
taking, but it is not a demonstrated gain.

### The increment over the market is negative under every variant

| ours | log loss, market only | log loss, market + ours | increment |
|---|---:|---:|---:|
| `K_T` 4.0 | 0.6978 | 0.7060 | -0.00823 |
| `K_T` 4.0 + level | 0.6978 | 0.7045 | -0.00666 |
| `K_T` 8.0 | 0.6978 | 0.7112 | -0.01344 |
| `K_T` 8.0 + level | 0.6978 | 0.7116 | -0.01385 |

Every increment is negative: on this market, adding our probability to the market's makes the market-only model
**worse**. The refit roughly halves the damage, from -0.01344 to -0.00823, and does not create an increment.

### Against the two gates

1. **Against the incumbent: not established.** The refit is better on MAE and on discrimination in every
   comparison, but the paired clustered interval on the market scores spans zero.
2. **Against the price: fails.** The increment is negative under every variant, refit or not.

So the honest summary of this step is that it removes some of a known harm and demonstrates no gain. `K_T` 4.0
for attempts is worth adopting because it costs nothing measurable and is directionally consistent, the level
correction is not, and the passing markets still cannot be presented as adding information over the price.

## The ladder, paired on identical items

31,843 items on 838 player-games, every forecast scored on the same games, markets, books and lines.

| model | Brier | log loss |
|---|---:|---:|
| market | 0.2461 | 0.6853 |
| **v2 + platt calibration** | **0.2492** | 0.6913 |
| full Marcel, window 3 | 0.2666 | 0.7836 |
| v2, raw | 0.2779 | 0.7618 |
| constant 0.5 | 0.2500 | |

Paired per-item differences, clustered by player-game:

| comparison | difference | clustered 95% |
|---|---:|---:|
| calibration minus raw v2 | +0.02873 | +/- 0.00967 |
| Marcel minus raw v2 | +0.01134 | +/- 0.01193 |
| calibration minus Marcel | +0.01739 | +/- 0.00936 |
| market minus calibration | +0.00308 | +/- 0.00216 |

Read plainly:

1. **Calibration is the biggest single win available and it costs two parameters.** Its interval excludes
   zero. Nothing else measured here comes close per unit of effort.
2. **Multi-season history helps v2 but is not established at this sample.** +0.01134 with the clustered
   interval spanning zero, and no individual market is established either. The direction is consistent with
   the window ladder above, but it is not yet a finding.
3. **Calibration beats history** by 0.01739, and that interval excludes zero. If only one of the two is done
   first, it is calibration.
4. **Marcel's log loss is worse than v2's** (0.7836 against 0.7618) even though its Brier is better. An
   empirical hit rate makes confident wrong calls that log loss punishes harder, so Marcel is not a
   straightforward upgrade on both proper scoring rules.
5. After calibration the market is still ahead by 0.00308 and that interval excludes zero, so the repair
   closes most of the gap and does not close all of it.

## What this says to do

1. Ship the Platt map on the served P(over). Two parameters, no new data, and it takes the served number from
   worse than a coin flip to roughly the market. The forward-only check lands on the same 0.2488, so the gain is
   not an artifact of training on the future. Two constraints: refit it each week on the weeks so far, and serve
   the raw number in week 1, where there is nothing to fit on.
2. Do not feed prior seasons into the point estimate. They hurt MAE monotonically. The current season plus
   regression to the position mean is the best point model measured here, and it beats what the site serves.
3. Do use prior seasons for the probability's denominator and for early-season coverage, since that is where
   they demonstrably help.
4. Refit the aging curve on residuals, not levels, before judging it. The version here should not ship.
5. Re-run the paired ladder after calibration is in, because the Marcel-versus-v2 comparison has an interval
   that spans zero and more weeks of 2026 props will narrow it.
6. Take `K_T` 4.0 for attempts and drop the level correction. Section 7 measures both: the refit is better on MAE
   and discrimination in every comparison including held-out 2026, but the paired clustered interval on the
   market scores spans zero, so it is a near-free directionally consistent change rather than a demonstrated
   gain. The level correction does not transfer and is dropped. The two passing markets still cannot be
   presented as adding information over the price, because the increment is negative either way.
7. Fix the passing grader's population. It selects the quarterback who led his team in attempts in the finished
   game, which is post-game information. The pregame-only rebuild is in `audit_nfl_passing_projections.py` and
   should replace the filter in the grader.
8. Judge the next feature by the two gates in section 4, not by a Brier target and not by the size of the
   stack coefficient. Against the incumbent with a paired clustered interval, and separately against the
   market-only model.

## Reproducing

```bash
cd backend
export LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db
FIT="2013 2014 2015 2016 2017 2018 2019 2020 2021"

python3 calibrate_nfl_prop_probabilities.py --season 2026 --csv /tmp/cal_items.csv
python3 calibrate_nfl_prop_probabilities.py --season 2026 --mode forward --csv /tmp/cal_fwd.csv
python3 measure_nfl_prop_discrimination.py --season 2026 --boot 150    # AUC, decomposition, increment
python3 audit_nfl_passing_projections.py --season 2026                 # volume vs efficiency
python3 diagnose_nfl_qb_volume.py --season 2026                        # where the volume error lives, K_T sweep
python3 refit_nfl_qb_volume.py --season 2026 --fit-seasons $FIT --fit-max-week 5   # refit K_T, level, gates
python3 marcel_nfl_backtest.py --season 2025 --window 3 --fit-seasons $FIT          # MAE ladder
python3 marcel_nfl_backtest.py --season 2026 --props --window 3 --csv /tmp/m3.csv --fit-seasons $FIT
```

Backfill, one season per call, add `--dry-run` first:

```bash
LP_DB_PATH=... python3 ingest_nfl_weekly_stats.py --year 2013 --all-positions
LP_DB_PATH=... python3 ingest_nfl_player_ages.py
```
