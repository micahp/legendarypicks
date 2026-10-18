#!/usr/bin/env python3
"""reconcile_fbs_archive.py -- do the archive's sources agree with each other?

Checks, per season:

  games        cfb_schedules (all divisions), FBS-vs-FBS, completed; espn_cfb_schedules;
               ncaa_mfb_schedule (team rows / 2); espn_cfb_pbp, cfbfastR_cfb_pbp, ncaa_mfb_pbp and
               espn_cfb_linescores (distinct game ids)
  scores       cfb_schedules vs espn_cfb_schedules on shared game ids (home/away points)
               cfb_schedules vs espn_cfb_linescores: sum of periods per team equals the points
               cfb_schedules vs espn_cfb_pbp: the pbp's running score at the last play equals the points
  FBS flag     home_division/away_division and fbs_game, so the Phase 1 population is countable

Reads only the columns it needs. Writes research/fbs/archive-reconcile.csv and prints the table.

Usage:
  /root/legendarypicks/backend/venv/bin/python backend/reconcile_fbs_archive.py [--dir research/fbs/parquet]
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
from collections import defaultdict

import pyarrow.parquet as pq


def files(d, release):
    return sorted(glob.glob(os.path.join(d, release, "*.parquet")))


def read_cols(path, cols):
    names = pq.ParquetFile(path).schema_arrow.names
    keep = [c for c in cols if c in names]
    return pq.read_table(path, columns=keep).to_pylist()


def season_counts(d):
    out = defaultdict(dict)
    for f in files(d, "cfb_schedules"):
        for r in read_cols(f, ["season", "completed", "home_division", "away_division", "fbs_game",
                               "home_id", "away_id", "home_points", "away_points", "game_id"]):
            s = r["season"]
            c = out[s].setdefault("cfb_schedules", {"games": 0, "fbs_fbs": 0, "completed": 0, "ids": set()})
            c["games"] += 1
            c["ids"].add(r["game_id"])
            if r["home_division"] == "fbs" and r["away_division"] == "fbs":
                c["fbs_fbs"] += 1
            if r["completed"]:
                c["completed"] += 1
    for release, key in (("espn_cfb_schedules", "espn_cfb_schedules"), ("espn_cfb_linescores", "espn_cfb_linescores"),
                         ("espn_cfb_pbp", "espn_cfb_pbp"), ("cfbfastR_cfb_pbp", "cfbfastR_cfb_pbp"),
                         ("ncaa_mfb_pbp", "ncaa_mfb_pbp"), ("espn_cfb_team_box", "espn_cfb_team_box")):
        for f in files(d, release):
            names = pq.ParquetFile(f).schema_arrow.names
            idcol = "game_id" if "game_id" in names else "contest_id"
            ids = set(r[idcol] for r in read_cols(f, [idcol]))
            s = int(f.rsplit("_", 1)[1].split(".")[0])
            out[s].setdefault(key, {"games": 0, "ids": set()})
            out[s][key]["games"] = len(ids)
            out[s][key]["ids"] = ids
    for f in files(d, "ncaa_mfb_schedule"):
        rows = read_cols(f, ["contest_id", "season"])
        s = rows[0]["season"] if rows else 0
        ids = {r["contest_id"] for r in rows}
        out[s].setdefault("ncaa_mfb_schedule", {"games": 0, "rows": 0, "ids": ids})
        out[s]["ncaa_mfb_schedule"]["rows"] = len(rows)
        out[s]["ncaa_mfb_schedule"]["games"] = len(ids)
    return out


def score_checks(d):
    """(season, check, compared, agree) for the three score comparisons."""
    res = []
    # cfb_schedules points by game
    base = {}
    for f in files(d, "cfb_schedules"):
        for r in read_cols(f, ["season", "game_id", "home_points", "away_points", "home_id", "away_id"]):
            base[(r["season"], r["game_id"])] = (r["home_points"], r["away_points"])
    # 1. espn_cfb_schedules
    per = defaultdict(lambda: [0, 0])
    for f in files(d, "espn_cfb_schedules"):
        for r in read_cols(f, ["season", "game_id", "home_score", "away_score"]):
            k = (r["season"], r["game_id"])
            if k in base and base[k][0] is not None:
                per[r["season"]][0] += 1
                if (base[k][0], base[k][1]) == (r["home_score"], r["away_score"]):
                    per[r["season"]][1] += 1
    for s, (n, ok) in sorted(per.items()):
        res.append((s, "schedules vs espn_schedules", n, ok))
    # 2. linescores: sum periods per team == points (join through espn_cfb_schedules team ids)
    esp = {}
    for f in files(d, "espn_cfb_schedules"):
        for r in read_cols(f, ["season", "game_id", "home_id", "away_id"]):
            esp[(r["season"], r["game_id"])] = (r["home_id"], r["away_id"])
    per = defaultdict(lambda: [0, 0])
    for f in files(d, "espn_cfb_linescores"):
        rows = read_cols(f, ["game_id", "team_id", "value", "season"])
        agg = defaultdict(int)
        for r in rows:
            try:
                v = int(float(r["value"]))
            except (TypeError, ValueError):
                continue
            agg[(r["season"], r["game_id"], r["team_id"])] += v
        for (s, gid), (hid, aid) in esp.items():
            if s != int(f.rsplit("_", 1)[1].split(".")[0]):
                continue
            if (s, gid) not in base or base[(s, gid)][0] is None:
                continue
            hp, ap = base[(s, gid)]
            if (s, gid, hid) not in agg or (s, gid, aid) not in agg:
                continue
            per[s][0] += 1
            if agg[(s, gid, hid)] == hp and agg[(s, gid, aid)] == ap:
                per[s][1] += 1
    for s, (n, ok) in sorted(per.items()):
        res.append((s, "schedules vs linescore sum", n, ok))
    # 3. espn_cfb_pbp running score at the last play
    per = defaultdict(lambda: [0, 0])
    for f in files(d, "espn_cfb_pbp"):
        s = int(f.rsplit("_", 1)[1].split(".")[0])
        rows = read_cols(f, ["game_id", "pos_team_id", "def_pos_team_id", "pos_team_score", "def_pos_team_score"])
        last = {}
        for r in rows:
            last[r["game_id"]] = r
        for gid, r in last.items():
            if (s, gid) not in base or base[(s, gid)][0] is None:
                continue
            per[s][0] += 1
            hp, ap = base[(s, gid)]
            if r["pos_team_score"] in (hp, ap) and r["def_pos_team_score"] in (hp, ap) \
                    and r["pos_team_score"] + r["def_pos_team_score"] == hp + ap:
                per[s][1] += 1
    for s, (n, ok) in sorted(per.items()):
        res.append((s, "schedules vs pbp final", n, ok))
    # 4. ncaa_mfb_schedule scores (stats.ncaa.org) vs cfb_schedules points, joined on espn_game_id.
    # Independent publisher, so this is the only genuinely cross-source score check in the archive.
    ncaa = defaultdict(dict)
    for f in files(d, "ncaa_mfb_schedule"):
        for r in read_cols(f, ["season", "espn_game_id", "team_score", "opponent_score"]):
            if r.get("espn_game_id"):
                ncaa[r["season"]][str(r["espn_game_id"])] = sorted(
                    [r["team_score"], r["opponent_score"]], key=lambda x: (x is None, x))
    per = defaultdict(lambda: [0, 0])
    for (s, gid), (hp, ap) in base.items():
        got = ncaa.get(s, {}).get(str(gid))
        if got is None or hp is None:
            continue
        per[s][0] += 1
        if got == sorted([hp, ap]):
            per[s][1] += 1
    for s, (n, ok) in sorted(per.items()):
        res.append((s, "schedules vs ncaa_schedule", n, ok))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default=os.path.join("research", "fbs", "parquet"))
    ap.add_argument("--out", default=os.path.join("research", "fbs", "archive-reconcile.csv"))
    a = ap.parse_args(argv)
    counts = season_counts(a.dir)
    scores = score_checks(a.dir)

    rows = []
    print("%-6s %8s %8s %9s %8s %9s %8s %8s %9s" % (
        "season", "cfb_sch", "FBS-FBS", "espn_sch", "ncaa_sch", "espn_pbp", "fastR_pbp", "linescr", "ncaa_pbp"))
    for s in sorted(counts):
        c = counts[s]
        g = lambda k: (c.get(k) or {}).get("games", "")
        print("%-6s %8s %8s %9s %8s %9s %8s %8s %9s" % (
            s, g("cfb_schedules"), c.get("cfb_schedules", {}).get("fbs_fbs", ""), g("espn_cfb_schedules"),
            g("ncaa_mfb_schedule"), g("espn_cfb_pbp"), g("cfbfastR_cfb_pbp"), g("espn_cfb_linescores"),
            g("ncaa_mfb_pbp")))
        rows.append({"season": s,
                     "cfb_schedules_games": g("cfb_schedules"),
                     "cfb_schedules_fbs_fbs": c.get("cfb_schedules", {}).get("fbs_fbs", ""),
                     "cfb_schedules_completed": c.get("cfb_schedules", {}).get("completed", ""),
                     "espn_cfb_schedules_games": g("espn_cfb_schedules"),
                     "ncaa_mfb_schedule_games": g("ncaa_mfb_schedule"),
                     "espn_cfb_pbp_games": g("espn_cfb_pbp"),
                     "cfbfastR_cfb_pbp_games": g("cfbfastR_cfb_pbp"),
                     "espn_cfb_linescores_games": g("espn_cfb_linescores"),
                     "ncaa_mfb_pbp_games": g("ncaa_mfb_pbp")})

    print("\nscore agreement (compared games, agree, rate):")
    srows = []
    for s, check, n, ok in scores:
        rate = (ok / n) if n else 0.0
        print("  %-6s %-30s %6d %6d  %.4f" % (s, check, n, ok, rate))
        srows.append({"season": s, "check": check, "compared": n, "agree": ok, "rate": round(rate, 4)})

    with open(a.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["season"], lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    score_out = a.out.replace(".csv", "-scores.csv")
    with open(score_out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(srows[0]) if srows else ["season"], lineterminator="\n")
        w.writeheader()
        w.writerows(srows)
    print("\nwrote %s and %s" % (a.out, score_out))


if __name__ == "__main__":
    main()
