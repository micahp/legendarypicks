# V1.7 WAS–NYG: repair the 47 excluded seeds and the full-game validity flag

**Source:** Original frozen 1,000-seed `v1.7-1000-pr43` experiment, preserved
under `research/was-nyg-player-projection-replay-2026-11-13`, commit `8b68ae90`.
Original result: **953 mechanically completed**, **47 distinct excluded**,
**0/1,000 `valid_full_game`**. Never overwrite the original experiment.

## Reproduced failure families

These were identified by inspecting all 47 pinned error envelopes from
`v1.7-1000-pr43-errors.jsonl.gz`, not guessed from aggregate counts:

| Family | Seeds | Changes |
|---|---:|---|
| Fractional receiving spot after missed FG | 30 | Preserve fractional spot and validate original source and expected adjustment |
| Goal-to-go floating-point epsilon | 3 | Derive goal-to-go from field position after penalty; keep strict reducer |
| Team vs player stat accounting | 10 | Credit whole-yard statistics on each play, identically to player and team; reject genuine mismatches |
| Nullified penalty inside a blocked-attempt decision trace | 3 | Verify the matched original decision and accepted nullification; no play statistics permitted |
| Accepted roughing on possession-changing fourth-down completion | 1 | Enforce at end of run in original offense coordinates, award automatic first, undo turnover-on-downs |

These 47 are the complete preserved error set. **Focused unit tests are NOT
a replacement for replaying the exact 47 seeds on the fast host**.

## Two distinct validity claims

- `valid_full_game` means the simulated game is complete, on a verified
  frozen input snapshot, has no active unsupported transition or blocker, and
  independently passes football/game-state checks. It no longer depends on
  whether the penalty *probability model* has been calibrated for release.
- `forecast_release_validated` means a mechanically valid game is ALSO
  eligible for forecast distribution publication. **For V1.7 research-only
  penalty rulings, this remains false**. `research_only_penalty_model` remains
  true. The batch aggregate reports both counts, and its release distribution
  excludes these games even if mechanically valid.
- The immutable run registry always marks the V1.7 research profile
  `exploratory`. Research-only box scores are not counted as published-valid
  player/score distributions. No V1.6 files or model parameters were changed.

## Run the exact failed seeds on the fast host

The original exact seed list is **[`failed-seeds.json`](./failed-seeds.json)**.
It can be supplied to the existing simulator's `--seed-list-file` CLI option.

Use the **same complete model, play-call, source, and snapshot options as the
original V1.7 1,000-seed run**; only switch to this fix branch's code, add
`--seed-list-file`, change `--games` to 47, and use a **NEW, EMPTY output
directory**. Ensure the model/source/snapshot hashes match the original
manifest; fail closed if they do not. The original production command cannot
be reconstructed solely from these saved results, so do not guess file paths
or omit the fitted penalty model, finalized snapshot, or source manifests.

The two extra flags to substitute into the original run command are:

```bash
--seed-list-file docs/research/slc-v17-failure-repairs-2026-11-13/failed-seeds.json \
--games 47
```

Run the strict saved-result verifier after the new 47-seed run:

```bash
PYTHONPATH=scripts/nfl_sequence python \
  scripts/nfl_sequence/verify_v17_seed_repairs.py \
  --failed-seeds docs/research/slc-v17-failure-repairs-2026-11-13/failed-seeds.json \
  --replay-report /path/to/NEW-v17-repair-47.json \
  --audit-out /path/to/NEW-v17-repair-47-audit.json
```

The command exits **nonzero** if even one of the 47 is still incomplete,
invalid, blocked, errored, or incorrectly release-validated. It also rejects
the wrong game, wrong profile, wrong seed count or missing seeds. Preserve
per-seed errors, ledger, new code/config hash and new audit artifact.

**Next gate**: after the 47/47 check passes, execute a clean **new** 1,000-seed
run on the same frozen inputs and new code. Do not mix the new batch with
old `v1.7-1000-pr43` records or reclassify that original artifact.
Run the usual independent validator and compare score and prop distributions
without treating one game as proof of predictive superiority.

The penalty-rule probabilities, foul acceptance/elections, kick-specific
denominators and other incomplete NFL-rule cases remain **research-only**.
