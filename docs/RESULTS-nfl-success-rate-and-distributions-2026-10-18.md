# NFL: success rate as a team feature, and the per-game distribution (2026-10-18)

Branch `feat/nfl-success-rate-and-distributions`, from `dev` at `6b637a65`. Read-only on `picks.dev.db`.
Not deployed, nothing pushed to production, no table written on the shared dev DB.

Micah's definition is used throughout: **success rate *is* the consistency measure** — the share of plays
that succeed. There is no separate SD-of-EPA feature. One feature, one definition, tested against raw EPA
per play as the control.

---

## A1. Does success rate help the game model?

### What is built, and from which plays

`backend/nfl_team_quality.py` builds two ratings per team-week, offense and defense, split pass and run:

| rating | definition |
|---|---|
| `epa_<pass|rush>_<off|def>` | weighted mean EPA per play — the existing input, the control |
| `succ_<pass|rush>_<off|def>` | weighted mean of the published `success` flag — the candidate |

Filter, and the counts at every step (2010-2025, printed by `filters_report`, not asserted):

| step | plays |
|---|---:|
| all plays | 737,117 |
| `play_type IN ('pass','run')` | 523,877 |
| with `epa` not null | 523,875 |
| two-point attempts removed | 522,300 |
| classified **pass** (`pass_attempt=1 OR qb_dropback=1`) | 318,141 |
| classified **run** (not pass, `rush_attempt=1`) | 204,159 |

Kickoffs, punts, field goals, extra points, `no_play`, kneels and spikes are excluded by the `play_type`
filter; two-point tries are excluded explicitly because they are a different play with a different baseline.
Every remaining play lands in exactly one bucket, so a play can never be counted as both a pass and a run.

Weights are `0.5 ** (weeks_ago / 6)`, the half-life the EPA model already uses. The window is the previous
season plus the current season's plays before the target week. The target week is never in its own window.
Each mean is shrunk toward its league prior with `n_eff / (n_eff + K)`: `K = 150` for EPA (the EPA model's
LAM) and `K = 300` for success, where `n_eff` is Kish's effective sample size. The median effective sample
per team-week on these data is 547 plays, so the success shrink matters; K = 150 / 300 / 600 are all reported.

### The test

`backend/nfl_success_rate_backtest.py`. Three arms, identical construction, fitted on the same pool and
scored on the same games:

| arm | features |
|---|---|
| **M0** control | EPA differentials (pass, rush) + home, for margin; EPA sum-differentials for total |
| **M1** treatment | M0 + success-rate differentials (pass, rush) |
| **S** diagnostic | success rate only — is it a substitute for EPA, not just an addition? |

Targets: home margin, total, and P(home wins) = Normal(margin_hat, sigma), sigma the pool's residual SD
(population form). Chronological: each game is predicted by a regression fitted on every game **before**
its week, ratings from plays before its week only.

**Population:** test seasons 2023-2025, weeks 3-18, 720 games (719 after the one tie). The training pool at
2023 week 3 is 2011-2022 plus 2023 weeks 1-2; it grows chronologically and is never shuffled. Clustered
intervals resample whole weeks (48 clusters) because games in a week share ratings and conditions.

### Result: success rate does not help

Success-rate shrink K = 300 (the pre-registered value):

| arm | games | Brier | log loss | MAE margin | MAE total | reliability | resolution |
|---|---:|---:|---:|---:|---:|---:|---:|
| M0 control | 720 | 0.2243 | 0.6399 | 10.465 | 10.646 | 0.00228 | 0.02573 |
| M1 EPA + success | 720 | 0.2242 | 0.6398 | 10.456 | 10.641 | 0.00360 | 0.02733 |
| S success only | 720 | 0.2275 | 0.6470 | 10.527 | 10.652 | 0.00105 | 0.02092 |

Paired per game, clustered by week (negative = the arm is better; 719 games, 48 weeks):

| comparison | Brier winner | log loss | MAE margin | MAE total |
|---|---|---|---|---|
| M1 − M0 | -0.00010 [-0.00074, +0.00056] | -0.00017 [-0.00163, +0.00130] | -0.00803 [-0.03431, +0.01912] | -0.00617 [-0.03625, +0.02516] |
| S − M0 | +0.00320 [-0.00204, +0.00857] | +0.00715 [-0.00397, +0.01909] | +0.06915 [-0.11966, +0.26627] | +0.00464 [-0.05329, +0.06582] |

