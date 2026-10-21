# NHL V3 Phase 1 deterministic replay

Research-only implementation based on the approved full-frame schema at
`33c6b8fad5c36fd7749557c6b56bb21898e33135`.

## Run

From the repository root, the complete command verifies all pinned derived and
official inputs, rehashes every raw PBP and shift body, replays all 4,876 games,
reconciles shift dispositions and TOI, and writes the report:

```sh
/root/legendarypicks/backend/venv/bin/python \
  research/nhl/nhl-v3-phase1-replay-2026-10-21/run_replay.py \
  --report-out research/nhl/nhl-v3-phase1-replay-2026-10-21/REPLAY-REPORT.md
```

Use `--skip-raw-body-verification` only when replaying already hash-verified
normalized ledgers and the raw cache is temporarily unavailable. A report made
with that option is not the full-frame acceptance result. Paths can be supplied
with `--artifacts`, `--official`, `--labels`, `--label-summary`, and `--raw`;
the file pins remain fixed and every supplied copy must match them.

Run the bounded regression and failure-injection suite with:

```sh
/root/legendarypicks/backend/venv/bin/python \
  research/nhl/nhl-v3-phase1-replay-2026-10-21/test_replay_engine.py
```

## Reusable interfaces

- `replay_data.load_bundle()` validates the pinned source artifacts, official
  results, and the approved purpose-aware NHL label reader.
- `replay_data.iter_game_event_groups()` streams events one game at a time in
  source order. It never sorts by event ID or period clock.
- `replay_data.iter_shift_intervals()` preserves each shift row and its
  component disposition; scoring does not consume shift data.
- `replay_model.GameStateMachine` performs deterministic event transitions.
- `prospective.PregameSnapshot` is the future simulator's only feature input;
  it rejects features published after scheduled start.

## Raw data

Raw response bodies remain outside Git at
`/root/lp-data/nhl-fullframe-event-audit-2026-10-21/raw/{pbp,shifts}/`.
The audited normalized ledgers are under
`/root/lp-data/nhl-fullframe-event-audit-2026-10-21/derived/hardened-final/`.
Restore the artifact directory to those paths from the organization's durable
copy, then run the full command above. It checks compressed and decompressed
hashes, byte counts, response sidecars, endpoint/game identity, payload shape,
and row counts before replay. Existing storage/restore notes are in
`../fullframe-event-audit-2026-10-21/STORAGE-AND-REPRODUCIBILITY.md`.

## Scope limits

This replays observed historical events for reconstruction checks. It does not
infer missing events, continuous possession, player movement, or puck tracking.
No probability is fitted or supplied. Phase 2 stochastic component proposals
are in `PHASE2-STOCHASTIC-COMPONENTS.md`.
