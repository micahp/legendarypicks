"""The game-id vocabulary boundary: nflverse keys vs ESPN event ids.

Sibling of `season_keys.py` (season vocabulary) and `team_codes.py` (team
vocabulary), and it exists for the same reason. A wrong season key does not
raise — it misses. A wrong GAME key does something worse: it inserts, and the
season silently doubles.

NFL 2024 and 2026 are keyed nflverse-style (`2024_01_BAL_KC`); 2025 is keyed by
ESPN event id. `team_game_results` has PRIMARY KEY(league, game_id, team), so an
ESPN-keyed write lands BESIDE the nflverse row for the same game rather than
over it: a 2024 run took the season from 285 games to 557 while printing
"wrote 272 games". The row count was true and the claim it implied was false.

The discriminator is the underscore: nflverse keys are underscore-delimited,
ESPN event ids are pure digits. That is a measured shape difference, not a
guess — the two vocabularies that have ever existed in these tables.

Every writer of a game_id-keyed table must call `guard_game_id_vocabulary()`
before writing, so the refusal lives in one place instead of N scripts. A guard
copied into N scripts is N places to forget it — that is the entire lesson of
the doubling bug.
"""

from __future__ import annotations

import sqlite3


def foreign_game_ids(con: sqlite3.Connection, league: str, season=None,
                     table: str = "team_game_results") -> list[str]:
    """Distinct game_ids in (league[, season]) that use another vocabulary.

    `season` is optional because team_game_stats — which shares game_id with
    team_game_results — has no season column; a league-scoped call is the same
    check over the whole league.
    """
    if season is None:
        rows = con.execute(
            f"SELECT DISTINCT game_id FROM {table} WHERE league=?", (league,)).fetchall()
    else:
        rows = con.execute(
            f"SELECT DISTINCT game_id FROM {table} WHERE league=? AND season=?",
            (league, season)).fetchall()
    return [g for (g,) in rows if "_" in str(g)]


def guard_game_id_vocabulary(con: sqlite3.Connection, league: str, season=None, *,
                             replace_vocabulary: bool = False,
                             dry_run: bool = False,
                             table: str = "team_game_results") -> int:
    """Refuse to write into (league[, season]) when it holds foreign-keyed rows.

    Compare before writing, not after: an INSERT OR REPLACE keys on
    (league, game_id, team), so a wrong-keyed write does not raise — it lands
    beside the rows it should have replaced, and the season silently doubles.

    Returns 0 when it is safe to write, 1 when refusing. With
    --replace-vocabulary (and not dry_run) the foreign rows are deleted first:
    migrating a vocabulary is a delete-then-write decision, never a side effect
    of a backfill.
    """
    foreign = foreign_game_ids(con, league, season, table)
    scope = f"{league} {season}" if season is not None else league
    if foreign and not replace_vocabulary:
        print(f"  REFUSING to write: {scope} already holds {len(foreign)} games "
              f"keyed in another vocabulary (e.g. {foreign[0]!r}), and ESPN event ids "
              f"would land beside them, not over them.")
        print("  Migrate the season deliberately with --replace-vocabulary, or leave it.")
        return 1
    if foreign and replace_vocabulary and not dry_run:
        if season is None:
            gone = con.execute(
                f"DELETE FROM {table} WHERE league=? AND game_id LIKE '%!_%' ESCAPE '!'",
                (league,)).rowcount
        else:
            gone = con.execute(
                f"DELETE FROM {table} WHERE league=? AND season=?"
                " AND game_id LIKE '%!_%' ESCAPE '!'", (league, season)).rowcount
        con.commit()
        print(f"  --replace-vocabulary: dropped {gone} rows over {len(foreign)} "
              f"foreign-keyed games before writing")
    return 0
