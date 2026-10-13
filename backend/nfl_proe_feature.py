#!/usr/bin/env python3
"""nfl_proe_feature.py -- pass rate over expected (PROE) as a candidate feature.

xpass is nflverse's expected pass probability for a play, pass_oe the pass over expected in percentage points
(100 x (pass - xpass)). Both were backfilled onto nfl_pbp for 2010 to 2025 by backfill_nfl_pbp_proe.py (2026-10-13).
PROE says how much more (or less) a team passes than its situation predicts, a style marker that the earlier features
(EPA, success rate, CPOE, turnover and penalty rates) do not carry.

Plumbing is `nfl_feature_backtest.py` unchanged (`stack`, `report`, the shared KEEP rule and groups). This file only
registers features with its `@feature` decorator. Every shared rule there applies.

PRE-REGISTERED (written 2026-10-13 before the first run of this file)

Records: per team-game from nfl_pbp by the team that had the ball: n = plays with a pass_oe value, s = their sum.
proe_net: two columns. (1) offense PROE difference: a team's offense PROE = (sum + 200 x league) / (n + 200) over its
last 8 team games strictly before the game (the window crosses season boundaries, as in the pressure features),
league = the same mean pooled over every team-game of the SAME season strictly before the game; column = home minus
away. (2) PROE faced difference: the same quantity computed on the opponents' offense in those games (how far
opponents pass above expectation against that defense); column = home minus away. No expected sign is registered for
either column; the keep rule does not need one.
Alone: proe_net as two columns in the stack on frozen v1, judged against the plain stack B with the shared KEEP rule
(pooled 2011-2023 interval of Brier(F) - Brier(B) entirely below zero, and the 2024 and 2025 point differences not
above zero).
On top of Elo: elo_plus_proe adds the same two columns to the stack that already holds `elo_diff`
(nfl_elo_replica.elo_diff, the fourth model on the Model tab), judged against the Elo stack.
This is the fifth and sixth test run on seasons earlier work has already used; it is reported as is, and a pass would be
weaker evidence than the first feature's.

Usage: LP_DB_PATH=<dev db> venv/bin/python nfl_proe_feature.py --feature proe_net|elo_plus_proe
"""
from __future__ import annotations

import argparse
import bisect
import sqlite3
import sys

import nfl_elo_replica as er
import nfl_feature_backtest as fb

WIN = 8
K = 200.0


def _records(con):
    recs, per_team, games, by_season = {}, {}, {}, {}
    q = ("SELECT season, week, game_id, posteam, COUNT(pass_oe), COALESCE(SUM(pass_oe), 0.0) FROM nfl_pbp "
         "WHERE season BETWEEN 2010 AND 2025 AND posteam IS NOT NULL AND pass_oe IS NOT NULL "
         "GROUP BY season, week, game_id, posteam")
    for s, w, g, t, n, sm in con.execute(q):
        key = (int(s), int(w), g)
        recs[(g, t)] = (key, n, sm)
        per_team.setdefault(t, []).append(key)
        games.setdefault(g, []).append(t)
        by_season.setdefault(int(s), []).append((key, n, sm))
    for t in per_team:
        per_team[t].sort()
    opp = {}
    for g, ts in games.items():
        if len(ts) == 2:
            opp[(g, ts[0])], opp[(g, ts[1])] = ts[1], ts[0]
    cum = {}
    for s, rs in by_season.items():
        rs.sort(key=lambda r: r[0])
        c = [(0, 0.0)]
        for r in rs:
            c.append((c[-1][0] + r[1], c[-1][1] + r[2]))
        cum[s] = ([r[0] for r in rs], c)
    return recs, per_team, opp, cum


def proe_columns(con, rows):
    recs, per_team, opp, cum = _records(con)
    cols = {}
    for r in rows:
        s, w = int(r["season"]), int(r["week"])
        cutoff = (s, w, "")
        keys, c = cum[s]
        n_lg, s_lg = c[bisect.bisect_left(keys, cutoff)]
        if n_lg == 0:
            raise ValueError("no same-season league history before %s" % r["game_id"])
        league = s_lg / n_lg

        def rate(team, own):
            ks = per_team[team]
            j = bisect.bisect_left(ks, cutoff)
            n = tot = 0.0
            for k in ks[max(0, j - WIN):j]:
                x = recs.get((k[2], team if own else opp.get((k[2], team))))
                if x is not None:
                    n += x[1]; tot += x[2]
            return (tot + K * league) / (n + K)
        h, a = r["home"], r["away"]
        cols[r["game_id"]] = [rate(h, True) - rate(a, True), rate(h, False) - rate(a, False)]
    return fb._complete(rows, cols)


def _join(*parts):
    out = {}
    for p in parts:
        for k, v in p.items():
            out[k] = out.get(k, []) + list(v)
    return out


@fb.feature
def proe_net(con, rows):
    return proe_columns(con, rows), None


@fb.feature
def elo_plus_proe(con, rows):
    return _join(er.elo_diff(con, rows)[0], proe_columns(con, rows)), None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--feature", required=True, choices=["proe_net", "elo_plus_proe"])
    a = ap.parse_args(argv)
    con = sqlite3.connect("file:%s?mode=ro" % fb.DB, uri=True)
    rows = fb.base_rows(con)
    if a.feature == "elo_plus_proe":
        base = fb.stack(rows, er.elo_diff(con, rows)[0])
        label = "elo_plus_proe (F = Elo stack + columns, B = Elo stack)"
    else:
        base, label = fb.stack(rows), "proe_net"
    cols, sigma_fn = fb.FEATURES[a.feature](con, rows)
    fb.report(rows, base, fb.stack(rows, cols, sigma_fn), label)
    return 0


if __name__ == "__main__":
    sys.exit(main())
