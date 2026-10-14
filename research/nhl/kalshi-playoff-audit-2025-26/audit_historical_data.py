#!/usr/bin/env python3
"""Recheck NHL game identity and outcome fields in the standalone DuckDB."""
import csv
import json
import os
from collections import Counter
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DB = os.environ.get("NHL_MODEL_DB", "/root/nhl_database_2025-26-playoffs.duckdb")

con = duckdb.connect(DB, read_only=True)

games = con.execute("""
    WITH team_games AS (
        SELECT season, gameId, count(DISTINCT team) AS team_count,
               min(goalsFor) AS low_goals, max(goalsFor) AS high_goals
        FROM teams_gamelogs
        WHERE situation = 'all'
        GROUP BY season, gameId
    )
    SELECT count(*),
           sum((team_count <> 2)::INT),
           sum((low_goals = high_goals)::INT)
    FROM team_games
""").fetchone()

shot_games = con.execute("""
    SELECT season, game_id, count(DISTINCT homeTeamWon) AS winner_label_count,
           min(homeTeamWon) AS home_won_min, max(homeTeamWon) AS home_won_max,
           any_value(homeTeamCode) AS home_code,
           any_value(awayTeamCode) AS away_code
    FROM shots
    GROUP BY season, game_id
""").fetchall()
shot_by_key = {(int(s), int(g)): (int(n), int(lo), int(hi), home, away)
               for s, g, n, lo, hi, home, away in shot_games}

team_rows = con.execute("""
    SELECT season, gameId, team, max(goalsFor) AS goals_for,
           max(gameDate) AS game_date, max(home_or_away) AS home_or_away
    FROM teams_gamelogs
    WHERE situation = 'all'
    GROUP BY season, gameId, team
    ORDER BY season, gameId, team
""").fetchall()
by_game = {}
for season, game_id, team, goals, game_date, home_or_away in team_rows:
    by_game.setdefault((int(season), int(game_id)), []).append(
        {"team": team, "goals": float(goals), "game_date": int(game_date),
         "home_or_away": home_or_away})

missing_shots = []
winner_conflicts = []
games_with_bad_team_count = []
multi_winner_labels = []
matched_shot_games = 0
for (season, game_id), teams in by_game.items():
    shot = shot_by_key.get((season, game_id % 100000))
    if shot is None:
        missing_shots.append({"season": season, "game_id": game_id,
                              "game_date": teams[0]["game_date"], "teams": teams})
        continue
    matched_shot_games += 1
    label_count, home_won_min, home_won_max, home_code, away_code = shot
    if label_count != 1:
        multi_winner_labels.append({"season": season, "game_id": game_id,
                                    "label_count": label_count})
    score_by_team = {x["team"]: x["goals"] for x in teams}
    if len(teams) != 2:
        games_with_bad_team_count.append({"season": season, "game_id": game_id,
                                          "teams": teams})
        continue
    home_goals = score_by_team.get(home_code)
    away_goals = score_by_team.get(away_code)
    if home_goals is None or away_goals is None:
        continue
    if home_goals != away_goals and ((home_goals > away_goals) != bool(home_won_min)):
        winner_conflicts.append({"season": season, "game_id": game_id,
                                 "home": home_code, "away": away_code,
                                 "home_goals": home_goals, "away_goals": away_goals,
                                 "shots_homeTeamWon": home_won_min})

phoenix_raw = json.loads((HERE / "official_phoenix_schedules_2011-14.json").read_text())
phoenix_games = {}
phoenix_schedule_counts = {}
for season_text, payload in phoenix_raw.items():
    season = int(season_text)
    selected = [g for g in payload["games"] if g.get("gameType") in (2, 3)]
    phoenix_schedule_counts[season] = len(selected)
    phoenix_games.update({int(g["id"]): g for g in selected})

phoenix_rows = con.execute("""
    SELECT season, gameId, home_or_away
    FROM teams_gamelogs
    WHERE season IN (2011, 2012, 2013)
      AND team = 'ARI' AND situation = 'all'
    GROUP BY season, gameId, home_or_away
    ORDER BY season, gameId
""").fetchall()
phoenix_by_season = Counter()
phoenix_mismatches = []
phoenix_unmatched = []
for season, game_id, db_home_away in phoenix_rows:
    schedule = phoenix_games.get(int(game_id))
    if schedule is None:
        phoenix_unmatched.append(int(game_id))
        continue
    expected = ("HOME" if schedule["homeTeam"]["abbrev"] == "PHX" else
                "AWAY" if schedule["awayTeam"]["abbrev"] == "PHX" else "NOT_PHOENIX")
    phoenix_by_season[int(season)] += 1
    if db_home_away != expected:
        phoenix_mismatches.append({"season": int(season), "game_id": int(game_id),
                                   "database_home_or_away": db_home_away,
                                   "official_home": schedule["homeTeam"]["abbrev"],
                                   "official_away": schedule["awayTeam"]["abbrev"]})

