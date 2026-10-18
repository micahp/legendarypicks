#!/usr/bin/env python3
"""grade_nfl_prop_probabilities.py -- Spec B section 5, props: grade our P(over) on settled NFL props.

PRE-REGISTERED 2026-10-13, committed before it was run. Read-only: prints, and writes a CSV only if asked.

Population. Props on the dev DB exist for the 2026 season only (none for 2025), so the projection is the version 2
engine run walk-forward for 2026: each player-game from games before its week and that game's final injury
report, constants as frozen (fitted on 2024), i.e. what the job would have produced, recomputed now. It is not a
captured pre-kickoff number; the captured comparison starts with the weekly job.
  weeks      2026 regular season, weeks 2 to the last week with a final score.
  markets    receiving_yards, receptions, targets (receivers: RB, WR, TE); passing_yards, pass_attempts,
             pass_completions, passing_touchdowns (quarterbacks, only in games where he led his team in attempts
             BEFORE the target week -- pregame information, `--population pregame`, the default. The old
             post-game filter, the QB who led the team in attempts in the finished game, is retained only as
             `--population postgame` to reproduce the pre-fix number and is never a forecast population).
  books      sportsbooks only: bovada and the rotowire sportsbook feeds (betmgm, betrivers, caesars, draftkings,
             fanduel, hardrock). Pick'em sources carry a fixed price and are excluded.
  item       one per (nflverse game, player, market, book, line): the latest captured over and under at that line.
             Both sides are required; the market's P(over) is the over's implied probability with the vig removed
             multiplicatively. Lines that are whole numbers (a push is possible) are excluded and counted.
  played     the player has a box-score line in that game; otherwise the item is excluded and counted (our number
             is conditional on playing, and a book voids a prop on a player who does not play).
  outcome    actual from the box score > line. The book's own settlement (prop_results.hit) is compared and the
             disagreements counted, never used.
Our P(over) is the share of 4,000 simulated draws above the line (engine simulate / simulate_qb, seed fixed per
player-game).
Reported, per market group and overall: n items and distinct player-games; Brier of ours and of the market on the
same items; calibration in 10 bins of our P(over) (mean predicted, observed rate, n); and "our side": items where
our P(over) differs from the market's by more than 0.05, our side being over if ours is higher, its hit rate, and
the mean market probability of that side (the hit rate expected if the market is right). Items from different
books on the same player-game are not independent; the distinct player-game count is printed beside every n.
No gate.

Usage: LP_DB_PATH=... python3 grade_nfl_prop_probabilities.py --season 2026 [--csv out.csv]
"""
import argparse
import csv
import json
import math
import os
import sqlite3
import zlib
from collections import defaultdict

import nfl_player_projection_v2 as eng
import player_splits

RECEIVING = {"receiving_yards": (1, "rec_yds"), "receptions": (0, "rec"), "targets": (3, "tgt")}
PASSING = {"passing_yards": (1, "pass_yds"), "pass_attempts": (3, "att"), "pass_completions": (0, "cmp"),
           "passing_touchdowns": (2, "pass_td")}
BOOKS = ("bovada", "rotowire:betmgm-sb", "rotowire:betrivers-sb", "rotowire:caesars-sb",
         "rotowire:draftkings-sb", "rotowire:fanduel-sb", "rotowire:hardrock-sb")
N_SIMS = 4000
EDGE = 0.05


def implied(odds):
    return 100.0 / (odds + 100.0) if odds > 0 else -odds / (-odds + 100.0)


def devig(over_odds, under_odds):
    o, u = implied(over_odds), implied(under_odds)
    return o / (o + u)


