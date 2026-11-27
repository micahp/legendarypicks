#!/usr/bin/env python3
"""ingest_nba_player_movement.py -- NBA.com's official player movement file.

Source: https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json
(one static file, 2015-07-01 onward, signings / waives / trades). Asked 2026-11-12
with a plain client: 200, 10,142 rows, 1,813 trade rows. One request per run.

What the file does and does not say (measured 2026-11-12):

* A multi-team trade is ONE `GroupSort` ("Trade 2025005" holds the seven-team
  Durant deal) and every asset is its own row. The description is the canonical
  statement of direction: "<to> received <asset> from <from>."
* `TEAM_SLUG` is the RECEIVING team on all 1,813 trade rows. That is used only as
  an independent cross-check of the description, never as the source of direction.
* `TEAM_ID` is NOT a reliable from-team on trade rows. It is stored raw and never
  read for direction.
* The date is the effective date. An earlier agreement date is not in this file.
* Pick, cash and "draft consideration" rows carry PLAYER_ID 0.

Fail loud: the raw row is always kept. A trade row whose description does not
parse, or whose slug disagrees with the description, is stored with
`direction_check` set to 'unparsed' or 'conflict' and counted in the result, and
the run is `incomplete`. Only `direction_check='ok'` may feed a relationship.
A feed that shrinks or goes backwards in time is refused, not written.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys

import paced_http
import team_codes

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
URL = "https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json"
SOURCE = "nba.com:player-movement"

# Plain client, no browser headers: this file answers one.
_FETCH = paced_http.Fetcher(
    headers={"User-Agent": "legendarypicks-ingest/1.0"}, timeout=60, retry_waits=())

COLUMNS = ("Transaction_Type", "TRANSACTION_DATE", "TRANSACTION_DESCRIPTION", "TEAM_ID",
           "TEAM_SLUG", "PLAYER_ID", "PLAYER_SLUG", "Additional_Sort", "GroupSort")
TYPES = {"Signing", "Waive", "Trade", "ContractConverted", "AwardOnWaivers"}
SHRINK_FLOOR = 0.99      # refuse a feed with fewer than 99% of the previous row count

# Full team name as the descriptions spell it -> repo canonical code.
TEAM_NAME_TO_CODE = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GS", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "LA Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NO", "New York Knicks": "NY",
    "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SA", "Toronto Raptors": "TOR", "Utah Jazz": "UTAH",
    "Washington Wizards": "WSH",
}
# TEAM_SLUG as the file publishes it -> repo canonical code.
SLUG_TO_CODE = {
    "blazers": "POR", "bucks": "MIL", "bulls": "CHI", "cavaliers": "CLE", "celtics": "BOS",
    "clippers": "LAC", "grizzlies": "MEM", "hawks": "ATL", "heat": "MIA", "hornets": "CHA",
    "jazz": "UTAH", "kings": "SAC", "knicks": "NY", "lakers": "LAL", "magic": "ORL",
    "mavericks": "DAL", "nets": "BKN", "nuggets": "DEN", "pacers": "IND", "pelicans": "NO",
    "pistons": "DET", "raptors": "TOR", "rockets": "HOU", "sixers": "PHI", "spurs": "SA",
    "suns": "PHX", "thunder": "OKC", "timberwolves": "MIN", "warriors": "GS",
    "wizards": "WSH",
}
_TRADE = re.compile(r"^(?P<to>.+?) (?:received|acquired) (?P<what>.+?) from (?P<frm>.+?)\.?$")
_NON_PLAYER = re.compile(r"pick|draft|cash|consideration|rights|exception|swap", re.I)


class MovementFeedError(RuntimeError):
    """The feed cannot be safely published."""


def ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS nba_player_movement_snapshots(
        id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, source_url TEXT NOT NULL,
        captured_at TEXT NOT NULL, checksum TEXT NOT NULL UNIQUE, row_count INTEGER NOT NULL,
        min_date TEXT NOT NULL, max_date TEXT NOT NULL, status TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS nba_player_movement(
        id INTEGER PRIMARY KEY AUTOINCREMENT, row_key TEXT NOT NULL UNIQUE,
        snapshot_id INTEGER NOT NULL, transaction_date TEXT NOT NULL,
        transaction_type TEXT NOT NULL, group_sort TEXT, description TEXT NOT NULL,
        source_team_id TEXT, source_team_slug TEXT, nba_player_id TEXT, nba_player_slug TEXT,
        additional_sort REAL, to_team TEXT, from_team TEXT, asset_kind TEXT,
        direction_check TEXT NOT NULL, player_id INTEGER, ingested_at TEXT NOT NULL)""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_npm_player ON nba_player_movement(player_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_npm_group ON nba_player_movement(group_sort, transaction_date)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_npm_date ON nba_player_movement(transaction_date)")


def _clean_id(value) -> str | None:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return str(number) if number > 0 else None


def parse_row(row: dict) -> dict:
    """Structured fields for one raw row. Never guesses: a miss is 'unparsed'."""
    out = {"to_team": None, "from_team": None, "asset_kind": None, "direction_check": "ok"}
    if row["Transaction_Type"] != "Trade":
        out["direction_check"] = "not_a_trade"
        return out
    match = _TRADE.match(str(row["TRANSACTION_DESCRIPTION"]).strip())
    if not match:
        out["direction_check"] = "unparsed"
        return out
    to_code = TEAM_NAME_TO_CODE.get(match["to"])
    from_code = TEAM_NAME_TO_CODE.get(match["frm"])
    if not to_code or not from_code or to_code == from_code:
        out["direction_check"] = "unparsed"
        return out
    out["to_team"], out["from_team"] = to_code, from_code
    has_player_id = _clean_id(row.get("PLAYER_ID")) is not None
    out["asset_kind"] = "player" if has_player_id and not _NON_PLAYER.search(match["what"]) else "other"
    if SLUG_TO_CODE.get(row.get("TEAM_SLUG")) != to_code:
        out["direction_check"] = "conflict"     # slug (receiver) disagrees with the description
    return out


def row_key(row: dict) -> str:
    return hashlib.sha256(json.dumps({c: row.get(c) for c in COLUMNS}, sort_keys=True,
                                     default=str).encode()).hexdigest()


def validate(payload) -> list[dict]:
    try:
        block = payload["NBA_Player_Movement"]
        rows = block["rows"]
    except (KeyError, TypeError) as exc:
        raise MovementFeedError(f"feed has no NBA_Player_Movement.rows: {exc!r}")
    if not isinstance(rows, list) or not rows:
        raise MovementFeedError("feed has no rows")
    for index, row in enumerate(rows):
        missing = [c for c in COLUMNS if c not in row]
        if missing:
            raise MovementFeedError(f"row {index} lacks columns {missing}")
        if row["Transaction_Type"] not in TYPES:
            raise MovementFeedError(f"row {index} has unknown Transaction_Type {row['Transaction_Type']!r}")
        if not str(row["TRANSACTION_DATE"])[:10] or not row["TRANSACTION_DESCRIPTION"]:
            raise MovementFeedError(f"row {index} lacks a date or description")
    return rows


def _player_lookup(con: sqlite3.Connection) -> dict[str, int]:
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "player_source_ids" not in tables:
        return {}
    return {str(k): int(p) for p, k in con.execute(
        "SELECT player_id, source_player_key FROM player_source_ids "
        "WHERE league='nba' AND source='nba.com'")}


def ingest(con: sqlite3.Connection, payload: dict, *, source_url: str = URL,
           now: str | None = None) -> dict:
    rows = validate(payload)
    now = now or dt.datetime.now(dt.timezone.utc).isoformat()
    checksum = hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
    dates = sorted(str(r["TRANSACTION_DATE"])[:10] for r in rows)
    ensure_schema(con)
    prior = con.execute("SELECT id, row_count, max_date, checksum FROM nba_player_movement_snapshots "
                        "ORDER BY id DESC LIMIT 1").fetchone()
    if prior and prior[3] == checksum:
        return {"status": "unchanged", "snapshot_id": prior[0], "rows": len(rows), "inserted": 0}
    if prior and len(rows) < prior[1] * SHRINK_FLOOR:
        raise MovementFeedError(f"feed shrank: {len(rows)} rows against {prior[1]} in snapshot {prior[0]}")
    if prior and dates[-1] < prior[2]:
        raise MovementFeedError(f"feed went backwards: newest {dates[-1]} against {prior[2]}")

    players = _player_lookup(con)
    counts = {"ok": 0, "conflict": 0, "unparsed": 0, "not_a_trade": 0}
    ids_seen, ids_matched = set(), set()
    problems = []
    inserted = 0
    if con.in_transaction:
        con.commit()          # the caller's own pending work, not ours to roll back
    con.execute("BEGIN IMMEDIATE")
    try:
        cur = con.execute(
            "INSERT INTO nba_player_movement_snapshots(source, source_url, captured_at, checksum, "
            "row_count, min_date, max_date, status) VALUES(?,?,?,?,?,?,?, 'pending')",
            (SOURCE, source_url, now, checksum, len(rows), dates[0], dates[-1]))
        snapshot_id = cur.lastrowid
        for row in rows:
            parsed = parse_row(row)
            counts[parsed["direction_check"]] += 1
            if parsed["direction_check"] in ("conflict", "unparsed") and len(problems) < 5:
                problems.append({"check": parsed["direction_check"], "date": str(row["TRANSACTION_DATE"])[:10],
                                 "description": str(row["TRANSACTION_DESCRIPTION"])[:120]})
            nba_id = _clean_id(row.get("PLAYER_ID"))
            if nba_id:
                ids_seen.add(nba_id)
            player_id = players.get(nba_id) if nba_id else None
            if player_id:
                ids_matched.add(nba_id)
            cur = con.execute(
                """INSERT OR IGNORE INTO nba_player_movement(row_key, snapshot_id, transaction_date,
                   transaction_type, group_sort, description, source_team_id, source_team_slug,
                   nba_player_id, nba_player_slug, additional_sort, to_team, from_team, asset_kind,
                   direction_check, player_id, ingested_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (row_key(row), snapshot_id, str(row["TRANSACTION_DATE"])[:10], row["Transaction_Type"],
                 row.get("GroupSort"), row["TRANSACTION_DESCRIPTION"],
                 _clean_id(row.get("TEAM_ID")), row.get("TEAM_SLUG"), nba_id, row.get("PLAYER_SLUG") or None,
                 row.get("Additional_Sort"), parsed["to_team"], parsed["from_team"], parsed["asset_kind"],
                 parsed["direction_check"], player_id, now))
            inserted += cur.rowcount
        status = "complete" if not (counts["conflict"] or counts["unparsed"]) else "incomplete"
        con.execute("UPDATE nba_player_movement_snapshots SET status=? WHERE id=?", (status, snapshot_id))
        con.execute("COMMIT")
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    return {"status": status, "snapshot_id": snapshot_id, "rows": len(rows), "inserted": inserted,
            "direction": counts, "min_date": dates[0], "max_date": dates[-1],
            "player_ids_matched": f"{len(ids_matched)} of {len(ids_seen)}", "problems": problems}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=DB)
    parser.add_argument("--file", help="read this saved copy instead of fetching")
    args = parser.parse_args(argv)
    if args.file:
        with open(args.file) as handle:
            payload = json.load(handle)
    else:
        payload = _FETCH.json(URL)
    con = sqlite3.connect(args.db, timeout=60)
    result = ingest(con, payload, source_url=args.file or URL)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in ("complete", "unchanged") else 2


if __name__ == "__main__":
    sys.exit(main())
