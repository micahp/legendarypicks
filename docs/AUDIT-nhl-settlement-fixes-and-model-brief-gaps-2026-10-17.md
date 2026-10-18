# NHL model: market-settlement fixes and open research gaps (2026-10-17)

## This branch is a pricing / display fix, not a trained-model upgrade

Branch: `fix/nhl-settlement-and-card-clarity`. The independent frozen B3 Elo, B5 xG Poisson, and B7 Elo+xG Poisson model parameters, locked forecasts, stored historic recommendations and official results remain unchanged.

### Fixed for newly frozen selections

1. **Whole-goal totals:** model win, lose and push masses are disjoint. An Under 6.0 wins on 0–5 goals, pushes on 6, loses on 7+. The old selector included 6 in Under-win probability and could overstate EV. EV now equals `P(win) * net_odds - P(loss)`; pushes return zero. P(edge) compares the model's probability **conditional on no push** with the two-way no-vig market probability.
2. **Regular-season shootout goals:** quoted full-game total probabilities use the frozen joint score matrix and add one goal to tied statistical scores that resolve through a shootout. The underlying model and original fixed-target reference grades are not rewritten. When the outcome cannot be priced credibly (missing full matrix for most lines, unsupported playoff handling), skip the total as a betting candidate; never pretend a statistical 6.5 probability is automatically a settled-market 6.5 probability.
3. **Settlement grading:** total bets on exactly a whole-number line report `{won:null, push:true, settlement:"push"}` rather than a loss. Frozen selection and official grade rows remain immutable. Settlement is a derived interpretation of them.
4. **Versioned policy:** new picks are `ev-max-2-settlement` and record `push_probability` through an additive schema migration; existing rows retain their saved `rule_version`, price, selection, edge and EV. Old total EV is marked legacy/unverified in the UI rather than being displayed as an actionable edge.
5. **Quote freshness:** an unknown, future, or older-than-five-minute quote is not verified as fresh for a new qualifying selection. Stale positive-EV estimates are labeled as unverified, not recommendations.
6. **Card clarity:** the goal-margin distance to the bookmaker's fixed ±1.5 puck line is a **line gap, not a betting edge**. The projected vs posted total gap is also just a distance, not EV. Unlocked previews must show current/posted lines, never `Locked line`. The Record tab grades any frozen pick/lean Win, Loss or Push irrespective of whether it qualified for a wager; a game without a frozen pick cannot retroactively claim a correct selection.

Run the targeted regression checks on the server before merge/deployment:

```bash
python -m unittest backend/test_nhl_model_locks.py
npx jest --runInBand components/Leagues/NhlModelTab.test.tsx
```

Verify the migration on a backup of the standalone NHL lock DB before applying to production. The new policy must not be retrospectively substituted for `ev-max-1`. When interpreting historical total picks, do not reuse their legacy EV as calibrated or push-aware.

## Relative to docs/BRIEF-nhl-prediction-model.md, important work not yet established

- **Goalie and lineup input:** confirmed starters, regressed GSAx/high-danger shot difficulty, lineup availability and projected player/line ice time; timestamp initial and confirmed-starter forecasts.
- **Different strengths:** separate 5-on-5, PP, PK and empty-net/scoring states, opportunities and pace rather than a single 5v5 rolling game-average xG rate.
- **Schedule/context:** rest, back-to-back, travel, home ice, roster churn, opponent-adjusted shot quantity and quality, high-danger attempts and finishing shrinkage.
- **Probability model:** compare independent Poisson with overdispersed/correlated scoring, event/period-level Monte Carlo, regulation-time winner, explicit OT/SO and empty-net settlement. Monte Carlo sampling of the same Poisson is a control, not an intrinsic improvement.
- **Benchmark ladder:** reproducible, chronological B0–B2, B4 and realistic market-implied baselines; matching no-vig prices to **the same games and settlement**; report sample sizes, uncertainty, reliability, resolution and log loss.
- **B7 naming:** deployed `B7_elo_xg_poisson` is Elo + 5v5 xG, **not** the full goalie, lineup, scheduling B7 proposed in the original brief.
- **Independent model call:** every eligible matchup should eventually have a timestamped, frozen fan-facing moneyline → +1.5 → total policy version, graded Win/Loss/Push regardless of EV. No quote must not stop *predictive* calls, but a missing quote must stop *priced wager* claims. These are separate ledgers.
- **Downstream props:** player shots/goals/assists/points/saves/blocks tied to team opportunities, projected TOI and later the joint game simulator; only after the team-scoring evaluation is adequate.
- **Licensing:** MoneyPuck historical vs 2026–27 xG definitions differ and commercial usage requires clarification; document provenance and permission before production expansion.

## Forward-only Platt research candidate (separate from these fixes)

Test **time-forward** sigmoid calibration as a *challenger* on moneyline, +1.5 cover, and total probabilities. Train only on earlier settled games; hold out later games and compare matched-game Brier, log loss, calibration, discrimination, reliability and resolution to raw models and no-vig market baselines. Stratify by early season, standings points percentage and market. Avoid pool leakage across models and never double-count multiple line alternatives from the same game as independent observations. For whole-number totals, use conditional-on-no-push probability, and separately preserve/grade push mass and full score-distribution coherence.

Prior NFL forward Platt evidence in `docs/CANDIDATE-nfl-player-props-forward-platt-v1.md` showed strict matched-sample Brier raw 0.2743 → Platt 0.2502 vs market 0.2469, with AUC falling from 0.5229 to 0.4991 and worse full predictive distribution. It improved probability scoring but did **not** establish betting-market superiority or additional distributional information. NHL should not automatically promote the calibration layer on that evidence.

All changes to fitted NHL models and tiered selection policy require a separate research go/no-go review. This patch changes market math and presentation only.
