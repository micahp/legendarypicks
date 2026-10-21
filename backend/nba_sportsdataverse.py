"""Shared schema and helpers for SportsDataverse's NBA Stats releases."""
import json
import sqlite3
from typing import Optional


SOURCE = "sportsdataverse_nba_stats"
PLAYER_ID_SOURCE = "nba.com"
LOGS_TABLE = "player_game_logs_sportsdataverse"
GAMES_TABLE = "nba_sportsdataverse_games"
RELEASES_TABLE = "nba_sportsdataverse_releases"

DDL = (
    """CREATE TABLE IF NOT EXISTS nba_sportsdataverse_releases (
           season INTEGER PRIMARY KEY,
           source_season INTEGER NOT NULL,
           release_hash TEXT NOT NULL,
           boxscore_rows INTEGER NOT NULL,
           boxscore_games INTEGER NOT NULL,
           schedule_rows INTEGER NOT NULL,
           current_release_available INTEGER NOT NULL,
           checked_at TEXT NOT NULL,
           imported_at TEXT NOT NULL
       )""",
    """CREATE TABLE IF NOT EXISTS nba_sportsdataverse_games (
           source_game_id TEXT PRIMARY KEY,
           season INTEGER NOT NULL,
           source_season INTEGER NOT NULL,
           espn_event_id TEXT,
           game_date TEXT NOT NULL,
           home TEXT NOT NULL,
           away TEXT NOT NULL,
           home_score INTEGER NOT NULL,
           away_score INTEGER NOT NULL,
           game_type TEXT NOT NULL,
           release_hash TEXT NOT NULL,
           ingested_at TEXT NOT NULL
       )""",
    """CREATE INDEX IF NOT EXISTS idx_nba_sdv_games_event
       ON nba_sportsdataverse_games(espn_event_id)""",
    """CREATE TABLE IF NOT EXISTS player_game_logs_sportsdataverse (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           player_id INTEGER,
           league TEXT NOT NULL,
           season INTEGER NOT NULL,
           game_no TEXT NOT NULL,
           game_id TEXT,
           source_game_id TEXT NOT NULL,
           game_date TEXT NOT NULL,
           team TEXT NOT NULL,
           opponent TEXT NOT NULL,
           home_away TEXT NOT NULL,
           stats TEXT NOT NULL,
           source TEXT NOT NULL,
           source_player_key TEXT NOT NULL,
           appearance_status TEXT NOT NULL,
           dnp_comment TEXT,
           release_hash TEXT NOT NULL,
           ingested_at TEXT NOT NULL,
           game_type TEXT NOT NULL,
           UNIQUE(league, source_player_key, season, game_no)
       )""",
    """CREATE INDEX IF NOT EXISTS idx_pglsdv_player_date
       ON player_game_logs_sportsdataverse(player_id, game_date)""",
    """CREATE INDEX IF NOT EXISTS idx_pglsdv_league_game
       ON player_game_logs_sportsdataverse(league, game_id)""",
)


NBA_STAT_FIELDS = {
    "PTS": "PTS",
    "REB": "REB",
    "AST": "AST",
    "STL": "STL",
    "BLK": "BLK",
    "TO": "TO",
    "3PM": "3PM",
    "FGM": "FGM",
    "FTM": "FTM",
}

ESPN_STAT_TO_SDV = {
    "PTS": "PTS",
    "REB": "REB",
    "AST": "AST",
    "STL": "STL",
    "BLK": "BLK",
    "TO": "TO",
    "3PM": "3PM",
    "FG:made": "FGM",
    "FT:made": "FTM",
}


def ensure_schema(connection: sqlite3.Connection) -> None:
    """Create only the additive SportsDataverse tables and indexes."""
    for statement in DDL:
        connection.execute(statement)


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def current_source_game(connection: sqlite3.Connection, espn_event_id: str):
    """Return the latest published release's game row for an app event, if present."""
    if not table_exists(connection, GAMES_TABLE) or not table_exists(connection, RELEASES_TABLE):
        return None
    return connection.execute(
        """SELECT g.* FROM nba_sportsdataverse_games g
             JOIN nba_sportsdataverse_releases r
               ON r.season=g.season AND r.release_hash=g.release_hash
            WHERE g.espn_event_id=? ORDER BY g.season DESC LIMIT 1""",
        (str(espn_event_id),),
    ).fetchone()


def current_player_line(connection: sqlite3.Connection, player_id: int,
                        espn_event_id: str):
    """Return a player line only from the active SportsDataverse release."""
    if not table_exists(connection, LOGS_TABLE) or not table_exists(connection, RELEASES_TABLE):
        return None
    return connection.execute(
        """SELECT l.* FROM player_game_logs_sportsdataverse l
             JOIN nba_sportsdataverse_releases r
               ON r.season=l.season AND r.release_hash=l.release_hash
            WHERE l.league='nba' AND l.player_id=? AND l.game_id=?
            ORDER BY l.season DESC LIMIT 1""",
        (int(player_id), str(espn_event_id)),
    ).fetchone()


def value_for_market(stats_json: str, market: str) -> Optional[float]:
    """Read one of the ten supported NBA market values from our normalized JSON."""
    from settlement.market_mapping import resolve_compound_market, resolve_market

    try:
        stats = json.loads(stats_json or "{}")
    except (TypeError, ValueError):
        return None
    mapping = resolve_market("nba", market)
    if mapping is None:
        return None
    category, stat_key = mapping
    if category is None:
        components = resolve_compound_market("nba", market)
        if not components:
            return None
        total = 0.0
        for _component_category, component_key in components:
            normalized = ESPN_STAT_TO_SDV.get(component_key)
            if normalized is None or stats.get(normalized) is None:
                return None
            try:
                total += float(stats[normalized])
            except (TypeError, ValueError):
                return None
        return total
    normalized = ESPN_STAT_TO_SDV.get(stat_key)
    if normalized is None or stats.get(normalized) is None:
        return None
    try:
        return float(stats[normalized])
    except (TypeError, ValueError):
        return None
