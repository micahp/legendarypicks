# FBS learnings

Append-only. One entry per thing we learned the hard way, with the evidence that proves it.
If an entry is later overturned, do not delete it — add a new entry that says so and links back.

Format:

```
## YYYY-MM-DD — one-line headline
**Learned:** what is now known.
**Evidence:** artifact, commit, or measured number.
**Consequence:** what we stop or start doing because of it.
```

Rules:
- A learning needs evidence. "It seems like" is not an entry.
- A null result is an entry. Knowing what does not work is the point.
- Numbers carry their population and sample size.
- Write it when you learn it, not at the end.

---

## 2026-10-18 — Elo warm-up depth is not what separates us from published Basic Elo
**Learned:** Holding G2 and its hyperparameters fixed and varying only the warm-up start
(2022 → 2018 → 2014 → 2010 → 2004) moves Brier from 0.2133 to 0.2103, a paired
Δ of −0.0030 [−0.0041, −0.0018] on the same 2,398 games. It flattens at 13 seasons and closes
only 18.9% of the gap to published Basic Elo (0.1976), leaving 0.01271.
**Evidence:** `RESULT-FBS-WARMUP-ABLATION-20261018.md`, commit `4f20e1fa`, five arm ledgers,
arm A reproduces Phase 1 G2 at 0.213269 exactly.
**Consequence:** five warm-up seasons is the right depth. Do not spend more effort on archive
history as a route to the baseline — the remaining gap is the model, the features, or the
population. Any future "we need more data" argument has to beat this result first.

## 2026-10-18 — A margin-aware rating does not beat plain Elo
**Learned:** G3 (margin-adjusted strength) scored 0.2155 against G2's 0.2133. Paired difference
+0.0023 with a 95% interval of [−0.0023, +0.0065] — spans zero.
**Evidence:** `RESULT-FBS-GAME-WINNERS-20261018.md`, commit `4a59cb6e`.
**Consequence:** keep G0–G2 as references. Do not re-run G3 as if it were untested, and do not
add team-stat inputs on the assumption that margin information must help.

## 2026-10-18 — Most of the published benchmark ladder is not comparable to ours
There are three distinct classes and mixing them produces false conclusions:
1. **Our market-blind baselines** — G0–G3, results only. **G2 is our chronological Elo and is
   not Glicko-2**; Glicko-2 is an unrelated published comparator at 0.1890.
2. **Published market-blind ratings** — Colley 0.2070, Basic Elo 0.1976 (**the only fair peer
   for G2**), Glicko-2 0.1890, Massey 0.1847, Margin Elo 0.1820, Simple ACR 0.1773.
3. **Market-derived** — the spread-implied line 0.1714 *is the market*, a ceiling not a rival;
   Blitzcast's 0.1813 **takes spread and market probability as input features**, so it largely
   encodes the market and cannot be compared to a results-only model as an equal.
**Evidence:** `BASELINE-DISTINCTIONS.md`; the brief's own warning about Blitzcast.
**Consequence:** every table names the class in the row, not a footnote. Never present a model
that ingests odds as evidence of independent predictive skill.

## 2026-10-18 — The betting release has no moneyline and no timestamp, in any year
**Learned:** `espn_cfb_betting` publishes 2004–2026, and every file checked (2014, 2019, 2025,
2026) carries `game_spread, over_under, home_favorite, home_team_spread,
game_spread_available, odds_source` — no two-sided moneyline and no quote timestamp.
**Evidence:** direct parquet schema inspection, 2026-10-18.
**Consequence:** the market benchmark can only ever be **spread-derived**, calibrated on prior
seasons and labelled as spread-derived. It will never give a de-vigged moneyline comparison.
Do not keep re-checking older years hoping the schema differs.

