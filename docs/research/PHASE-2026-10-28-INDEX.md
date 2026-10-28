# Phase index, 2026-10-28: forward projections and the holdout baseline

Status: in progress. Nothing pushed. Research only. 2026 is the holdout for every model (user, 2026-10-28). Forward projections are allowed for 2026 games that have not been played yet, issued before kickoff. The baseline never reads a 2026 result.

This index supersedes sections 3, 4, 5 and 9 of `CONTEXT-SUMMARY-LEGENDARY-PICKS-2026-10-28.md` where they conflict. The base is `origin/dev` `382f5ffe`, not local dev.

## The baseline

- Reference: the 2022 to 2025 regular season only (`e1_drive.POOL_SEASONS`). The loaders refuse 2026 (`HOLDOUT_SEASON`).
- Mode: `--context-mode unconditioned`. The pool has no pre-cutoff 2026 games.
- The v1 comparison is off for 2026 targets. It fit v1 on 2026 results.
- Games: 2026 regular-season games whose schedule date is after 2026-10-28. There are 165. The list came from schedule dates only; no score column was read. Games already played are not in the list, because a projection made after the result is not a forward projection.

## The runner

`scripts/nfl_sequence/simulate_pregame_batch.py`:

- `--resume` continues a per-seed ledger, `<out stem>.seeds.jsonl`. Line one pins the inputs (game, as-of, snapshot hash, reference hash, mode). A resume with different inputs is refused. Seeds that errored are simulated again. A partial last line from an interrupted run is dropped.
- `--max-simulation-errors N` stops the run once more than N seeds have errored. Every finished seed stays in the ledger.
- Without `--resume`, an existing ledger is refused (`FileExistsError`), so progress is never overwritten silently.

## Verified in this session

| check | result |
|---|---|
| full sequence suite (`python3 -m pytest -q scripts/nfl_sequence/test_*.py`, repo root) | 326 passed (317 before, 9 added) |
| `test_holdout_2026.py` | 2 passed |
| `test_seed_ledger.py` | 7 passed |
| smoke, `2026_08_CAR_GB`, one seed, as of 2026-10-28T13:45:52Z | 1 valid game; ledger written |
| rerun with `--games 2 --resume` at the same as-of | seed 1 reused, seed 2 simulated; rerun without `--resume` refused |

## Not done

- The 165-game run. One game has been smoke-tested. The next steps are a one-seed smoke over all 165 games, then the 10,000-run projections with `--resume`.
- The team playbooks, the splits model and the role-based decision model are not on `research/lp-event-phase1-2026-10-28`. The forward runs use the E2 statistical model on this branch with the 2022 to 2025 pool. The playbooks are in the Gridiron repo (`97841be`). The splits model is on `origin/research/nfl-historical-splits-2026-10-27`. The role model is not built. None of these is in the projections yet.
- The faster machine is not set up. It needs this branch checked out and a copy of `/root/legendarypicks/backend/data/picks.dev.db` (3.4 GB, read only).
- Open holdout items: baseline section 4, items 3 to 6.

## Decisions for the user

1. In-season updates: may any model use 2026 results from before a cutoff? Under the current rule, no. A 2026 cutoff is refused by the loaders, and `pregame_context` still needs a guard.
2. Which projections count for this run: the E2 statistical model alone, or wait for the playbook and role-based models?
3. Faster machine: host, path, and whether to copy the database there.

## Rules in force

- The 2026 holdout applies to every model. No 2026 result is read for fitting, tuning or comparison.
- No push to `dev` or `main`. Pushing the phase branch needs explicit approval.
- No deploy, no production default change.
- Commits stage named files only.
