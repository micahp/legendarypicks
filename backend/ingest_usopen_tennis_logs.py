#!/usr/bin/env python3
"""Publish US Open singles match logs from the official point-by-point feed.

The US Open completed-match index is the population authority.  Each match is
then fetched from IBM SlamTracker's history endpoint and reduced to the six
counting stats offered by Underdog.  All source data is fetched and validated
before one short DEV transaction; identity ambiguity fails closed.

Usage:
  python3 ingest_usopen_tennis_logs.py --dry-run
  LP_DB_PATH=/absolute/picks.dev.db python3 ingest_usopen_tennis_logs.py \
    --apply --expect-matches N --expect-source-rows N --backup /absolute/backup.db
"""
import argparse
import collections
import datetime as dt
import json
import os
import pathlib
import sqlite3
import sys
import time
import unicodedata
import urllib.request


YEAR = 2026
BASE = f"https://www.usopen.org/en_US/scores/feeds/{YEAR}"
EVENT_DAYS = BASE + "/completed_matches/eventDays.json"
HISTORY = BASE + "/slamtracker/history/{match_id}C.json"
DB_PATH = os.environ.get("LP_DB_PATH", "data/picks.dev.db")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
MIN_INTERVAL = float(os.environ.get("LP_USOPEN_MIN_INTERVAL") or 0.20)
TABLE = "player_game_logs_usopen"
STAT_FIELDS = ("aces", "double_faults", "games_won", "breakpoints_won",
               "points_won", "sets_won", "total_games", "match_winner")
CODE_FIELDS = {"Ace": "aces", "DoubleFault": "double_faults",
               "GameWinner": "games_won", "BreakPointWon": "breakpoints_won",
               "PointWinner": "points_won", "SetWinner": "sets_won"}
DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER,
    league TEXT NOT NULL,
    season INTEGER NOT NULL,
    game_no TEXT NOT NULL,
    game_id TEXT NOT NULL,
    game_date TEXT NOT NULL,
    opponent TEXT,
    stats TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'usopen.org',
    source_player_key TEXT NOT NULL,
    ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
    game_type TEXT NOT NULL,
    UNIQUE(league, source_player_key, season, game_no)
);
CREATE INDEX IF NOT EXISTS idx_pglu_player_date
    ON {TABLE}(player_id, game_date);
CREATE INDEX IF NOT EXISTS idx_pglu_league_date
    ON {TABLE}(league, game_date);
