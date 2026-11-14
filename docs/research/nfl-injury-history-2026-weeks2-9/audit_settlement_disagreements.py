#!/usr/bin/env python3
"""Export every walk-forward settlement disagreement with row-level evidence.

Read-only companion to run_prop_projection_backtest.py. It re-derives the same
eligible prop population for 2026 Weeks 2-9, then writes one row per case where
the recorded sportsbook settlement (prop_results.hit) disagrees with the
settlement implied by the grader's stat value, together with the source's own
settled actual value. No grader code, settlement row, or backtest artifact is
modified.
"""
import csv
import json
import statistics
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import grade_nfl_prop_probabilities as grader
import nfl_player_projection_v2 as engine
import player_splits

SEASON = 2026
WEEKS = tuple(range(2, 10))
MARKETS = tuple(grader.RECEIVING) + tuple(grader.PASSING)


def load_candidates(con):
    """Same population as grader.collect(), but keep the prop row identity of the
    surviving 'over' line and the source's own settled actual value."""
    sql = (
        "SELECT p.id, p.game_id, p.player_id, p.market, p.source, p.line, p.side, p.odds, "
        "p.captured_at, r.hit, r.actual_value, r.settled_at, g.espn_event_id, g.date "
        "FROM props p JOIN prop_games g ON g.id = p.game_id "
        "LEFT JOIN prop_results r ON r.prop_id = p.id "
        "WHERE g.league = 'nfl' AND p.market IN (%s) AND p.source IN (%s) AND p.odds IS NOT NULL"
        % (",".join("?" * len(MARKETS)), ",".join("?" * len(grader.BOOKS)))
    )
    rows = con.execute(sql, MARKETS + tuple(grader.BOOKS)).fetchall()
    nfl = player_splits.prop_game_nfl_ids(con, {r[1] for r in rows})
    latest = {}
    for row in rows:
        _id, pg, pid, market, book, line, side, odds, cap, hit, av, sat, espn, date = row
        gid = nfl.get(pg)
        if gid is None or not gid.startswith("%d_" % SEASON):
            continue
        key = (gid, pid, market, book, float(line), side)
        if key not in latest or cap > latest[key][8]:
            latest[key] = row
    kept = {}
    for key, row in latest.items():
        gid, pid, market, book, line, side = key
        if side != "over":
            continue
        under = latest.get((gid, pid, market, book, line, "under"))
        if under is None or line == int(line):
            continue
        kept[key] = (row, under)
    return kept


