# V1 Complete Thanksgiving regression repair candidate — 2026-11-27

Baseline: LP `41680940cb61749dd91c4e04ba374a9df8952600`, Gridiron `f1adc6777fa415abf72c29df96ca2e3c7d90b942`, evidence [72ea3e69](https://github.com/micahp/legendarypicks/tree/72ea3e69/docs/research/week12-thanksgiving-blackfriday-slc-2026). 265/300 valid, 35 failures; no replaced seeds. Candidate Grid `0cd3c4bde29f2f1ddd8778313bfd34b9000bcf26`. No forecast readiness or promotion claim.

- Physical/statistical field spots: preserve measured coordinates and signed displacement, project end-zone geometry only at the statistical boundary. Interior spots cannot round to scoring boundaries. Reject coordinates beyond the end lines. Gridiron and LP use matching projection.
- Kick returns: use actual catch/recovery location; preserve the dead-ball location separately from restart and return yards. Held returner leaving sideline must not be treated as an untouched illegal kickoff. Guard generic missed-kick termination from live blocked-FG handling. Unrecovered loose blocked kicks exiting the field remain a named unsupported rule case, never fabricated recovery.
- Defensive touchback: separate actual possession acquisition, field exit and scoring evidence; correct own-20 restart to 80 yards to opponent goal. Unresolved impetus/momentum cases remain blocked. No safety inferred from integer rounding.
- Goal-line dead balls: do not promote an interior rounded spot to a score. Explicit touchback and goal-line events retained. Correct special midfield kickoff touchback restart.
- Blocked FG: preserve live play terminal separately from period-ending terminal. Accept period expiration only with matching quarter/clock/possession and actual legal live transition.
- Live time and progress: original 12s pre-possession deadline; 36s maximum for live return/recovery with rolling displacement, possession/phase changes and real tackle lifecycle. Slow movement is not a stall. No synthetic whistle at deadline. Shared progress tracker also used in run executor; pass attempts use existing run-style contact reach. Contact behavior and distribution changes require regression testing.

## Exact regression evidence

Nine exact play calls were extracted from the full `replay_diagnostic` strings in the published summary JSON (six pass caps and three run no-progress). They are stored with source pin, game IDs and seed IDs in Grid `test/fixtures/thanksgiving-2026-live-failures.json`. All 26 other failed-seed call records must be recovered from the hash-pinned host archives; summaries contain reasons but not full calls. Preserve original game seeds and snapshot SHA256.

Run, using clean pinned checkouts and the approved host environment after resource checks:
```sh
# Gridiron
node test/thanksgiving-2026-regression.mjs
npm run test:autonomous
# LP
cd scripts/nfl_sequence
python -m unittest test_thanksgiving_runtime_repair test_autonomous_game test_event_expansion_rules
```

Do not interpret focused tests as full-game validity. Next acceptance: reproduce the nine original failures on the baseline, replay on candidate, extract/replay all other failed calls with original engine and state, run exact 35 full-game seeds plus controls, then original 300-game cohort and preregistered holdout. Compare legality, score/possession/stat reconciliation, and distributions without changing model assumptions. Any remaining missing facts or invalid seeds are blockers. No archive deletion, host jobs or production changes were performed here.