## 2026-10-18 — Prior-play form beats Elo, and closes most of the gap to Basic Elo
**Learned:** Increment (b) — EPA, success rate, explosiveness and tempo recomputed from pre-snap
fields, fitted only on seasons strictly earlier than the target — took walk-forward Brier from
G2's **0.2133 to 0.2026** on 2,397 games, a paired **−0.01068 [−0.01444, −0.00650]** on 65
UTC-week blocks. Frozen 2025 holdout: 0.2208 → **0.2080**, **−0.01279 [−0.01768, −0.00763]**
on 807 games. 2026 development: 0.2051 → **0.1954**, −0.00971 [−0.01557, −0.00188]. Every
individual season improves (2022 −0.0132, 2023 −0.0148, 2024 −0.0087, 2025 −0.0086,
2026 −0.0097). Against the published Basic Elo at 0.1976 this closes **68% of the gap**, leaving
0.0050.
**Evidence:** `RESULT-FBS-PHASE3-B-20261018.md`, commit `886ffdf4`; pre-registration in
`d7a197c1`; ten of ten gates pass.
**Consequence:** B2 is the standing model and every later increment is judged against **B2**, not
G2. Two design facts carry the result: the recalibration-only control B1 moves nothing
(0.2134 vs 0.2133), so the gain is information rather than rescaling; and reliability falls
0.0097 → 0.0003 while resolution rises 0.0373 → 0.0394, so it is separating winners better
rather than merely being better calibrated. Success rate carries the signal (+0.4239
standardised); EPA is nearly inert (−0.0243) once success is present.
**Corrections made before adoption:** the first run used day blocks instead of the
pre-registered week blocks, and the first holdout scored B2 against a walk-forward G2 that
carries 2025 information — an honest frozen-G2 baseline made the holdout result *stronger*
(−0.00842 → −0.01279). Both corrections are disclosed in §7 of the result.

## 2026-10-18 — Id type mismatches produce silent empty joins, and they bite twice
**Learned:** `cfb_schedules.game_id` is int64 while `ncaa_mfb_pbp.espn_game_id` is a string, so a
raw set intersection is empty and a coverage table reads zero without erroring. The same class of
bug hit the FBS feature build at the home/away join.
**Evidence:** caught mid-flight in `audit_fbs_game_coverage.py` and `reconcile_fbs_archive.py`;
previously bit the prop-join work.
**Consequence:** cast every id side to `str` before joining, and **assert a non-zero join count**
as a test. A zero should fail loudly, never render as a coverage number.

## 2026-10-18 — `season_type` is a string, so `!= 2` is a no-op
**Learned:** `cfb_schedules.season_type` holds `"regular"` / `"postseason"`, not an integer, so
the original `!= 2` filter admitted postseason games into a "regular season" population.
**Evidence:** fixed in the Phase 2 coverage audit, commit `aa6bd378`.
**Consequence:** inspect the dtype before filtering a categorical. Re-check any population count
produced before this fix.

## 2026-10-18 — Publisher-derived columns leak, and are not observations
**Learned:** `cfb_paper_index_games.paper_share` is fitted on who won. Weekly snapshots with
`through_week == W` include week W. `rolling_windows_2026` has one `as_of_date` of 2026-10-15,
an end-of-season snapshot that leaks in a mid-season backtest.
**Evidence:** Phase 2 leakage register, `AUDIT-FBS-ARCHIVE-20261018.md`.
**Consequence:** `paper_share` is banned from any pregame feature. To forecast week W use a
verified `W-1` snapshot. Keep publisher-scored features in a separate class from raw
observations, and check `as_of` against kickoff for every table that has one.

## 2026-10-18 — Prefix filters silently drop assets
**Learned:** A release-prefix filter excluded a 1,100 MB cfbfastR file with no error; separately,
multi-season files were labelled as 2025.
**Evidence:** both self-caught during Phase 2, recorded in `AUDIT-FBS-ARCHIVE-20261018.md`.
**Consequence:** reconcile downloaded bytes against the release asset list and fail on a
shortfall. Never infer a file's season from its name.

## 2026-10-18 — Day-block bootstrap makes a gate anti-conservative
**Learned:** The Phase 3 pre-registration specified UTC **calendar-week** blocks. The first
implementation grouped by `utc_date`, which understates dependence between games and inflates
significance for the one-sided gates.
**Evidence:** caught before adoption; the week-block re-run is what was adopted at `886ffdf4`.
**Consequence:** block on the pre-registered unit. If the harness and the ladder disagree, the
ladder wins and the run is redone — an interim number is not a result.

