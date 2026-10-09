#!/usr/bin/env python3
"""Publish nflverse's weekly NFL injury reports with stable-ID resolution.

The nflverse injury artifact is one published row per player/week. It carries a
GSIS id, final report status, latest practice status, and injury labels. Rows are
copied as published; identities resolve by GSIS first and by nflverse's
GSIS-to-ESPN crosswalk second. Names are retained for the review queue only and
are never used as join keys.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import os
import sqlite3
import time
import urllib.request

from team_codes import normalize_optional


DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
SOURCE = "nflverse_injuries"
URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "injuries/injuries_{year}.parquet"
)
PLAYERS_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "players/players.parquet"
)
CACHE_MAX_AGE_S = 6 * 60 * 60
REQUIRED = {
    "season", "week", "team", "gsis_id", "full_name",
    "report_status", "practice_status", "report_primary_injury",
}


def _download(url: str, path: str, refresh: bool = False) -> str:
    if (
        refresh
        or not os.path.exists(path)
        or time.time() - os.path.getmtime(path) > CACHE_MAX_AGE_S
    ):
        urllib.request.urlretrieve(url, path)
    with open(path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    print(f"  artifact: {path} ({os.path.getsize(path)} bytes)")
    print(f"  sha256  : {digest}")
    return path


def fetch_injuries(year: int, cache_dir: str, refresh: bool = False) -> str:
    return _download(
        URL.format(year=year),
        os.path.join(cache_dir, f"injuries_{year}.parquet"),
        refresh,
    )


def fetch_identity_crosswalk(cache_dir: str, refresh: bool = False) -> dict:
    path = _download(
        PLAYERS_URL,
        os.path.join(cache_dir, "nflverse_players.parquet"),
        refresh,
    )
    import pyarrow.parquet as pq

    table = pq.read_table(path, columns=["gsis_id", "espn_id"]).to_pydict()
    result = {}
    for gsis, espn in zip(table["gsis_id"], table["espn_id"]):
        if not gsis or espn is None:
            continue
        value = str(espn).strip()
        if value:
            result[str(gsis)] = (
                str(int(float(value)))
                if value.replace(".", "", 1).isdigit()
                else value
            )
    if not result:
        raise RuntimeError("nflverse player crosswalk contained no GSIS->ESPN ids")
    return result


def read_artifact(path: str, year: int) -> list[dict]:
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    have = set(parquet.schema.names)
    missing = sorted(REQUIRED - have)
    if missing:
        raise RuntimeError(
            "injury artifact is missing required columns: {}".format(
                ", ".join(missing)
            )
        )
    columns = sorted(REQUIRED | ({"date_modified"} if "date_modified" in have else set()))
    rows = pq.read_table(path, columns=columns).to_pylist()
    rows = [row for row in rows if int(row["season"]) == year]
    if not rows:
        raise RuntimeError(f"injury artifact has no rows for season {year}")

    keys = []
    for row in rows:
        if not row.get("gsis_id") or row.get("week") is None or not row.get("team"):
            raise RuntimeError("injury artifact has a blank GSIS id, team, or week")
        row["team"] = normalize_optional("nfl", str(row["team"]))
        keys.append((year, int(row["week"]), row["team"], str(row["gsis_id"])))
    return collapse_final_reports(rows, keys)


def collapse_final_reports(rows: list[dict], keys=None) -> list[dict]:
    """Select the publisher's latest revision for each player/week report.

    nflverse normally publishes one row per key, but 2024 contains two players
    whose Questionable report was superseded by Out later the same weekend.
    ``date_modified`` is the publisher's ordering field. A duplicate without a
    unique latest timestamp remains an error rather than an arbitrary choice.
    """
    if keys is None:
        keys = [
            (int(row["season"]), int(row["week"]), row["team"], str(row["gsis_id"]))
            for row in rows
        ]
    grouped = {}
    for key, row in zip(keys, rows):
        grouped.setdefault(key, []).append(row)
    final = []
    superseded = 0
    for key, revisions in grouped.items():
        if len(revisions) == 1:
            final.append(revisions[0])
            continue
        if any(not row.get("date_modified") for row in revisions):
            raise RuntimeError(
                f"injury artifact has revisions without date_modified for {key}"
            )
        ordered = sorted(revisions, key=lambda row: str(row["date_modified"]))
        if str(ordered[-1]["date_modified"]) == str(ordered[-2]["date_modified"]):
            raise RuntimeError(
                f"injury artifact has tied latest revisions for {key}"
            )
        final.append(ordered[-1])
        superseded += len(revisions) - 1
    if superseded:
        print(
            f"  selected {len(final)} final weekly reports; "
            f"{superseded} older publisher revisions superseded"
        )
    return final


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS injury_reports(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          league TEXT NOT NULL,
          season INTEGER NOT NULL,
          week INTEGER NOT NULL,
          team TEXT NOT NULL,
          player_id INTEGER,
          gsis_id TEXT NOT NULL,
          report_status TEXT,
          practice_status TEXT,
          primary_injury TEXT,
          date_modified TEXT,
          source TEXT NOT NULL,
          ingested_at TEXT NOT NULL,
          UNIQUE(league, season, week, team, gsis_id)
        );
        CREATE INDEX IF NOT EXISTS idx_injury_reports_player_season
          ON injury_reports(player_id, season, week);
        CREATE INDEX IF NOT EXISTS idx_injury_reports_team_season
          ON injury_reports(team, season, week);
        CREATE TABLE IF NOT EXISTS unresolved_players(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL,
          raw_name TEXT NOT NULL,
          league TEXT NOT NULL,
          team TEXT,
          first_seen TEXT NOT NULL,
          count INTEGER DEFAULT 1,
          source_player_key TEXT,
          reason TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_unresolved_players_source_key
          ON unresolved_players(source, league, source_player_key);
        """
    )


