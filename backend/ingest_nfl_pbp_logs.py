#!/usr/bin/env python3
"""Retain a curated nflverse play-by-play table for play-level analysis.

Per-player game logs come from ``ingest_nfl_weekly_stats.py``.  This ingest owns
only the additive ``nfl_pbp`` table.

Usage: python3 ingest_nfl_pbp_logs.py [--year 2025]
"""
import os
import sqlite3
import sys


DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)


# A curated query layer, not all 372 source columns and not an archival copy.
# The selection keeps game/play context plus the passing, rushing, receiving,
# lateral, eligibility, and efficiency fields used by play-level analysis.
# nflverse rewrites historical files in place, so retaining the raw artifact
# with a checksum remains a separate concern.
_PLAY_COLS = [
    "game_id", "play_id", "season", "week", "posteam", "defteam",
    "home_team", "away_team", "game_date",
    "qtr", "down", "ydstogo", "yardline_100", "game_seconds_remaining",
    "play_type", "epa", "wpa", "qb_epa", "air_yards", "yards_gained", "cpoe",
    "passer_player_id", "rusher_player_id", "receiver_player_id",
    "pass_location", "run_location", "run_gap", "complete_pass", "touchdown",
    "series", "series_result", "drive", "success", "shotgun",
    "sack", "two_point_attempt",
    "pass_attempt", "rush_attempt", "passing_yards", "rushing_yards",
    "receiving_yards", "pass_touchdown", "rush_touchdown", "interception",
    "lateral_receiver_player_id", "lateral_receiver_player_name",
    "lateral_receiving_yards",
    "lateral_rusher_player_id", "lateral_rusher_player_name",
    "lateral_rushing_yards",
]


def ensure_pbp_table(con: sqlite3.Connection) -> None:
    """Create nfl_pbp (additive, idempotent). One row per play."""
    cols = ", ".join('"{}"'.format(column) for column in _PLAY_COLS)
    con.execute(
        "CREATE TABLE IF NOT EXISTS nfl_pbp ({}, UNIQUE(game_id, play_id))".format(
            cols
        )
    )
    # CREATE TABLE IF NOT EXISTS is a no-op against a table built from an older,
    # shorter _PLAY_COLS, so widen it explicitly.
    have = {row[1] for row in con.execute("PRAGMA table_info(nfl_pbp)")}
    for column in _PLAY_COLS:
        if column not in have:
            con.execute('ALTER TABLE nfl_pbp ADD COLUMN "{}"'.format(column))

    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_pbp_game ON nfl_pbp(game_id, play_id)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_pbp_passer "
        "ON nfl_pbp(passer_player_id, season)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_pbp_rusher "
        "ON nfl_pbp(rusher_player_id, season)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_pbp_receiver "
        "ON nfl_pbp(receiver_player_id, season)"
    )
    con.commit()


def ingest(year: int = 2025) -> int:
    import warnings

    warnings.filterwarnings("ignore")
    import nfl_data_py as nfl

    print("Loading nflverse pbp {}...".format(year))
    frame = nfl.import_pbp_data([year])
    if "season_type" in frame.columns:
        frame = frame[frame["season_type"] == "REG"]
    print("  {} regular-season plays".format(len(frame)))

    missing = sorted(set(_PLAY_COLS) - set(frame.columns))
    if missing:
        # Fail loud rather than silently persisting a narrower table than the
        # readers expect.
        raise RuntimeError(
            "pbp source is missing expected columns: {}".format(missing)
        )

    con = sqlite3.connect(DB)
    ensure_pbp_table(con)
    plays = frame[_PLAY_COLS].astype(object).where(
        frame[_PLAY_COLS].notna(), None
    )
    con.executemany(
        "INSERT OR REPLACE INTO nfl_pbp ({}) VALUES ({})".format(
            ",".join('"{}"'.format(column) for column in _PLAY_COLS),
            ",".join("?" for _ in _PLAY_COLS),
        ),
        plays.itertuples(index=False, name=None),
    )
    con.commit()
    retained = con.execute(
        "SELECT COUNT(*) FROM nfl_pbp WHERE season=?", (year,)
    ).fetchone()[0]
    con.close()
    print("  retained {} plays".format(retained))
    return retained


if __name__ == "__main__":
    selected_year = 2025
    if "--year" in sys.argv:
        selected_year = int(sys.argv[sys.argv.index("--year") + 1])
    ingest(selected_year)