def pregame_leader(hist, season, team, week):
    """The quarterback with the most attempts for this team in games BEFORE this week. Pregame information.

    This is the population the passing markets are graded on. It replaces the post-game filter (the QB who
    led the team in attempts in the finished game), which selected the population on the outcome.
    """
    tot = defaultdict(int)
    for w, rows in hist.by_team[(season, team)].items():
        if w >= week:
            continue
        for r in rows:
            if r.pos == "QB" and r.att:
                tot[r.pid] += r.att
    if not tot:
        return None
    return max(sorted(tot), key=lambda p: tot[p])


def postgame_leader(hist, season, team, week):
    """The QB who led his team in attempts in the finished game. LOOK-AHEAD; kept only to reproduce the old
    number for the before/after comparison. Never grade on this."""
    rows = hist.by_team[(season, team)].get(week, [])
    if not rows:
        return None
    return max(rows, key=lambda x: (x.att, -x.pid)).pid


def quantile(sorted_vals, q):
    k = (len(sorted_vals) - 1) * q
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def tight(p):
    return min(1.0 - 1e-9, max(1e-9, p))


def logit(p):
    p = tight(p)
    return math.log(p / (1.0 - p))


def sigmoid(z):
    if z >= 0:
        e = math.exp(-z)
        return 1.0 / (1.0 + e)
    e = math.exp(z)
    return e / (1.0 + e)


def logloss(p, y):
    p = tight(p)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def clustered(diffs, clusters):
    """Mean and 1.96 * clustered SE of per-item differences, clustered by player-game."""
    n = len(diffs)
    if not n:
        return None
    mean = sum(diffs) / n
    g = len(clusters)
    if g < 2:
        return mean, 0.0, n, g
    var = g / (g - 1.0) * sum((sum(v) - len(v) * mean) ** 2 for v in clusters.values()) / n ** 2
    return mean, 1.96 * math.sqrt(var), n, g


def collect(con, season):
    """[(nfl game id, player id, market, book, line, p_market_over, book_hit)] and exclusion counts."""
    markets = tuple(RECEIVING) + tuple(PASSING)
    rows = con.execute(
        "SELECT p.game_id, p.player_id, p.market, p.source, p.line, p.side, p.odds, p.captured_at, r.hit "
        "FROM props p JOIN prop_games g ON g.id = p.game_id LEFT JOIN prop_results r ON r.prop_id = p.id "
        "WHERE g.league = 'nfl' AND p.market IN (%s) AND p.source IN (%s) AND p.odds IS NOT NULL"
        % (",".join("?" * len(markets)), ",".join("?" * len(BOOKS))), markets + BOOKS).fetchall()
    nfl = player_splits.prop_game_nfl_ids(con, {r[0] for r in rows})
    latest = {}
    for pg, pid, market, book, line, side, odds, cap, hit in rows:
        gid = nfl.get(pg)
        if gid is None or not gid.startswith("%d_" % season):
            continue
        key = (gid, pid, market, book, float(line), side)
        if key not in latest or cap > latest[key][0]:
            latest[key] = (cap, odds, hit)
    items, skipped = [], {"whole_line": 0, "one_side": 0}
    for (gid, pid, market, book, line, side), (cap, odds, hit) in latest.items():
        if side != "over":
            continue
        under = latest.get((gid, pid, market, book, line, "under"))
        if under is None:
            skipped["one_side"] += 1
            continue
        if line == int(line):
            skipped["whole_line"] += 1
            continue
        items.append((gid, pid, market, book, line, devig(odds, under[1]), hit))
    return items, skipped