def _unique_owners(connection: sqlite3.Connection, column: str) -> dict:
    owners = {}
    for player_id, source_id in connection.execute(
        f"SELECT id,{column} FROM players "
        f"WHERE league='nfl' AND {column} IS NOT NULL AND {column} != ''"
    ):
        owners.setdefault(str(source_id), set()).add(player_id)
    return {
        source_id: next(iter(player_ids))
        for source_id, player_ids in owners.items()
        if len(player_ids) == 1
    }


def publish(year: int, rows: list[dict], gsis_to_espn: dict,
            db_path: str = DB, dry_run: bool = False) -> dict:
    connection = sqlite3.connect(db_path, timeout=60)
    connection.execute("PRAGMA busy_timeout=60000")
    direct = _unique_owners(connection, "nfl_gsis_id")
    espn = _unique_owners(connection, "espn_id")

    prepared = []
    unresolved = {}
    direct_count = fallback_count = 0
    ingested_at = datetime.now(timezone.utc).isoformat()
    for row in rows:
        gsis_id = str(row["gsis_id"])
        player_id = direct.get(gsis_id)
        if player_id is not None:
            direct_count += 1
        else:
            player_id = espn.get(gsis_to_espn.get(gsis_id))
            if player_id is not None:
                fallback_count += 1
        if player_id is None:
            unresolved[gsis_id] = row
        date_modified = row.get("date_modified")
        prepared.append((
            "nfl", year, int(row["week"]), row["team"], player_id, gsis_id,
            row.get("report_status"), row.get("practice_status"),
            row.get("report_primary_injury"),
            str(date_modified) if date_modified is not None else None,
            SOURCE, ingested_at,
        ))

    print(
        f"  identity rows: {direct_count} direct, {fallback_count} via ESPN, "
        f"{len(unresolved)} unresolved GSIS ids"
    )
    if dry_run:
        connection.close()
        return {
            "source_rows": len(rows), "stored_rows": 0,
            "direct_rows": direct_count, "fallback_rows": fallback_count,
            "unresolved_ids": len(unresolved),
        }

    ensure_schema(connection)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM injury_reports WHERE league='nfl' AND season=? AND source=?",
            (year, SOURCE),
        )
        connection.executemany(
            """INSERT INTO injury_reports(
                 league,season,week,team,player_id,gsis_id,report_status,
                 practice_status,primary_injury,date_modified,source,ingested_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            prepared,
        )

        resolved_ids = {row[5] for row in prepared if row[4] is not None}
        if resolved_ids:
            placeholders = ",".join("?" for _ in resolved_ids)
            connection.execute(
                "DELETE FROM unresolved_players WHERE source=? AND league='nfl' "
                f"AND source_player_key IN ({placeholders})",
                [SOURCE] + sorted(resolved_ids),
            )
        for gsis_id, row in unresolved.items():
            existing = connection.execute(
                """SELECT id FROM unresolved_players
                   WHERE source=? AND league='nfl' AND source_player_key=?""",
                (SOURCE, gsis_id),
            ).fetchone()
            occurrence_count = sum(
                1 for item in rows if str(item["gsis_id"]) == gsis_id
            )
            values = (
                str(row.get("full_name") or gsis_id), row["team"],
                occurrence_count, "no canonical owner for published GSIS id",
            )
            if existing:
                connection.execute(
                    """UPDATE unresolved_players
                       SET raw_name=?,team=?,count=?,reason=? WHERE id=?""",
                    values + (existing[0],),
                )
            else:
                connection.execute(
                    """INSERT INTO unresolved_players(
                         source,raw_name,league,team,first_seen,count,
                         source_player_key,reason
                       ) VALUES(?,?,'nfl',?,?,?,?,?)""",
                    (SOURCE, values[0], values[1], ingested_at,
                     occurrence_count, gsis_id, values[3]),
                )

        stored = connection.execute(
            "SELECT COUNT(*) FROM injury_reports "
            "WHERE league='nfl' AND season=? AND source=?",
            (year, SOURCE),
        ).fetchone()[0]
        if stored != len(rows):
            raise RuntimeError(
                f"injury target reconciliation failed: {stored} stored != "
                f"{len(rows)} publisher rows"
            )
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        raise
    connection.close()
    return {
        "source_rows": len(rows), "stored_rows": stored,
        "direct_rows": direct_count, "fallback_rows": fallback_count,
        "unresolved_ids": len(unresolved),
    }


def default_season(db_path: str = DB) -> int:
    connection = sqlite3.connect(db_path)
    row = connection.execute("SELECT MAX(season) FROM nfl_schedule").fetchone()
    connection.close()
    if not row or row[0] is None:
        raise RuntimeError("cannot select NFL season: nfl_schedule is empty")
    return int(row[0])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int)
    parser.add_argument("--artifact", help="pinned local injury parquet")
    parser.add_argument("--cache-dir", default="/tmp")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    year = args.year or default_season()
    print(f"nflverse injuries -> injury_reports (year={year})")
    path = args.artifact or fetch_injuries(year, args.cache_dir, args.refresh)
    rows = read_artifact(path, year)
    print(f"  {len(rows)} published injury rows")
    crosswalk = fetch_identity_crosswalk(args.cache_dir, args.refresh)
    result = publish(year, rows, crosswalk, dry_run=args.dry_run)
    print(
        "  stored {stored_rows} of {source_rows} rows; "
        "unresolved stable ids: {unresolved_ids}".format(**result)
    )


if __name__ == "__main__":
    main()
