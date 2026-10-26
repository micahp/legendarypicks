# NHL Full-Game v0.2b: 2021 Paired Evaluation

Date: 2026-10-26
Branch: `research/nhl-game-state-v02b-2026-10-25`
Implementation commit: `e329d67c`
Preregistration: [`NHL-FULL-GAME-V02B-PREREG-2026-10-25.md`](NHL-FULL-GAME-V02B-PREREG-2026-10-25.md), commit `32869e40`
Machine-readable results: [`2021-paired-evaluation-v1.json`](../../research/nhl/statistical-full-game-v0.2b/results/2021-paired-evaluation-v1.json)

## Finding

The player/goalie-informed v0.2b candidates did not improve game-level prediction over either v0.1 or the simpler forward-only team-rate reference. On the 1,100 games with complete predictions from every candidate and reference, the team-rate reference had the lowest goal CRPS, final-score energy, winner Brier, and team SOG CRPS. Paired game-bootstrap intervals also put each v0.2b candidate behind both references on the pairwise-complete populations.

This is not a clean ablation of the marginal value of player and goalie inputs: the candidates also differ in event generation, historical-template use, and state handling. The result is that the current player/goalie-informed simulator has not demonstrated predictive value, not that player or goalie information cannot help. Keep v0.2b research-only; no candidate was selected and no gate changed.

## Population and pregame data coverage

- The frozen 2021 development population has 1,292 eligible targets out of 1,312 listed games. The other 20 were quarantined because event-derived shots on goal disagree with independent box-score SOG; the cause was unresolved. The target rows were all retained in the evaluation artifact.
- Training uses 1,921 eligible 2019–2020 games. 2021 is development data; the previously exposed 2022 data were excluded.
- A projected player and goalie pool could be constructed for both teams in 1,291 of 1,292 eligible games. The one input failure is `2021020002` (VGK–SEA, 2021-10-12): Seattle had no prior-appearance player pool. This is historical roster coverage, not a simulation-rule failure.
- Historical players and goalies are projected from eligible prior appearances and prior goalie starts. This does not establish that the projected players were actually available for the target game. The target game's actual lineup, starter, shifts, and results were not used. Starting goalie identity remains uncertain.
- The evaluator groups target games by calendar date, builds every pregame snapshot before admitting any result from that date, and uses only games with dates strictly earlier than the target. The v0.2b transition model was trained on 2019–2020 only. This prevents target and same-day result leakage in the constructed history. The archived historical rows do not preserve a verifiable original publication timestamp for every input, so this establishes a strict date-based information cutoff, not a source-by-source proof of historical publication time.
- The read-only Legendary Picks NHL database inventory in the preregistration found no 2021 player/roster history: those tables begin in 2025/26. The 2021 backtest therefore uses the independently verified GameCenter archive with forward-only history, rather than later database rows that would leak future information. Current ingested database rows remain useful for prospective simulations when each row's game date and capture/ingest time precede the frozen pregame cutoff. The evaluation did not write to either database.

## Matched predictive results

Lower is better. The table below reports means on the same 1,100 games with complete predictions from all five systems. The team-rate reference is an independent-Poisson score-rate model using forward-only shrunk team goal and SOG rates; it does not generate a chronological event stream.

| Model | Reg+OT goal CRPS / team | Final-score energy | Winner Brier | Team SOG CRPS |
|---|---:|---:|---:|---:|
| Historical team-rate reference | **0.9746** | **1.5458** | **0.2385** | **3.7862** |
| Frozen v0.1 | 0.9933 | 1.5825 | 0.2482 | 3.9186 |
| B0 alpha2 | 1.0606 | 1.6869 | 0.2643 | 4.2274 |
| B1 state-integrity candidate | 1.0638 | 1.6955 | 0.2594 | 4.1549 |
| B2 state-conditioned transitions | 1.1134 | 1.7842 | 0.2602 | 4.2746 |

Paired differences below are candidate minus reference, so positive values favor the reference. Brackets are 95% paired game-bootstrap intervals from 2,000 resamples. Each comparison uses the same games for both models; its `n` differs because candidate coverage differs. These intervals condition on the frozen simulation draws.

### Against the historical team-rate reference

| Candidate | n | Goal CRPS Δ [95% CI] | Energy Δ [95% CI] | Brier Δ [95% CI] | SOG CRPS Δ [95% CI] |
|---|---:|---:|---:|---:|---:|
| B0 alpha2 | 1,291 | +0.0851 [0.0708, 0.0994] | +0.1385 [0.1175, 0.1598] | +0.0257 [0.0174, 0.0337] | +0.4408 [0.4007, 0.4799] |
| B1 | 1,207 | +0.0907 [0.0769, 0.1050] | +0.1528 [0.1321, 0.1746] | +0.0238 [0.0148, 0.0332] | +0.3659 [0.3116, 0.4169] |
| B2 | 1,174 | +0.1402 [0.1179, 0.1640] | +0.2435 [0.2103, 0.2803] | +0.0232 [0.0151, 0.0316] | +0.4777 [0.4082, 0.5502] |

### Against frozen v0.1

| Candidate | n | Goal CRPS Δ [95% CI] | Energy Δ [95% CI] | Brier Δ [95% CI] | SOG CRPS Δ [95% CI] |
|---|---:|---:|---:|---:|---:|
| B0 alpha2 | 1,291 | +0.0657 [0.0502, 0.0814] | +0.1017 [0.0784, 0.1252] | +0.0152 [0.0064, 0.0239] | +0.3046 [0.2493, 0.3532] |
| B1 | 1,207 | +0.0718 [0.0567, 0.0866] | +0.1163 [0.0935, 0.1393] | +0.0140 [0.0043, 0.0237] | +0.2286 [0.1639, 0.2954] |
| B2 | 1,174 | +0.1215 [0.0975, 0.1468] | +0.2069 [0.1700, 0.2469] | +0.0128 [0.0036, 0.0218] | +0.3459 [0.2680, 0.4267] |

