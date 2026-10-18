#!/usr/bin/env python3
"""audit_fbs_game_coverage.py -- for every FBS-vs-FBS game, does a play-by-play exist?

The archive is only useful for modelling if the games we care about have events. This script answers
that directly instead of counting files: it takes every game in `cfb_schedules` where both teams are
FBS, then asks which event sources contain that game's id.

  cfb_schedules      home_division == away_division == 'fbs'  -> the population
  espn_cfb_pbp       game_id                                  -> ESPN ids (same id space as cfb_schedules)
  cfbfastR_cfb_pbp   game_id                                  -> CFBD ids (checked: overlap reported)
  ncaa_mfb_pbp       contest_id                               -> separate id space, cannot be joined;
                                                                 reported as a season count only

Writes research/fbs/archive-game-coverage.csv and prints one row per season.

Usage: /root/legendarypicks/backend/venv/bin/python backend/audit_fbs_game_coverage.py
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
from collections import defaultdict

import pyarrow.parquet as pq


def col(path, names, cols):
    t = pq.read_table(path, columns=[c for c in cols if c in names])
    return t.to_pylist()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default=os.path.join("research", "fbs", "parquet"))
    ap.add_argument("--out", default=os.path.join("research", "fbs", "archive-game-coverage.csv"))
    a = ap.parse_args(argv)

    pop = defaultdict(dict)          # season -> game_id -> completed
    for f in sorted(glob.glob(os.path.join(a.dir, "cfb_schedules", "*.parquet"))):
        for r in pq.read_table(f, columns=["season", "game_id", "home_division", "away_division",
                                           "completed", "season_type"]).to_pylist():
            if r["home_division"] != "fbs" or r["away_division"] != "fbs":
                continue
            if r["season_type"] not in (None, "regular"):   # regular season only
                continue
            pop[r["season"]][str(r["game_id"])] = bool(r["completed"])

    def ids_of(release, idcol="game_id"):
        out = defaultdict(set)
        for f in sorted(glob.glob(os.path.join(a.dir, release, "*.parquet"))):
            names = pq.ParquetFile(f).schema_arrow.names
            if idcol not in names:
                continue
            for r in pq.read_table(f, columns=[idcol, "season"]).to_pylist():
                out[r["season"]].add(str(r[idcol]))
        return out

    espn = ids_of("espn_cfb_pbp")
    fastr = ids_of("cfbfastR_cfb_pbp")
    # ncaa_mfb_pbp carries espn_game_id, so it can be joined to the ESPN id space after all
    ncaa = defaultdict(set)
    for f in sorted(glob.glob(os.path.join(a.dir, "ncaa_mfb_pbp", "*.parquet"))):
        for r in pq.read_table(f, columns=["espn_game_id", "season"]).to_pylist():
            if r["espn_game_id"]:
                ncaa[r["season"]].add(str(r["espn_game_id"]))

    rows = []
    print("%-6s %6s %9s %9s %9s %9s %8s" % ("season", "games", "espn_pbp", "fastr", "either", "ncaa_pbp", "either%"))
    for s in sorted(pop):
        games = set(pop[s])
        e = len(games & espn.get(s, set()))
        f_ = len(games & fastr.get(s, set()))
        either = len(games & (espn.get(s, set()) | fastr.get(s, set())))
        n = len(games & ncaa.get(s, set()))
        pct = (either / len(games)) if games else 0.0
        print("%-6s %6d %9d %9d %9d %9d %7.1f%%" % (s, len(games), e, f_, either, n, 100 * pct))
        rows.append({"season": s, "fbs_games_regular": len(games),
                     "completed": sum(1 for v in pop[s].values() if v),
                     "espn_pbp_games": e, "cfbfastR_pbp_games": f_,
                     "any_pbp_games": either, "ncaa_pbp_matching_ids": n,
                     "coverage_rate": round(pct, 4),
                     "cfbfastR_id_overlap": round(len(games & fastr.get(s, set())) / max(1, min(len(games), len(fastr.get(s, set())))), 4)})
    with open(a.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print("\nwrote %s" % a.out)


if __name__ == "__main__":
    main()