## 2026-10-18 — Two agents on one job looks like progress and is not
**Learned:** codex began Phase 2 archive work while hermes was already downloading the same
archive, after a manager dispatched Phase 2 to both. Nothing told the first agent to stop.
**Evidence:** `fbs_archive_phase2.py` and `research/fbs/archive/` appeared in
`/root/lp-fbs-audit` while hermes held `/root/lp-fbs-archive`.
**Consequence:** one owner per workstream, stated explicitly, and a reassignment includes an
explicit stop for the agent being moved. A reset does not fix this class of drift.

## 2026-10-18 — Finished work sits unpushed and therefore invisible
**Learned:** `feat/fbs-archive` was four commits ahead of origin and the tennis branch did not
exist on origin at all, while both were described as done.
**Evidence:** `git ls-remote` vs local tips, 2026-10-18.
**Consequence:** "done" means committed **and** pushed to a named branch. Report the branch, the
SHA and the push state every time.

## 2026-10-18 — Increment (b)'s gain is information, not recalibration, and it is stable per season
**Learned:** Adding the four prior-play differences to the G2 logit moved Brier 0.2133 → 0.2026 on
2,397 walk-forward games 2023–25 (paired −0.01068 [−0.01444, −0.00650], 65 UTC-week blocks). The
recalibration-only control B1 moved +0.00011 [−0.00012, +0.00037], so the gain is new information.
The 2025 frozen holdout against the frozen G2 (0.2208) gave −0.01279 [−0.01768, −0.00763]; 2026
development gave −0.00971 [−0.01557, −0.00188]. Every season 2022–2026 is negative on its own, and
half-life 3 and 10 give −0.01084 and −0.00914 pooled.
**Evidence:** `RESULT-FBS-PHASE3-B-20261018.md`, commit `886ffdf4`; ladders `d7a197c1`, `c3a4a31b`.
**Consequence:** B2 is the standing model; family (c) must beat B2, not G2. Always score a
recalibration-only control next to a feature increment — without B1 an ADOPTED verdict cannot
distinguish information from rescaling.

## 2026-10-18 — A column named `*_score_play` was a 0/1 flag, and it silently flattened EP
**Learned:** `cfbfastR_cfb_pbp.offense_score_play` holds only {0, 1} — a scoring flag, not points. Using
it as points gave 9.0 points per game (vs 52.0 actual) and an EP surface spanning ±2, so every EPA was
between −2 and +2 and `explosive = EPA >= 2` fired for 0 of 122,527 plays. `pts_scored` carries the
signed points ({−7, −2, 0, 3, 7}) and sums to 52.0 per game, matching the schedule.
**Evidence:** value counts on `play_by_play_2025.parquet`; EP curve and EPA distribution before/after.
**Consequence:** validate a target's units against an independent total (here, points per game) before
fitting anything. A feature that is identically zero is a unit bug, not a modelling result.

## 2026-10-18 — I changed estimators when the bug was upstream
**Learned:** With a flat EPA distribution I concluded the 215-cell EP surface was too noisy and replaced
cell means with a ridge regression. The surface was not the problem — the target was in the wrong units.
After the points fix, cell means gave EPA SD 4.04 and the ridge gave 3.78; the estimator change was
cosmetic next to the 20× change from fixing the target.
**Evidence:** same commit as the entry above; before/after EPA SD and per-game point totals.
**Consequence:** when a distribution is compressed to implausibility, check units and ranges first, then
estimator smoothness. Record which change actually moved the number.

