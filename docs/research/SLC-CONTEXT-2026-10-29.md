# SLC context summary, 2026-10-29

Research branch: `research/slc-decision-layer-2026-10-29` (pushed through `94260513`; later commits listed below). Snapshot used
throughout: `2026_08_CAR_GB` (Week 8 2026), 100 seeds per arm, valid full games only, paired by seed. 2026 outcomes not used anywhere.

## Working rules set this session

- Tests first (red), then the code that makes them green.
- Push findings for review. Do not act on a finding without the user's review.
- The playbook layer is required by the user. Whether it is a separate input (versus carried by the decision labels) is for review.
- No em dashes in docs.

## What is done

- **Decision model categories A to N as labels.** `decision_layer.py`. Calibrated to the decision model's own 2025 counts for all 14
  categories (test: `DatabaseCalibration`). Positions come from the nflverse players release, the decision model's source.
- **Labels reach the pre-event choice and the outcome.** Receiver role (A) and carrier role (B) are drawn from the team prior. Outcome
  lifts are taken against the labelled rows' own mix. A row filter draws the sampled row from label-matched rows, with fallback.
- **Trick plays.** A non-QB throws and a QB catches at measured rates (63 of 35,293 passes; 17 of 33,802 targets, 2024 and 2025).
  A receiver is always a different player from the passer. Invariants pinned in `test_participant_invariants.py`.
- **Receiver and carrier shares.** `share_distributions.py`: one Dirichlet draw of shares per game, concentration fitted on the prior
  season (median about 17). Wired behind `--playcall-dirichlet-shares` (off by default). Tests green.
- **Playbook input.** `playbook_prior.py`: pass depth, pass location and run gap from the 2025 playbook files, replacing the decision
  draw for those categories where the playbook has a prior (fallback recorded). Behind `--playcall-playbook`, which needs
  `--playcall-decision`. Tests green. Three-game smoke run: 3 of 3 valid.
- **QB-opportunity validation check.** `qb_opportunity_check.py`, validation only (not an input).
- **Playbook cross-check.** `playbook_crosscheck.py`: 96 of 96 team-category pairs agree (2025) once `LA` and `WAS` are mapped to
  `LAR` and `WSH`.
- **Model card and notes.** `SLC-MODEL-CARD-2026-10-29.md`, `SLC-DECISION-LAYER-UPLIFT-2026-10-29.md`,
  `SLC-YARDS-REPLAY-2024-2026-10-29.md`, `SLC-REVIEW-FINDINGS-2026-10-29.md`, and the matched-seed note (updated).
- **LP model cards.** Refresh sections added on local branch `docs/model-cards-refresh-2026-10-28` (`45037686`). Not pushed.

## Matched arms, CAR-GB, 100 seeds, valid games

| arm | total | margin | paired vs base |
|---|---:|---:|---|
| score_clock_v2 | 39.99 | -0.43 | base |
| shares_v2 (player shares) | 39.99 | -0.43 | identical to base |
| dirichlet_v1 (player shares, per-game shares) | 39.99 | -0.43 | identical to shares_v2 (99 paired) |
| decision_unfiltered (lifts only) | 43.29 | -3.52 | total +3.68 ± 1.63 vs shares |
| decision_v3 (lifts and row filter) | 50.24 | +2.60 | total +10.36 ± 1.68 vs shares |
| target_roles_v2 | 39.99 | -0.43 | identical to base |
| streak team, individual buckets | | | margin -0.49 ± 0.72 |
| streak league, individual buckets | | | margin +1.73 ± 1.60 |
| coverage, 300 seeds | | | margin +0.74 ± 0.97, total +1.26 ± 0.98 |

Real regular-season totals: 45.82 (2024) and 46.03 (2025). Home margin 1.87 and 2.07.

Reading: dropbacks, runs and the QB or receiver identity change credit, not points, unless they also condition the outcome. The row
filter accounts for +6.39 ± 1.78 of the decision layer's +10.36 total uplift. The filtered layer overshoots the real total by about four.

## Measured, recorded for review

1. **Row filter (20 seeds).** Same charted seasons in both arms, and the same event mix. Outcomes differ within buckets: completions
   20-49 touchdown 0.074 with the filter, 0.032 without, and yards 12.4 against 10.1. Hypothesis: label-matched rows carry higher-yield
   outcomes. Untested by category.
2. **Simulated pace about 10 percent high.** Against 2025: dropbacks +9.0 percent, runs +11.6, scrimmage plays +10.2. Pass share 0.563
   against 0.569. The excess is in total plays, and score-clock SLC has it without the decision layer, so it sits in the clock and drive
   model.
3. **Red-zone yardage gap, unchanged.** Replay against 2024, matched plays: pass 1-19 yards 0.52 against 3.78 actual; run 1-19 0.69 against
   2.80.

## Open, and why

- **Row-filter default.** Left on. Review. The lift-only layer is nearer the real total and is the recommendation.
- **Playbook as the default input.** Built, off by default. The matched arm is not yet run. Review: the playbook files and the decision
  labels describe the same plays, so this may change nothing.
- **Red-zone fix.** Not made. It is an engine change that acts on finding 3, so it waits for review.
- **Pace.** Not investigated beyond the measurement above. Waits for review.

## Next steps

1. Run the two matched arms for the playbook input (`decision` with player shares, and the same with `--playcall-playbook`), 100 seeds
   each, on the current code.
2. Commit and push the playbook input (`playbook_prior.py`, its tests, and the plumbing). These files are not yet committed.
3. Review the findings and decide the three defaults above.

## Commits on the SLC branch today

`35e7d864`, `0eae58b5`, `5437ad7d`, `18ddc892`, `94260513`, `ddc289cd`, `2bb41d30`, `7d66f989`, `b7bad9bb`, plus the uncommitted
playbook work.
