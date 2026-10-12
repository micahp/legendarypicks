#!/usr/bin/env python3
"""nfl_ladder.py -- the benchmark ladder (north star stage 1) and the season-start (carryover)
sweep for v1. Read-only: the database is opened with mode=ro and nothing is recorded.

PRE-REGISTERED 2026-10-12, before any run of this file.

--ladder: identical games = REG games of 2011-2020 that v1 grades (weeks 2 and later; v1 makes no
  week 1 forecast), with an outcome (no tie), a de-vigged moneyline and a 538 Elo row joined on
  (season, home, away). Rungs, Brier on those games:
  - coin flip 0.5
  - home field: share of home wins (ties dropped, neutral games excluded) over every REG game of
    seasons 2010 to S-1 in nfl_schedule; 0.5 at a neutral site
  - 538 Elo: nfl_elo_538.elo_prob1
  - v1: frozen walk-forward p_model (nfl_feature_backtest.FROZEN)
  - B: v1 recalibrated by the stack (nfl_feature_backtest.stack, no feature columns)
  - market: de-vigged moneyline
  Paired bootstrap (5,000) of v1 - Elo, B - Elo and Elo - market, pooled and by week bucket
  2-4, 5-8, 9+. 538 Elo's week 1 Brier is printed alone, since v1 has no week 1 forecast.

--carryover: v1 with shrink in {0.2, 1/3, 0.5, 2/3} x prior_games in {2, 4, 8} (12 configs;
  the current v1 is shrink 1/3, prior_games 4). Other parameters as FROZEN. Each config's B (the
  stack, no feature columns) is graded on the nfl_feature_backtest groups: 2011-2023 pooled,
  2024, 2025. Selection: the config with the lowest pooled 2011-2023 B Brier. It replaces the
  current v1 only if its paired difference against the current config has a pooled 2011-2023
  interval entirely below zero AND the 2024 and 2025 point differences are not above zero. The
  2011-2023 interval of the selected config is optimistic (it was chosen on those games); 2024 is
  the honest check. Weeks 2-4 are also reported, since that is where the gap sits.

Usage: LP_DB_PATH=<dev db> venv/bin/python nfl_ladder.py --ladder | --carryover
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

import nfl_backtest as nb
import nfl_feature_backtest as fb
import nfl_metrics as nm
from team_codes import normalize

REPS = 5000
BUCKETS = (("weeks 2-4", 2, 4), ("weeks 5-8", 5, 8), ("weeks 9+", 9, 99))
SHRINKS = (0.2, 1.0 / 3.0, 0.5, 2.0 / 3.0)
PRIOR_GAMES = (2.0, 4.0, 8.0)


def rows_for(con, overrides=None):
    p = dict(fb.FROZEN)
    p.update(overrides or {})
    out = []
    for s in fb.SEASONS:
        out += nb.backtest_season(con, s, p)
    return out


def home_rates(con):
    """season -> home win share over REG games of 2010 to season - 1 (ties, neutral excluded)."""
    by = {}
    for s, hs, as_, loc in con.execute(
            "SELECT season, home_score, away_score, location FROM nfl_schedule "
            "WHERE game_type = 'REG' AND home_score IS NOT NULL AND away_score IS NOT NULL"):
        if (loc or "").strip().lower() == "neutral" or hs == as_:
            continue
        w, n = by.get(int(s), (0, 0))
        by[int(s)] = (w + (1 if hs > as_ else 0), n + 1)
    out = {}
    for s in range(2011, 2026):
        w = sum(by[x][0] for x in by if x < s)
        n = sum(by[x][1] for x in by if x < s)
        out[s] = w / float(n)
    return out


def elo_probs(con):
    elo = {}
    for season, t1, t2, p in con.execute(
            "SELECT season, team1, team2, elo_prob1 FROM nfl_elo_538 "
            "WHERE playoff = '0' AND CAST(season AS INTEGER) BETWEEN 2011 AND 2020"):
        elo[(int(season), normalize("nfl", t1), normalize("nfl", t2))] = float(p)
    return elo


def diff(a, b, label):
    lo_hi = nm.bootstrap_mean_diff_ci(a, b, reps=REPS)
    return "%s %+.4f [%+.4f,%+.4f]" % (label, *lo_hi)


def ladder(con):
    rows = rows_for(con)
    base = fb.stack(rows)
    elo = elo_probs(con)
    hr = home_rates(con)
    g = [r for r in rows if 2011 <= r["season"] <= 2020 and r["p_market"] is not None
         and r["outcome"] is not None]
    j = [r for r in g if (r["season"], r["home"], r["away"]) in elo]
    print("graded v1 games 2011-2020 with a moneyline %d, joined to 538 %d, unjoined %d"
          % (len(g), len(j), len(g) - len(j)))

    def report(sub, name):
        y = [r["outcome"] for r in sub]
        b = lambda ps: [(p - o) ** 2 for p, o in zip(ps, y)]
        coin = b([0.5] * len(sub))
        home = b([0.5 if r["neutral"] else hr[r["season"]] for r in sub])
        e = b([elo[(r["season"], r["home"], r["away"])] for r in sub])
        v1 = b([r["p_model"] for r in sub])
        bb = b([base[r["game_id"]][1] for r in sub])
        mk = b([r["p_market"] for r in sub])
        m = lambda x: sum(x) / len(x)
        print("%-10s n=%4d Brier coin %.4f home %.4f elo %.4f v1 %.4f B %.4f market %.4f"
              % (name, len(sub), m(coin), m(home), m(e), m(v1), m(bb), m(mk)))
        print("%-10s        %s | %s | %s | %s" % ("", diff(v1, e, "v1-elo"), diff(bb, e, "B-elo"),
                                                  diff(home, e, "home-elo"),
                                                  diff(e, mk, "elo-mkt")))
    report(j, "2011-2020")
    for name, lo, hi in BUCKETS:
        report([r for r in j if lo <= r["week"] <= hi], name)
    print("note: v1 makes no week 1 forecast, so week 1 games are not in these rows.")


def carryover(con):
    groups = fb.GROUPS
    results = {}
    for sh in SHRINKS:
        for pg in PRIOR_GAMES:
            rows = rows_for(con, {"shrink": sh, "prior_games": pg})
            base = fb.stack(rows)
            gr = fb.graded(rows)
            results[(sh, pg)] = {r["game_id"]: ((base[r["game_id"]][1] - r["outcome"]) ** 2,
                                                r["season"], r["week"]) for r in gr}
            print("ran shrink %.3f prior_games %.0f" % (sh, pg), flush=True)
    cur = results[(1.0 / 3.0, 4.0)]
    ids = sorted(cur)

    def sel(res, seasons, wk=None):
        return [res[i][0] for i in ids if res[i][1] in seasons
                and (wk is None or wk[0] <= res[i][2] <= wk[1])]
    print("\nconfig                  B Brier 2011-23  2024    2025    weeks 2-4 (2011-23)")
    for k in sorted(results):
        res = results[k]
        print("shrink %.3f games %.0f   %.4f          %.4f  %.4f  %.4f" % (
            k[0], k[1], *(sum(x) / len(x) for x in (
                sel(res, groups[0][1]), sel(res, groups[1][1]), sel(res, groups[2][1]),
                sel(res, groups[0][1], (2, 4))))))
    best = min(results, key=lambda k: sum(sel(results[k], groups[0][1])))
    print("\nselected: shrink %.3f prior_games %.0f (current: shrink 0.333 prior_games 4)" % best)
    for name, seasons in groups:
        print("  %-9s %s" % (name, diff(sel(results[best], seasons), sel(cur, seasons),
                                       "selected-current")))
    print("  %-9s %s" % ("wk 2-4", diff(sel(results[best], groups[0][1], (2, 4)),
                                        sel(cur, groups[0][1], (2, 4)), "selected-current")))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ladder", action="store_true")
    g.add_argument("--carryover", action="store_true")
    a = ap.parse_args(argv)
    con = sqlite3.connect("file:%s?mode=ro" % fb.DB, uri=True)
    if a.ladder:
        ladder(con)
    else:
        carryover(con)
    return 0


if __name__ == "__main__":
    sys.exit(main())