## 2026-10-18 — A frozen holdout scored against a non-frozen baseline is not a holdout
**Learned:** The 2025 holdout was first scored with the walk-forward G2 (Brier 0.2082) as the baseline.
That G2 carries 2025 results the increment never sees, and it understated the gain at −0.00842. Scored
against the harness's frozen G2 (0.2208), the honest difference is −0.01279.
**Evidence:** `RESULT-FBS-PHASE3-B-20261018.md` §7; `fbs_game_winner_holdout_2025_20261018.csv`.
**Consequence:** in a frozen comparison every model in the row must use frozen inputs, baseline
included. If the baseline cannot be frozen, the period is a walk-forward, not a holdout.

## 2026-10-18 — Licence tracking came back after being deleted, and the manager asked for it
**Learned:** Micah removed licence tracking from the manifest and docs, then the Phase 3 brief required
a licence section; it was re-added and had to be removed again. The instruction that matters is the
owner's, not a brief's checklist.
**Evidence:** removal commit `d9df3bc3` (section 11 deleted, endpoint section renumbered).
**Consequence:** no licence field, column, section or note anywhere. If a brief asks for one, say so and
stop rather than re-adding it.

## 2026-10-18 — Drive splits beat the prior-play model, but by less and not every season
**Learned:** Increment (c) — seven drive/box-score differences from `espn_cfb_pbp`, as-of ratings —
scored 0.1965 against B2's 0.2027 and G2's 0.2133 on 2,397 walk-forward games (C2 − B2 −0.00609
[−0.00925, −0.00258], 65 week blocks). Frozen 2025: C2 0.2004 vs B2 0.2080, C2 − B2 −0.00755
[−0.01234, −0.00262]. But the per-season edge over B2 is not universal: 2022 +0.0003, 2024 −0.0038
[−0.0091, +0.0024], 2026 −0.0018 [−0.0056, +0.0025].
**Evidence:** `RESULT-FBS-PHASE3-B-20261018.md` §12, `research/fbs/phase3-c/metrics.csv` and
`paired.csv`, commit `b2b6076d`.
**Consequence:** C2 is the standing single family, and its gain is smaller than (b)'s
(−0.0061 vs −0.0107 against G2). Any further family now has to clear a higher bar, and the combined
(b)+(c) block is the obvious next pre-registration rather than another single family.

## 2026-10-18 — Float team ids produce a silent zero-match, a third variant of the id bug
**Learned:** ESPN `pos_team_id` arrives as int64 in some seasons and float64 in others, so `astype(str)`
gave "1234.0" against the side map's "1234" and the rating merge matched 853 of 2,670 games with no
error — the feature table looked complete and was 3 seasons wide.
**Evidence:** caught while building (c); the 3-season probe returned 2,575 games instead of 2,670.
**Consequence:** cast ids through `Int64` before stringifying, and assert the merged game count equals
the input game count. This joins the int-vs-str and empty-join entries above: every id join needs a
count assertion, not just a dtype cast.

## 2026-10-18 — Rest, travel and weather carry no winner signal in FBS
**Learned:** D2 = G2 + rest difference, away travel distance and longitude shift scored 0.2138 against
G2's 0.2133 on 2,397 walk-forward games: D2 − G2 +0.00055 [−0.00018, +0.00135], D2 − D1 +0.00044
[−0.00021, +0.00116]. Adding kickoff temperature and wind changed nothing (0.2138, D2w − C2 +0.01733).
No season put D2 ahead of G2 by a resolvable margin.
**Evidence:** `RESULT-FBS-PHASE3-B-20261018.md` §13 (audit) and §14 (result), `research/fbs/phase3-d/`,
commit `5f6bb9d8`.
**Consequence:** family (d) is closed and will not be revisited with other definitions. Pregame context
in a seven-day sport is already inside Elo; stop proposing rest/travel/weather features.

## 2026-10-18 — The archive had location and weather after the brief said it would not
**Learned:** The dispatch expected travel and weather to be absent. `cfb_team_info` carries city,
state and coordinates for 96.8% of teams (2022+), enough for great-circle travel, and
`cfb_matchup_line` carries kickoff temperature and wind for 2015–2026 at ~98% fill inside the
evaluation window. Weather appears in no stats release; the derived matchup table is the only source.
**Evidence:** `RESULT-FBS-PHASE3-B-20261018.md` §13.1–13.3.
**Consequence:** audit before accepting a brief's claim of absence. Weather stayed secondary because the
matchup table has undocumented provenance, and the null held with and without it — so the provenance
question never had to decide the verdict.

