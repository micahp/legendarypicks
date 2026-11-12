# V1.6 V2 infrastructure port: preclassified historical outcomes and diagnostics

## Scope

This ports the parts of the V2 operational infrastructure that were missing in V1.6.
It does **not** port V2 strength, sack-mass substitution, player workload, or experimental
transition probabilities. V1.5 is frozen on its own branch and remains unchanged.

The five V2 blocker fixes were already on by default in V1.6 as of `6b1c22ab`.
This work preserves the run/scramble backoff policy and its selected intent.

## One-time historical preprocessing (outside simulation)

From repository root, using the **same pinned database** as the simulation:

```bash
python3 scripts/nfl_sequence/slc_materialized_history.py build \
  --db /path/to/pinned-nfl.sqlite \
  --out ~/.cache/legendarypicks/slc-history.sqlite

python3 scripts/nfl_sequence/slc_materialized_history.py inspect \
  --out ~/.cache/legendarypicks/slc-history.sqlite
```

The new SQLite artifact contains the original historical row payload, all four
legacy classification variants (scrambles enabled/disabled × separate sack-fumbles
enabled/disabled), exclusion reasons, and the five V2 backoff support levels
(exact cell; down+field; down+distance; field zone; league intent).
The artifact is prepared before the run and kept separate from the source DB.

When an ingested game changes, update that game's materialized rows and support
index instead of classifying every historical game again. Only use the incremental
command if the game is the **only** source-data change:

```bash
python3 scripts/nfl_sequence/slc_materialized_history.py refresh-game \
  --db /path/to/pinned-nfl.sqlite \
  --out ~/.cache/legendarypicks/slc-history.sqlite \
  --game-id 2025_01_ARI_DAL --only-this-game-changed
```

Otherwise rebuild from the updated source with `build --replace`. A metadata
mismatch in database file state, classifier code, or artifact schema fails closed.

## Simulation usage

For the named `v1_6_candidate` profile, the batch CLI defaults to
`~/.cache/legendarypicks/slc-history.sqlite`. It **refuses to simulate** if
that file does not exist, and prints the preprocessing command. It no longer
silently invokes `e1.classify()` to construct a missing source artifact.

Explicit path:

```
--slc-profile v1_6_candidate \
--slc-materialized-history /path/to/slc-history.sqlite
```

Only for a controlled old/new parity run:

```
--slc-profile v1_6_candidate --slc-legacy-history-build
```

Do not use the legacy option for normal V1.6 runs. The old E1 classifier
is retained strictly as a parity oracle and explicit rebuild tool.

## V2 diagnostics

`--trace-outcome-probabilities` stores per-play event probabilities at each
active conditional weighting stage in the seed ledger, including first/second
down sacks, selected historical backoff, and pass-label group selection.
Tracing is opt-in and must not consume any RNG draws.

Invalid simulation seeds automatically write immutable gzip files under
`<out stem>.failures/`, with their failure envelope, seed, pinned
snapshot identity, paired input root, and any available ordered game record.

The prebuilt hierarchical support index is queried when the V1.6 materialized
artifact is enabled. Candidate IDs are mapped back to annotated, cutoff-safe
source rows and restored to their original pool order; dynamic participant and
scramble eligibility filters still apply at selection time.

## Verification and freeze criteria

Focused tests:

```bash
python3 -m unittest discover -s scripts/nfl_sequence -p 'test_slc_materialized_history.py'
python3 -m unittest discover -s scripts/nfl_sequence -p 'test_slc_failure_capture.py'
python3 -m unittest discover -s scripts/nfl_sequence -p 'test_slc_playcall.py'
```

Required on the pinned 3.97 GB snapshot before freeze:

1. Run a complete cold materialization and record its time and size separately
   from game simulation.
2. Compare materialized versus `--slc-legacy-history-build` with identical
   cutoffs, options, sources and seeds. Require identical source row selection,
   classified outcomes, exclusions, candidate ordering, game validity and
   sampled game records.
3. Compare total reference-build wall time and peak RSS cold/warm. A mere
   reduction in `classify()` calls is not evidence of a faster whole setup.
4. Reproduce ARI–DAL's original seed-1 sparse fourth-down cell with all five
   blocker fixes enabled; confirm backoff retains selected run when eligible
   broader support exists, and records any last-resort guard redirection.
5. Confirm sampling probabilities, game-winner Brier, third-down and
   fourth-down-short distributions. The classification move and diagnostics
   are **infrastructure**, not evidence of improved calibration.

This was implemented from repository inspection without running the pinned
historical database here. Do not mark any of those checks passed until run
artifacts exist.