Every interval spans zero. The point estimates are a hair better for M1 and a hair worse for S, and both are
inside noise.

**Shrink sensitivity is not the explanation.** At K = 150, 300 and 600 the M1 Brier is 0.2242, 0.2242 and
0.2241; MAE margin 10.457, 10.456, 10.456. The null result is not a shrinkage artefact, so it is not something
to tune away.

**The decomposition says the same thing.** Adding success raises reliability error (0.00228 → 0.00360) as
much as it raises resolution (0.02573 → 0.02733). It re-spreads the probabilities without making them more
informative. A feature that only recalibrates is not adding information, and here it does not even reliably
recalibrate.

**Verdict: success rate does not help the game-level model beyond raw EPA.** It is redundant with EPA at
this level, not harmful. Success-only is slightly worse than EPA-only, which is consistent with success rate
carrying much of the same signal less efficiently. This is a feature test and the answer is no; nothing here
was tuned after the result.

What this does **not** say: success rate might still help a play-level model, a situational model (third
down, red zone), or a player-prop model. It says nothing at the team-game margin/total/winner level, which is
the target it was tested on.

### Population and construction caveats

- The control is the **same weighted-mean construction** as the treatment, so the test isolates the feature.
  It is not `nfl_epa_model`'s ridge: the ridge imposes a sum-to-zero constraint across teams and is a
  different estimator, so M0's Brier is not comparable to the v2 model card's number.
- Team-level ratings cannot see who was on the field: injuries, weather and game state are all unmodelled.
- One feature, one definition — no interaction terms, no per-position or per-down splits were tried, because
  trying them after a null is exactly the tuning the brief rules out.

---

## A2. The NFL per-game distribution

### The object

`nfl_game_distributions`, written by `backend/nfl_game_distribution.py`, one row per
`(game_id, model_version)`, and frozen at lock. Each row stores:

```
margin_mean, margin_sd      home margin  ~ Normal(margin_mean, margin_sd)
total_mean,  total_sd       game total   ~ Normal(total_mean,  total_sd)
method = 'gaussian_margin_and_total_independent'
params_json                 the fit's coefficients, pool size, half-life, shrink and play count
line_snapshot_id            the market line the row was locked against
locked_at, as_of
```

From those four numbers, analytically and with no sampling:

```
P(home wins)     = P(margin > 0)
P(home covers X) = P(margin > X)
P(total over Y)  = P(total > Y)
```

**What it is not, stated plainly.** It is not a joint score distribution: home and away scores are neither
stored nor drawn, and the two independent normals can imply negative scores. Its tails are thinner than a
football score distribution because scoring is discrete and right-skewed. It has no push mass: on a
whole-number line the normal gives zero probability of an exact push, so pushes are counted at grading time
and excluded. Those are defects, and they are why the coverage check below matters as much as the Brier.

**Reproducible.** The parameters are the whole object. There is no seed and no hidden state: anyone holding
the four numbers regenerates exactly the same probabilities months later. `test_nfl_game_distributions.py`
asserts this and asserts that a second write for the same `(game, model_version)` is refused, not
overwritten.

**Frozen at lock.** `--write` refuses any game whose kickoff has passed (and raises on an unknown kickoff),
and the insert is `INSERT OR IGNORE`, so an existing row is never rewritten. A row prefers the locked
`line_snapshot_id` line over the schedule's closing line; the schedule is the fallback only for locks that
predate snapshots.

### The grading, and what it says

720 walk-forward distributions for 2023-2025 weeks 3-18, produced by the same builder the lock uses, graded
from the stored parameters only. Lines: the schedule's closing spread/total (no lock snapshots exist for
these seasons). Moneylines are present for every game, so the winner market is priced with the same
multiplicative devig the player props use.

