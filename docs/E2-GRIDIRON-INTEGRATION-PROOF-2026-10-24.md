# E2 Gridiron integration proof (2026-10-24)

What was run, against what, and what it showed. Nothing in the Gridiron repository was changed. Its adapter was imported
read-only, from a `git archive` of its committed tree and from its working tree, and both gave the same results.

## Pins

- LP base commit for the envelope: `1ca7560924fe` (full SHA in `docs/fixtures/e2/e2-game-envelope-seed1.json`).
- Gridiron adapter: `/root/gridiron-e2-game-viewer` HEAD `854cea5` (committed tree, extracted with `git archive`). This is
  the older pin, kept for the record.
- Gridiron integration references, pushed and re-run on 2026-10-24: `research/gridiron-e2-game-viewer-2026-10-24` at
  `de64ae12` (remote `de64ae1`), and `research/gridiron-e3-physical-timing-2026-10-24` at `13b18faa` (remote `13b18fa`). Both
  heads ship `web/lp-game-record-adapter.js`. Results: `docs/evidence/e2/gridiron-adapter-proof-de64ae12.json` and
  `...-13b18faa.json`, produced by `scripts/nfl_sequence/evidence_e2/gridiron_adapter_proof.mjs`. Both accept the envelope
  (143 plays, 24 drives, A 14, B 10, 0 football-state findings), with the same 8 record-level and 6 v1-document violations as
  above. At `de64ae12` the repository's own `test/lp-game-record-adapter.mjs` also passes.
- Fixture manifest: `docs/fixtures/e2/MANIFEST.json`.

## Inputs

- LP envelope: `docs/fixtures/e2/e2-game-envelope-seed1.json`, pinned to `1ca7560924fe`. Contract `gridiron.lp-full-game-payload` 1.0.0, wrapping the
  unaltered LP engine record for seed 1 (`docs/fixtures/e2/e2-game-seed1.json`). 24 drives, 143 plays.
- LP shared v1 document: `docs/fixtures/e2/e2-game-seed1.v1.json`, produced by `scripts/nfl_sequence/shared_v1.py` from the
  same record.
- Gridiron adapter: `web/lp-game-record-adapter.js` in `/root/gridiron-e2-game-viewer`.
  - HEAD `854cea5`, extracted with `git archive HEAD` into the scratchpad (committed version);
  - the working tree of the same repository, which has eight modified files and several untracked files from another
    session. The adapter file itself is modified in the working tree.

## Runs

```
node run_head_adapter.mjs e2_envelope_seed1.json e2-game-seed1.v1.json
```

Results, committed tree (HEAD `854cea5`):

- `adaptLpGamePayload(envelope)`: accepted. Source play count 143, 24 drives, `validation.passed = true`, 0 findings.
- Record-level `auditGridironContractV1Record(record)` (the engine record in the envelope): 8 violations: mode, stable game
  id, model version, rules version, as-of time, real home/away identities, roster snapshot, `valid_full_game`.
- Shared v1 document `auditGridironContractV1Record(document)`: 6 violations: mode, stable game id, as-of time, real
  home/away identities, roster snapshot, `valid_full_game`.

The working-tree adapter gives the same two audits (the earlier run against it).

## What the adapter checks that this proof therefore covers

- the envelope contract name and version;
- the source fields (repository, branch, `producer_worktree_dirty` as a boolean, producer file hashes);
- the record's drive structure, the drive-index audit (the 23 mismatches the adapter test pinned against the older LP record are
  absent from this record), and the football-state audit;
- the shared-v1 audit, reported in full above.

## Gaps this proof does not close

- The six shared-v1 violations (mode, game id, as-of time, real team identities, roster snapshot, `valid_full_game`) are
  genuine: this record is an authored hypothetical, not a pregame simulation, and `valid_full_game` is false by design.
- `duration_seconds` is null on every play. The Gridiron audit does not check it; the LP checker does.
- The envelope's `producer_worktree_dirty` is recorded as `false` only for the committed producer state. The producer files are
  pinned by SHA-256 in the envelope.
- The Gridiron repository's own adapter test (`test/lp-game-record-adapter.mjs`) pins the older LP record and asserts that it is
  rejected. That test is not run here, because it is a fixture pin in another session's uncommitted work. The adapter accepts
  the current record.
