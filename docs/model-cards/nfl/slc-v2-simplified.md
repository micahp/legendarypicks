# SLC V2 Simplified and conditioning arms

[Registry](README.md) · [SLC](../../architecture/SLC.md)

Research pin `41a759e3`, [conditioning implementation](https://github.com/micahp/legendarypicks/blob/41a759e3/scripts/nfl_sequence/slc_playcall.py#L766-L845). Same historical PlayCallSampler execution, with optional row conditioning mode disabled (Simplified), support-aware, or soft; legacy preserves original sequential filters. Disabled skips optional formation, coverage, streak, label, target role and exact-spot row filters, not necessarily upstream event-probability adjustments. Support-aware/soft retain optional conditioning differently; inspect [helper](https://github.com/micahp/legendarypicks/blob/41a759e3/scripts/nfl_sequence/slc_row_conditioning.py) and exact configuration. Not V2 Pure. No matched held-out results independently recovered here; no promotion. Reconcile with newer V2 personnel-first changes before integration.
