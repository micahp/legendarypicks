# Evaluation and benchmarks

[Handbook](../README.md) · [Model comparison](MODEL-COMPARISON.md) · [Benchmark ladder](BENCHMARKS.md) · [Methodology](METHODOLOGY.md)

Three separate questions: (1) does the code generate legal, reproducible games, (2) do distributions resemble real NFL football, (3) do probabilities forecast held-out outcomes better? A passing fixture or a visually plausible game cannot answer (3).

Method: define cohort, publication cutoff, source hashes, exact variant/profile/seed roots, target, comparator, uncertainty and stop condition before testing. Preserve blocked seeds; report requested/valid coverage. Hold out chronologically; never select on evaluated outcomes and relabel as prospective. Paired variants use same inputs and stable RNG stream roots; seed numbers alone are insufficient. Brier and log loss for probabilities, MAE for points/margin/totals, distribution calibration and CRPS where applicable. Distinguish prop-line and game-level denominators, market de-vig method and quote timestamp. Report Monte Carlo error and uncertainty, cost and predictive benefit. Do not add complexity for its own sake. See [NFL model card](../model-cards/nfl.md) and [CEG measurement lessons](https://github.com/micahp/legendarypicks/blob/8d86d430/docs/research/slc-ceg-2026-11-24/FINDINGS-FOR-V2-AND-V1-COMPLETE.md).