"""
_last_request = [0.0]


def fold(value):
    text = unicodedata.normalize("NFKD", str(value or "")).encode(
        "ascii", "ignore").decode("ascii")
    return " ".join("".join(c for c in text.lower()
                              if c.isalnum() or c.isspace()).split())


def _get(url):
    wait = MIN_INTERVAL - (time.monotonic() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=40) as response:
        payload = json.loads(response.read().decode("utf-8", "replace"))
    _last_request[0] = time.monotonic()
    return payload


def full_name(team):
    return " ".join(x for x in (team.get("firstNameA"), team.get("lastNameA")) if x)


def completed_singles(get=_get):
    """Return the independently indexed completed main-draw singles population."""
    days = get(EVENT_DAYS).get("eventDays") or []
    matches = {}
    fetched_days = 0
    for day in days:
        events = set(day.get("events") or [])
        if not events.intersection({"MS", "WS"}):
            continue
        payload = get(day["url"])
        fetched_days += 1
        for match in payload.get("matches") or []:
            if match.get("eventCode") not in ("MS", "WS"):
                continue
            if match.get("statusCode") != "D" or not match.get("match_id"):
                continue
            match_id = str(match["match_id"])
            if match_id in matches and matches[match_id] != match:
                raise RuntimeError(f"conflicting completed match {match_id}")
            matches[match_id] = match
    if not matches:
        raise RuntimeError("US Open completed-match index returned no singles")
    return list(matches.values()), fetched_days


def aggregate_match(match, points):
    """Reduce source-coded point outcomes and reconcile to the match summary."""
    if not isinstance(points, list) or not points:
        raise RuntimeError(f"match {match['match_id']} has no point history")
    # SlamTracker may prefix narrative rows such as "Players arrive on court."
    # They have no PointID, zero epoch, Stage=inf, and are not played points.
    # A row with a real PointID but no winner remains a hard source failure.
    bad = [p for p in points if p.get("PointID") and
           str(p.get("PointWinner") or "0") not in ("1", "2")]
    if bad:
        raise RuntimeError(f"match {match['match_id']} has uncoded played points")
    points = [p for p in points if p.get("PointID") and
              str(p.get("PointWinner") or "0") in ("1", "2")]
    if not points:
        raise RuntimeError(f"match {match['match_id']} has no played points")
    stats = [collections.Counter(), collections.Counter()]
    for point in points:
        for source_field, target in CODE_FIELDS.items():
            code = str(point.get(source_field) or "0")
            if code in ("1", "2"):
                stats[int(code) - 1][target] += 1
    if sum(s["points_won"] for s in stats) != len(points):
        raise RuntimeError(f"match {match['match_id']} point reconciliation failed")
    teams = [match.get("team1") or {}, match.get("team2") or {}]
    set_scores = match.get("scores", {}).get("sets") or []
    expected_games = [sum(int(pair[i].get("score") or 0) for pair in set_scores)
                      for i in (0, 1)]
    for i in (0, 1):
        expected_sets = int(teams[i].get("totalSetsWon") or 0)
        if stats[i]["sets_won"] != expected_sets:
            raise RuntimeError(f"match {match['match_id']} set reconciliation failed")
        if stats[i]["games_won"] != expected_games[i]:
            raise RuntimeError(f"match {match['match_id']} game reconciliation failed")
    winner = str(match.get("winner") or "0")
    if winner not in ("1", "2") or str(points[-1].get("MatchWinner") or "0") != winner:
        raise RuntimeError(f"match {match['match_id']} winner reconciliation failed")
    total_games = sum(expected_games)
    for i in (0, 1):
        stats[i]["total_games"] = total_games
        stats[i]["match_winner"] = 1 if winner == str(i + 1) else 0
    game_date = dt.datetime.fromtimestamp(float(match["epoch"]) / 1000,
                                          dt.timezone.utc).date().isoformat()
    league = "atp" if match["eventCode"] == "MS" else "wta"
    rows = []
    for i in (0, 1):
        source_id = teams[i].get("idA")
        if not source_id:
            raise RuntimeError(f"match {match['match_id']} missing player source id")
        rows.append({"league": league, "season": YEAR,
                     "game_no": f"usopen-{match['match_id']}",
                     "game_id": str(match["match_id"]), "game_date": game_date,
                     "name": full_name(teams[i]), "opponent": full_name(teams[1 - i]),
                     "source_player_key": str(source_id),
                     "game_type": str(match.get("roundName") or "main draw"),
                     "stats": {field: int(stats[i][field]) for field in STAT_FIELDS}})
    return rows


def spine(con):
    index = collections.defaultdict(list)
    for player_id, name, league in con.execute(
            "SELECT id,name,league FROM players WHERE league IN ('atp','wta')"):
        index[(league, fold(name))].append(player_id)
    return index


def resolve_rows(rows, index):
    counts = collections.Counter()
    for row in rows:
        matches = index.get((row["league"], fold(row["name"])), [])
        item = dict(row)
        item["player_id"] = matches[0] if len(matches) == 1 else None
        counts["resolved" if len(matches) == 1 else
               "ambiguous" if matches else "unresolved"] += 1
        yield item
    counts["source_rows"] = len(rows)


def fetch_rows(get=_get):
    matches, day_count = completed_singles(get)
    rows = []
    for match in matches:
        rows.extend(aggregate_match(match, get(HISTORY.format(match_id=match["match_id"]))))
    return rows, {"completed_days": day_count, "matches": len(matches),
                  "source_rows": len(rows)}


def publish(con, rows):
    # execute() preserves the caller's transaction; executescript() would
    # silently commit the BEGIN IMMEDIATE before the rows were written.
    for statement in DDL.split(";"):
        if statement.strip():
            con.execute(statement)
    sql = f"""INSERT INTO {TABLE}
        (player_id,league,season,game_no,game_id,game_date,opponent,stats,
         source,source_player_key,game_type)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(league,source_player_key,season,game_no) DO UPDATE SET
          player_id=COALESCE(excluded.player_id,{TABLE}.player_id),
          opponent=excluded.opponent,stats=excluded.stats,
          ingested_at=datetime('now'),game_type=excluded.game_type"""
    for row in rows:
        con.execute(sql, (row["player_id"], row["league"], row["season"],
                          row["game_no"], row["game_id"], row["game_date"],
                          row["opponent"], json.dumps(row["stats"], sort_keys=True),
                          "usopen.org", row["source_player_key"], row["game_type"]))


def require_apply_contract(args, audit, db_path):
    """Refuse a write unless it matches a separately observed dry-run."""
    if not args.apply:
        return
    if args.expect_matches is None or args.expect_source_rows is None:
        raise RuntimeError("apply requires --expect-matches and --expect-source-rows")
    observed = (audit["matches"], audit["source_rows"])
    expected = (args.expect_matches, args.expect_source_rows)
    if observed != expected:
        raise RuntimeError(
            "source population changed since dry-run: "
            f"expected matches/rows={expected}, observed={observed}")
    if not args.backup:
        raise RuntimeError("apply requires --backup with an absolute new path")
    backup_path = pathlib.Path(args.backup)
    if not backup_path.is_absolute():
        raise RuntimeError("backup path must be absolute")
    backup_path = backup_path.resolve()
    if backup_path == db_path:
        raise RuntimeError("backup path must differ from database path")
    if backup_path.exists():
        raise RuntimeError(f"backup path already exists: {backup_path}")
    if not backup_path.parent.is_dir():
        raise RuntimeError(f"backup parent does not exist: {backup_path.parent}")


def verified_backup(con, backup_path):
    """Take a WAL-safe SQLite backup and verify it before publication."""
    destination = sqlite3.connect(str(backup_path))
    try:
        con.backup(destination)
        check = destination.execute("PRAGMA quick_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError(f"backup quick_check failed: {check}")
        destination.commit()
    except Exception:
        destination.close()
        try:
            backup_path.unlink()
        except FileNotFoundError:
            pass
        raise
    finally:
        try:
            destination.close()
        except Exception:
            pass
    return check


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-matches", type=int)
    parser.add_argument("--expect-source-rows", type=int)
    parser.add_argument("--backup")
    args = parser.parse_args(argv)
    if args.dry_run and args.apply:
        parser.error("--dry-run and --apply are mutually exclusive")
    db_path = pathlib.Path(DB_PATH).resolve()
    if not db_path.is_file():
        parser.error(f"database must already exist: {db_path}")
    rows, audit = fetch_rows()
    con = sqlite3.connect(str(db_path), timeout=60)
    try:
        resolved = list(resolve_rows(rows, spine(con)))
        identity = collections.Counter("resolved" if r["player_id"] is not None else
                                       "unresolved" for r in resolved)
        print(f"source: {audit['completed_days']} days, {audit['matches']} matches, "
              f"{audit['source_rows']} player logs")
        print(f"identity: {identity['resolved']} resolved, {identity['unresolved']} unresolved")
        if not args.apply:
            print("dry-run: source and reconciliation passed; nothing written")
            return 0
        require_apply_contract(args, audit, db_path)
        backup_path = pathlib.Path(args.backup).resolve()
        backup_check = verified_backup(con, backup_path)
        print(f"backup: {backup_path}; quick_check={backup_check}")
        con.execute("BEGIN IMMEDIATE")
        publish(con, resolved)
        con.commit()
        check = con.execute("PRAGMA quick_check").fetchone()[0]
        stored = con.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
        if check != "ok" or stored < len(resolved):
            raise RuntimeError(f"publication postcondition failed: rows={stored}, check={check}")
        print(f"published: {stored} US Open player logs; quick_check={check}")
        return 0
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
