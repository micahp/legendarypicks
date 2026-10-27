#!/usr/bin/env python3
"""Audit projected NHL roster coverage from a cutoff-safe DB snapshot, read-only."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

SIM_DIR = Path(__file__).resolve().parents[1] / "statistical-full-game-v0.2b"
sys.path.insert(0, str(SIM_DIR))
import nhl_game_state_sim as sim  # noqa: E402


def _position_group(position: str) -> str:
    return "F" if position in {"C", "L", "R", "LW", "RW", "F"} else position


def audit(database: Path, game_date: str, cutoff_text: str) -> dict[str, Any]:
    target_date = dt.date.fromisoformat(game_date)
    cutoff = dt.datetime.fromisoformat(cutoff_text.replace("Z", "+00:00"))
    if cutoff.tzinfo is None or cutoff.date() > target_date:
        raise ValueError("cutoff must be timezone-aware and no later than the target game date")
    if not database.is_file():
        raise FileNotFoundError(f"NHL roster database not found: {database}")
    uri = f"file:{database}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        snapshot = connection.execute(
            "SELECT id,season,source,captured_at,published_at,source_checksum "
            "FROM roster_snapshots WHERE league='nhl' AND status IN ('published','superseded') "
            "AND captured_at<=? AND published_at<=? ORDER BY published_at DESC LIMIT 1",
            (cutoff.isoformat(), cutoff.isoformat()),
        ).fetchone()
        if snapshot is None:
            raise ValueError(f"no published NHL roster snapshot available before {cutoff.isoformat()}")
        teams = [str(row[0]) for row in connection.execute(
            "SELECT DISTINCT team FROM roster_memberships WHERE snapshot_id=? "
            "AND roster_status='active' ORDER BY team", (snapshot["id"],)
        ).fetchall()]
    finally:
        connection.close()
    if not teams:
        raise ValueError(f"roster snapshot {snapshot['id']} has no active team memberships")

    team_rows = []
    for team in teams:
        roster = sim.load_roster(database, team, target_date.isoformat(), cutoff)
        if roster.coverage.get("snapshot_id") != snapshot["id"]:
            raise ValueError(f"{team}: roster loader selected a different snapshot")
        counts: dict[str, int] = {"F": 0, "D": 0, "G": 0}
        for player_id in roster.game_roster_ids:
            group = _position_group(roster.players[player_id].position)
            if group not in counts:
                raise ValueError(f"{team}: unsupported projected position {group!r}")
            counts[group] += 1
        if counts["F"] != 12 or counts["D"] != 6 or counts["G"] not in {1, 2}:
            raise ValueError(f"{team}: projected roster position counts are invalid: {counts}")
        team_rows.append({"team": team, "projected_roster_size": len(roster.game_roster_ids),
                          "position_counts": counts,
                          "goalie_candidates": roster.coverage.get("goalie_candidates", 0),
                          "goalies_selected": len(roster.goalie_ids)})

    return {
        "report_kind": "read_only_pregame_roster_projection_coverage",
        "database_path": str(database),
        "database_access": "SQLite mode=ro and PRAGMA query_only=ON; roster loader uses mode=ro",
        "target_game_date": target_date.isoformat(),
        "capture_cutoff_utc": cutoff.isoformat().replace("+00:00", "Z"),
        "target_game_lineup_or_outcome_used": False,
        "snapshot": {key: snapshot[key] for key in
                     ("id", "season", "source", "captured_at", "published_at", "source_checksum")},
        "teams_attempted": len(teams),
        "teams_projected": len(team_rows),
        "projection_failures": 0,
        "roster_sizes": {str(size): sum(row["projected_roster_size"] == size for row in team_rows)
                          for size in sorted({row["projected_roster_size"] for row in team_rows})},
        "teams": team_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=sim.DEFAULT_DB)
    parser.add_argument("--game-date", required=True)
    parser.add_argument("--cutoff", required=True,
                        help="timezone-aware ISO timestamp, strictly before target date")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.database, args.game_date, args.cutoff)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"teams_projected": result["teams_projected"],
                      "projection_failures": result["projection_failures"],
                      "snapshot_id": result["snapshot"]["id"],
                      "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