class Projector(object):
    def __init__(self, hist, params=None):
        self.hist = hist
        self.params = params
        self.cache = {}

    def draws(self, season, row, kind):
        key = (row.game_id, row.pid, kind)
        if key in self.cache:
            return self.cache[key]
        seed = zlib.crc32(("%s|%d|%s" % key).encode()) & 0xffff
        out = None
        if kind == "rec":
            v = eng.project(self.hist, season, row.week, row.pid, row.pos, row.team, row.opp, row.game_id)
            if v is not None and v.get("tgt", 0) > 0:
                out = eng.simulate(v["tgt"], v["rec"] / v["tgt"], v["rec_yds"] / v["rec"] if v["rec"] > 0 else 0.0,
                                   v["rec_td"] / v["tgt"], n=N_SIMS, seed=seed)
        else:
            v = eng.project_qb(self.hist, season, row.week, row.pid, row.team, row.opp, row.game_id,
                               p_in=self.params)
            if v is not None and v["att"] > 0:
                out = eng.simulate_qb(v["att"], v["cmp"] / v["att"], v["pass_yds"] / v["cmp"] if v["cmp"] > 0 else 0.0,
                                      v["pass_td"] / v["att"], n=N_SIMS, seed=seed)
        self.cache[key] = out
        return out


def grade(con, season, hist=None, population="pregame", marcel=False, params=None):
    """Graded items. `population` is 'pregame' (the QB who led his team in attempts before the week) or
    'postgame' (the QB who led it in the finished game; look-ahead, for the before/after comparison only)."""
    hist = hist or eng.History.load(con, [season - 1, season])
    final_weeks = {w for (w,) in con.execute(
        "SELECT DISTINCT week FROM nfl_schedule WHERE season=? AND game_type='REG' AND home_score IS NOT NULL",
        (season,))}
    items, skipped = collect(con, season)
    skipped.update({"not_played": 0, "week": 0, "no_projection": 0, "not_lead_passer": 0, "position": 0})
    proj = Projector(hist, params)
    graded, disagree = [], 0
    for gid, pid, market, book, line, p_mkt, book_hit in items:
        week = int(gid.split("_")[1])
        if week < 2 or week not in final_weeks:
            skipped["week"] += 1
            continue
        row = next((r for r in hist.by_player.get((season, pid), []) if r.game_id == gid), None)
        if row is None:
            skipped["not_played"] += 1
            continue
        if market in RECEIVING:
            if row.pos not in ("RB", "WR", "TE"):
                skipped["position"] += 1
                continue
            idx, attr = RECEIVING[market]
            kind = "rec"
        else:
            if row.pos != "QB":
                skipped["position"] += 1
                continue
            leader = (pregame_leader(hist, season, row.team, row.week) if population == "pregame"
                      else postgame_leader(hist, season, row.team, row.week))
            if leader != pid:
                skipped["not_lead_passer"] += 1
                continue
            idx, attr = PASSING[market]
            kind = "qb"
        draws = proj.draws(season, row, kind)
        if draws is None:
            skipped["no_projection"] += 1
            continue
        p_ours = sum(1 for d in draws if d[idx] > line) / len(draws)
        actual = getattr(row, attr)
        outcome = 1 if actual > line else 0
        if book_hit is not None and int(book_hit) != outcome:
            disagree += 1
        vals = sorted(d[idx] for d in draws)
        entry = {"game_id": gid, "player_id": pid, "market": market, "book": book, "line": line,
                 "p_ours": p_ours, "p_market": p_mkt, "actual": actual, "over": outcome,
                 "group": "passing" if kind == "qb" else "receiving",
                 "proj": None, "proj_marcel": None,
                 "cov80": 1 if quantile(vals, 0.1) <= actual <= quantile(vals, 0.9) else 0}
        v = eng.project_qb(hist, season, row.week, row.pid, row.team, row.opp, row.game_id, p_in=params) \
            if kind == "qb" \
            else eng.project(hist, season, row.week, row.pid, row.pos, row.team, row.opp, row.game_id)
        if v is not None:
            entry["proj"] = v.get(attr)
        if marcel:
            entry["proj_marcel"] = eng.marcel(hist, season, row.week, pid, attr)
        graded.append(entry)
    return graded, skipped, disagree