## 2026-10-18 — A family can beat G2 and still be discarded, and that is the useful result
**Learned:** Coaching tenure plus returning production (E2) beat G2 by −0.00425 [−0.00691, −0.00157] and
beat its own recalibration control by −0.00436 on 2,397 walk-forward games, yet trailed C2 by +0.01252
and so failed the pre-registered gate. It is ahead of G2 in four of five seasons (2023 −0.0082
[−0.01309, −0.00305]).
**Evidence:** `RESULT-FBS-PHASE3-B-20261018.md` §15–16, `research/fbs/phase3-e/`, commit `cc7eebdb`.
**Consequence:** the C2 bar is doing real work — a family with genuine signal about a third the size of
the drive splits does not ship. Keep reporting the G2 comparison even when the C2 gate fails, otherwise
a real effect gets recorded as a null.

## 2026-10-18 — The 247Sports talent composite moves the model, but it is not allowed to decide anything
**Learned:** Adding talent and net transfer talent to E2 took pooled Brier from 0.2090 to 0.2023
(E2+ − C2 +0.00583 [−0.00043, +0.01205], interval touching zero) and 2026 from 0.1994 to 0.1835.
**Evidence:** `research/fbs/phase3-e/metrics.csv`, secondary variant in §16.
**Consequence:** talent is the strongest non-drive input seen so far and is also the one with
undocumented 247Sports provenance, so it stays secondary. If a licensed talent source ever exists
(CFBD /talent when the quota resets), that is the first thing to re-test properly.

## 2026-10-18 — Coverage measured on the wrong population reads as a data failure
**Learned:** Coach-tenure coverage looked like 71.9% when measured over all ESPN-PBP games, because that
set includes FCS opponents. On the actual FBS evaluation population it is 91.5% (both head coaches), with
returning production 100%, talent 98.6% and transfer talent 100%.
**Evidence:** `research/fbs/phase3-e/run.log` coverage block vs the all-games probe.
**Consequence:** always report coverage on the evaluated population, not on the raw joined table. A rate
over the wrong denominator looks like missing data and invites a pointless re-audit.

## 2026-10-18 — Form is real but thinner than coaching, and both lose to drive splits
**Learned:** Recent form (last three team-games minus the team's own full-history rating, on offence and
defence EPA and success) beat G2 by −0.00260 [−0.00444, −0.00084] pooled and −0.00482 on the 2025 frozen
holdout, but trailed C2 by +0.01417. Half-life 3 and 10 changed nothing material (−0.00321 and −0.00254
vs G2).
**Evidence:** `RESULT-FBS-PHASE3-B-20261018.md` §17–18, `research/fbs/phase3-f/`, commit `3afb6a99`.
**Consequence:** family (f) is closed. The ordering is now clear: drive splits (C2, −0.0168 vs G2) >
coaching/returning production (E2, −0.0043) > form (F2, −0.0026). Adding another marginal pregame block is
not where the remaining gap is.

## 2026-10-18 — Form's sign flips by season, so report per-season signs even when pooled is significant
**Learned:** F2 was worse than G2 in 2022 (+0.0014) and 2023 (+0.0008) and better in 2024 (−0.0055
[−0.00883, −0.00183]), 2025 (−0.0031) and 2026 (−0.0031). A pooled interval below zero hides that two of
five seasons are the wrong sign.
**Evidence:** §18 stability table, `research/fbs/phase3-f/forecasts_walk_forward.csv`.
**Consequence:** any family carried forward needs a per-season sign test, not just a pooled interval.
Record the pattern; do not build on two-vs-three split without a mechanism.

