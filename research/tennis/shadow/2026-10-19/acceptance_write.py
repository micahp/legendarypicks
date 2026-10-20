#!/usr/bin/env python3
"""Write-path check on a copy of the database, for real upcoming matches.

Copies the source database (SQLite backup API, source opened read-only), then runs
backend/tennis_shadow.write_shadow_locks for each match id, twice. The match dict is built the way the slate loop in
routers/games/misc.py builds it (latest scoreboard snapshot, spine identities), so the identity and surface inputs are
the served pipeline's. The served table is hashed before and after to show it is unchanged.

The window time is set explicitly (`--locked-at`), because the real clock is not inside the pre-match window for these
matches. This is a simulation of the endpoint's write, not an endpoint run.
  python3 -I research/tennis/shadow/2026-10-19/acceptance_write.py --source <DB, read-only> \
      --copy <scratch path> --league wta --game-ids 185543 185525 --locked-at 2026-10-20T04:30:00+00:00 \
      --out <json>
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
import tennis_shadow as shadow  # noqa: E402


def copy_database(source: str, target: str) -> None:
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def served_hash(con: sqlite3.Connection) -> tuple[int, str]:
    rows = con.execute("SELECT * FROM tennis_model_locks ORDER BY league, game_id").fetchall()
    return len(rows), hashlib.sha256(repr(rows).encode()).hexdigest()


def match_from_snapshot(con: sqlite3.Connection, league: str, game_id: str) -> dict:
    row = con.execute(
        "SELECT game_id,payload,start_time FROM scoreboard_snapshots WHERE league=? AND game_id=? "
        "ORDER BY fetched_at DESC LIMIT 1", (league, game_id)).fetchone()
    if row is None:
        raise SystemExit(f"{game_id}: no scoreboard snapshot")
    game = json.loads(row[1])
    home, away = game.get("home") or {}, game.get("away") or {}
    identity = {}
    for side_name, side in (("home", home), ("away", away)):
        espn = str(side.get("athlete_id") or "")
        player = con.execute("SELECT id FROM players WHERE league=? AND espn_id=?", (league, espn)).fetchone()
        sackmann = None
        if player:
            found = con.execute(
                "SELECT source_player_key FROM player_source_ids WHERE source='sackmann' AND league=? AND player_id=?",
                (league, player[0])).fetchone()
            sackmann = str(found[0]) if found else None
        identity[side_name] = {"espn_id": espn, "sackmann_player_id": sackmann}
    return {"gameId": str(row[0]), "startTime": row[2], "home": home.get("name"), "away": away.get("name"),
            "tournamentId": str(game.get("tournament_id") or ""), "event": game.get("event"), "identity": identity}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--copy", required=True)
    parser.add_argument("--league", required=True, choices=("atp", "wta"))
    parser.add_argument("--game-ids", nargs="+", required=True)
    parser.add_argument("--locked-at", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    locked_at = dt.datetime.fromisoformat(args.locked_at)
    copy_database(args.source, args.copy)
    con = sqlite3.connect(args.copy)
    result: dict = {"league": args.league, "locked_at": locked_at.isoformat(), "matches": []}
    try:
        served_before = served_hash(con)
        shadow.ensure_table(con)
        replays: dict = {}
        for game_id in args.game_ids:
            match = match_from_snapshot(con, args.league, game_id)
            start = dt.datetime.fromisoformat(match["startTime"].replace("Z", "+00:00"))
            first = shadow.write_shadow_locks(con, args.league, match, start.astimezone(dt.timezone.utc), locked_at, replays)
            second = shadow.write_shadow_locks(con, args.league, match, start.astimezone(dt.timezone.utc), locked_at, replays)
            con.commit()
            rows = con.execute(
                "SELECT model_version, status, locked_at, projection FROM tennis_shadow_locks "
                "WHERE league=? AND game_id=? ORDER BY model_version", (args.league, game_id)).fetchall()
            result["matches"].append({
                "game_id": game_id, "event": match["event"], "tournament_id": match["tournamentId"],
                "home": match["home"], "away": match["away"], "rows_written_first_run": first,
                "rows_written_second_run": second,
                "rows": [{"model_version": r[0], "status": r[1], "locked_at": r[2],
                          "projection": json.loads(r[3])} for r in rows],
            })
        served_after = served_hash(con)
        total = con.execute("SELECT COUNT(*) FROM tennis_shadow_locks").fetchone()[0]
        result["served_table_rows_before_after"] = [served_before[0], served_after[0]]
        result["served_table_hash_unchanged"] = served_before == served_after
        result["shadow_rows_total"] = total
    finally:
        con.close()
    Path(args.out).write_text(json.dumps(result, indent=1, sort_keys=True, default=str) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "matches"}, default=str))
    for match in result["matches"]:
        print(match["game_id"], match["event"], "first", match["rows_written_first_run"],
              "second", match["rows_written_second_run"])
        for row in match["rows"]:
            print("  ", row["model_version"], row["status"], row["projection"].get("probability"),
                  row["projection"].get("surfaceSource"), row["projection"].get("projectedWinner"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
