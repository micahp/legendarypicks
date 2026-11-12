# V1.6 joint early-down sampling and drive-progression experiment

**Status:** protocol, not results
**Date:** 2026-11-12
**Purpose:** isolate the remaining sack, third-down-distance, and fourth-down-short gaps in one controlled experiment. Keep the fourth-down decision policy fixed. Test whether early-down sampling is the shared cause, and determine whether the G/I/N sack-label correction helps or harms calibration.

## Repository and evidence state

The G/I/N correction is on `slc-v1.6` in commit `6df31da6`. The controlled ARI–DAL replay and its frozen input are recorded in [the drive-progression report](README.md). With blocker fixes enabled, both first-down and second-down 6–9 sack rates moved toward history, while third-and-3–5 and fourth-and-short opportunities rose slightly. It covered 10 paired seeds in one matchup, so it motivates this experiment but does not settle the correction.

An interim rerun raised `playcall_no_run_outcomes_in_cell:(4, '4-6', '80-99')` on seed 1 at fourth-and-4 with the ball 14 yards from the offense's own goal line (`yardline_100=86`). That command omitted `--slc-blocker-fix run_scramble_backoff`; it was a configuration omission, not evidence that the enabled backoff path fails. With all five recorded blocker fixes enabled, both replay arms completed all 10 seeds, including seed 1. Artifact-backed SLC runs now enable those five blocker fixes by default; `--slc-disable-blocker-fix` is reserved for explicit research ablations.

The exact fourth-down support gap also has a separate bounded guard, enabled by default for the named `v1_6_candidate` profile. When the chosen fourth-down run or dropback has no historical support but the other scrimmage intent does, it switches to that supported intent and records the original intent and fallback reason. It does not change the already-made kick-versus-go decision. The factorial must use this same guard in every arm and report its use as a fourth-down call-selection fallback; include a guard-off sensitivity count, but do not mix that ablation into the primary comparison. If neither scrimmage intent has historical support, the run remains invalid under the support gate.

## Questions and hypotheses

The experiment separates four candidate causes:

1. **Call selection:** first- or second-down dropback frequency differs from historical frequency for the same situation.
2. **Event selection:** after a run or dropback is selected, the conditional event weights suppress sacks or other negative outcomes.
3. **Yardage selection:** the event is reasonable, but sampled yards fail to reproduce the historical gain/loss and line-to-gain distribution.
4. **Label conditioning:** adding G/I/N to sack rows changes event weights or sampled source rows in a way that worsens held-out calibration.

The shared-cause hypothesis predicts that correcting one or more early-down mechanisms will increase negative early-down outcomes, move third-down distances away from excess 3–5-yard situations, and reduce excess fourth-and-5-or-short opportunities. These are predictions to test, not assumed effects.

## Stage 0: source support and fallback audit — all four downs

Before any rate comparison, construct a support table from the exact pinned 2022–2025 source pool. For every down (1–4), distance band, field-zone bucket, and selected intent, record:

- eligible exact-cell row count, after the same penalty, lateral, scramble, and source-row filters used by the simulator;
- support at each configured backoff level: exact cell, down plus field zone, down plus distance, field zone, and league intent;
- number of decisions selecting that intent, selected fallback level, source-row count, and rejected-row count;
- separate counts for ordinary runs, QB scrambles, dropbacks, and kick actions.

A focused regression fixture covers fourth-and-4–6 at `yardline_100=80–99`: the exact cell has no ordinary run rows, but broader run support exists. With `run_scramble_backoff` enabled, it verifies that the sampler preserves the selected `run` intent, draws an eligible ordinary-run row from down-field support, and records its level and count. A second fixture covers the observed case where no run support exists but dropback support does; the V1.6 guard redirects the scrimmage intent, records the fallback, and leaves kick share unchanged. Extend the support matrix across exact, down-field, down-distance, field-zone, and league-intent levels so terminal behavior is explicit. Report intent redirections separately from ordinary source-row backoff.

**Validity gate:** every simulated intent must either draw from a documented supported level or produce a separately counted, explicit unrecoverable-support status. Any thrown support exception or unrecorded fallback invalidates that arm's behavioral comparison. Report support failures by down even if no game fails.

## Stage 1: historical mechanism scoring

Use the same event definitions and eligible-play filters as the simulator. Fit on 2022–2024 and score 2025 as a held-out season; repeat walk-forward by season as a sensitivity check. Report pooled 2022–2025 historical rates only as descriptive game-level targets.

Score the three sampling stages separately:

- **Call:** run/dropback Brier score and log loss by down, distance, field zone, and score/clock band.
- **Event:** multiclass log loss and Brier score conditional on selected intent; separately report sack/dropback, sack/fumble, incompletion, interception, fumble, and negative-play calibration on downs 1–4.
- **Yardage:** conditional gain/loss distribution after event selection, including mean, negative-yard rate, probability of gaining the line to gain, and residuals by exact yards-to-go.
- **Label correction:** on identical held-out plays, compare the legacy labels (G/I/N absent on sacks) with corrected labels. Score G/I/N event weights and row filtering separately, then together. Include support counts and shrinkage for every context; a rate moving in one small simulated sample is not itself proof of calibration improvement.

