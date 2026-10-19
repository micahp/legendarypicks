# RESULTS: NFL history-window ablation on fixed test games

Run 2026-10-19 on `research/nfl-history-window-2026-10-19` (off `origin/dev` `fbd1dad6`), against
`research/nfl/PREREG-nfl-history-window-2026-10-19.md` (commit `a91d136f`, pushed **before** the run).
Every number below is from `backend/nfl_history_window.py`; the per-game and per-period CSVs are in
`research/nfl/history-window-2026-10-19/`.

Reproduce:

```bash
cd /root/lp-nfl-history-window
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
  /root/legendarypicks/backend/venv/bin/python3 backend/nfl_history_window.py
```

Read-only: the dev DB is opened `mode=ro`. No production or prod-DB write.

## Verdict (evidence, not adoption): no arm meets the registered keep rule

Widening the prior's history window from one season to two, three, or all available seasons changes
the pooled 2013-2020 Brier by **≤ 0.0001**, and every pooled interval includes zero. The 2024 holdout
also includes zero; the 2025 holdout is **slightly worse** for every wider arm. **Under the registered
keep rule, no arm qualifies.** The adoption verdict is Micah's; this document is evidence.

The honest reading: under the frozen v1 parameter set, **the prior's history window is not a lever.**
The tiny pooled gains (W2 −0.000095, W3 −0.000079, ALL −0.000080) are smaller than the per-season
sign flips (2016 +0.0002, 2018 +0.0003, 2017 −0.0004) and do not survive the holdouts.

## Reproduction check — PASS, bit-identical

The W=1 arm is the incumbent: `prior_for_season` → `season_fit(S-1)` → `prior_from_fit`. Before any
scoring, the harness compared the explicit W=1 prior and the shared backtest loop against
`nfl_backtest.backtest_season(con, S, FROZEN)` on every graded game:

| season | n graded | max &#124;p_model diff&#124; |
|---|---:|---:|
| 2013 | 239 | **0.0** |
| 2014 | 239 | **0.0** |
| 2015 | 240 | **0.0** |
| 2016 | 238 | **0.0** |
| 2017 | 241 | **0.0** |
| 2018 | 239 | **0.0** |
| 2019 | 240 | **0.0** |
| 2020 | 239 | **0.0** |
| 2024 | 256 | **0.0** |
| 2025 | 255 | **0.0** |

The W=1 arm is bit-identical to the incumbent. The only difference between arms is the prior.

## Population

Primary = scored REG games, weeks 2+, seasons 2013-2020, where every arm has a prediction. Holdouts
2024 and 2025 are scored separately. Ties (`outcome is None`) are excluded from Brier/log loss and
counted. The game set is identical across arms (verified per season; no difference).

| period | n graded | blocks | ties excluded |
|---|---:|---:|---:|
| 2013 | 239 | 16 | 1 |
| 2014 | 239 | 16 | 1 |
| 2015 | 240 | 16 | 0 |
| 2016 | 238 | 16 | 2 |
| 2017 | 241 | 16 | 0 |
| 2018 | 239 | 16 | 1 |
| 2019 | 240 | 16 | 0 |
| 2020 | 239 | 16 | 1 |
| **pooled 2013-2020** | **1,915** | **128** | **6** |
| 2024 holdout | 256 | 17 | 0 |
| 2025 holdout | 255 | 17 | 1 |

The block is `(season, Monday of the game's gameday week)`; 16 blocks per primary season, 17 in each
holdout. 2021-2023 are outside the registered evaluation; 2010-2012 are warm-up history only.

## Arms and the chain

Frozen v1 parameters for every arm: `half_life 6.0`, `cap 14.0`, `cap_points None`, `prior_games 4.0`,
`shrink 1/3`, `sigma 13.295`. The only difference is the prior's window:

| arm | prior for season S |
|---|---|
| **W=1** | incumbent: final fit of S-1 with no prior, then shrink |
| **W=2** | recursive chain S-2 → S-1 |
| **W=3** | recursive chain S-3 → S-1 |
| **ALL** | recursive chain 2010 → S-1 |

The chain is `f = season_fit(base, no prior); for t in base+1..S-1: f = season_fit(t, prior=shrink(f)); prior_S = shrink(f)`. The shrink is applied at every link. This is a recursive prior, not a pooled
multi-season fit and not an average of final fits. Seasons before `base` do not influence the prior.

## Primary 2013-2020: per season and pooled