B1 improves SOG CRPS versus B0 by 0.0712 (95% CI −0.1356 to −0.0131), but its goal, energy, and winner differences versus B0 are not resolved from zero. B2 is worse than B0 on goal CRPS and energy, with intervals above zero; its SOG and winner differences versus B0 are not resolved. B1's SOG improvement over B0 does not close its gap to either simpler reference.

## Distributional realism

The following are observed and generated count means and variances. Goals are regulation plus overtime goals per team; SOG is per team; attempts and penalties are per game. The historical-rate reference does not produce attempts, penalties, OT, or shootout event processes.

| Measure (mean / variance) | Observed | B0 | B1 | B2 | Team-rate | v0.1 |
|---|---:|---:|---:|---:|---:|---:|
| Reg+OT goals / team | 3.097 / 3.160 | 3.030 / 2.618 | 2.962 / 2.761 | 3.717 / 4.576 | 2.960 / 3.019 | 2.912 / 2.835 |
| SOG / team | 31.602 / 47.792 | 31.234 / 12.504 | 31.376 / 22.315 | 32.350 / 61.529 | 30.899 / 31.926 | 30.618 / 40.246 |
| Shot attempts / game | 113.25 / 145.51 | 110.18 / 105.30 | 110.11 / 105.07 | 110.79 / 138.71 | — | 110.64 / 120.64 |
| Penalties / game | 7.396 / 11.643 | 6.715 / 8.270 | 6.372 / 6.718 | 6.790 / 8.280 | — | 7.099 / 9.787 |

| Frequency | Observed | B0 | B1 | B2 | v0.1 |
|---|---:|---:|---:|---:|---:|
| Games reaching OT | 21.52% | 18.05% | 16.96% | 14.86% | 15.64% |
| Games reaching shootout | 7.35% | 5.77% | 5.00% | 11.46% | 5.29% |

B0 and B1 substantially understate SOG variance; B2 raises it above the observed variance and also overstates goal variance and shootout frequency. B0 and B1 understate score-margin variance (5.35 and 5.99 versus 7.09 observed), while B2 overstates it (9.18). Mean event counts alone therefore conceal material distribution errors.

Player deployment realism was not evaluated against target-game shifts or TOI. The candidates use remapped historical shift templates and maintain simulated personnel ledgers, but this run does not establish realistic player-level TOI, shift duration, or line deployment. No player-level accuracy or goalie calibration claim is made.

## Failures and quarantines

- Upstream source quarantine: 20 of 1,312 listed 2021 games were ineligible because event-derived SOG did not reconcile to box-score SOG. No repair was inferred.
- All 1,292 eligible target rows remain in the JSON. Complete prediction coverage was: v0.1 1,292/1,292; B0 1,291/1,292; team-rate 1,291/1,292; B1 1,207/1,292; B2 1,174/1,292. Only 1,100 games have complete predictions from all five.
- B1 lacks 85 target predictions: the Seattle input failure plus 84 games with one or more failed simulation draws. It had 87 draw failures: 52 penalties expired without a preceding expiration event, and 35 left a penalized player on the ice.
- B2 lacks 118 target predictions: the same Seattle input failure plus 117 games with draw failures. It had 121 draw failures: 68 missing penalty-expiration events and 53 penalized-player-on-ice violations.
- These are real state-consistency failures, not missing target labels. Candidate metrics are explicitly incomplete against the full 1,292-game denominator. Shift-row quarantine totals in the JSON aggregate repeated simulation draws and are not counts of unique source rows or periods.

## Runtime, uncertainty, and artifact notes

- The authoritative frozen Monte Carlo count is **10 draws per B0/B1/B2 target**, with 10,000 draws per v0.1 and team-rate reference. The preregistration's final amendment and `execution_configuration` specify 10. The JSON `limitations[0]` text incorrectly says “Twelve”; this stale sentence does not match the actual seeds, per-game draw counts, or frozen configuration. The machine-readable result was left byte-for-byte unchanged.
- Summing the per-target generation timers gives 16,090.078 seconds (about 4.47 hours) across B0, B1, B2, and the team-rate reference. This is accumulated model-generation elapsed work, not end-to-end wall time. The JSON's `total_wall_seconds=871.374` and `source_preparation_and_fit_seconds=56.168` cover only the final resumed evaluator invocation; its timer resets on resume. Total elapsed wall time for all invocations cannot be recovered from this result artifact.
- Game-bootstrap uncertainty is conditional on the frozen 10 candidate draws. The result also includes a five-versus-five split-half Monte Carlo sensitivity diagnostic. These development intervals do not cover model-fitting uncertainty or establish performance on a fresh season.
- Result JSON SHA-256: `b2e1601991bae1af4b638ac16947e3c83d1f4e06eb3d203550910534ff147e6e`.

## Decision and next evidence needed

Do not adopt B0, B1, or B2. Keep the statistical game generator as a research prototype and retain the frozen v0.1 artifacts. The team-rate reference beats the candidates on matched predictive scoring, while the candidates also show under/overdispersion and penalty-state failures. This run does not show that player or goalie features add predictive skill over team-level rates.

The 2021 population was used for development and the 2022 population is exposed. A properly frozen later-season or prospective evaluation is still required before any adoption claim. A future experiment should isolate player and goalie feature value from event-process changes, improve complete prediction coverage, validate player deployment against source shifts, and repair penalty/manpower transitions before expanding the engine further.

No production forecasts, database rows, frozen Phase 2A/v0.1 results, or physical simulation code were changed. No candidate was selected and no gate changed.
