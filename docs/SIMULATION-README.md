# NFL models and simulation: how we got here

Status as of 2026-11-02. Sources: `docs/model-cards/nfl.md`, `docs/research/SLC-MODEL-CARD-2026-10-29.md`,
`docs/research/SLC-V2-RESEARCH-PLAN-2026-11-02.md`, `docs/research/PBV1-SAMPLER-SPEC-2026-11-02.md`,
`docs/CONTEXT-2026-11-02-SLC-V2.md` and the participation research folder. Each claim below points at one of those files.

The repo never expands the name "SLC". This README uses it as a label only.

## Status legend

- **Adopted**: the production baseline for its product surface.
- **Research**: built and tested, not adopted. Nothing in it changes a default.
- **Rejected**: tested against its pre-registered rule and failed.
- **Open**: not built, or built but not validated.

## 1. v1 points: the adopted game model

- **Model:** `nfl-v1`, shown as "v1 points" on the Model page. It predicts game winner, expected points, margin and total.
- **Status:** adopted game baseline. It has a frozen 2025 holdout. It is not market-validated.
- **Why it matters here:** it is the reference that every later challenger is compared with.

Challengers to v1 points, from the model card:

| Model | Status |
|---|---|
| v2 EPA (`nfl-epa-v2`) | Trial. Its 2025 evaluation did not establish an improvement over v1 points. |
| v1 plus Elo (`nfl-v1+elo stack`) | Research challenger. Some retrospective gains, not confirmed prospectively. |

## 2. Score simulation, October 2026

Before the full-game engine, the team tested how to sample final scores.

- **Placeholder score sampler:** still the default.
- **Real-score history option:** in the code, selectable, but it failed gate G4. Its simulated spread across teams was too narrow. The record is `docs/RESULTS-nfl-sim-scores-2026-10-13.md`.
- **Spread hypothesis (G4 follow-up):** the narrow spread was blamed on the expected margins. That was refuted. The spread problem sits in the sampler, not in the ratings. Record: `docs/RESULTS-nfl-sim-g4-elo-2026-10-13.md`.

## 3. Pregame play-sequence and contextual full-game specs, October 2026

- **Pregame play-sequence generator v1** (`docs/SPEC-nfl-pregame-play-sequence-generator-v1.md`): proposed, not implemented. Goal: one hypothetical game from a frozen pre-kickoff snapshot, as a chronological play script. It is an entertainment product, not a forecast of record.
- **Contextual full-game simulation** (`docs/SPEC-NFL-CONTEXTUAL-FULL-GAME-SIMULATION-2026-10-25.md`, NFL-CONTEXT-SIM-V1): research specification. It asks for one matchup at one moment in the season, with thousands of differing outcomes, and for team, player and clock state to update play by play.

## 4. SLC v1: the full-stack play-by-play engine (`slc_v1_incomplete`)

The engine simulates a regular-season game play by play from a pregame snapshot. Model card: `docs/research/SLC-MODEL-CARD-2026-10-29.md`. Readiness: `docs/research/SLC-READINESS-2026-10-28.md`.

What is connected:

- Score-clock play-call artifact, on by default.
- Trick throws and QB catches at measured rates, on by default.
- Formation and personnel, team outcome splits, score-state splits, win-loss streak splits, defensive labels, decision labels (categories A to N), Dirichlet player shares, playbook priors. Each is behind an opt-in flag.

Status:

- Engine runs complete games with zero errors on the Week 8 2026 snapshot (`2026_08_CAR_GB`, `2026_08_KC_DEN`).
- **No layer stack is calibrated end to end.** The audit is `docs/research/SLC-LAYER-CALIBRATION-AUDIT-2026-10-29.md`.
- Exact-yardline sampling changes red-zone and touchdown rates. Conversion remains below actual (`docs/CONTEXT-2026-11-02-SLC-V2.md` and the Week 8 handoff).
- The 10,000-seed batch has not been run for the full stack. Archived batches must not be rerun.

## 5. SLC v2: research plan, milestones and PBV1

Plan: `docs/research/SLC-V2-RESEARCH-PLAN-2026-11-02.md`. Two tracks: historical realism, and weekly matchup intelligence.

Rules that govern every step:

- Hash-pinned layers change only behind disabled-by-default research flags, each with a numbered freeze amendment.
- Integrate one component at a time: PBV1 first, then P1 pass share, then P2 target share.
- Flags off must reproduce `v1_full_stack` exactly (a regression test).
- No 2026 outcome is read to develop or select an arm. Holdout exposure rules apply.
- No production default changes, no production database writes, no deployment.