Brier (lower is better). Δ is **arm minus W=1**, paired on `game_id`; negative means the arm is better.
95% interval: `week_block_bootstrap_mean_diff` (this branch), 2,000 reps, seed **20261019**, blocks
`(season, Monday gameday week)`, game-count weighted.

| season | n | blocks | ties | W1 Brier | W2 Δ [95%] | W3 Δ [95%] | ALL Δ [95%] |
|---|---:|---:|---:|---:|---|---|---|
| 2013 | 239 | 16 | 1 | 0.211433 | −0.000252 [−0.000787, +0.000218] | −0.000251 [−0.000831, +0.000217] | −0.000251 [−0.000831, +0.000217] |
| 2014 | 239 | 16 | 1 | 0.217013 | −0.000166 [−0.000716, +0.000312] | −0.000201 [−0.000745, +0.000274] | −0.000203 [−0.000748, +0.000272] |
| 2015 | 240 | 16 | 0 | 0.229652 | −0.000190 [−0.000839, +0.000656] | −0.000280 [−0.000941, +0.000569] | −0.000284 [−0.000939, +0.000559] |
| 2016 | 238 | 16 | 2 | 0.229324 | **+0.000102** [−0.000550, +0.000713] | **+0.000196** [−0.000505, +0.000873] | **+0.000201** [−0.000503, +0.000875] |
| 2017 | 241 | 16 | 0 | 0.220363 | **−0.000422** [−0.000846, **−0.000037**] | −0.000402 [−0.000866, +0.000001] | **−0.000409** [−0.000880, **−0.000001**] |
| 2018 | 239 | 16 | 1 | 0.226487 | **+0.000233** [−0.000285, +0.000765] | **+0.000276** [−0.000274, +0.000874] | **+0.000282** [−0.000267, +0.000886] |
| 2019 | 240 | 16 | 0 | 0.224189 | −0.000032 [−0.000271, +0.000214] | +0.000012 [−0.000239, +0.000274] | +0.000008 [−0.000250, +0.000273] |
| 2020 | 239 | 16 | 1 | 0.219355 | −0.000030 [−0.000519, +0.000454] | +0.000021 [−0.000478, +0.000535] | +0.000023 [−0.000472, +0.000534] |
| **pooled** | **1,915** | **128** | **6** | **0.222226** | **−0.000095** [−0.000273, +0.000094] | **−0.000079** [−0.000264, +0.000121] | **−0.000080** [−0.000266, +0.000122] |

**Only 2017 has a pooled-interval-excluding-zero improvement** (W2 and ALL, about −0.0004). It is
offset by 2016 and 2018 moving the other way, and by 2019-2020 being flat. The per-season signs are
not a stable trend.

Log loss (pooled): W1 **0.634131**; W2 **0.633915** (−0.000216 [−0.000601, +0.000202]); W3
**0.633956** (−0.000175 [−0.000584, +0.000273]); ALL **0.633954** (−0.000177 [−0.000587, +0.000265]).
Every interval includes zero.

## Holdouts 2024 and 2025 (scored separately)

| period | n | blocks | ties | W1 Brier | W2 Δ [95%] | W3 Δ [95%] | ALL Δ [95%] |
|---|---:|---:|---:|---:|---|---|---|
| 2024 | 256 | 17 | 0 | 0.220971 | −0.000111 [−0.000540, +0.000422] | −0.000127 [−0.000596, +0.000458] | −0.000132 [−0.000606, +0.000462] |
| 2025 | 255 | 17 | 1 | 0.228811 | **+0.000026** [−0.000372, +0.000451] | **+0.000027** [−0.000394, +0.000475] | **+0.000026** [−0.000403, +0.000478] |

2024 is a small, unresolved improvement; 2025 is a small, unresolved **worsening**. Neither holdout
improves with an interval below zero.

## Keep rule, applied exactly as registered

For each arm, the rule requires all three: pooled 2013-2020 Brier improves with the paired interval
entirely below 0; 2024 improves with the interval entirely below 0; 2025 improves with the interval
entirely below 0.

| arm | pooled | 2024 | 2025 | meets rule |
|---|---|---|---|---|
| W2 | −0.000095, CI includes 0 | −0.000111, CI includes 0 | +0.000026, CI includes 0 | **no** |
| W3 | −0.000079, CI includes 0 | −0.000127, CI includes 0 | +0.000027, CI includes 0 | **no** |
| ALL | −0.000080, CI includes 0 | −0.000132, CI includes 0 | +0.000026, CI includes 0 | **no** |