| market | n | base rate | Brier ours | Brier constant | log loss ours | constant | reliability | resolution | ours − constant |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| winner | 719 | 0.551 | **0.2243** | 0.2474 | 0.6399 | 0.6880 | 0.0023 | 0.0257 | -0.02316 [-0.03284, -0.01320] |
| spread | 704 | 0.513 | 0.2646 | 0.2498 | 0.7245 | 0.6928 | 0.0173 | 0.0022 | +0.01477 [+0.00768, +0.02213] |
| total | 715 | 0.512 | 0.2634 | 0.2499 | 0.7229 | 0.6929 | 0.0129 | 0.0006 | +0.01355 [+0.00573, +0.02111] |

Pushes: 16 on the spread, 5 on the total; excluded. One tie excluded from the winner.

Winner against the market: Brier 0.2088, log loss 0.6046, reliability 0.0014, resolution 0.0400;
**ours − market = +0.01542 [+0.01018, +0.02106]** — the market is ahead and the interval excludes zero.
Spread and total have **no market probability**: the database stores game lines, not two-sided spread/total
prices, so the market column is absent rather than invented. That is a real gap in the data, not a choice.

Distribution coverage of the stated p10-p90 band (nominal 80 / 10 / 10): margin **80.4%** inside (8.6% below,
11.0% above), total **81.4%** inside (8.3% below, 10.3% above). The *scale* of the distribution is right.

**The spread and total probabilities are worse than a constant and carry almost no information.** The
calibration tables show why:

```
spread   predicted 0.546 -> observed 0.495      predicted 0.635 -> observed 0.452
total    predicted 0.550 -> observed 0.498      predicted 0.643 -> observed 0.524
```

For the spread the relationship is inverted at the top of the range: the model's confidence points the wrong
way. The diagnostic is the correlation between how far the model's margin sits from the line and how far the
actual result sits from the line: **−0.088** for the spread, **+0.006** for the total. In words: when this
model disagrees with the closing line, the disagreement carries no information about the result, and on the
spread it is slightly anti-informative. The distribution is a faithful rendering of the model's margin and
total estimates; those estimates simply are not good enough to price a line that the market has already
priced well.

**Verdict.** The stored object does what A2 asked — one frozen, reproducible object produces P(winner),
P(cover) and P(over), and the winner probability beats the constant base rate (0.2243 against 0.2474, interval
excluding zero). It must **not** be presented as a spread or total forecast: on this population its cover and
over probabilities are worse than a coin flip (0.2646 and 0.2634 against 0.2498/0.2499), and its confidence is
inverted on the spread. Grading them honestly is the deliverable; making them look tradeable would be
fabrication.

### Why the winner probability works and the line probabilities do not

They come from the same normal. The difference is the anchor. P(home wins) is evaluated at zero, where the
model's own mean is the only input. P(cover) is evaluated at the market line, which is a better estimate of
the same quantity than the model's mean; so the model's deviation from the line is mostly its own error, and
treating that deviation as signal produces overconfidence. The 80.4% band coverage says the spread is the
right size; it is the location relative to the line that is not informative. Fixing this is not a distribution
problem — it is the same "increment over the market is not established" finding the prop work already
recorded, now visible at the line level.

---

## What was not done

- **No tuning after the null.** Success-rate shrink was reported at three values, not searched; no extra
  features, interactions or per-situation splits were tried.
- **No deploy, no push, no writes to the shared dev DB.** `nfl_game_distributions` was exercised on a
  temporary database only; the writer, the freeze rule and the kickoff guard are tested there.
- **No joint score distribution.** The two-normal object is what the current model implies; a
  nearest-neighbour score sampler exists (`nfl_score_dist.py`) but it belongs to v1 expected points and was
  not wired to this model.
- **No market price for spreads and totals.** Recorded as absent.

## Reproducing

```bash
cd backend
export LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db
VENV=/root/legendarypicks/backend/venv/bin/python

$VENV nfl_success_rate_backtest.py                      # A1: filter counts, three arms, paired intervals
$VENV grade_nfl_game_distributions.py --backtest-seasons 2023 2024 2025   # A2
$VENV nfl_game_distribution.py --seasons 2023 --first-rating-season 2010  # dry run of the writer
$VENV -m unittest test_nfl_game_distributions -v        # freeze + reproducibility
```