Milestones (from the context summary):

| Milestone | Status |
|---|---|
| M2 PBV1 sampler | Primary target (RB plus FB) passes under the B0 reading of criterion (c). The RB-only target has no retrospective fold, so (c) is not evaluated for it. |
| M3 play-call ablation | Situation cell model rejected. Worse than the production model on log loss in both folds. |
| M4 weekly models | P1 pass share and P2 target share built and frozen. P1 tempo and go rate rejected. P3 defense rejected as built. P2 snap share inconclusive. |
| M5 integration | PBV1 hook written, flag off. The flags-off regression does not match the baseline yet. |
| M6 prospective locks | Not started. Week 10 has 14 games. |
| M7 decisions | Decision ledger committed. |

### PBV1: the package sampler

- **What it is:** a sampler for the package on each snap (RB plus FB, or RB only), with cells by play family, down, distance and red zone.
- **Data:** the HPV1 contract, 2022 to 2025 scrimmage plays. HPV1 is the data contract; PBV1 is the experiment name.
- **Evidence:** frozen results in `docs/research/pbv1-sampler-2026-11-02/`. Development folds 2023 and 2024 show gains over the marginal package distribution. Criterion (c) (retrospective-fold sign) is open under one reading.
- **Limit:** personnel does not reach outcomes in `v1_full_stack`. The PBV1 hook changes the recorded label only, unless personnel is added to the outcome match, which is a model change needing an owner decision.

### Participation research (this folder, 2026-11-02)

Folder: `docs/research/participation-model-2026-11-02/`. Research only. Not in the simulator.

Question: when the offense substitutes, who comes off and who goes on, and how much does that matter for the simulated distributions?

| Step | Result (2025 holdout) |
|---|---|
| Substitution gap, gate with feasibility | Season-primary pools and snap-level labels. Joint plus drive model: 1.313 entries per clean pair against 1.342 observed. Feasible arms have zero unfillable steps. Pools use full-season labels, so this is a retrospective oracle. |
| Cutoff-safe individual substitutions | Persistence beats the current mechanism on exact identity. Precision is 0.70 against 0.38. |
| Identity model | Entrant recall 0.783 against 0.763 for recency. Gain is small. Not wired into the simulator. |
| Snap share | 2023 to 2025 out-of-sample MSE beats the group baseline. Not split by package. |
| Depth roles | About 1 percent MSE reduction. WR and TE only. |
| Touch and play type | Small holdout log-loss gain. |
| 2022 positions | Reconstructed from PFR snap counts. Matched agreement with on-field labels: WR 99.97%, TE 99.96%, RB 98.95%, FB 96.6%. |

Open: the 2022 label drop still reaches the gate's skill fits through `lineup_fit.py` and the touch analysis. Fixing it changes the fitted tables and needs a rerun.

## 6. Where each layer stands

| Layer | Adopted | Research | Rejected | Open |
|---|---|---|---|---|
| Game winner, points, margin, total | v1 points | v2 EPA, v1 plus Elo | | |
| Score sampler | placeholder | real-score history | | |
| Play-call artifact | score-clock | | | |
| PBV1 package sampler | | RB plus FB (primary), RB only | | criterion (c), RB-only fold |
| P1 pass share | | built, frozen | | |
| P1 tempo, P1 go rate | | | rejected | |
| P2 target share | | built, frozen | | full-stack comparator |
| P2 snap share | | | | inconclusive |
| P3 defense | | | rejected as built | redesign |
| Substitution, identity, depth, touch | | participation research | | integration |

## 7. Files to start from

- `docs/model-cards/nfl.md`: the adopted and challenger game models.
- `docs/research/SLC-MODEL-CARD-2026-10-29.md`: what SLC v1 connects and its flags.
- `docs/research/SLC-V2-RESEARCH-PLAN-2026-11-02.md`: the v2 plan and milestones.
- `docs/research/PBV1-SAMPLER-SPEC-2026-11-02.md`: the pre-registered PBV1 spec.
- `docs/CONTEXT-2026-11-02-SLC-V2.md`: the working state, open problems and owner decisions.
- `docs/research/participation-model-2026-11-02/`: the substitution, identity and snap-share research.

## 8. Owner decisions still open

1. Confirm the B0 reading of criterion (c) for PBV1.
2. Whether personnel conditions the outcome match, or PBV1 stays label-only.
3. Whether the identity model and depth offsets go into the candidate simulator, given their small gains.
4. Whether the gate moves to cutoff-safe pools before any SLC integration.