def measured(graded, label):
    """The facet numbers for one population: accuracy, probability, uncertainty, distribution."""
    n = len(graded)
    if not n:
        return None
    pg = len({(g["game_id"], g["player_id"]) for g in graded})
    base = sum(g["over"] for g in graded) / n
    out = {"label": label, "n": n, "player_games": pg, "over_rate": base,
           "brier_ours": sum((g["p_ours"] - g["over"]) ** 2 for g in graded) / n,
           "brier_market": sum((g["p_market"] - g["over"]) ** 2 for g in graded) / n,
           "brier_base": sum((base - g["over"]) ** 2 for g in graded) / n,
           "ll_ours": sum(logloss(g["p_ours"], g["over"]) for g in graded) / n,
           "ll_market": sum(logloss(g["p_market"], g["over"]) for g in graded) / n,
           "ll_base": sum(logloss(base, g["over"]) for g in graded) / n,
           "cov80": sum(g["cov80"] for g in graded) / n}
    with_proj = [g for g in graded if g.get("proj") is not None]
    out["mae_ours"] = (sum(abs(g["proj"] - g["actual"]) for g in with_proj) / len(with_proj)
                       if with_proj else None)
    with_marcel = [g for g in graded if g.get("proj_marcel") is not None and g.get("proj") is not None]
    out["mae_marcel"] = (sum(abs(g["proj_marcel"] - g["actual"]) for g in with_marcel) / len(with_marcel)
                         if with_marcel else None)
    out["n_mae_marcel"] = len(with_marcel)
    # paired, clustered by player-game
    d, cl = [], defaultdict(list)
    for g in graded:
        x = (g["p_ours"] - g["over"]) ** 2 - (g["p_market"] - g["over"]) ** 2
        d.append(x)
        cl[(g["game_id"], g["player_id"])].append(x)
    out["pair_brier_market"] = clustered(d, cl)
    d2, cl2 = [], defaultdict(list)
    for g in with_marcel:
        x = abs(g["proj"] - g["actual"]) - abs(g["proj_marcel"] - g["actual"])
        d2.append(x)
        cl2[(g["game_id"], g["player_id"])].append(x)
    out["pair_mae_marcel"] = clustered(d2, cl2) if d2 else None
    return out


def print_table(rows):
    """One row per market, every facet cell in it."""
    print("\n  %-20s %6s %6s %9s %9s %9s %8s %8s %9s %9s %7s" % (
        "market", "items", "pgames", "Brier", "mktBrier", "baseBrier", "logloss", "mktLL",
        "MAE", "marcelMAE", "cov80"))
    for r in rows:
        if not r:
            continue
        pm = r["pair_mae_marcel"]
        print("  %-20s %6d %6d %9.4f %9.4f %9.4f %8.4f %8.4f %9s %9s %7.3f" % (
            r["label"], r["n"], r["player_games"], r["brier_ours"], r["brier_market"],
            r["brier_base"], r["ll_ours"], r["ll_market"],
            ("%.3f" % r["mae_ours"]) if r["mae_ours"] is not None else "n/a",
            ("%.3f" % r["mae_marcel"]) if r["mae_marcel"] is not None else "n/a", r["cov80"]))
        if r["pair_brier_market"]:
            m, ci, nn, gg = r["pair_brier_market"]
            print("    paired Brier ours-market %+.5f +/- %.5f (n=%d, %d player-games)" % (m, ci, nn, gg))
        if pm:
            m, ci, nn, gg = pm
            print("    paired MAE ours-marcel %+.4f +/- %.4f (n=%d, %d player-games)" % (m, ci, nn, gg))


