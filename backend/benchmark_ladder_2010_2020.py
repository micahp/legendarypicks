#!/usr/bin/env python3
"""benchmark_ladder_2010_2020.py -- the rungs of the benchmark ladder on IDENTICAL games.

Rungs (STRATEGY-forecasting-north-star, "The bar is a benchmark ladder"): coin flip, home field
only, 538 Elo, frozen v1, closing market. Read-only: the database is opened with mode=ro.

Pre-registered before the run (2026-10-13):
  Game set  Regular-season games 2010 to 2020, weeks 2 on, that `nfl_backtest.backtest_season`
            grades (the same set `market_baseline_2010_2025.py` uses), kept only when every rung
            has a probability and the game has a winner. Ties are excluded for every rung.
            Postseason games are not in the set (the backtest is REG only).
  Coin      p(home) = 0.5.
  Home      p(home) = (H + 1) / (N + 2): H home wins in N earlier non-tied, non-neutral games in
            nfl_schedule (REG, 2010 on, date order, strictly before the game's own date); a
            neutral-site game gets 0.5. A walk-forward rate with a Laplace prior; nothing from
            the game itself or later games.
  Elo       538's `elo_prob1` (team1 is the home team) from `nfl_elo_538`, joined on (game date,
            home team, away team), OAK read as LV. Where 538 lists the two teams in the other order
            (neutral-site and relocated games), the same game is found by the reversed pair and the
            probability is 1 - elo_prob1; the count is printed. A game with no Elo row either way
            FAILS the run, it is not skipped. 538 fit its constants on this history, so this rung
            is a flattering bar.
  v1, mkt   `p_model` and `p_market` from the backtest rows (frozen v1; de-vigged moneyline).
Output: per-season and pooled Brier for each rung, and the paired difference of v1 against each
other rung with a 95% bootstrap interval.

Usage: LP_DB_PATH=<dev db> venv/bin/python benchmark_ladder_2010_2020.py
"""
import os
import sqlite3
import statistics as stt

import nfl_backtest as nb
import nfl_metrics as nm

FROZEN = {"half_life": 6.0, "cap": 14.0, "cap_points": None, "sigma": 13.295}
SEASONS = range(2010, 2021)
DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")
ELO_CODE = {"OAK": "LV"}


def home_rate_by_game(con):
    """{game_id: p(home)} walk-forward, see the module docstring."""
    games = con.execute(
        "SELECT game_id, gameday, location, home_score, away_score FROM nfl_schedule "
        "WHERE game_type='REG' AND season>=2010 AND home_score IS NOT NULL "
        "ORDER BY gameday, game_id").fetchall()
    out, wins, n = {}, 0, 0
    by_day = {}
    for gid, day, loc, hs, as_ in games:
        by_day.setdefault(day, []).append((gid, (loc or "").strip().lower() == "neutral", hs, as_))
    for day in sorted(by_day):
        rate = (wins + 1) / (n + 2)
        for gid, neutral, hs, as_ in by_day[day]:
            out[gid] = 0.5 if neutral else rate
        for gid, neutral, hs, as_ in by_day[day]:
            if neutral or hs == as_:
                continue
            n += 1
            wins += 1 if hs > as_ else 0
    return out


def elo_by_game(con):
    elo = {}
    for date, t1, t2, p1 in con.execute(
            "SELECT date, team1, team2, elo_prob1 FROM nfl_elo_538 "
            "WHERE CAST(season AS INTEGER) BETWEEN 2010 AND 2020"):
        elo[(date, ELO_CODE.get(t1, t1), ELO_CODE.get(t2, t2))] = float(p1)
    return elo


def main():
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    home = home_rate_by_game(con)
    elo = elo_by_game(con)
    day = {gid: d for gid, d in con.execute(
        "SELECT game_id, gameday FROM nfl_schedule WHERE season BETWEEN 2010 AND 2020")}
    rows, missing, flipped = [], [], []
    for s in SEASONS:
        for x in nb.backtest_season(con, s, FROZEN):
            if x["outcome"] is None or x["p_market"] is None:
                continue
            key = (day[x["game_id"]], x["home"], x["away"])
            if key in elo:
                p_elo = elo[key]
            elif (key[0], key[2], key[1]) in elo:
                p_elo = 1.0 - elo[(key[0], key[2], key[1])]
                flipped.append(x["game_id"])
            else:
                missing.append(x["game_id"])
                continue
            x["p_elo"], x["p_home"] = p_elo, home[x["game_id"]]
            rows.append(x)
    if missing:
        raise SystemExit("FAIL: %d graded games have no 538 Elo row, e.g. %s" % (len(missing), missing[:5]))
    rungs = [("coin flip", lambda x: 0.5), ("home field only", lambda x: x["p_home"]),
             ("538 Elo", lambda x: x["p_elo"]), ("v1", lambda x: x["p_model"]),
             ("closing market", lambda x: x["p_market"])]

    def brier(rs, f):
        return [(f(x) - x["outcome"]) ** 2 for x in rs]

    def table(name, rs):
        print("%-10s n=%-5d " % (name, len(rs)) + "  ".join(
            "%s %.4f" % (n, stt.mean(brier(rs, f))) for n, f in rungs))

    for s in SEASONS:
        table(str(s), [x for x in rows if x["season"] == s])
    table("2010-2020", rows)
    print("\npaired difference, v1 minus rung (negative = v1 better), 95% bootstrap interval:")
    v1 = brier(rows, rungs[3][1])
    for n, f in rungs:
        if n == "v1":
            continue
        pt, lo, hi = nm.bootstrap_mean_diff_ci(v1, brier(rows, f), reps=5000)
        print("  v1 - %-16s %+.4f [%+.4f, %+.4f]" % (n, pt, lo, hi))
    print("\n538 rows matched on the reversed team order: %d %s" % (len(flipped), flipped))
    print("home rate at the end: %.4f; games: %d" % (stt.mean(x["p_home"] for x in rows), len(rows)))


if __name__ == "__main__":
    main()
