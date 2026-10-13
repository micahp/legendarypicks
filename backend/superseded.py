#!/usr/bin/env python3
"""superseded.py: work that has already been done, in a form that cannot be forgotten.

THE TRAP THIS EXISTS TO CLOSE.

On 2026-08-24 someone measured that five per-league dedupers each silently orphaned rows,
wrote `spine_merge.py` as one generic replacement that discovers referencing columns from the
schema, and recorded all of it in a context summary.

None of that stopped the trap. Three weeks later:

  - The five superseded scripts were still present and still runnable.
  - `AGENTS.md` still told every agent "Cleanup: dedupe_mlb.py / dedupe_nfl.py".
  - `spine_merge.py` was referenced by no unit, no cron and no runner.
  - 129 orphaned references sat on prod and 98 on dev, and one of them
    (`player_id=33312`) aborted an MLS log migration with a KeyError while 10,574
    real rows went unmigrated.
  - And on 2026-09-06 a session wrote `player_merge.py`, a worse copy of
    `spine_merge.py`, because it never found the original. It was deleted the moment
    the context summary was read.

A summary is a record, not a guardrail. It only works if the next person reads the right one
of 87 files before touching the right one of 12 scripts. This is the same shape as an ingest
that exists but is scheduled by nothing: the knowledge was never the missing part.

WHAT THIS DOES INSTEAD. Every superseded entry refuses at the moment of the mistake and names
its replacement. Running `dedupe_mlb.py` now prints why it was replaced and exits non-zero,
so the trap springs on the person walking into it rather than on the data.

ADDING AN ENTRY IS THE LAST STEP OF REPLACING SOMETHING. If it feels like paperwork, compare
it to spending an afternoon rebuilding a tool that already existed.
"""
import sys
from typing import Dict, NamedTuple


class Superseded(NamedTuple):
    replacement: str
    on: str
    why: str


# module or script name -> what replaced it.
REGISTRY: Dict[str, Superseded] = {
    "dedupe_mlb": Superseded(
        replacement="spine_merge.py",
        on="2026-08-24",
        why=("touches 5 of the 14 tables carrying a player_id, so it orphans the rest "
             "silently; only 5 of those 14 declare a foreign key. It also calls a shared "
             "mlbam_id 'provably the same person', and 124 of 317 duplicate groups were two "
             "different people"),
    ),
    "dedupe_nfl": Superseded(
        replacement="spine_merge.py",
        on="2026-08-24",
        why=("touches 3 of the 14 tables carrying a player_id and misses all EIGHT nfl_* "
             "tables, so it orphans them silently"),
    ),
    "merge_mls_prop_players": Superseded(
        replacement="spine_merge.py",
        on="2026-08-24",
        why="touches 1 of the 14 tables carrying a player_id",
    ),
}


def refuse(name: str) -> None:
    """Exit non-zero, naming the replacement. Call this first in a superseded script.

    Deliberately fatal rather than a warning. A warning on a repair script is read after the
    repair has already run, which is exactly too late for a merge that deletes rows.

    Fatal only when the script is being RUN, though. Refusing an IMPORT refuses far more than
    the repair: `test_mlb_identity_invariants.py` imports `pick_canonical` from `dedupe_mlb`
    to assert the invariant still holds, and a SystemExit at import time took down pytest
    COLLECTION, so the entire backend suite stopped running rather than one script. The
    danger being guarded against is executing a merge that deletes rows, and an import does
    not do that. An importer still gets the notice on stderr.
    """
    entry = REGISTRY.get(name)
    if entry is None:
        return
    caller = sys._getframe(1).f_globals.get("__name__")
    print(
        "REFUSED: {name} was superseded by {repl} on {on}.\n"
        "  why: {why}.\n"
        "  {repl} discovers every referencing column from the schema each run, so it cannot\n"
        "  miss a table that was added later. Use it instead:\n"
        "      venv/bin/python spine_merge.py --help\n"
        "  If you genuinely need the old behaviour, read it in git history rather than\n"
        "  running it: git show HEAD:backend/{name}.py".format(
            name=name, repl=entry.replacement, on=entry.on, why=entry.why),
        file=sys.stderr)
    if caller == "__main__":
        raise SystemExit(2)
