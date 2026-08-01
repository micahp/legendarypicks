#!/usr/bin/env python3
"""Retired NFL season-aggregate writer.

This module used ``nfl_data_py.import_weekly_data`` to derive a second,
zero-filled view of NFL box scores in ``player_stats``. The maintained weekly
artifact now has one owner: ``ingest_nfl_weekly_stats.py`` writes the copied
per-game facts. ``ingest_nfl_season_stats.py`` separately copies nflverse's
published regular-season summary into ``player_stats``.

Keeping two runnable writers let an old command overwrite current aggregates
with different row inclusion, rounding, and null semantics. The public
``ingest_nfl`` name remains as a no-op so stale timers or operator muscle memory
cannot mutate data.
"""

import sys


def ingest_nfl(season: int = 2024) -> int:
    print(
        "ingest_nfl.py is retired; no data written. "
        "Run ingest_nfl_weekly_stats.py and ingest_nfl_season_stats.py."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(ingest_nfl())