def main():
    db = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/legendarypicks/backend/data/picks.dev.db")
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE
    con = sqlite3.connect("file:%s?mode=ro" % db.resolve(), uri=True, timeout=30)
    con.execute("BEGIN")
    try:
        raw = engine.History.load(con, [SEASON - 1, SEASON])
        hist = engine.History(raw.rows, {})
        final_weeks = {w for (w,) in con.execute(
            "SELECT DISTINCT week FROM nfl_schedule WHERE season=? AND game_type='REG' "
            "AND home_score IS NOT NULL", (SEASON,))}
        players = {int(pid): (gsis, name, team) for pid, gsis, name, team in con.execute(
            "SELECT id,nfl_gsis_id,name,team FROM players WHERE league='nfl'")}
        raw_stats = {(pid, gid): stats for pid, gid, stats in con.execute(
            "SELECT player_id, game_id, stats FROM player_game_logs WHERE league='nfl' AND season=? "
            "AND source='nflverse_weekly'", (SEASON,))}
        sched = {gid: (away, home, day) for gid, away, home, day in con.execute(
            "SELECT game_id, away_team, home_team, gameday FROM nfl_schedule WHERE season=?", (SEASON,))}

        kept = load_candidates(con)
        mismatches = []
        eligible = 0
        for (gid, pid, market, book, line, _side), (over, under) in kept.items():
            week = int(gid.split("_")[1])
            if week not in WEEKS or week not in final_weeks:
                continue
            log = next((r for r in hist.by_player.get((SEASON, pid), ()) if r.game_id == gid), None)
            if log is None:
                continue
            if market in grader.RECEIVING:
                if log.pos not in ("RB", "WR", "TE"):
                    continue
                attr = grader.RECEIVING[market][1]
                proj = engine.project(hist, SEASON, week, pid, log.pos, log.team, log.opp, gid)
                if proj is None or proj.get("tgt", 0) <= 0:
                    continue
            else:
                if log.pos != "QB" or grader.pregame_leader(hist, SEASON, log.team, week) != pid:
                    continue
                attr = grader.PASSING[market][1]
                proj = engine.project_qb(hist, SEASON, week, pid, log.team, log.opp, gid)
                if proj is None or proj.get("att", 0) <= 0:
                    continue
            eligible += 1
            hit = over[9]
            our_value = getattr(log, attr)
            if hit is None:
                continue
            ours = 1 if our_value > line else 0
            if int(hit) == ours:
                continue
            src_value = over[10]
            src_implied = None if src_value is None else (1 if src_value > line else 0)
            info = players.get(pid, (None, None, None))
            away, home, day = sched.get(gid, (None, None, None))
            stats = json.loads(raw_stats[(pid, gid)]) if (pid, gid) in raw_stats else {}
            mismatches.append({
                "week": week, "game_id": gid, "game_date": day or over[13],
                "away": away, "home": home, "espn_event_id": over[12],
                "prop_game_id": over[1], "prop_id": over[0],
                "under_prop_id": under[0],
                "player_id": pid, "gsis_id": info[0], "player_name": info[1],
                "log_team": log.team, "position": log.pos,
                "market": market, "stat_field": attr,
                "book": book, "line": line,
                "over_odds": over[7], "under_odds": under[7],
                "captured_at": over[8], "settled_at": over[11],
                "recorded_settlement_hit": int(hit),
                "source_settled_actual": src_value,
                "source_implied_settlement": src_implied,
                "our_stat_value": our_value,
                "our_implied_settlement": ours,
                "our_stats_json": json.dumps(stats, sort_keys=True),
                "stat_fields_present": ",".join(sorted(stats)),
            })

        mismatches.sort(key=lambda r: (r["week"], r["game_id"], r["player_name"] or "", r["market"],
                                       r["book"], r["line"]))
        out_csv = out_dir / "settlement-disagreements-2026-weeks2-9.csv"
        fields = list(mismatches[0]) if mismatches else []
        with out_csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(mismatches)

        def counts(key):
            return dict(sorted(Counter(r[key] for r in mismatches).items(),
                               key=lambda kv: (-kv[1], str(kv[0]))))

        by_player_market = Counter("%s|%s" % (r["player_name"], r["market"]) for r in mismatches)
        groups = {
            "by_player": counts("player_name"),
            "by_player_market": dict(sorted(by_player_market.items(), key=lambda kv: (-kv[1], kv[0]))),
            "by_market": counts("market"),
            "by_game": counts("game_id"),
            "by_book": counts("book"),
            "by_position": counts("position"),
        }
        causes = Counter()
        for r in mismatches:
            if r["source_settled_actual"] is None:
                causes["source actual unavailable"] += 1
            elif float(r["source_settled_actual"]) != float(r["our_stat_value"]):
                causes["source settled actual != our stat value"] += 1
            else:
                causes["source actual agrees with us; recorded hit contradicts it"] += 1
        report = {
            "season": SEASON, "weeks": list(WEEKS),
            "eligible_prop_line_rows": eligible,
            "disagreement_rows": len(mismatches),
            "disagreement_rate": (len(mismatches) / eligible) if eligible else None,
            "distinct_player_game_markets": len({(r["game_id"], r["player_id"], r["market"])
                                                 for r in mismatches}),
            "distinct_players": len({r["player_id"] for r in mismatches}),
            "distinct_games": len({r["game_id"] for r in mismatches}),
            "distinct_books": len({r["book"] for r in mismatches}),
            "pre_classification": dict(causes),
            "groups": groups,
            "rows_out": str(out_csv),
        }
        (out_dir / "settlement-disagreements-summary.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
    finally:
        con.rollback()
        con.close()


if __name__ == "__main__":
    main()
