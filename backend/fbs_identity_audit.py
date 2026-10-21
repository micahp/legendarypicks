"""Independent audit of coverage-identity exceptions and schedule reconciliation against ESPN.

For each listed game, fetches the ESPN scoreboard for the game's date (one request per distinct
date, paced) and compares: event ID present, season, UTC date, home/away orientation of both teams,
completion status, and final score. Raw responses are cached so the audit can be re-run offline.

usage: python fbs_identity_audit.py GAMES.csv CACHE_DIR OUT.csv
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import urllib.request

import pandas as pd

SCOREBOARD = ("https://site.api.espn.com/apis/site/v2/sports/football/"
              "college-football/scoreboard?groups=80&limit=400&dates=%s")
PACE_SECONDS = 1.0


def normalise(value) -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", str(value).lower())
    return " ".join(text.split())


def scoreboard(date: str, cache_dir: str) -> dict:
    path = os.path.join(cache_dir, "scoreboard-%s.json" % date)
    if not os.path.exists(path):
        with urllib.request.urlopen(SCOREBOARD % date, timeout=30) as response:
            body = response.read()
        with open(path, "wb") as handle:
            handle.write(body)
        time.sleep(PACE_SECONDS)
    with open(path) as handle:
        return json.load(handle)


def espn_events(payload: dict) -> dict[str, dict]:
    out = {}
    for event in payload.get("events", []):
        competition = (event.get("competitions") or [{}])[0]
        teams = {c["homeAway"]: c for c in competition.get("competitors", [])}
        home, away = teams.get("home", {}), teams.get("away", {})
        status = (competition.get("status") or {}).get("type", {})
        out[str(event.get("id"))] = {
            "espn_date_utc": event.get("date", ""),
            "espn_season": (event.get("season") or {}).get("year"),
            "espn_home": (home.get("team") or {}).get("location", ""),
            "espn_away": (away.get("team") or {}).get("location", ""),
            "espn_home_id": str((home.get("team") or {}).get("id", "")),
            "espn_away_id": str((away.get("team") or {}).get("id", "")),
            "espn_home_score": home.get("score"), "espn_away_score": away.get("score"),
            "espn_completed": bool(status.get("completed", False)),
        }
    return out


def audit(games: pd.DataFrame, cache_dir: str) -> pd.DataFrame:
    games = games.copy()
    games["game_id"] = games["game_id"].astype(str)
    # ESPN files a game under its Eastern date; the UTC date is wrong for early-UTC kickoffs.
    if "et_date" not in games.columns:
        games["et_date"] = games["start_date_utc"].str[:10].str.replace("-", "", regex=False)
    games["date"] = games["et_date"].astype(str)
    results = []
    for date, group in games.groupby("date"):
        events = espn_events(scoreboard(date, cache_dir))
        for rec in group.itertuples(index=False):
            ev = events.get(rec.game_id)
            row = {"season": rec.season, "game_id": rec.game_id, "date": date,
                   "schedule_home": rec.home_team, "schedule_away": rec.away_team,
                   "schedule_start_utc": rec.start_date_utc,
                   "frame_home_team_id": rec.home_team_id, "frame_away_team_id": rec.away_team_id,
                   "frame_home_score": rec.home_score, "frame_away_score": rec.away_score,
                   "frame_result_known": bool(pd.notna(rec.y))}
            if ev is None:
                row["verdict"] = "espn_event_absent_on_date"
                results.append(row)
                continue
            row.update(ev)
            same_ids = (str(rec.home_team_id) == ev["espn_home_id"]
                        and str(rec.away_team_id) == ev["espn_away_id"])
            same_names = (normalise(ev["espn_home"]) == normalise(rec.home_team)
                          and normalise(ev["espn_away"]) == normalise(rec.away_team))
            same_teams = same_ids and same_names
            same_date = ev["espn_date_utc"][:10] == str(rec.start_date_utc)[:10]
            same_season = str(ev["espn_season"]) == str(rec.season)
            scores_match = (pd.notna(rec.home_score) and str(ev["espn_home_score"]) == str(int(rec.home_score))
                            and str(ev["espn_away_score"]) == str(int(rec.away_score)))
            row.update({"teams_match": same_teams, "ids_match": same_ids, "names_match": same_names,
                        "date_match": same_date, "season_match": same_season,
                        "espn_completed": ev["espn_completed"], "scores_match": scores_match})
            if not ev["espn_completed"]:
                row["verdict"] = "espn_not_final"
            elif same_ids and same_names and same_date and same_season and scores_match:
                row["verdict"] = "confirmed"
            else:
                row["verdict"] = "disagreement"
            results.append(row)
    return pd.DataFrame(results)


def main(argv=None) -> int:
    games_csv, cache_dir, out_csv = sys.argv[1:4]
    os.makedirs(cache_dir, exist_ok=True)
    games = pd.read_csv(games_csv, dtype={"game_id": str, "home_team_id": str, "away_team_id": str})
    result = audit(games, cache_dir)
    result.to_csv(out_csv, index=False)
    print(result["verdict"].value_counts().to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
