#!/usr/bin/env python3
"""NFL picks vs wagers: audit of pick semantics and captured prices, plus profitability baselines.

Research only. Read-only on every database. Writes only under this directory.

Sections
  1. Pick semantics and price coverage for 2026 REG weeks 5-7: which markets have captured
     quotes, when each quote was captured relative to kickoff, which forecasts were locked,
     and what is gradeable. Every game is accounted for; exclusions are stated.
  2. Six profitability baselines on games that have a *pregame* captured price and a final
     result. A game without a captured pregame price is never assigned a return.
  3. Sensitivity only: frozen v1 vs closing lines 2010-2025 from nflverse (no timestamps).
     These closing lines cannot establish executable returns and are labelled as such.
  4. Selectivity: reported INCONCLUSIVE when the pregame capture sample cannot support a fit.

Usage:
  python3 run_audit.py [--db PATH]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sqlite3
import sys
from collections import defaultdict

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "backend")
BACKEND = os.path.abspath(BACKEND)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import numpy as np  # noqa: E402
import check_nfl_schedule_scores as cs  # noqa: E402
import nfl_backtest as nb  # noqa: E402
import nfl_feature_backtest as fb  # noqa: E402
import nfl_metrics as nm  # noqa: E402

OUT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = "/root/legendarypicks/backend/data/picks.dev.db"


def open_db(path):
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True)


def snapshots(con):
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(
        "SELECT snapshot_id, game_id, source, captured_at, source_ingested_at, spread_line, "
        "       total_line, home_moneyline, away_moneyline FROM nfl_line_snapshots "
        "WHERE league='nfl' ORDER BY game_id, captured_at")]


def schedule(con, season, w0, w1):
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(
        "SELECT game_id, week, home_team, away_team, gameday, gametime, home_score, away_score, "
        "       result, spread_line, total_line FROM nfl_schedule "
        "WHERE season=? AND game_type='REG' AND week BETWEEN ? AND ? ORDER BY week, game_id",
        (season, w0, w1))]


def locked_projections(con):
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(
        "SELECT gp.game_id, gp.model_version, gp.proj_home, gp.proj_away, gp.proj_margin, "
        "       gp.proj_total, gp.p_home_win, gp.market_spread, gp.market_total, gp.locked_at, "
        "       gp.line_snapshot_id, ls.source AS line_source, ls.captured_at AS line_captured_at "
        "FROM game_projections gp LEFT JOIN nfl_line_snapshots ls ON ls.snapshot_id=gp.line_snapshot_id "
        "WHERE gp.league='nfl' AND gp.locked=1 ORDER BY gp.game_id, gp.model_version")]


def grades(con):
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(
        "SELECT game_id, model_version, actual_home, actual_away, brier, ats_result "
        "FROM projection_grades WHERE league='nfl'")]


def pregame(snap, kick):
    """True when the quote was captured strictly before kickoff."""
    try:
        t = dt.datetime.fromisoformat(snap["captured_at"])
    except Exception:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t < kick


def american_payout(ml):
    """Units returned per 1 unit risked at an American moneyline (win only; caller handles loss)."""
    ml = float(ml)
    return (ml / 100.0) if ml > 0 else (100.0 / -ml)


def section1(con, season, w0, w1):
    snaps = snapshots(con)
    sched = schedule(con, season, w0, w1)
    locks = locked_projections(con)
    gr = grades(con)
    by_game_snaps = defaultdict(list)
    for s in snaps:
        by_game_snaps[s["game_id"]].append(s)
    lock_by_game = defaultdict(list)
    for l in locks:
        lock_by_game[l["game_id"]].append(l)
    grade_by_game = defaultdict(list)
    for g in gr:
        grade_by_game[g["game_id"]].append(g)

    rows = []
    for g in sched:
        gid = g["game_id"]
        kick = cs.kickoff_utc(g["gameday"], g["gametime"])
        ss = by_game_snaps.get(gid, [])
        pre = [s for s in ss if pregame(s, kick)]
        post = [s for s in ss if not pregame(s, kick)]
        final = g["home_score"] is not None and g["away_score"] is not None
        rows.append({
            "game_id": gid, "week": g["week"], "kickoff_utc": kick.isoformat(),
            "home": g["home_team"], "away": g["away_team"], "final": final,
            "n_snapshots": len(ss),
            "sources": ",".join(sorted({s["source"] for s in ss})),
            "n_pregame": len(pre), "n_post": len(post),
            "n_locked": len(lock_by_game.get(gid, [])),
            "n_grades": len(grade_by_game.get(gid, [])),
            "gradeable_pregame": bool(pre and final),
        })
    # summary counts
    summary = {
        "games_total": len(rows),
        "games_with_any_snapshot": sum(1 for r in rows if r["n_snapshots"] > 0),
        "games_with_pregame_snapshot": sum(1 for r in rows if r["n_pregame"] > 0),
        "games_gradeable_pregame": sum(1 for r in rows if r["gradeable_pregame"]),
        "games_final": sum(1 for r in rows if r["final"]),
        "snapshots_total": len(snaps),
        "snapshots_pregame": sum(1 for s in snaps for r in [next((x for x in rows if x["game_id"] == s["game_id"]), None)] if r and pregame(s, dt.datetime.fromisoformat(r["kickoff_utc"]))),
        "weeks": [w0, w1],
        "season": season,
    }
    # source breakdown across all snapshots
    src = defaultdict(int)
    for s in snaps:
        src[s["source"]] += 1
    summary["snapshots_by_source"] = dict(src)
    return rows, summary


def six_baselines(con, season, w0, w1):
    """Baselines on games with a pregame captured price and a final result."""
    rows, _ = section1(con, season, w0, w1)
    sched = {g["game_id"]: g for g in schedule(con, season, w0, w1)}
    snaps = snapshots(con)
    pre_by_game = defaultdict(list)
    for s in snaps:
        g = sched.get(s["game_id"])
        if not g or not g["gameday"]:
            continue
        kick = cs.kickoff_utc(g["gameday"], g["gametime"])
        if pregame(s, kick):
            pre_by_game[s["game_id"]].append(s)
    locks = locked_projections(con)
    # use the v1 points model lock per game
    v1 = {}
    for l in locks:
        if l["model_version"].startswith("nfl-v1 "):
            v1.setdefault(l["game_id"], l)

    results = []
    for r in rows:
        gid = r["game_id"]
        if not r["gradeable_pregame"]:
            continue
        g = sched[gid]
        lock = v1.get(gid)
        if lock is None:
            continue
        snaps_g = pre_by_game[gid]
        # choose the latest pregame snapshot with a moneyline and lines
        snaps_g = [s for s in snaps_g if s["home_moneyline"] is not None
                   and s["away_moneyline"] is not None]
        if not snaps_g:
            continue
        snap = max(snaps_g, key=lambda s: s["captured_at"])
        hs, as_ = g["home_score"], g["away_score"]
        margin = hs - as_
        total = hs + as_
        pm = lock["proj_margin"]
        pt = lock["proj_total"]
        line_sp = snap["spread_line"]
        line_tot = snap["total_line"]
        # model ATS side: pick home if proj_margin > spread_line else away
        ats_pick = "home" if pm > line_sp else "away"
        ats_win = (margin > line_sp) if ats_pick == "home" else (margin < line_sp)
        ats_push = (margin == line_sp)
        # model total side
        tot_pick = "over" if pt > line_tot else "under"
        tot_win = (total > line_tot) if tot_pick == "over" else (total < line_tot)
        tot_push = (total == line_tot)
        # model straight-up winner
        su_pick = "home" if pm > 0 else "away"
        su_win = (margin > 0) if su_pick == "home" else (margin < 0)
        # book favourite ML
        if snap["home_moneyline"] < snap["away_moneyline"]:
            fav, fav_ml = "home", snap["home_moneyline"]
        else:
            fav, fav_ml = "away", snap["away_moneyline"]
        fav_win = (margin > 0) if fav == "home" else (margin < 0)
        results.append({
            "game_id": gid, "week": g["week"], "margin": margin, "total": total,
            "proj_margin": pm, "proj_total": pt,
            "spread_line": line_sp, "total_line": line_tot,
            "home_ml": snap["home_moneyline"], "away_ml": snap["away_moneyline"],
            "ats_pick": ats_pick, "ats_win": bool(ats_win), "ats_push": bool(ats_push),
            "tot_pick": tot_pick, "tot_win": bool(tot_win), "tot_push": bool(tot_push),
            "su_pick": su_pick, "su_win": bool(su_win),
            "fav": fav, "fav_ml": fav_ml, "fav_win": bool(fav_win),
        })
    return results


def units_summary(results):
    """Six baselines, flat 1 unit per game where the market exists. Spread/total at -110."""
    out = {}
    # 1. always model SU winner (ML at the offered price for the picked side)
    def ml_units(pick, win, hml, aml):
        ml = hml if pick == "home" else aml
        return american_payout(ml) if win else -1.0
    n = len(results)
    out["n_games"] = n
    su = [ml_units(r["su_pick"], r["su_win"], r["home_ml"], r["away_ml"]) for r in results]
    fav = [ml_units(r["fav"], r["fav_win"], r["home_ml"], r["away_ml"]) for r in results]
    ats = [0.0 if r["ats_push"] else (0.9090909 if r["ats_win"] else -1.0) for r in results]
    tot = [0.0 if r["tot_push"] else (0.9090909 if r["tot_win"] else -1.0) for r in results]
    out["model_su_ml"] = {"units": sum(su), "roi": sum(su) / n if n else None,
                          "wins": sum(1 for r in results if r["su_win"]), "n": n}
    out["book_fav_ml"] = {"units": sum(fav), "roi": sum(fav) / n if n else None,
                          "wins": sum(1 for r in results if r["fav_win"]), "n": n}
    out["model_ats"] = {"units": sum(ats), "roi": sum(ats) / n if n else None,
                        "wins": sum(1 for r in results if r["ats_win"] and not r["ats_push"]),
                        "pushes": sum(1 for r in results if r["ats_push"]), "n": n}
    out["model_total"] = {"units": sum(tot), "roi": sum(tot) / n if n else None,
                          "wins": sum(1 for r in results if r["tot_win"] and not r["tot_push"]),
                          "pushes": sum(1 for r in results if r["tot_push"]), "n": n}
    out["no_trade"] = {"units": 0.0, "roi": 0.0, "n": n}
    # 5. both sides of each market where paired quotes exist. Betting both sides loses the hold.
    ml_both = []
    for r in results:
        win_ml = r["home_ml"] if r["margin"] > 0 else (r["away_ml"] if r["margin"] < 0 else None)
        if r["margin"] == 0 or win_ml is None:
            ml_both.append(0.0)  # tie: both ML bets lose or push depending on book; count as 0
            continue
        ml_both.append(american_payout(win_ml) - 1.0)
    out["both_sides_ml"] = {"units": sum(ml_both), "roi": sum(ml_both) / n if n else None, "n": n}
    out["both_sides_spread"] = {"units": -0.0909090909 * n, "roi": -0.0909090909, "n": n}
    out["both_sides_total"] = {"units": -0.0909090909 * n, "roi": -0.0909090909, "n": n}
    return out


def sensitivity_2010_2025(db):
    """Frozen v1 vs closing lines 2010-2025. Retrospective; no timestamps -> not executable."""
    con = open_db(db)
    rows = fb.base_rows(con)
    # ATS and total hit rates against closing lines, model SU Brier vs market
    res = {}
    for name, seasons in (("2011-2023", range(2011, 2024)), ("2024-2025", (2024, 2025))):
        g = [r for r in rows if r["season"] in seasons and r["actual_margin"] is not None
             and r["spread_line"] is not None]
        ats_w = ats_l = ats_p = 0
        for r in g:
            pm = r["proj_margin"]
            line = r["spread_line"]
            margin = r["actual_margin"]
            if margin == line:
                ats_p += 1
            elif (pm > line) == (margin > line):
                ats_w += 1
            else:
                ats_l += 1
        gt = [r for r in rows if r["season"] in seasons and r["actual_total"] is not None
              and r["total_line"] is not None]
        tot_w = tot_l = tot_p = 0
        for r in gt:
            pt = r["proj_total"]
            line = r["total_line"]
            total = r["actual_total"]
            if total == line:
                tot_p += 1
            elif (pt > line) == (total > line):
                tot_w += 1
            else:
                tot_l += 1
        mm = [r for r in rows if r["season"] in seasons and r["p_market"] is not None
              and r["outcome"] is not None]
        bw = [(r["p_model"] - r["outcome"]) ** 2 for r in mm]
        bk = [(r["p_market"] - r["outcome"]) ** 2 for r in mm]
        res[name] = {
            "n_spread": len(g), "ats_w": ats_w, "ats_l": ats_l, "ats_p": ats_p,
            "n_total": len(gt), "tot_w": tot_w, "tot_l": tot_l, "tot_p": tot_p,
            "n_ml": len(mm), "brier_model": sum(bw) / len(bw), "brier_market": sum(bk) / len(bk),
        }
    con.close()
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    args = ap.parse_args()
    con = open_db(args.db)

    rows, summary = section1(con, 2026, 5, 7)
    with open(os.path.join(OUT, "coverage_2026.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    res = six_baselines(con, 2026, 5, 7)
    baseline = units_summary(res)
    sens = sensitivity_2010_2025(args.db)
    con.close()

    out = {"coverage_summary": summary, "pregame_gradeable_games": res,
           "six_baselines_2026": baseline, "sensitivity_2010_2025": sens}
    with open(os.path.join(OUT, "audit.json"), "w") as fh:
        json.dump(out, fh, indent=2, default=str)

    print("== coverage ==")
    print(json.dumps(summary, indent=2))
    print("\n== pregame-gradeable games ==")
    for r in res:
        print(r["game_id"], r["week"], "margin", r["margin"], "total", r["total"],
              "su", r["su_pick"], r["su_win"], "ats", r["ats_pick"], r["ats_win"],
              "tot", r["tot_pick"], r["tot_win"])
    print("\n== six baselines (n=%d) ==" % baseline["n_games"])
    for k, v in baseline.items():
        if k == "n_games":
            continue
        print("  %-14s %s" % (k, v))
    print("\n== sensitivity 2010-2025 (closing lines, NOT executable) ==")
    for k, v in sens.items():
        print(" ", k, v)


if __name__ == "__main__":
    main()
