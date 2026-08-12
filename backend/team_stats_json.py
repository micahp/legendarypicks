"""Read and write `team_game_stats.stats` — the JSON home for per-game team stats.

Why this module exists: team_game_stats was one wide table whose columns encoded
NBA's and NHL's idea of a game. NCAAF filled 5 of ~45 columns and was NULL in the
rest; the next sport would have widened it again. player_game_logs already stores
per-game stats as JSON and takes any league's keys without a DDL change, so team
stats follow it (Micah, 2026-08-11).

The migration is deliberately additive and two-sided:

  * writers populate BOTH the JSON blob and the legacy columns,
  * readers prefer the blob and fall back to the columns.

so that a database migrated at a different time from the code it serves is never
wrong, only redundant. Prod holds nba/nfl/nhl rows written by the old path and is
not migrated by this change; dropping the frozen columns is a separate step that
must not happen until every reader is on `stats` AND prod has been backfilled.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from team_stats_schema import all_stat_keys, stat_keys_for


def stats_to_json(league: str, values: Mapping[str, Any]) -> str:
    """Serialise a league's declared stats to the JSON stored in `stats`.

    Only keys the league DECLARES are written, and only when they carry a value.
    Both halves matter:

      * an undeclared key would make the blob "whatever the publisher sent",
        which is the failure the registry exists to prevent;
      * a None written as JSON null is indistinguishable from a real zero once
        it reaches a table cell, and a dash is not a zero.
    """
    keys = stat_keys_for(league)
    out = {k: values[k] for k in keys if values.get(k) is not None and values.get(k) != ""}
    return json.dumps(out, separators=(",", ":"), sort_keys=True)


def stats_from_row(row: Any) -> dict[str, Any]:
    """Per-game stats for one team_game_stats row, blob first, columns second.

    Accepts anything indexable by column name (sqlite3.Row, dict). Unparseable
    JSON is treated as absent and falls through to the columns rather than
    raising: a malformed blob must not take a page down when the columns that
    predate it are still sitting right there.
    """
    raw = _get(row, "stats")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed:
                return parsed
        except (ValueError, TypeError):
            pass
    return {k: _get(row, k) for k in all_stat_keys() if _get(row, k) is not None}


def _get(row: Any, key: str) -> Optional[Any]:
    """Column lookup that tolerates a row simply not having the column.

    sqlite3.Row raises IndexError for an unknown key, and a database migrated
    later than the code is exactly when that happens — the `stats` column may
    not exist yet. That is absence, not an error.
    """
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return None