def report(graded, label):
    n = len(graded)
    if not n:
        print("%s: no items" % label)
        return
    pg = len({(g["game_id"], g["player_id"]) for g in graded})
    b_ours = sum((g["p_ours"] - g["over"]) ** 2 for g in graded) / n
    b_mkt = sum((g["p_market"] - g["over"]) ** 2 for g in graded) / n
    print("%s: %d items, %d player-games; Brier ours %.4f, market %.4f; over rate %.3f" % (
        label, n, pg, b_ours, b_mkt, sum(g["over"] for g in graded) / n))
    for b in range(10):
        lo, hi = b / 10.0, (b + 1) / 10.0
        cell = [g for g in graded if lo <= g["p_ours"] < hi or (b == 9 and g["p_ours"] == 1.0)]
        if cell:
            print("  bin %.1f-%.1f  n %5d  predicted %.3f  observed %.3f" % (
                lo, hi, len(cell), sum(g["p_ours"] for g in cell) / len(cell), sum(g["over"] for g in cell) / len(cell)))
    edge = [g for g in graded if abs(g["p_ours"] - g["p_market"]) > EDGE]
    if edge:
        hits = sum(1 for g in edge if (g["over"] == 1) == (g["p_ours"] > g["p_market"]))
        expect = sum(g["p_market"] if g["p_ours"] > g["p_market"] else 1 - g["p_market"] for g in edge) / len(edge)
        print("  our side (|ours - market| > %.2f): %d items, %d player-games, hit %.3f; market says %.3f" % (
            EDGE, len(edge), len({(g["game_id"], g["player_id"]) for g in edge}), hits / len(edge), expect))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--population", choices=("pregame", "postgame"), default="pregame",
                    help="pregame (default, corrected) or postgame (look-ahead; reproduces the old number)")
    ap.add_argument("--marcel", action="store_true", help="also project marcel-lite on the same player-games")
    ap.add_argument("--kt-att", type=float, help="override K_T_ATT (team-attempt shrinkage) for this run")
    ap.add_argument("--calibration", help="JSON of {week: [a, b]} forward Platt maps; labels items v2-platt")
    ap.add_argument("--csv")
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    params = {"K_T_ATT": a.kt_att} if a.kt_att is not None else None
    graded, skipped, disagree = grade(con, a.season, population=a.population, marcel=a.marcel, params=params)
    print("population %s%s; excluded: %s; our outcome disagrees with the book's settlement on %d graded items"
          % (a.population, ("" if a.kt_att is None else ", K_T_ATT %.1f" % a.kt_att), skipped, disagree))
    if a.calibration:
        with open(a.calibration) as fh:
            maps = {int(k): tuple(v) for k, v in json.load(fh).items()}
        for g in graded:
            w = int(g["game_id"].split("_")[1])
            ab = maps.get(w)
            g["p_raw"] = g["p_ours"]
            g["model"] = "v2-platt" if ab else "v2"
            g["calib"] = "map" if ab else "raw_no_map"
            if ab:
                g["p_ours"] = sigmoid(ab[0] * logit(g["p_ours"]) + ab[1])
        applied = [g for g in graded if g["calib"] == "map"]
        fallback = [g for g in graded if g["calib"] == "raw_no_map"]
        print("calibrated model v2-platt: %d items with a forward map, %d served raw (no map for that week: %s)"
              % (len(applied), len(fallback), sorted({g["game_id"].split("_")[1] for g in fallback}, key=int)))
        print("\n-- v2-platt, every item it served (raw fallback where a week has no map) --")
        report(graded, "v2-platt")
        rows = [measured([g for g in graded if g["market"] == m], m) for m in list(RECEIVING) + list(PASSING)]
        print_table(rows)
        graded = applied
        print("\n-- v2-platt, map applied only (%d items) --" % len(graded))
    report(graded, "all")
    for group in ("receiving", "passing"):
        report([g for g in graded if g["group"] == group], group)
    rows = [measured([g for g in graded if g["market"] == m], m) for m in list(RECEIVING) + list(PASSING)]
    print_table(rows)
    for market in list(RECEIVING) + list(PASSING):
        sub = [g for g in graded if g["market"] == market]
        if sub:
            report(sub, market)
    if a.csv and graded:
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(graded[0]))
            w.writeheader()
            w.writerows(graded)


if __name__ == "__main__":
    main()
