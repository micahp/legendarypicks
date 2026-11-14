# SLC release freeze roadmap: V1.5 to V2.0 (2026-11-11)

**Release decision.** Preserve V1.5 as historical evidence; put the three corrected football mechanisms into V1.6, penalties into V1.7, and opponent-adjusted team strength into semantic V2.0. All work stays research-only until its gate passes. This document freezes the SCOPE, not yet the unfinished V1.6 implementation.

## Version ledger

| Version | Status | Owned mechanisms |
| --- | --- | --- |
| V1.5 | Historical control frozen | Existing season-adapted model and saved 121-game ablation. Do not alter or silently regrade saved artifacts. Old label mode must be explicitly set to legacy when reproducing it using later runners. The old producer source commit and model/reference hashes still matter for exact reproduction; a flag does not substitute for the old code. |
| V1.6 | Scope locked, implementation pending A/B/C acceptance | C: dropback sacks/turnovers, corrected A/D/E conditioning, remaining coverage/backoff checks. A: conditional gains and third-down chain progression. B: fourth-down situations versus go/punt/FG decisions. |
| V1.7 | Reserved | Penalty occurrence, disposition, yardage/down/clock enforcement and legal continuation; evaluate independently against V1.6. |
| V2.0 | Reserved | True jointly fitted offense and defense opponent-adjusted strength, conditional pass/run events and gains, downs, sacks/turnovers, and red-zone execution. PR #37 is an early offline prototype, not a complete V2.0 engine. |

Important: the existing CLI flag --slc-v2 names an older experimental lineup/participation/RNG configuration and does NOT mean this future semantic V2.0 strength release. Existing historical V2 research results retain their original names.

## Three bounded V1.6 closeout gates

A. Yardage and third downs: match observed down/distance/field/intent, then score yards and line-to-gain probability, buckets 0/negative/10+/20+, third-down attempts and conversions by distance. Apply only changes that improve out-of-sample scoring. No new modifier merely to raise or lower a team score.

B. Fourth-down situations and decisions: decompose observed opportunity mixture times observed decision policy, observed mixture times simulated policy, simulated mixture times observed policy, and simulated mixture times simulated policy. Correct policy ONLY if observed-context coaching decisions demonstrably fail; otherwise fix the upstream situation distribution.

C. Dropbacks and turnovers: stop conditioning sack occurrence on throw-only A/D/E labels. Use conditional A/D/E among pass attempts, preserve sack fumbles as both sacks and turnovers, exclude unknown-penalty rows, and independently audit coverage and sparse backoff. The isolated historical conditional scores are encouraging, but final full-game behavior and generated label quality need bounded matched checks.

For every gate: record accepted correction, rejected candidate or remaining limitation with an evidence path, game-clustered proper scores and sample sizes. End V1.6 with one frozen chosen code commit, a command/config manifest and bounded paired game grading. Track sacks, turnovers, first downs, fourth downs, TD/FG, carries/targets, teams scoring 0–9 and <=10, games totaling >=60, winner Brier/log loss and score CRPS. Do not indefinitely tune until a particular game score looks right.

V1.7 must be a separate penalty-only experiment. V2.0 must first beat the league situation-cell and the V1.6/1.7 incumbent event models on matched held-out plays, then run a small paired full-game study. New true-strength effects replace, not stack with, legacy global team-event outcome ratios.

## Automatic observational input inventory

Every normal batch invocation with --out now creates a unique .inputs.<UTC>-<nanoseconds>.json beside the output. It records at start and end: explicit source file paths, availability, file size, modification UTC time/nanoseconds, code Git HEAD, requested expected hashes, and SHA-256 of files up to 32 MiB. Larger DB/Parquet sources record their size and timestamp without an expensive mandatory full hash. Changed paths are marked clearly. After a successful run, the same sidecar copies the authoritative model ID, configuration hash, reference hash, snapshot hash, source cutoff, and integration-code hashes from the completed simulator payload. This distinguishes OS-level file observations from model inputs actually resolved by the engine.

This log is NOT part of RNG or model reference identity. A live database changing does not fail the inventory or require the user to manually align hashes. An actual paired causal experiment may still require a stable source snapshot, and current *model-specific required hashes / source preflight* are not bypassed.

An input modification timestamp is not its publication time; a skipped large SHA-256 is not an assertion of byte-identical reproducibility. Old runs preserve their original observed hashes. Each attempt/resume gets a separate sidecar, so failure before seed generation remains visible.

To protect V1.5, the batch runner and direct engine now default to legacy pass-label handling again. V1.6 candidate runs must request --playcall-pass-label-mode conditional explicitly until the model is versioned and frozen. The existing auto alias remains available when deliberately selected. Neither the historical V1.5 data nor live simulation defaults are silently relabeled as an accepted V1.6.

Tests: python3 -m unittest discover -s scripts/nfl_sequence -p test_run_input_inventory.py -v
