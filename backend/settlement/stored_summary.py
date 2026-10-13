"""Read ESPN game summaries persisted by ingest_game_summaries.py."""
import json
import sqlite3


def ensure_table(con: sqlite3.Connection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS game_summaries(
        league TEXT NOT NULL,
        espn_event_id TEXT NOT NULL,
        payload TEXT NOT NULL,
        state TEXT NOT NULL,
        completed INTEGER NOT NULL,
        fetched_at TEXT NOT NULL,
        source TEXT NOT NULL,
        PRIMARY KEY (league, espn_event_id))""")


def load(con: sqlite3.Connection, league: str, event_id: str):
    """Return one stored raw summary payload, or None when none was ingested."""
    ensure_table(con)
    row = con.execute(
        "SELECT payload FROM game_summaries WHERE league=? AND espn_event_id=?",
        (league, str(event_id)),
    ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        return None


def boxscore(con: sqlite3.Connection, league: str, event_id: str):
    payload = load(con, league, event_id)
    return payload.get("boxscore") if isinstance(payload, dict) else None