This stage identifies whether the label change improves out-of-sample event prediction and whether any regression enters through event weighting, source-row filtering, or their interaction.

## Stage 2: paired full-game factorial

Run a 2×2×2×2 factorial (16 arms). All arms use the same frozen roster snapshots, database, play-call artifact, streak inputs, game settings, and seed set. Use paired random roots by matchup and seed. Keep all fourth-down policy parameters identical. The four binary factors are:

| Factor | Current level | Diagnostic level |
|---|---|---|
| A. First/second-down call selection | Current V1.6 call probabilities | Add a fitted logit intercept within down/distance/field cells so mean dropback probability matches the historical cell rate; preserve score/clock and team offsets |
| B. Early-down event mix | Current conditional event weights | Draw from unweighted historical event counts within selected intent and exact situation cell, using the common support/backoff rules; turn off only outcome reweighting layers and do not change yardage sampling |
| C. Early-down yardage | Current exact-distance yardage | Diagnostic ablation to the existing down/distance-bucket yardage path; preserve selected event |
| D. Sack context labels | Corrected G/I/N labels on all dropbacks, including sacks | Legacy G/I/N handling with sack rows unlabeled |

Fit A's intercepts on 2022–2024, score the fixed procedure on 2025, then refit on 2022–2025 for the prospective simulation. For B, use only source rows available to that arm's cutoff; the held-out scoring uses 2022–2024 as the event pool and 2025 as the test set. Freeze the cell definitions, minimum support, and any shrinkage before the simulation runs. Apply A–C only to decisions or outcomes on downs 1–2. Apply D wherever the decision-label layer is used. The support/backoff fix from Stage 0 is common to every arm, not an experimental factor.

Use the two pinned Week 8 matchups already in the repository: ARI–DAL and ATL–TB. Run 100 paired seeds per matchup per arm (200 simulated games / 400 team-games per arm). Use seeds 1–100 in each matchup and identical seed-roots across all arms. If any arm fails the Stage 0 validity gate, repair the support path and rerun the complete factorial; do not drop only its failed seeds.

## Outcomes and analysis

Compute every outcome for each arm from the same ordered-play definitions. Report both pooled counts/rates and game-level distributions, with both teams in a simulated game kept together as one resampling block.

**Primary endpoint:** fourth-and-5-or-short situations per team-game. Compare each predeclared candidate arm that retains current exact-distance yardage (C=current) with the all-current arm. Estimate paired differences and simultaneous 95% matchup-stratified bootstrap intervals over matchup/seed blocks. A meaningful improvement requires the selected arm's point estimate to close at least 25% of the all-current arm's excess over the historical rate and its interval to exclude zero in the improving direction. Select the least complex arm that meets this rule. The C=diagnostic arms estimate yardage-layer effects and cannot be selected as a release correction unless Stage 1 independently shows the bucket path improves held-out yardage scoring. The fourth-down action policy itself must be unchanged.

**Required linked outcomes:**

- first-down sack/dropback rate and second-down 6–9 sack/dropback rate;
- early-down negative plays per team-game and mean gain;
- third-and-3–5, third-and-10+, and all third-down distance-band counts per team-game;
- fourth-down distance bands, including 1–2, 3–5, and 6–9 yards to go;
- third-down conversion, turnovers per team-game, and source-support/backoff use on downs 1–4.

Estimate the four factorial main effects and interactions on the primary and linked outcomes. The A×B and B×D contrasts are especially diagnostic: they show whether call mix masks event suppression and whether the G/I/N correction changes event sampling. Attribute a change to yardage only if C changes the transition-distance outcomes while event rates remain stable.

## Decision rules

- **Do not freeze V1.6** if fourth-and-short opportunities fail the primary improvement rule, if a sampling exception remains, or if the joint arm materially worsens turnover calibration.
- If A dominates, correct early-down call selection; if B dominates, correct conditional event probabilities; if C dominates, revisit yardage sampling; if interactions dominate, implement the smallest supported joint correction.
- Retain the G/I/N correction only if held-out scoring supports it or the full-game effect is beneficial without material calibration harm. If corrected labels worsen held-out scoring, investigate shrinkage/context support or disable their outcome influence while preserving correct source labels.
- The aim is material movement toward historical behavior, not exact agreement on every metric. Report uncertainty and any remaining gap rather than declaring a workstream resolved from a directional point estimate alone.

## Reproduction and provenance

Pin the database, snapshot, artifact, streak files, source commits, configuration hash, RNG-root manifest, and code hashes in the result record. The ARI–DAL snapshot and its exact hash are in [the existing evidence record](README.md#reproduction-inputs); use the checked-in ATL–TB snapshot at `docs/research/slc-week8-2026/snapshots/2026_08_ATL_TB.json` for the second matchup. Preserve the ordered-play exports and per-seed outcomes for every arm. Do not compare arms unless their raw input hashes, seed roots, and enabled settings match, apart from the declared factorial factor.
