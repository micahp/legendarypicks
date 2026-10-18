#!/usr/bin/env python3
"""capture_espn_weekly_projections.py -- store ESPN's published weekly player projections beside ours (Spec B 5, 6).

One bulk fantasy endpoint (lm-api-reads.fantasy.espn.com, kona_player_info) returns, per player, a stat entry
for every scoring period with statSourceId = 1 (ESPN's projection) and statSourceId = 0 (the actual). This
captures the projection entries for RB/WR/TE, 50 players per request, most-owned first, and writes them to
player_projections as model_version 'espn-weekly', source 'espn', scenario 'base', with as_of = the capture time.

Request budget (espn-request-budget skill): pages x 1 request, spaced MIN_INTERVAL seconds apart, host budget
HOST_BUDGET so the job refuses instead of meeting the wall, disk cache so a rerun inside the TTL costs nothing.
A dry run issues the same requests (it is one spend with the real run, and the cache makes the second free).

What it does NOT know: when ESPN last changed a past week's projection. ESPN returns its current stored value
for a week already played; whether that was the number shown before kickoff is unverified. A capture made
after kickoff is never graded by grade_nfl_player_projections.py (as_of is after kickoff); it is used only by
the labelled retrospective comparison in backtest_nfl_player_projection_v2.py --vs-espn.

Usage: LP_DB_PATH=... python3 capture_espn_weekly_projections.py --season 2026 --weeks 6 [--pages 8] [--dry-run]
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys

import paced_http
from ppr_scoring import STAT_IDS

URL = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leaguedefaults/3"
       "?view=kona_player_info&limit={limit}&offset={offset}")
PAGE = 50
MIN_INTERVAL = 3.0
HOST_BUDGET = 40
MODEL_VERSION = "espn-weekly"
OUR_STAT = {"tgt": STAT_IDS["targets"], "rec": STAT_IDS["receptions"],
            "rec_yds": STAT_IDS["rec_yds"], "rec_td": STAT_IDS["rec_td"]}
TEAM_FIX = {"LAR": "LA", "WSH": "WAS"}   # ESPN abbreviations to nflverse's, as in players.team vs nfl_schedule


def fetch_pages(season, pages, cache_dir):
    out = []
    for i in range(pages):
        flt = {"players": {"filterSlotIds": {"value": [2, 4, 6]}, "limit": PAGE, "offset": i * PAGE,
                           "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}}
        fetch = paced_http.Fetcher(min_interval=MIN_INTERVAL, retry_waits=(), timeout=60, cache_dir=cache_dir,
                                   host_budget=HOST_BUDGET, on_exhausted="refuse",
                                   headers={"User-Agent": "Python-urllib/3.8", "X-Fantasy-Filter": json.dumps(flt)})
        doc = fetch.json(URL.format(season=season, limit=PAGE, offset=i * PAGE))
        players = doc.get("players", [])
        out.extend(players)
        if len(players) < PAGE:
            break
    return out


def projections(entity, weeks):
    """{week: {our stat: value}} from one ESPN player entity (statSourceId 1, split type 1 = a single week)."""
    res = {}
    for st in entity.get("player", {}).get("stats", []):
        week = st.get("scoringPeriodId")
        if st.get("statSourceId") == 1 and st.get("statSplitTypeId") == 1 and week in weeks:
            stats = st.get("stats") or {}
            res[week] = {k: float(stats[str(v)]) for k, v in OUR_STAT.items() if str(v) in stats}
    return res


def game_for(con, season, week, team):
    row = con.execute(
        "SELECT game_id FROM nfl_schedule WHERE season=? AND week=? AND game_type='REG' AND (home_team=? OR away_team=?)",
        (season, week, team, team)).fetchone()
    return row[0] if row else None


def store(con, season, weeks, players, as_of):
    ours = {espn_id: (pid, team) for pid, espn_id, team in con.execute(
        "SELECT id, espn_id, team FROM players WHERE league='nfl' AND espn_id IS NOT NULL")}
    run_id = "espn-%d-%s" % (season, as_of.replace(":", "").replace("-", "")[:15])
    con.execute(
        "INSERT INTO model_runs (run_id, league, season, week, model, model_version, started_at, params_json, status) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (run_id, "nfl", season, None, "espn-weekly", MODEL_VERSION, as_of, json.dumps({"weeks": sorted(weeks)}), "ok"))
    rows, unmatched, no_game = [], 0, 0
    for e in players:
        who = ours.get(str(e.get("id")))
        if who is None:
            who = ours.get(e.get("id"))
        if who is None:
            unmatched += 1
            continue
        pid, team = who
        team = TEAM_FIX.get(team, team)
        for week, stats in projections(e, weeks).items():
            gid = game_for(con, season, week, team)
            if gid is None:
                no_game += 1          # bye week or a team change: no game to attach it to
                continue
            for stat, value in stats.items():
                rows.append((run_id, "nfl", season, week, gid, pid, team, stat, value, None, None, None,
                             "base", MODEL_VERSION, "espn", None, as_of))
    con.executemany(
        "INSERT OR IGNORE INTO player_projections (run_id, league, season, week, game_id, player_id, team, stat, mean, "
        "median, p10, p90, scenario, model_version, source, p_plays, as_of) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    return run_id, len(rows), unmatched, no_game


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--weeks", required=True, help="e.g. 6 or 3-18")
    ap.add_argument("--pages", type=int, default=8)
    ap.add_argument("--cache-dir", default="/tmp/lp-espn-weekly-cache")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    lo, _, hi = a.weeks.partition("-")
    weeks = set(range(int(lo), int(hi or lo) + 1))
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    os.makedirs(a.cache_dir, exist_ok=True)
    players = fetch_pages(a.season, a.pages, a.cache_dir)
    print("fetched %d players from ESPN" % len(players))
    if a.dry_run:
        print("dry run: nothing stored; sample", [(e.get("id"), projections(e, weeks)) for e in players[:2]])
        return
    con = sqlite3.connect(path, timeout=30)
    as_of = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    run_id, n, unmatched, no_game = store(con, a.season, weeks, players, as_of)
    print("stored %d rows under %s; %d ESPN players not matched to ours; %d player-weeks with no game" % (
        n, run_id, unmatched, no_game))


if __name__ == "__main__":
    main()
