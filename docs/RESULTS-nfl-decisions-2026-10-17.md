# The four decided changes: results, 2026-10-17

Branch `scratch/spec-b-rebase`, worktree `/root/lp-player-proj`, from tip `37682186`. Read-only on
`picks.dev.db` except one additive table (`nfl_prop_calibration`, described in section 3). Not deployed, not
merged to dev. The MAE gate was not touched, retuned or bypassed anywhere in this work.

Micah's four decisions, in the order they were implemented:

1. Fix the passing grader's population (look-ahead).
2. Adopt `K_T` 4.0 for team pass attempts.
3. Add forward Platt as its own model, not as a replacement.
4. Make each facet complete and honestly graded.

---

## 1. The passing grader no longer selects its population on the outcome

### What changed

`grade_nfl_prop_probabilities.py` kept the quarterback who led his team in attempts **in the finished game**
(`max(team_rows, key=lambda x: (x.att, -x.pid))`), which reads the target week's box score. It now uses
`pregame_leader` — the quarterback with the most attempts for that team in the games **before** the target
week. The function lives in the grader; `audit_nfl_passing_projections.py` re-exports it so there is one
definition, not two. The old filter is retained as `postgame_leader` behind `--population postgame` **only**
to reproduce the pre-fix numbers; the default and every number below unless labelled otherwise is pregame.

Nothing else about the item definition moved: same books, same devig, same whole-line exclusion, same
"must have played" rule, same 4,000-draw simulation with the same seeds.

### How much the population moves

| | post-game (old) | pregame (new) |
|---|---:|---:|
| items, all markets | 33,519 | 32,758 |
| player-games, all markets | 920 | 909 |
| items, passing markets only | 8,926 | 8,165 |
| player-games, passing only | 122 | 111 |
| receiving items | 24,593 | 24,593 (unchanged) |

Per market: **832 items left the population and 71 entered it** (32,687 items are shared); 12 player-games
left and 1 entered. Sixteen team-weeks have a different pregame leader from the post-game one. On the shared
items every forecast is byte-identical — the fix changes membership, not any number the model produced, which
is why a paired comparison across the two populations is exactly zero everywhere and is not reported as a
finding.

The audit's count: 113 pregame quarterback-games against 124 post-game in 2026 weeks 2-6.

### Before and after, every passing market

Same model, same constants (`K_T` 8.0 at this point — the `K_T` change is section 2), only the population
changes. Brier and log loss are item-level; MAE is the engine's point projection against the actual.

| market | items old → new | player-games | Brier ours | market Brier | log loss ours | market log loss | MAE ours |
|---|---|---|---:|---:|---:|---:|---:|
| passing_yards | 6,693 → 6,129 | 122 → 111 | 0.2815 → **0.2758** | 0.2435 → 0.2436 | 0.7654 → **0.7490** | 0.6800 → 0.6801 | 62.888 → 63.154 |
| pass_attempts | 797 → 735 | 122 → 111 | 0.2719 → **0.2595** | 0.2506 → 0.2503 | 0.7594 → **0.7133** | 0.6943 → 0.6938 | 7.411 → 7.281 |
| pass_completions | 701 → 635 | 122 → 111 | 0.2952 → **0.2724** | 0.2488 → 0.2485 | 0.8145 → **0.7406** | 0.6907 → 0.6903 | 5.237 → 5.048 |
| passing_touchdowns | 735 → 666 | 122 → 111 | 0.2410 → 0.2420 | 0.2377 → 0.2392 | 0.6746 → 0.6765 | 0.6684 → 0.6714 | 0.895 → 0.893 |
| **passing, pooled** | 8,926 → 8,165 | 122 → 111 | **0.2784 → 0.2713** | 0.2441 → 0.2442 | **0.7613 → 0.7392** | 0.6812 → 0.6814 | — |

Gap to the market on the corrected population, paired and clustered by player-game (ours minus market):

| market | Brier gap | clustered 95% |
|---|---:|---:|
| passing_yards | +0.03219 | +/- 0.01871 |
| pass_attempts | +0.00918 | +/- 0.02001 |
| pass_completions | +0.02383 | +/- 0.01934 |
| passing_touchdowns | +0.00278 | +/- 0.01514 |