official_results = json.loads((HERE / "official_conflicting_results.json").read_text())
official_by_id = {int(x["game_id"]): x["payload"] for x in official_results}
for conflict in winner_conflicts:
    official = official_by_id.get(int(conflict["game_id"]))
    if official is None:
        raise RuntimeError(f"Missing official result response for conflict {conflict['game_id']}")
    if (official["homeTeam"]["abbrev"] != conflict["home"] or
        official["awayTeam"]["abbrev"] != conflict["away"] or
        official["homeTeam"]["score"] != conflict["home_goals"] or
        official["awayTeam"]["score"] != conflict["away_goals"]):
        raise RuntimeError(f"Official result does not resolve conflict {conflict['game_id']}")

missing_official = []
for miss in missing_shots:
    for team in miss["teams"]:
        if team["team"] not in ("BUF", "WSH"):
            raise RuntimeError(f"Unexpected team in missing-shot game: {miss}")
    official = official_by_id.get(miss["game_id"])
    if official is None:
        raise RuntimeError(f"Missing official result response for {miss['game_id']}")
    missing_official.append({"game_id": miss["game_id"],
        "official_game_state": official.get("gameState"),
        "official_last_period_type": (official.get("periodDescriptor") or {}).get("periodType"),
        "official_home": official["homeTeam"]["abbrev"],
        "official_home_score": official["homeTeam"]["score"],
        "official_away": official["awayTeam"]["abbrev"],
        "official_away_score": official["awayTeam"]["score"],
        "team_log_goals_by_team": {x["team"]: x["goals"] for x in miss["teams"]}})
    if (official["homeTeam"]["abbrev"] != "BUF" or
        official["awayTeam"]["abbrev"] != "WSH" or
        (official.get("periodDescriptor") or {}).get("periodType") != "SO" or
        official["homeTeam"]["score"] != 3 or official["awayTeam"]["score"] != 4):
        raise RuntimeError(f"Official result does not resolve missing-shot game {miss['game_id']}")

if games[1] or games_with_bad_team_count:
    raise RuntimeError(f"Unexpected team counts in {games[1]} games")
if multi_winner_labels:
    raise RuntimeError(f"Multiple home-winner labels in {len(multi_winner_labels)} games")
extra_shot_games = set(shot_by_key) - {(s, g % 100000) for s, g in by_game}
if len(by_game) != 23222 or matched_shot_games != 23221:
    raise RuntimeError(f"Unexpected joined game coverage: team logs={len(by_game)}, matched shots={matched_shot_games}")
if len(missing_shots) != 1 or len(winner_conflicts) != 2:
    raise RuntimeError(f"Unexpected label audit: missing shots={len(missing_shots)}, conflicts={len(winner_conflicts)}")
if phoenix_unmatched or len(phoenix_rows) != 228 or len(phoenix_mismatches) != 115:
    raise RuntimeError("Phoenix venue reconciliation differs from the documented source snapshot")

summary = {
    "database_path_read_only": DB,
    "team_log_games": len(by_game),
    "games_with_not_exactly_two_teams": int(games[1]),
    "games_with_tied_team_log_goal_totals": int(games[2]),
    "shot_table_games": len(shot_by_key),
    "team_log_games_matched_to_shots": matched_shot_games,
    "team_games_without_shot_table_record": missing_shots,
    "shot_table_games_without_team_log_by_season": dict(Counter(s for s, _ in extra_shot_games)),
    "games_with_multiple_distinct_homeTeamWon_labels": len(multi_winner_labels),
    "non_tied_team_score_vs_shot_winner_conflicts": winner_conflicts,
    "phoenix_schedule_game_counts_by_duckdb_season": phoenix_schedule_counts,
    "phoenix_team_game_rows_joined": len(phoenix_rows) - len(phoenix_unmatched),
    "phoenix_home_away_mismatches_by_season": dict(Counter(x["season"] for x in phoenix_mismatches)),
    "phoenix_unmatched_official_schedule_game_ids": phoenix_unmatched,
    "missing_shot_game_official_result": missing_official,
    "official_result_source_file": "official_conflicting_results.json",
    "phoenix_schedule_source_file": "official_phoenix_schedules_2011-14.json",
}
(HERE / "historical_integrity_summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(summary, ensure_ascii=False, indent=2))
