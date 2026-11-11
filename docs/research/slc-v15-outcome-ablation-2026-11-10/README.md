# V1.5 outcome-layer ablation

Regraded on 2026-11-11 from the completed fast-host worker artifacts. No simulations were rerun.

## Results

Each matchup has 20 paired seeds, with the `team_offense_defense_outcomes` layer disabled in the ablation arm. All 20 pairs in each matchup passed full-game validation and box-score reconciliation. There were no seed errors.

| Matchup | Control points (away / home) | Ablation points (away / home) | Seeds |
| --- | ---: | ---: | ---: |
| MIN–NO | MIN 19.55 / NO 18.80 | MIN 20.05 / NO 20.00 | 20/20 valid |
| SEA–DEN | SEA 19.00 / DEN 19.00 | SEA 20.80 / DEN 20.05 | 20/20 valid |
| DEN–ARI | DEN 20.15 / ARI 22.65 | DEN 19.00 / ARI 23.65 | 20/20 valid |

These are small exploratory samples. They do not establish a general scoring effect or support a production change.

## Provenance

- Simulation code commit recorded in each run manifest: `67d3f552` (`Support paired V1.5 historical outcome ablations`).
- Report grader: commit `b67ce23b` (`Preserve player role variation in paired reports`), cherry-picked onto the current `slc-v2` branch.
- RNG protocol: v2; same paired seed roots within each control/ablation comparison.
- Seeds: 2–21 for each matchup.
- Input snapshots, model artifacts, frozen database identity, worker outputs, seed ledgers, and box-score exports are SHA-256 recorded in each JSON report. The large raw worker files remain on the fast host.
- The original failed grader logs are preserved with the fast-host run. The reports below were generated as separate `reprocessed-b67ce23b` artifacts; original worker outputs and manifests were not changed.

## Reports

- [MIN–NO paired report](MIN-NO.json)
- [SEA–DEN paired report](SEA-DEN.json)
- [DEN–ARI paired report](DEN-ARI.json)
- [Reprocessing summary](REPROCESSED-SUMMARY.json)

The report fix treats a player’s stable ID, name, and team as identity. It records observed positions by arm, because a player can appear under a special-teams position in one box score and a standard position in another. This preserves role changes without rejecting otherwise matching rosters.