## 2026-10-18 — Three families failing the C2 bar is evidence about where the signal is
**Learned:** (d) rest/travel/weather added nothing, (e) coaching/returning added −0.0043 vs G2, (f) form
added −0.0026. All three fail C2, and the drive/box-score splits from (c) carry roughly four to six times
the information of the next best family.
**Evidence:** §14, §16, §18 gate tables.
**Consequence:** family (g) should test a different functional form on C2's features rather than adding a
fourth pregame block. If (g) also fails, the ladder is exhausted and C2 is the game-winner model.

## 2026-10-18 — The first thing that beat C2 was an estimator change, not another covariate
**Learned:** Two-level random intercepts (team-season effects nested in conference means) on C2's own
linear predictor beat C2 by −0.00190 [−0.00255, −0.00125] pooled and −0.00283 [−0.00463, −0.00100] in 2026,
with a negative sign in all five seasons. The hierarchy alone beat G2 by −0.00473.
**Evidence:** `RESULT-FBS-PHASE3-B-20261018.md` §19–20, `research/fbs/phase3-g/`, commit `88573876`.
**Consequence:** before adding a fourth pregame block to a saturated model, ask whether the estimator is
wasting the features already present. Four families of new covariates produced nothing; one change of
functional form did.

## 2026-10-18 — A quarter of "drive performance" was persistent team identity
**Learned:** With team-season random effects in the model, the seven drive splits contribute −0.01393
instead of −0.01677 — pooling absorbed roughly 17% of their signal, and the hierarchy supplies about a
quarter of C2's total edge over G2 on its own.
**Evidence:** §20 paired table, G1 − G2 −0.00473 vs C2 − G2 −0.01677.
**Consequence:** drive features are partly re-measuring team quality each week. If a future model wants
finer within-season dynamics, model the team effect explicitly rather than adding more weekly aggregates.

## 2026-10-18 — A frozen holdout cannot test a model whose mechanism is within-season updating
**Learned:** G2h is resolvable pooled and in 2026 but flat on the frozen holdout (−0.00036 [−0.00154,
+0.00042]). The mechanism explains it: the holdout fits once through 2024, so every 2025 team-season effect
is unseen and shrinks to its conference mean — the model degrades to C2 plus a conference prior.
**Evidence:** §20 holdout diagnostics (sd u 0.086, 398 team-seasons, fit through 2024 only).
**Consequence:** when a model's gain comes from re-estimating latent state inside the season, the frozen
holdout is the wrong confirmation test; report that explicitly instead of calling the result unresolved
noise. Prospective week-by-week games are the right confirmation.

## 2026-10-18 — Convergence thresholds must match what the optimiser can deliver
**Learned:** L-BFGS-B on a ~700-parameter penalised logistic stops on line-search precision at about 1e-5,
not the 1e-6 pre-registered; one fold stalled at 1.006e-05 and the run aborted rather than silently
accepting it.
**Evidence:** §20 declared deviation; 360/360 folds converged at max|grad| 9.7e-06 with up to three
restarts from the stopped point.
**Consequence:** pre-register a convergence rule the chosen optimiser can actually reach, and report the
achieved gradient norm rather than asserting a threshold. Aborting on failure is right; loosening silently
is not.

## 2026-10-18 — A win probability is not a score distribution, and the gap is in the total
**Learned:** On the identical 2,397/807/350 population, an over-dispersed NegBin score model (H0b) beats
the winner-only control H1 by −2.3257 [−2.6051, −2.0475] CRPS on margin and −1.0672 [−1.3276, −0.8099] on
total, and beats it on cover and over/under Brier too. Its margin PIT is clean (p = 0.968 walk-forward,
0.633 holdout) and its interval coverage is within 0.05 at 50/80/90. It still fails CP3 because the
**total** PIT rejects on the walk-forward pool (p = 0.0016).
**Evidence:** `RESULT-FBS-PHASE4-SCORES-20261018.md`, `research/fbs/phase4/`, `docs/frozen-fbs-phase4-scores.json`.
**Consequence:** G2h's ratings do support a score model, but "beats the winner model" and "is calibrated"
are different claims. The remaining work is the shape of the total, not more team strength.