**No wider-window arm meets the registered keep rule.** W=1 is the incumbent and is unchanged by
construction. The adoption verdict is Micah's.

## Benchmarks (benchmark only — never an adoption argument)

From `docs/RESULTS-benchmark-ladder-2010-2020-2026-10-13.md`: **538 Elo 0.2193**, **closing market
0.2104**, on the doc's 2010-2020 set (n = 2,633; 538 constants fit on this history, so it is a
flattering bar).

On the **overlapping 2013-2020 games** (same definitions as `backend/benchmark_ladder_2010_2020.py`):

| rung | n | Brier |
|---|---:|---:|
| 538 Elo | 1,914 | 0.218971 |
| closing market | 1,914 | 0.210637 |
| W1 (for reference) | 1,915 | 0.222226 |

The benchmark overlap is 1,914, not 1,915, because `2017_04_CHI_GB` has no market moneyline; it is
excluded from the benchmark subset only, not from any arm score. The doc's 0.2193 / 0.2104 are on a
different (2010-2020) set and are not mixed with the 2013-2020 subset; both are shown with their own
n.

The arms trail both benchmarks on the overlapping games. That is consistent with the benchmark doc's
finding that the model does not yet beat 538 Elo or the market. It is context, not an argument for or
against a window.

## What this says

1. **The history window is not a lever under frozen v1.** The pooled Brier moves by at most 0.0001
   when the prior's window goes from 1 to 2, 3, or all seasons, and every pooled interval includes 0.
2. **The per-season effects are noise-sized and sign-unstable.** 2017 is the only season with a
   resolvable improvement (about −0.0004); 2016 and 2018 move the other way by similar amounts.
3. **The holdouts do not rescue it.** 2024 is a small unresolved improvement; 2025 is a small
   unresolved worsening. The registered keep rule is not met.
4. **The wider window changes the prior, but the prior is a small component of the fit.** The
   season-level prior carries a 4-prior-games pseudo-weight per team, while the current-season weekly
   fit uses every played week with a six-week half-life. The ablation shows the window is not where
   the signal is; it does not by itself prove why.

## Limitations

- One model and one parameter set (frozen v1). The window may interact with `half_life`, `cap`,
  `prior_games` or `shrink`; that interaction is not tested here.
- The chain is a **recursive prior** through `season_fit`, not a pooled multi-season fit and not an
  average of final fits. A different chaining definition could behave differently; this one is the
  registered one.
- 2021-2023 are not in the registered evaluation; 2010-2012 are warm-up only. The result is about
  2013-2020 plus the 2024/2025 holdouts, not about every season.
- The 2024 and 2025 holdouts have 17 blocks each; their intervals are wide relative to the tiny
  effects, so "no resolvable improvement" is not the same as "proven identical".
- Brier is the registered keep rule. Log loss is reported for completeness and is not a second gate.
- The 538 Elo and market are recomputed on the 1,914-game overlap; the doc's 0.2193 / 0.2104 are on a
  different set and are shown separately.
- No adoption, no gate change, no serving change, no prod DB write. The verdict is Micah's.

## Artifacts

- `backend/nfl_history_window.py` — chain, shared backtest loop, `week_block_bootstrap_mean_diff`,
  arm comparison, benchmark join.
- `research/nfl/PREREG-nfl-history-window-2026-10-19.md` — pre-registration, commit `a91d136f`.
- `research/nfl/history-window-2026-10-19/forecasts.csv` — every arm's per-game forecasts.
- `research/nfl/history-window-2026-10-19/arm_scores.csv` — per period, per arm: n, blocks, ties,
  Brier, log loss, paired differences and intervals.
- `research/nfl/history-window-2026-10-19/paired.csv` — long-form paired differences.
- `research/nfl/history-window-2026-10-19/benchmarks.csv` — 538 Elo and closing market on the overlap.
- `research/nfl/history-window-2026-10-19/MANIFEST.json` — SHA-256 and bytes of every artifact, the
  frozen parameters, the reproduction check and the population.

## What I deliberately did not do

- No adoption, no gate or threshold change, no serving or model-coefficient change.
- No prod or prod-DB write; the dev DB is `mode=ro`.
- No post-hoc window, parameter, test-set or bootstrap change. The run is exactly the registration.
- No merge to dev. The verdict is Micah's; this is evidence only.
