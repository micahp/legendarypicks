"""Shared fail-closed source-identity primitives for published prop feeds."""
import datetime as dt
import re
import sqlite3
import unicodedata
from typing import Optional


class SourceIdentityConflict(RuntimeError):
    """A supposedly stable publisher identifier would identify a new canonical row."""


def normalize_name(value: str) -> str:
    """Canonical/alias normalization without fuzzy matching."""
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", value.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", value)).strip()


def ensure_source_identity_schema(con: sqlite3.Connection) -> None:
    """Install additive source-key tables; display strings are never source IDs."""
    con.executescript("""
        CREATE TABLE IF NOT EXISTS player_source_ids(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL, league TEXT NOT NULL,
          source_player_key TEXT NOT NULL,
          player_id INTEGER NOT NULL REFERENCES players(id),
          first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
          UNIQUE(source, league, source_player_key));
        CREATE INDEX IF NOT EXISTS idx_player_source_ids_player
          ON player_source_ids(player_id, source, league);
        CREATE TABLE IF NOT EXISTS prop_game_source_ids(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL, league TEXT NOT NULL,
          source_game_key TEXT NOT NULL,
          game_id INTEGER NOT NULL REFERENCES prop_games(id),
          first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
          UNIQUE(source, league, source_game_key));
        CREATE INDEX IF NOT EXISTS idx_prop_game_source_ids_game
          ON prop_game_source_ids(game_id, source, league);
    """)
    columns = {row[1] for row in con.execute("PRAGMA table_info(unresolved_players)")}
    for column in ("source_player_key", "reason"):
        if column not in columns:
            con.execute("ALTER TABLE unresolved_players ADD COLUMN {} TEXT".format(column))
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_unresolved_players_source_key "
        "ON unresolved_players(source, league, source_player_key)"
    )


def queue_unresolved_player(
    con: sqlite3.Connection, *, source: str, league: str, source_player_key: str,
    player_name: str, team: Optional[str], reason: str,
) -> None:
    """Queue one source identity and retain the most recent publisher display data."""
    existing = con.execute(
        "SELECT id FROM unresolved_players WHERE source=? AND league=? AND source_player_key=?",
        (source, league, source_player_key),
    ).fetchone()
    if existing:
        con.execute(
            "UPDATE unresolved_players SET count=count+1, raw_name=?, team=?, reason=? WHERE id=?",
            (player_name, team, reason, existing["id"]),
        )
        return
    con.execute(
        "INSERT INTO unresolved_players(source,raw_name,league,team,first_seen,count,source_player_key,reason) "
        "VALUES(?,?,?,?,?,1,?,?)",
        (source, player_name, league, team, dt.datetime.now(dt.timezone.utc).isoformat(), source_player_key, reason),
    )


def bind_player_source_key(
    con: sqlite3.Connection, *, source: str, league: str, source_player_key: str,
    player_id: int, now: str,
) -> None:
    """Bind a stable publisher player key once, refusing every attempted repoint."""
    existing = con.execute(
        "SELECT player_id FROM player_source_ids WHERE source=? AND league=? AND source_player_key=?",
        (source, league, source_player_key),
    ).fetchone()
    if existing and existing["player_id"] != player_id:
        raise SourceIdentityConflict(
            "source player key {} maps to {} not {}".format(
                source_player_key, existing["player_id"], player_id
            )
        )
    if existing:
        con.execute(
            "UPDATE player_source_ids SET last_seen=? WHERE source=? AND league=? AND source_player_key=?",
            (now, source, league, source_player_key),
        )
    else:
        con.execute(
            "INSERT INTO player_source_ids(source,league,source_player_key,player_id,first_seen,last_seen) "
            "VALUES(?,?,?,?,?,?)",
            (source, league, source_player_key, player_id, now, now),
        )
