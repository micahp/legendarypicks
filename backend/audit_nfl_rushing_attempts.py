#!/usr/bin/env python3
"""audit_nfl_rushing_attempts.py -- reconcile the weekly box-score `carries` with
`nfl_pbp` rushing plays, per player-game, and report what each definition counts.

The weekly `carries` from `player_game_logs` is the target this workstream grades.
The play-by-play is the only source that says *which kind* of rushing play it was:
an ordinary run, a quarterback scramble (a `run` play with `qb_scramble = 1`), a
quarterback kneel, a two-point try, or a lateral. Before any distribution work we
need to know whether `carries` counts kneels and two-point tries, because they add
phantom "carries" to exactly the players whose counts are hardest to model.

Read-only. Usage:

    LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
        python3 audit_nfl_rushing_attempts.py --seasons 2024 2025 2026 [--json out.json]
"""
import argparse
import json
import os
import sqlite3
from collections import Counter, defaultdict


def connect():
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True)


def positions(con):
    """player_id -> position, for every player in `players`."""
    return {pid: pos for pid, pos in con.execute(
        "SELECT id, position FROM players WHERE league = 'nfl'")}


def log_carries(con, seasons):
    """(season, game_id, player_id, gsis) -> carries from the weekly box score."""
    out = {}
    marks = ",".join("?" * len(seasons))
    for season, game_id, pid, gsis, stats in con.execute(
            "SELECT season, game_id, player_id, source_player_key, stats "
            "FROM player_game_logs WHERE league = 'nfl' AND game_type = 'REG' "
            "AND season IN (%s)" % marks, list(seasons)):
        out[(season, game_id, pid, gsis)] = int(json.loads(stats).get("carries") or 0)
    return out


def pbp_carries(con, seasons):
    """(season, game_id, gsis) -> Counter of play kinds.

    `rusher_player_id` is the gsis id, which is what `player_game_logs.source_player_key`
    holds for nflverse rows, so the join is on the source key, not on our own id.
    """
    out = defaultdict(Counter)
    marks = ",".join("?" * len(seasons))
    for season, game_id, gsis, ptype, two_pt, scrambles in con.execute(
            "SELECT season, game_id, rusher_player_id, play_type, two_point_attempt, "
            "qb_scramble FROM nfl_pbp WHERE season IN (%s) AND rush_attempt = 1 "
            "AND rusher_player_id IS NOT NULL" % marks, list(seasons)):
        kind = "scramble" if scrambles else (ptype or "other")
        out[(season, game_id, gsis)][kind] += 1
        if two_pt:
            out[(season, game_id, gsis)]["two_pt"] += 1
    return out


def agree(rows, extract):
    n = len(rows)
    return sum(1 for r in rows if extract(r) == 0) / n if n else 0.0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seasons", type=int, nargs="+", default=[2024, 2025, 2026])
    ap.add_argument("--json")
    ap.add_argument("--examples", type=int, default=8)
    a = ap.parse_args(argv)

    con = connect()
    pos = positions(con)
    logs = log_carries(con, a.seasons)
    pbp = pbp_carries(con, a.seasons)

    groups = defaultdict(list)
    kinds_by_pos = defaultdict(Counter)
    examples = defaultdict(list)
    missing_pbp = 0
    for (season, game_id, pid, gsis), car in logs.items():
        p = pos.get(pid) or "?"
        g = "QB" if p == "QB" else ("RB" if p in ("RB", "FB") else "other")
        k = pbp.get((season, game_id, gsis), Counter())
        raw = sum(v for kk, v in k.items() if kk != "two_pt")
        no_2pt = raw - k["two_pt"]
        no_kneel = raw - k["qb_kneel"]
        both = no_2pt - k["qb_kneel"]
        groups[(season, g)].append((car, raw, raw - car, no_2pt - car, no_kneel - car,
                                    both - car, k["qb_kneel"], k["scramble"], k["two_pt"]))
        for kk in ("run", "scramble", "qb_kneel", "other"):
            kinds_by_pos[g][kk] += k[kk]
        kinds_by_pos[g]["two_pt"] += k["two_pt"]
        kinds_by_pos[g]["log"] += car
        if car and not raw:
            missing_pbp += 1
        if raw != car and len(examples["%d_%s" % (season, g)]) < a.examples:
            examples["%d_%s" % (season, g)].append(
                {"carries_log": car, "pbp_raw": raw, "kneels": k["qb_kneel"],
                 "scrambles": k["scramble"], "two_pt": k["two_pt"]})

    log_keys = {(s, gid, gs) for (s, gid, _, gs) in logs}
    orphans = len({(s, gid, gs) for (s, gid, gs) in pbp} - log_keys)

    report = {"seasons": a.seasons, "by_position": {}, "groups": {},
              "missing_pbp": missing_pbp, "orphans": orphans, "examples": examples}

    print("Agreement between weekly `carries` and nfl_pbp rushing plays, per player-game.")
    print("diff = pbp rushing plays - weekly carries, under four pbp definitions.")
    print("  %-6s %-4s %5s %7s %7s %7s %7s %7s %9s"
          % ("season", "grp", "n", "raw", "no_2pt", "no_kneel", "both", "exact", "mean_raw"))
    for (season, g), rows in sorted(groups.items()):
        if g == "other" or not rows:
            continue
        n = len(rows)
        rec = {"n": n,
               "exact_raw": agree(rows, lambda r: r[2]),
               "exact_no_2pt": agree(rows, lambda r: r[3]),
               "exact_no_kneel": agree(rows, lambda r: r[4]),
               "exact_no_kneel_no_2pt": agree(rows, lambda r: r[5]),
               "mean_diff_raw": sum(r[2] for r in rows) / n,
               "kneels_total": sum(r[6] for r in rows),
               "scrambles_total": sum(r[7] for r in rows),
               "two_pt_total": sum(r[8] for r in rows),
               "log_total": sum(r[0] for r in rows),
               "pbp_total": sum(r[1] for r in rows)}
        report["groups"]["%d_%s" % (season, g)] = rec
        print("  %-6d %-4s %5d %7.4f %7.4f %7.4f %7.4f %7d %+9.4f"
              % (season, g, n, rec["exact_raw"], rec["exact_no_2pt"],
                 rec["exact_no_kneel"], rec["exact_no_kneel_no_2pt"], n, rec["mean_diff_raw"]))

    print("\nWhat the rushing plays are made of (all requested seasons):")
    for g in ("QB", "RB", "other"):
        k = kinds_by_pos[g]
        log = k["log"]
        report["by_position"][g] = dict(k)
        if log:
            print("  %-5s box-score carries %7d | designed run %7d  scramble %6d  kneel %5d  "
                  "2pt %4d | scrambles %.1f%% of carries, kneels %.1f%%"
                  % (g, log, k["run"], k["scramble"], k["qb_kneel"], k["two_pt"],
                     100.0 * k["scramble"] / log, 100.0 * k["qb_kneel"] / log))

    print("\nBox-score rows with carries but no pbp rushing play: %d" % missing_pbp)
    print("pbp rushers with no box-score row: %d" % orphans)
    for key in sorted(examples):
        if examples[key]:
            print("  mismatches %s: %s" % (key, examples[key]))

    if a.json:
        with open(a.json, "w") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
        print("\nwrote %s" % a.json)


if __name__ == "__main__":
    main()
