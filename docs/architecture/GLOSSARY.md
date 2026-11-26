# Glossary

[Architecture](README.md) · [Model registry](../model-cards/README.md)

| Term | Definition |
|---|---|
| CEG | **Conditional Event Generation**. Fit distributions on historical events, generate a new coherent event at inference instead of sampling a historical row. [Definition](CEG.md). |
| CEG contract | Typed play/event facts (ceg-play-1/2/3); distinct from the CEG model. |
| SLC | NFL sequence simulation family (historical conditional play sampling and successor research). The original acronym expansion was not established in the inspected sources; do not invent one. [Definition](SLC.md). |
| HPV1 | Historical project/data contract for eligible observed NFL play classes and joint personnel records. |
| PBV1 | Historical personnel-package sampling experiment using HPV1. Not executable route diagrams. [Card](../model-cards/nfl/pbv1.md). |
| Playbook profile | Observed team-season tendencies from nflverse PBP and participation; not a recovered play call or Madden asset. |
| Executable play | Authored formation and per-player assignments consumed by a live engine. |
| V1 Pure / V2 Pure | Minimal statistical controls, distinct from V1 Complete and from frozen V1/V2. |
| V2 Simplified | Experimental disabled optional historical-row conditioning, not the same as a pure model. |
| V1 Complete | Autonomous 11-on-11 football, live decisions and physical outcomes; not completed merely because of its name. |
| Liquid AI | EA product terminology; our architecture is inspired by documented behavior, not recovered EA source. [Definition](LIQUID-AI.md). |
| Gridiron | Shared football player/ball physics and autonomous execution repository. |
| Frozen model | Exact source SHA, configuration, inputs, cutoff, RNG and artifact hashes. |
| Brier | Mean squared error of predicted probability vs binary outcome; lower is better. Compare only matched event/cohort definitions. |
| Proper score | Score that rewards honest probability forecasts (e.g. Brier/log loss). |
| Cutoff | Latest allowed information publication time for a historical or future forecast. |

Sources: [CEG plan](https://github.com/micahp/legendarypicks/blob/8d86d430/docs/research/SLC-CONDITIONAL-EVENT-GENERATION-PLAN.md), [PBV1 specification](https://github.com/micahp/legendarypicks/blob/9a2e8624/docs/research/PBV1-SAMPLER-SPEC-2026-11-02.md), [V1 Complete design](https://github.com/micahp/legendarypicks/blob/50c15508/docs/research/V1-COMPLETE-DESIGN.md).
