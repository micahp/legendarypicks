# SLC — Score-Clock Layered

[Architecture](README.md) · [Version registry](../model-cards/nfl/README.md)

SLC stands for **Score-Clock Layered**, as explicitly named in the [Original October 28 integration ledger](https://github.com/micahp/legendarypicks/blob/5f5887bc/docs/research/SLC-INTEGRATION-LEDGER-2026-10-28.md). It is the NFL full-game sequence modeling family. It simulates plays sequentially from a frozen matchup snapshot: down, distance, field position, clock, score, eligible personnel and prior data. Historical SLC variants draw a play event and historical source row using fitted probabilities and optional conditioning layers, then apply football rules. It generates a distribution of games, not an exact forecast of the next real game's play sequence.

```text
slc_engine.play -> game_state.play_game -> e1_drive.simulate
 -> PlayCallSampler.sample -> pre_event.chooser / choose
 -> event + source row + runoff + spot -> rules / stats -> next snap
```

In current V2, personnel-first preparation can advance the participation lineup before the run/pass draw, conditional on formation priors. PBV1 is explicitly rejected with personnel-first at the reviewed pin; do not silently combine them. V2 Simplified disables optional row filters but retains other upstream effects. V1 Pure is a separate minimal control, not simply a filter-off ablation.

Sources: [Game entry](https://github.com/micahp/legendarypicks/blob/9a2e8624/scripts/nfl_sequence/slc_engine.py#L444), [Call and outcome sampler](https://github.com/micahp/legendarypicks/blob/9a2e8624/scripts/nfl_sequence/slc_playcall.py#L429), [Personnel-first path](https://github.com/micahp/legendarypicks/blob/9a2e8624/scripts/nfl_sequence/pre_event.py#L426), [Row-conditioning arms](https://github.com/micahp/legendarypicks/blob/41a759e3/scripts/nfl_sequence/slc_playcall.py#L766). Frozen identities and build args come from [Portable registry](https://github.com/micahp/legendarypicks/blob/e0d3f603/scripts/nfl_sequence/slc_model_registry.py); a branch head is not a frozen model.

## Other execution strategies

[CEG](CEG.md) eliminates historical-row selection via fitted conditional distributions. [V1 Complete](../model-cards/nfl/slc-v1-complete.md) delegates live plays to [Gridiron](GRIDIRON.md); uses CEG typed contracts, not CEG's statistical generator.

## Data and evaluation

Pregame cutoff and provenance, player eligibility, independent seed streams and complete regulation/OT are required. Use original cohort-specific results; football realism alone cannot demonstrate forecasting skill. [Evaluation](../evaluation/README.md).