## 2026-10-18 — Independent Poisson is structurally too narrow for football scores
**Learned:** H0a and H0c cover 0.245 of their 50% intervals against 0.50 nominal, because a Poisson margin
has an SD near 7 while observed margins spread over 14. Only the NegBin over-dispersion (R fitted 2.01–5.82)
brought coverage to nominal (0.524/0.800/0.904).
**Evidence:** §21 pre-registration, walk-forward coverage table.
**Consequence:** never evaluate a Poisson score model on CRPS alone — it can look competitive on the mean
and be half-covering. Coverage and PIT both, always.

## 2026-10-18 — Home and away scores are not positively correlated after team strength
**Learned:** The bivariate Poisson shared component λ3 = max(0, Cov(h,a)) hit zero in all 1,025 date-block
fits, so H0c is numerically identical to H0a on every metric.
**Evidence:** `research/fbs/phase4/block_parameters.csv`, `lambda3_all_zero: true` in the frozen JSON.
**Consequence:** the correlated-score candidate is refuted for FBS with these ratings. Do not spend another
candidate on score correlation without a mechanism that survives conditioning on team strength.

## 2026-10-19 — The total PIT failure is a conditional mean error, not a shape error
**Learned:** H0b's total distribution fails G-CAL because its predicted mean total is about twice as
variable as the data supports: OLS of observed on predicted total (`pred_total`, the PMF mean) gives
slope **0.5032 ± 0.0691** walk-forward, **0.5173 ± 0.1221** on the holdout, and **0.489–0.516** by
season. Mean bias is +0.04 points, so the error is conditional, not global: conditional mean PIT runs
**0.648** (<40 predicted) to **0.404** (>70), in every season and on the holdout. The marginal PIT is
nearly uniform because the two ends cancel. Correcting the mean alone moves every bucket to ~0.50 and
removes the low-end narrowness (RMSE/SD 1.33 → 1.00); a residual high-μ over-dispersion remains
(RMSE/SD 0.91; R × 1.10–1.20 restores PIT), and predicted mass above 110 is 0.60% vs 0.08% observed
after the mean fix (14.4 games vs 2), still 2.5× at R × 1.5.
**Evidence:** `DIAGNOSIS-FBS-TOTAL-CALIBRATION-20261019.md`, frozen `research/fbs/phase4/` artifacts.
**Consequence:** the next total candidate should start with a reliability scale on the predicted mean
fitted on prior seasons, then refit R on calibrated residuals — not another distribution family. A
marginal PIT pass at n = 807 does not certify a total distribution when the conditional bias is this
large; condition every PIT on the predicted value.

## 2026-10-19 — The mean correction fixed the PIT and the gate moved to the 50% coverage clause
**Learned:** H0b-MC (prior-season OLS calibration of the H0b total mean) fixed the conditional mean:
post-correction slope **0.9043 [0.7800, 1.0285]** contains 1.0, and pooled total PIT goes
**0.0016 → 0.0869**. It still failed G-CAL, now on the 50% central coverage: **0.5340 → 0.5561**,
**+0.0561 > 0.05** (fails by 0.0061), while the 50% *shortest* interval sits at **0.4977**. The two
50% definitions disagree, so "coverage at 50%" is under-specified for the next pre-registration. The
correction also compressed the predicted-total range, leaving the pre-declared <40 and >70 buckets
with **n=9 and n=3**: the bucket reading lost power exactly where the old bias was largest. The 60–70
bucket still rejects (KS **p=0.0053**, mean PIT **0.527**) even though its mean is inside [0.45, 0.55].
**Evidence:** `RESULT-FBS-PHASE4B-H0B-MC-20261019.md`, `research/fbs/phase4b/` (summary, bucket_pit,
calibration, per_game_shift), `docs/frozen-fbs-phase4b-h0bmc.json`.
**Consequence:** name which 50% interval the gate means (central vs shortest) before the next
coverage-gated candidate. A mean calibration that fixes the PIT can trade the failure into the
coverage leg; report both interval definitions side by side. Bucket readings defined on the corrected
prediction lose power when the correction compresses the range — define buckets on the
*pre-correction* prediction or keep fixed-count bins.
