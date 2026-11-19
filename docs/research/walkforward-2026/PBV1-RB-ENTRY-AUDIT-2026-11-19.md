# PBV1 / participation field: 2026 RB entry audit

**19 November 2026.** Research only; not a model promotion or full-game simulation.

## Inputs

- Frozen 2026 Weeks 1–10 walk-forward snapshots (150 games), from `feat/oracle-walkforward-builders` at `9eaa6341`.
- Frozen 2022–2025 `field_v4_2022_2025.json` (the participation field's original player/team/personnel observations).
- The nine `through_week01.json` through `through_week09.json` snap-count cuts pushed in `9eaa6341`.
- **Caveat:** the underlying snap-count source file was last modified 2026-11-10. Prior-week clipping prevents target-week numbers entering the formula, but does not establish that earlier rows were unchanged when each historical forecast would have been issued. Snapshot source timestamps are also unverified. Treat all results as **retrospective**.

## Tested question and method

When an offense's first snap uses **11 personnel** (one RB-class slot), which eligible RB/FB player receives that slot?

We computed the exact normalized first-entry weights from `participation_field.Field.rate()` for the baseline and the cutoff-restricted updates used by HS and HE. `Out` and `Doubtful` players are excluded; `Questionable` and unlisted players remain candidates. `HS` means the original snap-count-blended multiplicative field weight (`PLAYER_N0=1` with clipping to 0.02–50); `HE` uses the player's 2026 snap share in earlier active games as the *entry weight*, falling back to historical weight if there are no earlier active games. It is not a new rollout or proposal.

For retrospective Weeks 8 and 9, we compared the resulting one-slot probability distribution to the **observed relative share of all RB/HB/FB offensive player-snaps** in the target team-game, measured from the Week 9 snap-count source. The metric is total-variation distance: `0.5 * sum(abs(first-entry probability - actual relative RB/HB/FB snap share))`. Lower indicates closer distributions.

**These two distributions are not identical quantities.** A first-play RB entry is not a whole-game RB snap-share projection, and changing participation weights may also change later substitution, group choice, carry and target assignment, and score. This is a diagnostic proxy, **not** a calibrated loss for predicted player/game outcomes. No sim seeds were run.

## Corrected results

| Target Week | Graded team-games | Historical field | HS current-snap blend | HE current-season entry |
|---|---:|---:|---:|---:|
| Week 8 | 28 | 0.4043 | 0.3419 | **0.2365** |
| Week 9 | 30 | 0.4462 | 0.3603 | **0.2544** |
| **Pooled, Weeks 8–9** | **58** | **0.4259** | **0.3514** | **0.2458** |

Weeks 1–7 and Week 10 have been supplied. The reproducible script below can score **all 150 snapshots** (Week 10 has no ground-truth Week 10 snap cut, so it produces input-only output for that week). The script has been authored but **was not run end-to-end in this review environment**. The above Week 8/9 results were computed independently by directly reading the source blobs.

The earlier Week 8/9 27-team/29-team calculations were **incomplete**: they omitted players whose raw snap position was `HB`, including Cincinnati. The corrected 28/30-team results above supersede those numbers.

## Confirmed `HB` source-label bug

The 2026 snap-count source uses `HB` for Cincinnati's backs. `snap_update.py` previously declared:

`SNAP_CLASS = {'RB': 'RB', 'FB': 'RB', 'TE': 'TE', 'WR': 'WR'}`

This omitted `HB` from `SnapCounts.class_shares()` and from unmatched skill-snaps coverage counting. Cincinnati has **541 recorded `HB` offensive player-snaps over 8 played games through Week 9**, and 506.096 recorded team snaps. The correct observed RB-class mean is **1.069 player-snaps per offensive team snap**, not **zero**. Before the fix, the current-season **grouping tilt** for Cincinnati effectively received no RB contribution despite its backs playing. This affects personnel grouping, not just reporting.

On this research branch, `SNAP_CLASS` now maps `HB` to `RB`, and `test_snap_update_positions.py` includes synthetic Cincinnati-like tests and a week-cutoff check. **These tests have not been run on the game's server in this review.** The frozen input files were not altered. If snap-count files are rebuilt using the corrected mapping, their hashes and possibly the unmatched skill coverage audit will differ; those changes must be tracked separately.

## Meaningful Week 10 input differences (not accuracy)

The Week 10 snapshots consume `through_week09.json`, with no Week 10 outcome data. Conditional first RB entry in 11 personnel:

| Depth-chart RB1 | Historical | HS | HE |
|---|---:|---:|---:|
| Kenneth Walker III, KC (Questionable) | 1.9% | 52.1% | 70.2% |
| Tyler Allgeier, ARI | 0.4% | 11.7% | 36.0% |
| Rachaad White, WSH | 0.5% | 10.1% | 43.1% |
| Ollie Gordon II, MIA | 10.7% | 35.9% | 36.9% |
| Alvin Kamara, NO | 80.8% | 51.5% | 27.5% |

These are conditional first-entry probabilities, not predicted carries and not game-long snap probabilities. `HE` reorders the most-favored candidate in multiple Week 10 teams. Missing or questionable game-day availability can still invalidate the candidate pool.

## Reproduction

The branch adds:

- `scripts/nfl_sequence/audit_rb_entry_2026.py`: standard-library static auditor that reads all 150 snapshots, the original field, and week-specific prior snap cuts. Weeks 1–9 compare with observed relative RB/HB/FB snaps; Week 10 reports input-only distributions. Prints per-week summaries and optionally writes per-team JSON.
- `scripts/nfl_sequence/test_snap_update_positions.py`: regression tests for the `HB` alias and no use of current-week snaps.
- `scripts/nfl_sequence/snap_update.py`: one-line `HB` class mapping correction.

From the repo root:

```bash
python3 -m unittest scripts/nfl_sequence/test_snap_update_positions.py
python3 scripts/nfl_sequence/audit_rb_entry_2026.py --out /tmp/pbv1_rb_entry_2026.json
```

These are lightweight analyses; they do not invoke the full SLC simulation.

## Next tests before adoption

1. Run the 150-snapshot static auditor and compare per-week totals, especially Weeks 1–7.
2. Verify historical snap-count publication/revision evidence and per-game roster/injury identities. Keep unverified evidence visibly distinct from invalid game results.
3. Fix or explicitly scope the `HB` grouping-tilt defect in any branches whose `snap_update.py` remains unchanged. Rebuild pin hashes if input files change, never silently.
4. Evaluate a controlled entry-weight change with matched, pinned simulation inputs and sufficient seeds. Grade player-game snap shares, carries and targets (including backups), lineup validity, game Brier, and prop Brier. **Do not treat this proxy improvement as a confirmed PBV1 improvement.**