### What this changes in the earlier conclusions

- **The passing numbers were worse than they look, not better.** The post-game filter was selecting a
  *harder* population: quarterbacks who threw a lot in the finished game include relief passers in
  blowouts. Correcting it improves pooled passing Brier by 0.0071 and log loss by 0.0221. The look-ahead was
  not flattering the model; it was penalising it.
- **No previously stated conclusion reverses.** The passing failure being a volume problem, the market being
  ahead on passing yards, and the increment over the market being unestablished all survive. What changes is
  the size of the claims: on the corrected population, pass attempts (+0.0092 +/- 0.0200), completions
  (+0.0238 +/- 0.0193) and touchdowns (+0.0028 +/- 0.0151) are all consistent with **no difference from the
  market**. Only passing yards (+0.0322 +/- 0.0187) still has the market ahead with an interval excluding
  zero. Saying "the market beats us on the passing markets" as a blanket statement was too strong before and
  is too strong now.
- MAE moves in different directions by market — passing yards 62.888 → 63.154 (worse), attempts 7.411 →
  7.281, completions 5.237 → 5.048, TDs 0.895 → 0.893 — so the population change is not a free improvement
  on point accuracy either. It is a correctness fix, and it is reported as one.
- **Population limitation, stated so it is not misread:** the pregame leader is defined by attempts to date,
  so a mid-season injury to the starter is not known to the definition. A spot starter's props are therefore
  excluded even though the market prices them. That is the price of defining the population without the
  outcome; it is not a defect in the fix.

### Docs that now contain a stale claim

| doc | what is stale |
|---|---|
| `docs/RESULTS-nfl-prop-baseline-2026-10-16.md` | every passing per-market row (lines 33, 52, 55, 79, 82) and the population line at 104 (33,519 items / 920 player-games / Brier 0.2747) — all post-game population |
| `docs/RESULTS-nfl-marcel-and-calibration-2026-10-16.md` | section 1 and 4 "raw v2 0.2747", the ladder (31,843 items on 838 player-games), and the per-market AUC table's 122 player-games — all post-game population. Section 5's audit numbers are pregame and stand |
| `docs/model-cards/nfl.md` (on `dev`) | "Spec B player props, 2026 weeks 2 to 5: 0.2747 / market 0.2460" |
| `.hermes` skill `legendarypicks-nfl-models` | the 0.2747 / 0.2460 ladder and "passing markets" lines |

A "superseded" note is added at the head of the two branch docs rather than editing their history.

---

## 2. `K_T` 4.0 for team pass attempts: adopted

`nfl_player_projection_v2.QB_DEFAULTS["K_T_ATT"] = 4.0`, used only by `project_qb` for the team's pass
attempts. Receiver volume stays on `K_T` 8.0. Completions, yards and TDs follow attempts automatically
because they are rates applied to it. The **level correction stays dropped** and is not referenced anywhere.

Measured on the corrected population, 2026 weeks 2-5, identical items on both arms (32,758), paired and
clustered by player-game (4.0 minus 8.0):

| market | Brier 8.0 → 4.0 | paired Brier | clustered 95% | MAE 8.0 → 4.0 | paired MAE |
|---|---|---|---:|---|---:|
| passing_yards | 0.2758 → 0.2730 | -0.00285 | +/- 0.00358 | 63.154 → 62.468 | -0.686 +/- 0.721 |
| pass_attempts | 0.2595 → 0.2568 | -0.00267 | +/- 0.00479 | 7.281 → 7.216 | -0.066 +/- 0.116 |
| pass_completions | 0.2724 → 0.2713 | -0.00107 | +/- 0.00409 | 5.048 → 5.014 | -0.034 +/- 0.062 |
| passing_touchdowns | 0.2420 → 0.2393 | -0.00271 | **+/- 0.00228** | 0.893 → 0.890 | -0.003 +/- 0.004 |
| all markets | 0.2728 → 0.2722 | -0.00067 | +/- 0.00080 | 27.175 → 27.045 | -0.131 +/- 0.140 |

