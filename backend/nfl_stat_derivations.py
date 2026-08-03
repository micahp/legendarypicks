"""Per-game NFL values that are computed, not published — defined exactly once.

`ingest_nfl_weekly_stats.py` is a mapping and stores nflverse's columns
unchanged. Anything that needs arithmetic to become a fantasy-facing number
lives here, and every surface that renders it imports from here.

The rule is not stylistic. The mock-draft router already carries the scar:
"recomputing them here would be a second implementation of the same number,
which is how the board and the pool ended up printing different figures for the
same player." Two callers rendering Misc TD from two sums is that failure again.
"""
from __future__ import annotations

from typing import Optional


def misc_td(stats: dict) -> Optional[int]:
    """ESPN's Misc TD: touchdowns that are neither rushing nor receiving.

    The two published components are disjoint in the artifact — no 2025
    player-week carries both — so this is an addition, not a union.

    `pt_return_tds` is deliberately excluded. It sits in nflverse's punting
    namespace and counts punt-return touchdowns *allowed*: every nonzero 2025 row
    belongs to a punter. Summing it would credit a punter with a touchdown he
    surrendered.
    """
    parts = [stats.get("st_td"), stats.get("fum_rec_td")]
    if all(part is None for part in parts):
        # Never measured is not zero. A row from an ingest that predates the
        # Misc block must not read as "he scored none".
        return None
    return sum(part or 0 for part in parts)


#: field name -> deriving function. Anything absent is read straight off the row.
DERIVED = {"misc_td": misc_td}


def with_derived(stats: dict) -> dict:
    """`stats` plus every derived field whose inputs are present."""
    out = dict(stats)
    for name, fn in DERIVED.items():
        value = fn(stats)
        if value is not None:
            out[name] = value
    return out
