#!/usr/bin/env python3
"""audit_nfl_participation_v2.py -- audit of the participation event before any v2 model code.

The v2 facet asks whether P(plays) from Spec B's own `recent_form` table (the P_LOG probabilities)
distinguishes the non-participants that the injury designation misses. This script measures, on the
candidate population v1 pre-registered, without fitting anything:

  1. the population, by season and position
  2. what "participation" means here: box-score appearance vs the availability flag, and how far apart
     the two events are
  3. how many non-participants the designation catches, and how many it misses (the 110-of-534 claim)
  4. the discrimination and calibration of Spec B's P_LOG table on this population
  5. cell counts for the (recent form) x (designation) cross, so the shrinkage constant is chosen from
     data rather than taste

Read-only on the DB.

    LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
        python3 audit_nfl_participation_v2.py --seasons 2024 2025 2026
"""
import argparse
import math
import os
import sqlite3
from collections import Counter, defaultdict

import nfl_player_projection_v2 as eng

WEEKS = set(range(3, 19))
PARAMS = dict(eng.DEFAULTS, K_T=8.0)
P_LOG = eng.P_LOG_2024


def auc(pairs):
    pos = [s for s, y in pairs if y == 1]
    neg = [s for s, y in pairs if y == 0]
    if not pos or not neg:
        return None
    ordered = sorted(pairs, key=lambda x: x[0])
    ranks, i = defaultdict(float), 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][0] == ordered[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    r_pos = sum(ranks[k] for k, (s, y) in enumerate(ordered) if y == 1)
    n1, n0 = len(pos), len(neg)
    return (r_pos - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def build(hist, season, weeks=WEEKS):
    """Every Spec B candidate with a positive carry mean (same population as v1)."""
    out = []
    for (s, team), team_weeks in hist.team_weeks.items():
        if s != season:
            continue
        for week in sorted(team_weeks):
            if week not in weeks:
                continue
            rows = hist.by_team[(s, team)][week]
            if not rows:
                continue
            game_id, opp = rows[0].game_id, rows[0].opp
            actual = {r.pid: r.car for r in rows}
            status = hist.status.get((s, game_id, team), {})
            for pid, pos in hist.candidates(s, team, week).items():
                if pos not in ("RB", "QB"):
                    continue
                got = eng.opportunities(hist, s, week, pid, pos, team, opp, game_id, "car", PARAMS)
                if not got or got[0] <= 0:
                    continue
                entry = status.get(pid, (None, None))
                k, last = hist.recent_form(s, team, week, pid)
                out.append({"season": s, "week": week, "team": team, "game_id": game_id,
                            "pid": pid, "pos": pos, "m": got[0], "y": actual.get(pid, 0),
                            "appeared": pid in actual, "status": entry[0] or "",
                            "played_flag": entry[1], "k": k, "last": last,
                            "p_log": hist.p_log(s, team, week, pid, P_LOG)})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, nargs="+", default=[2024, 2025, 2026])
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    hist = eng.History.load(con, sorted(a.seasons))

    items = {s: build(hist, s) for s in a.seasons}
    print("== 1. population (weeks 3-18, Spec B candidates with m > 0)")
    for s in a.seasons:
        rb = [i for i in items[s] if i["pos"] == "RB"]
        qb = [i for i in items[s] if i["pos"] == "QB"]
        print("  %d: %d candidate-games (RB %d, QB %d) | appeared %.3f"
              % (s, len(items[s]), len(rb), len(qb),
                 sum(i["appeared"] for i in items[s]) / max(1, len(items[s]))))
        if s >= 2024:
            both = [i for i in items[s] if i["played_flag"] is not None]
            agree = sum(1 for i in both if bool(i["played_flag"]) == i["appeared"])
            print("     availability known for %d (%.3f); appearance == played_flag for %.4f of those"
                  % (len(both), len(both) / len(items[s]), agree / max(1, len(both))))

    print("\n== 2. what the two participation events disagree about (RB, 2024-2026)")
    tab = Counter()
    for s in a.seasons:
        for i in items[s]:
            if i["pos"] != "RB" or i["played_flag"] is None:
                continue
            tab[(i["played_flag"], i["appeared"])] += 1
    for (pf, ap), n in sorted(tab.items()):
        print("  played_flag=%s appeared=%s : %d" % (pf, ap, n))

    print("\n== 3. non-participants and how many the designation catches")
    for s in a.seasons:
        for pos in ("RB", "QB", "RB+QB"):
            if pos == "RB+QB":
                sub = [i for i in items[s] if i["pos"] in ("RB", "QB")]
            else:
                sub = [i for i in items[s] if i["pos"] == pos]
            miss = [i for i in sub if not i["appeared"]]
            named = [i for i in miss if i["status"]]
            out_only = [i for i in miss if i["status"] == "Out"]
            print("  %d %-5s: %4d candidates, %3d non-appearances; designation on %3d (%.1f%%),"
                  " 'Out' on %3d (%.1f%%)"
                  % (s, pos, len(sub), len(miss), len(named), 100.0 * len(named) / max(1, len(miss)),
                     len(out_only), 100.0 * len(out_only) / max(1, len(miss))))
        rb_miss = [i for i in items[s] if i["pos"] == "RB" and not i["appeared"] and not i["status"]]
        if rb_miss:
            low = sum(1 for i in rb_miss if i["p_log"] <= 0.35)
            print("     RB undesignated non-appearances with P_LOG <= 0.35: %d of %d (%.1f%%)"
                  % (low, len(rb_miss), 100.0 * low / len(rb_miss)))

    print("\n== 3b. reconciliation with v1's 534 / 110 (v1 counted 'did not play' as played_flag != 1)")
    for s in a.seasons:
        sub = [i for i in items[s] if i["pos"] in ("RB", "QB")]
        nop = [i for i in sub if i["played_flag"] != 1]
        named = Counter(i["status"] for i in nop if i["status"])
        unknown = sum(1 for i in nop if i["played_flag"] is None)
        zero = sum(1 for i in nop if i["played_flag"] == 0)
        print("  %d: played_flag != 1 -> %d (flag 0: %d, no availability row: %d);"
              " designation on %d %s" % (s, len(nop), zero, unknown, sum(named.values()),
                                         dict(named)))
        active_no_row = sum(1 for i in sub if i["played_flag"] == 1 and not i["appeared"])
        print("     active (played_flag 1) but no box-score row: %d" % active_no_row)

    print("\n== 4. Spec B P_LOG on this population (RB)")
    for s in a.seasons:
        rb = [i for i in items[s] if i["pos"] == "RB"]
        if not rb:
            continue
        by_cell = defaultdict(lambda: [0, 0, 0.0])
        for i in rb:
            c = by_cell[(i["k"], i["last"])]
            c[0] += 1
            c[1] += 1 if i["appeared"] else 0
            c[2] += i["p_log"]
        brier = sum((i["p_log"] - (1.0 if i["appeared"] else 0.0)) ** 2 for i in rb) / len(rb)
        base = sum(1 for i in rb if i["appeared"]) / len(rb)
        brier_base = sum((base - (1.0 if i["appeared"] else 0.0)) ** 2 for i in rb) / len(rb)
        print("  %d: n=%d, P_LOG mean %.3f vs observed %.3f | Brier %.4f vs constant %.4f | AUC %.4f"
              % (s, len(rb), sum(i["p_log"] for i in rb) / len(rb), base, brier, brier_base,
                 auc([(i["p_log"], 1 if i["appeared"] else 0) for i in rb])))
        for cell in sorted(by_cell):
            n, k, psum = by_cell[cell]
            print("     (k=%d,last=%d) n=%4d  P_LOG %.3f  observed %.3f"
                  % (cell[0], cell[1], n, P_LOG.get("%d%d" % cell, float("nan")), k / n))

    print("\n== 5. (recent form) x (designation) cells on training seasons")
    for s in a.seasons[:1]:
        rb = [i for i in items[s] if i["pos"] == "RB"]
        cells = Counter((i["k"], i["last"], i["status"] or "none") for i in rb)
        print("  %d RB cells (n >= 20 shown):" % s)
        for key, n in cells.most_common():
            if n < 20:
                continue
            sub = [i for i in rb if (i["k"], i["last"], i["status"] or "none") == key]
            print("     k=%d last=%d %-12s n=%4d appeared %.3f"
                  % (key[0], key[1], key[2], n, sum(i["appeared"] for i in sub) / n))
        thin = sum(n for n in cells.values() if n < 20)
        print("     cells with n < 20: %d cells covering %d of %d RB candidates"
              % (sum(1 for n in cells.values() if n < 20), thin, len(rb)))


if __name__ == "__main__":
    main()