Read plainly: **directionally consistent in every market and established only on passing touchdowns**, where
the interval just excludes zero. Passing yards, attempts and completions all span zero. This is adopted as
Micah decided, and it must be described as a directionally consistent change rather than a demonstrated
gain. The receiving markets are byte-identical to two decimals, which is the control that the change is
scoped to quarterbacks.

---

## 3. Forward Platt is its own model: `v2-platt`

### How it is exposed

- **Two labelled models.** `GET /api/nfl/projections/player/{id}?market=&line=&model=v2|v2-platt`. `v2`
  (default) is the raw engine. `v2-platt` is the raw number passed through that week's logistic map. The
  response carries `"model": "v2-platt"`, `prob_over.p_over_raw`, and
  `prob_over.calibration = {a, b, n_items, fitted_at_utc, status}`. An unknown model is a 400, never a silent
  fallback.
- **The record distinguishes them.** The grader writes a `model` and a `calib` column per item, so a graded
  row says which model produced it. Nothing is retro-fitted onto items another model served.
- **Storage.** New additive table `nfl_prop_calibration(season, week, model_version, a, b, n_items,
  n_player_games, fitted_at_utc)`, primary key `(season, week, model_version)`. Written only by the fitter
  below; read with `CREATE TABLE` absent tolerated (returns "no map").
- **Weekly refit.** `nfl_prop_calibration.py --season 2026 --week <target> --write`, or
  `nfl_player_projections_job.py --fit-calibration`, which fits on every graded item in the weeks **before**
  the week being served and stores the row for the target week. Never the week being served.
- **Week-1 raw fallback.** A week with no earlier graded week has no map; the endpoint returns the raw
  probability and `calibration.status = "raw_no_map"`. On 2026 that is week 2, **8,200 of 32,758 items
  (25.0%)**, matching the handoff's "24% of items".

### The maps actually fitted (2026, pregame population, `K_T_ATT` 4.0)

| served week | a | b | fitted on |
|---|---:|---:|---|
| 2 | — | — | no earlier week; served raw |
| 3 | 0.23965 | +0.05781 | 8,200 items, 226 player-games |
| 4 | 0.20384 | +0.10125 | 16,062 items, 453 player-games |
| 5 | 0.17984 | +0.12579 | 25,057 items, 687 player-games |
| 6 (next to serve) | 0.23627 | +0.13528 | 32,758 items, 909 player-games |

The slope is well below 1 everywhere, so the map's work is almost entirely **shrinking toward 0.5**, which
is the signature of a model that is too confident rather than misinformed.

### Graded on exactly the items it served

`v2-platt`, map applied only — 24,558 items on 683 player-games (weeks 3-5):

| forecast | Brier | log loss | AUC | reliability | resolution |
|---|---:|---:|---:|---:|---:|
| raw v2 | 0.2743 | 0.7518 | 0.5314 | 0.0262 | 0.0021 |
| **v2-platt** | **0.2486** | **0.6899** | 0.5227 | 0.0009 | 0.0021 |
| market | 0.2463 | 0.6857 | 0.5595 | 0.0003 | 0.0034 |
| constant 0.5 | 0.2500 | 0.6931 | — | — | — |

Including the raw week-2 fallback, the model as served scores 0.2529 against the market's 0.2461 on 32,758
items.

Paired, clustered by player-game: **platt minus raw -0.02571 +/- 0.01020** (established);
**platt minus market +0.00227 +/- 0.00222** (market still ahead, and now by 0.002 rather than 0.026).

Per market, platt minus market: receiving yards -0.00069 +/- 0.00234 (level, spans zero), receptions +0.00602
+/- 0.00373 (market ahead), passing yards +0.00866 +/- 0.00614 (market ahead), attempts +0.00113 +/- 0.00578,
completions +0.00315 +/- 0.00729, passing TDs -0.00031 +/- 0.01818 (all three span zero).

