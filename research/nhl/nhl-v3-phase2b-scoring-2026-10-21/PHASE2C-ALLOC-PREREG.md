# Phase 2C allocation-dispersion ablation: pre-registration

**Status: preregistration only.** This pins the next isolated research ablation; no generator edit, fit, simulator run, candidate selection, adoption gate, promotion-rule change, or Phase 2A artifact edit is authorized here. Phase 2A remains frozen.

## 1. Parameterization

At each ordinary shot-attempt state, let the existing Phase 2A hazards be \(\lambda^0_H\) and \(\lambda^0_A\), with \(\Lambda=\lambda^0_H+\lambda^0_A\) and \(p_0=\lambda^0_H/\Lambda\). Those hazards are the current `shot_rate` outputs for each side and state ([`stochastic_model.py:191–238`](../nhl-v3-phase2a-stochastic-2026-10-21/stochastic_model.py#L191), [`:416–426`](../nhl-v3-phase2a-stochastic-2026-10-21/stochastic_model.py#L416)).

Add one nonnegative parameter `allocation_logit_sd = σ` to `FittedParameters`. For simulation game \(g\), draw one \(Z_g=σU_g\), \(U_g\sim N(0,1)\), once in `_GameBuilder.__init__` from its existing seeded RNG. For each state in that game, define the unique offset \(b(p_0,σ)\) satisfying

\[
\mathbb E_U[\operatorname{logit}^{-1}(\operatorname{logit}(p_0)+b(p_0,σ)+σU)]=p_0.
\]

Use deterministic 32-point Gauss–Hermite quadrature for this expectation and solve for \(b\) to absolute probability error below \(10^{-12}\). Then set

\[
p_H=\operatorname{logit}^{-1}(\operatorname{logit}(p_0)+b(p_0,σ)+Z_g),\qquad
\lambda_H=\Lambda p_H,\qquad \lambda_A=\Lambda(1-p_H).
\]

Thus the hazards always sum to the original \(\Lambda\), and the correction preserves each state's mean home allocation. Apply the same adjusted pair wherever the simulator reads side hazards: regulation wait, overtime wait, and the shot team's rate-proportional mark ([`stochastic_model.py:477–488`](../nhl-v3-phase2a-stochastic-2026-10-21/stochastic_model.py#L477), [`:551–566`](../nhl-v3-phase2a-stochastic-2026-10-21/stochastic_model.py#L551), [`:416–426`](../nhl-v3-phase2a-stochastic-2026-10-21/stochastic_model.py#L416)). The one \(Z_g\) is held fixed through regulation and OT; it is never redrawn per period or attempt.

At \(σ=0\), early-return the original \((\lambda^0_H,\lambda^0_A)\) pair before any logit or renormalization, set no allocation state, and skip the RNG call entirely. This preserves the exact floating-point rates and subsequent RNG stream of frozen Phase 2A. The new dataclass field must default to `0.0`; serialization writes `allocation_logit_sd`, deserialization treats a missing key as `0.0`, and `fit_parameters` returns `0.0` unless the isolated allocation fit supplies an estimate ([`stochastic_model.py:211–228`](../nhl-v3-phase2a-stochastic-2026-10-21/stochastic_model.py#L211), [`:269–310`](../nhl-v3-phase2a-stochastic-2026-10-21/stochastic_model.py#L269), [`:322–358`](../nhl-v3-phase2a-stochastic-2026-10-21/stochastic_model.py#L322), RNG initialization at [`:377–384`](../nhl-v3-phase2a-stochastic-2026-10-21/stochastic_model.py#L377)). No other fitted parameter changes.

## 2. Fit protocol

**Population.** Fit on regular-season game IDs in start-year seasons 2018, 2019, and 2020 only. The pinned official frame spans 2018-10-03–2019-04-06 (1,271 games), 2019-10-02–2020-03-11 (1,082), and 2021-01-13–2021-05-19 (868), 3,221 total. All 3,221 have accepted team-score targets; official team SOG is accepted for 3,181 and quarantined for 40. The allocation likelihood uses accepted ordinary shot attempts only, and applies the existing usable-timeline rule: 3,216 fit-eligible games and 362,508 attempt marks; exclude the five timeline-ineligible games. These counts are pinned in [`REPLAY-REPORT.md:25–39`](../nhl-v3-phase1-replay-2026-10-21/REPLAY-REPORT.md#L25) and [`TRAINING-DATA.json`](../nhl-v3-phase2a-stochastic-2026-10-21/TRAINING-DATA.json). The existing rule checks accepted ordinary-event chronology and valid clocks ([`run_phase2a.py:299–313`](../nhl-v3-phase2a-stochastic-2026-10-21/run_phase2a.py#L299)); the fit's accepted attempts and timeline eligibility are counted at [`:527–532`](../nhl-v3-phase2a-stochastic-2026-10-21/run_phase2a.py#L527), [`:591–615`](../nhl-v3-phase2a-stochastic-2026-10-21/run_phase2a.py#L591), and [`:650–688`](../nhl-v3-phase2a-stochastic-2026-10-21/run_phase2a.py#L650). Do not drop a quarantined SOG game from the attempt-allocation fit solely for its SOG disposition; do not include it in SOG evaluation.

**No in-sample first-stage probabilities.** Assign each eligible game to one of five folds by `int(SHA256(game_id).hexdigest()[:8], 16) % 5`. For each fold, fit every quantity that affects the Phase 2A baseline rate, including `poisson_coefficients` and `sog_reference`, on the other four folds only; then calculate \(p^0_{gi}\) for the held-out fold's accepted attempt states. The existing pregame snapshots use prior accepted team-SOG games and exclude same-date outcomes ([`run_phase2a.py:205–263`](../nhl-v3-phase2a-stochastic-2026-10-21/run_phase2a.py#L205)). Refit the ordinary Phase 2A components on the full 2018–2020 population with their original component-specific eligibility rules only after estimating \(σ\), then attach that estimate. Do not use 2021 or 2022 outcomes in either fit.

For each eligible attempt \(i\) in game \(g\), set \(y_{gi}=1\) for a home attempt and 0 for away. Reconstruct only the pre-attempt period, remaining clock, strength, and score state from that training game's accepted event path. With the out-of-fold baseline rates, calculate \(p^0_{gi}=\lambda^0_{H,gi}/(\lambda^0_{H,gi}+\lambda^0_{A,gi})\), where both rates use the same game snapshot and the side-specific state inputs to `shot_rate` ([`stochastic_model.py:191–238`](../nhl-v3-phase2a-stochastic-2026-10-21/stochastic_model.py#L191)).

**Estimator: marginal maximum likelihood.** Fit one shared Gaussian allocation effect per game. For standard-normal \(u\), define

\[
p_{gi}(u;σ)=\operatorname{logit}^{-1}(\operatorname{logit}(p^0_{gi})+b(p^0_{gi},σ)+σu),
\]
\[
\ell(σ)=\sum_g\log\int \phi(u)\prod_i p_{gi}(u;σ)^{y_{gi}}[1-p_{gi}(u;σ)]^{1-y_{gi}}\,du.
\]

Maximize \(\ell(σ)\) over \(σ\in[0,1]\), evaluating a fixed grid at 0.00, 0.025, …, 1.00, then refine only the best grid interval with bounded Brent optimization to tolerance \(10^{-6}\); ties choose the smaller \(σ\). If the best grid point is 0 or 1, report that boundary without refinement. Use 32-point Gauss–Hermite quadrature for the integral and evaluate each game likelihood in log space with log-sum-exp. This estimates between-game allocation heterogeneity while conditioning on the existing attempt count and event-state path, without Monte Carlo noise or a second-stage fit on in-sample rate predictions. Report a boundary estimate as a boundary result; do not widen the range after seeing it. The estimator and quadrature are deterministic, so the fit itself has no random seed.

**Scale check, not a target.** The 2021 diagnostic reports observed versus Phase 2A home-share variances of 0.006153 versus 0.003239 for attempts and 0.007255 versus 0.004549 for SOG. Its independent-margin logit-normal sizing implies \(σ\approx0.32391\) from attempts and \(σ\approx0.35035\) from SOG ([`TOTAL-PACE-SPLIT.md:20–25`](TOTAL-PACE-SPLIT.md#L20), [`:69–82`](TOTAL-PACE-SPLIT.md#L69)). Treat approximately 0.32 as the expected order of magnitude for an attempt-based estimate if that dispersion transports from 2021; 0.35 is a downstream SOG comparison only. These are descriptive 2021 values, not training targets or values to plug into the fit. A materially different 2018–2020 estimate triggers an eligibility, fold, likelihood, and quadrature audit, not manual adjustment. The exposed 2022 population is never used for fitting, tuning, threshold changes, or deciding the parameterization.

## 3. Evaluation fixed in advance

Evaluate the single fitted candidate on the 2021 development population against the frozen Phase 2A predictions for identical game IDs: 1,312 games for accepted attempt and score targets; 1,292 games for accepted official team SOG. Score CRPS is regulation-plus-OT team-goal CRPS, excluding shootout goals; SOG CRPS uses the official team SOG labels ([`run_phase2a.py:459–508`](../nhl-v3-phase2a-stochastic-2026-10-21/run_phase2a.py#L459), [`:923–947`](../nhl-v3-phase2a-stochastic-2026-10-21/run_phase2a.py#L923)). Use \(Δ=\text{candidate}-\text{Phase 2A}\), so negative CRPS deltas favor the candidate.

Use 16 candidate simulations per game, base seed 20261021, game IDs in sorted order, and the existing deterministic seed mapping `seed + game_index * 1000003 + trial` ([`run_phase2a.py:866–899`](../nhl-v3-phase2a-stochastic-2026-10-21/run_phase2a.py#L866)). Report paired per-game team SOG CRPS and regulation-plus-OT team-goal CRPS, plus the following for attempts and SOG separately: \(\operatorname{Var}(H)\), \(\operatorname{Var}(A)\), \(\operatorname{Cov}(H,A)\), \(\operatorname{Var}(H-A)\), home-share variance, and share index. For generated predictions, compute moments over game-by-draw rows; for observations, use one row per eligible game. Define \(N=H+A\), share \(s=H/N\), use positive-total rows for share moments, report zero-total rows separately, and define share index as \(\operatorname{Var}(s)/[\bar s(1-\bar s)\mathbb E(1/N)]\) using the observed mean share, consistently with the existing diagnostic ([`TOTAL-PACE-SPLIT.md:5–11`](TOTAL-PACE-SPLIT.md#L5)). Also report central 80% predictive-interval coverage for game attempt total, attempt margin, SOG total, and SOG margin; compute each interval from the 10th and 90th empirical quantiles of the 16 draws and report candidate-minus-Phase-2A coverage differences.

Use 2,000 paired game-ID cluster-bootstrap replicates, seed 20261022. Resample game IDs and keep both teams and all 16 draws for each sampled game together. Report 95% intervals for paired CRPS deltas, generated-minus-observed moments, count coverage, and candidate-minus-Phase-2A moment changes. The intervals condition on these 16 draws and do not include simulation Monte Carlo error, as in the existing analysis ([`share_mechanism.py:54–99`](share_mechanism.py#L54), [`:432–452`](share_mechanism.py#L432)). Record runtime, simulations completed, validation failures, and input/code SHA-256 values in the candidate JSON.

## 4. Research read criterion, not an adoption gate

Continue allocation work for further study only if the 2021 paired mean \(Δ\) SOG CRPS is \(\le 0\), and attempt \(\operatorname{Var}(H-A)\) reaches at least halfway from the Phase 2A value 165.813 to the observed value 323.520 ([`TOTAL-PACE-SPLIT.md:29–34`](TOTAL-PACE-SPLIT.md#L29)), i.e. at least 244.667 attempts², with the paired 95% game-cluster interval for candidate-minus-Phase-2A margin variance wholly above zero. Otherwise record this as a failed ablation. This is only a preregistered research continuation rule; it does not change any adoption gate or promotion rule.

## 5. Invalidation, artifacts, and validation

Any nonzero allocation parameter invalidates cached simulations and the old seed-to-event mapping. The zero default must retain the old mapping exactly. The eventual ablation must have its own runner and JSON result, with hashes for source inputs, out-of-fold rate fits, fitted parameters, simulator code, and outputs, following the provenance and validation pattern in [`share_mechanism.py:23–43`](share_mechanism.py#L23). Record frozen Phase 2A hashes before and after, and fail if any differ:

| Frozen Phase 2A artifact | Required SHA-256 before and after |
|---|---|
| `EVALUATION.json` | `24d5a55754a6b072f66203096a1936036a8d209df870ef6f8787bd0a22fc3930` |
| `FITTED-MODEL.json` | `8e0304b9dbe4230f9deb17abda0ebe79cd89653289d2661a1612d79f8914addb` |
| `REPORT.md` | `b0867d3cf1ef64a30469d087a03bda9ed156bbbbe020458b3efbb562473036f0` |

Re-run the full existing simulator validator on every candidate draw. It must continue to reconcile each attempt with exactly one outcome, derive SOG only from saved/goal outcomes, recompute goals and score snapshots, and validate monotone clocks and period order ([`stochastic_model.py:442–462`](../nhl-v3-phase2a-stochastic-2026-10-21/stochastic_model.py#L442), [`:719–835`](../nhl-v3-phase2a-stochastic-2026-10-21/stochastic_model.py#L719)). Recheck regulation period completion, tied-game OT entry, sudden-death termination, and shootout separation and final-score adjustment ([`stochastic_model.py:477–495`](../nhl-v3-phase2a-stochastic-2026-10-21/stochastic_model.py#L477), [`:551–597`](../nhl-v3-phase2a-stochastic-2026-10-21/stochastic_model.py#L551), [`:626–679`](../nhl-v3-phase2a-stochastic-2026-10-21/stochastic_model.py#L626)). Preserve component-specific eligibility/quarantine, pregame-only predictive inputs, and the no-actual-starting-goalie rule; simulation requests must remain replay-free ([`stochastic_model.py:465–470`](../nhl-v3-phase2a-stochastic-2026-10-21/stochastic_model.py#L465), eligibility handling at [`run_phase2a.py:459–508`](../nhl-v3-phase2a-stochastic-2026-10-21/run_phase2a.py#L459)).

## 6. Falsification

Allocation dispersion is the wrong or insufficient layer if the attempt margin variance moves toward observation but paired SOG CRPS worsens, SOG share dispersion overshoots observation, or total/margin count coverage degrades. A variance increase by itself is not evidence of improvement.