**The gain is the removal of false confidence, not added information.** Reliability falls from 0.0262 to
0.0009 while resolution does not move at all (0.0021, against the market's 0.0034). Pooled AUC **falls** from
0.5314 to 0.5227, because the map is monotone within a week and only the between-week slopes differ; nothing
was reordered within a week. A lower Brier here does **not** imply an edge: the market is still ahead, the
increment over it remains unestablished, and discrimination is still poor (0.52 against the market's 0.56).

---

## 4. The facet ladder

Populations are stated per row because they differ. Rows 1-2 are **2025, no props exist**, MAE only. Rows
3-4 are **2026 weeks 2-5 props**, the corrected pregame population, raw v2 with `K_T_ATT` 4.0. Nothing in
this table puts a 2025 MAE and a 2026 Brier in the same column without saying which is which.

### Point accuracy — MAE against Marcel-lite, paired, clustered by player-game

**2025, weeks 3-18, RB/WR/TE with 3+ earlier games (3,945 player-games):**

| facet | v2 | Marcel-lite | v2 - marcel | clustered 95% | gate |
|---|---:|---:|---:|---:|---|
| targets | 1.562 | 1.589 | -0.027 | [-0.053, +0.001] | tie |
| receptions | 1.207 | 1.237 | -0.029 | [-0.050, -0.009] | **gain** |
| receiving yards | 15.849 | 16.431 | -0.582 | [-0.872, -0.298] | **gain** |
| receiving TDs | 0.234 | 0.239 | -0.006 | [-0.011, -0.001] | **gain** |
| carries | 1.153 | 1.108 | +0.044 | [+0.010, +0.077] | **fail — worse, established** |
| rushing yards | 6.512 | 6.536 | -0.024 | [-0.213, +0.152] | tie |
| rushing TDs | 0.112 | 0.112 | +0.000 | [-0.003, +0.003] | tie |

**2025, QB passing (403 quarterback-games):**

| facet | v2 | Marcel-lite | v2 - marcel | clustered 95% | gate |
|---|---:|---:|---:|---:|---|
| attempts | 6.802 | 7.512 | -0.710 | [-1.025, -0.409] | **gain** |
| completions | 4.735 | 5.279 | -0.544 | [-0.766, -0.321] | **gain** |
| passing yards | 59.051 | 63.458 | -4.408 | [-7.106, -1.751] | **gain** |
| passing TDs | 0.971 | 1.010 | -0.039 | [-0.076, -0.002] | **gain** |

Carries moved from 1.182 (the figure in `docs/model-cards/nfl.md`) to 1.153 on today's engine, and the gate
still fails: +0.044 [+0.010, +0.077] worse than Marcel-lite. The rushing-carries candidate on
`feat/nfl-rushing-carries-dist-v1` is a **distribution** candidate and does not change the carry mean, so it
cannot pass this gate; it was evaluated against its own distribution gate and recorded NOT_ADOPTED. Wiring it
in would not repair this row.

### Probability and distribution — 2026 props, pregame population, `K_T_ATT` 4.0

Brier and log loss are item-level; "cov80" is the share of actuals inside the simulated p10-p90 band, whose
target is 80%. Paired differences are clustered by player-game.

| market | items | pg | Brier | market | const | log loss | market LL | MAE | marcel MAE (paired) | cov80 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| receiving_yards | 19,118 | 795 | 0.2721 | 0.2479 | 0.2498 | 0.7458 | 0.6890 | 25.333 | 28.343 (-2.551 +/- 2.163, n=8,701/344) | 0.827 |
| receptions | 5,475 | 783 | 0.2778 | 0.2424 | 0.2499 | 0.7721 | 0.6776 | 1.766 | 1.861 (-0.053 +/- 0.126, n=2,535/340) | 0.861 |
| passing_yards | 6,129 | 111 | 0.2730 | 0.2436 | 0.2459 | 0.7435 | 0.6801 | 62.468 | 69.186 (-0.779 +/- 9.247, n=2,883/50) | 0.850 |
| pass_attempts | 735 | 111 | 0.2568 | 0.2503 | 0.2500 | 0.7078 | 0.6938 | 7.216 | 8.162 (-0.473 +/- 1.485, n=356/50) | 0.841 |
| pass_completions | 635 | 111 | 0.2713 | 0.2485 | 0.2483 | 0.7389 | 0.6903 | 5.014 | 5.402 (-0.212 +/- 0.818, n=304/50) | 0.882 |
| passing_touchdowns | 666 | 111 | 0.2393 | 0.2392 | 0.2495 | 0.6709 | 0.6714 | 0.890 | 0.921 (-0.170 +/- 0.136, n=313/50) | 0.974 |

Brier against the market, paired and clustered: receiving yards +0.02414 +/- 0.01275; receptions +0.03542
+/- 0.01210; passing yards +0.02935 +/- 0.01812; attempts +0.00651 +/- 0.01888; completions +0.02276
+/- 0.01912; passing TDs +0.00006 +/- 0.01500. Established market edges: receiving yards, receptions and
passing yards. Tied: attempts, completions, TDs.

Distribution coverage is honest and slightly too wide: receiving yards 82.7% inside the p10-p90 band,
receptions 86.1%, passing yards 85.0%, attempts 84.1%, completions 88.2%, passing TDs 97.4%, against a
nominal 80%. The 2025 check says the same from the other side: receiving yards 87.0% inside, receptions
91.9%, QB attempts 87.1%, completions 87.1%, passing yards 87.6%, passing TDs 94.3%. The simulated intervals
over-cover; they are not too narrow, and they are widest where the distribution is most discrete (TDs).

### Cells that are explicitly not measured

| cell | reason |
|---|---|
| targets — probability, coverage | no `targets` prop exists on the dev DB (0 items). Point accuracy is measured: 1.562 vs 1.589, tie |
| carries — probability, coverage | carries is not a sportsbook market in the prop set; no items to grade |
| rushing yards — probability, coverage | same: the market is not in `collect()`, and the 2025 backtest prints no p10-p90 band for rushing |
| rushing TDs — probability, coverage | same |
| all facets — reliability/resolution | computed only for the prop markets where probabilities exist (section 3) |

---

## 5. What was not done, and why

- **No deploy, no merge to dev, nothing served from this branch.** The router change is on the branch and is
  exercised by unit tests against a synthetic DB, not by a running server.
- **The MAE gate was not touched.** It still says what it said; carries still fail it.
- **`K_T` was not refitted and the level correction was not reintroduced.**
- **Rushing efficiency was not modelled.** Section 5 of the carries plan (downstream rushing yards) is
  untouched; the carries experiment stopped at the count distribution.
- **The model card on `dev` was not edited** — it is outside this branch; it is listed as stale above for the
  manager to update at merge time.
- **No production DB table was altered.** The only DB change is the new `nfl_prop_calibration` table, which
  nothing else reads.

## 6. Reproducing

```bash
cd backend
export LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db

# P1: before and after (both arms are the same binary; only the population flag changes)
python3 grade_nfl_prop_probabilities.py --season 2026 --population postgame --marcel --csv /tmp/post.csv
python3 grade_nfl_prop_probabilities.py --season 2026 --population pregame  --marcel --csv /tmp/pre.csv
python3 compare_nfl_prop_grade_csvs.py --a /tmp/post.csv --b /tmp/pre.csv --label-a postgame --label-b pregame
python3 audit_nfl_passing_projections.py --season 2026

# P2: K_T_ATT 8.0 against 4.0 on identical items
python3 grade_nfl_prop_probabilities.py --season 2026 --kt-att 8 --marcel --csv /tmp/kt8.csv
python3 grade_nfl_prop_probabilities.py --season 2026 --kt-att 4 --marcel --csv /tmp/kt4.csv
python3 compare_nfl_prop_grade_csvs.py --a /tmp/kt8.csv --b /tmp/kt4.csv --label-a K_T8 --label-b K_T4

# P3: fit the forward maps, store the serving-week map, then grade the model it produces
python3 nfl_prop_calibration.py --season 2026 --week 6 --write --json /tmp/maps.json
python3 grade_nfl_prop_probabilities.py --season 2026 --calibration /tmp/maps.json --marcel --csv /tmp/platt.csv
python3 compare_nfl_prop_grade_csvs.py --a /tmp/kt4.csv --single --label-a "v2 raw"

# P4: the 2025 MAE ladder and coverage, and the per-facet 2026 table above
python3 backtest_nfl_player_projection_v2.py --run
python3 backtest_nfl_player_projection_v2.py --run-qb
python3 backtest_nfl_player_projection_v2.py --run-dist
/root/legendarypicks/backend/venv/bin/python -m unittest test_nfl_projections_api test_nfl_player_projection_v2
```
