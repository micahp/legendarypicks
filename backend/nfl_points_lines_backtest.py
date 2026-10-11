#!/usr/bin/env python3
"""nfl_points_lines_backtest.py -- projected points graded against the closing spread and the
closing total, with and without a QB adjustment and an injury adjustment. Read-only: the
database is opened with mode=ro, nothing is recorded, nothing is locked.

PRE-REGISTERED 2026-10-11, committed before any run of this file.

Projections
- Base rows: frozen v1 walk-forward (nfl_feature_backtest.base_rows), 2010-2025.
- Two stacks per target season S, fitted on rows of seasons 2010 to S-1 only:
    margin: actual home margin on [1, v1 projected margin, margin columns]
    total:  actual total       on [1, v1 projected total,  total columns]
  sigma_M and sigma_T are the residual sds (ddof 1) of those fits. Projected points:
  home = (T + M) / 2, away = (T - M) / 2.
- Models: v1 (frozen, unstacked; sigma_M 13.295, sigma_T = sd of its own total residuals on
  seasons before S), B (stacks with no columns), MP (market_prior column in the margin stack,
  as in nfl_feature_backtest), QBE and QBA (below), INJ (below).

Grading against the lines (each market reported separately)
- Spread: home covers when actual margin > spread_line. Push (equal) excluded and counted.
  q_cover = Phi((M - spread_line) / sigma_M). Pick home when M > spread_line (M equal to the
  line: no pick, counted). Hit rate = share of picks that win. Brier(q_cover) is compared with
  the line's own probability 0.5 by a paired bootstrap of Brier(q) - 0.25; negative means the
  projection beats the line. Hit rate has a bootstrap interval; the line cannot be "picked",
  so hit rate is reported against 50% and against 52.38% (the -110 break-even).
- Total: over when actual total > total_line, push excluded. q_over = 1 - Phi((total_line - T)
  / sigma_T). Same grading.
- Win Brier against the de-vigged moneyline (as before) is reported for the margin.
- Groups: 2011-2023 (development), 2024-2025 (confirmation). 5,000 paired resamples.

QB adjustment (built from nfl_pbp and nfl_schedule.home_qb_id / away_qb_id)
- Dropback: nfl_pbp pass_attempt = 1 with passer_player_id and epa (sacks included).
- Replacement level R(S): dropback-weighted mean EPA per dropback over all (QB, season) pairs
  with fewer than 200 dropbacks in seasons S-3..S-1. For 2010 (training only) the window is
  2010 itself, a disclosed in-sample choice that touches training rows only.
- QB rate at (S, w): (sum EPA + 200 * R(S)) / (dropbacks + 200) over the QB's dropbacks in
  seasons S-2 and S-1 and in season S weeks < w.
- Team baseline at (S, w): dropback-weighted mean of the rates of the QBs who threw the team's
  dropbacks in its last 8 REG games before (S, w), crossing seasons. No earlier game: column 0.
- QBE (expected starter): the team's starter (schedule qb id) in its previous REG game. From
  2024 on, if that QB is listed Out or Doubtful in injury_reports for (S, w, team), he is
  replaced by the team's other QB with the most dropbacks in those 8 games, else by R(S).
- QBA (actual starter, hindsight): the schedule qb id of the game itself. History records the
  actual starter after the fact; this variant is a proxy for information known 90 minutes
  before kickoff and is labelled hindsight.
- adj = rate(expected) - baseline per team. Columns: margin adj_home - adj_away, total
  adj_home + adj_away.
- Keep rule (as in nfl_feature_backtest): pooled 2011-2023 win-Brier F - B interval below zero
  and 2024-2025 point estimate not above zero. Cover and over Brier F - B are reported with
  intervals too.

Injury adjustment (2024-2025 only, the seasons with injury_reports)
- A team-week's load = sum, over non-QB players listed Out or Doubtful for (S, w, team), of the
  player's share of the team's touches (targets as receiver_player_id on pass plays plus
  carries as rusher_player_id with rush_attempt = 1) in weeks < w of season S. Players with 10
  or more dropbacks as passer for the team in those weeks are excluded (QBs are the QB term).
  Offensive line and defense are not covered: no per-week snap data for 2024 in the dev DB.
- Columns: margin load_home - load_away, total load_home + load_away, added to B.
  Coefficients are cross-fitted: 2025's from 2024's residuals of B, 2024's from 2025's (OLS
  without intercept). Two seasons only; reported as such.

Usage: LP_DB_PATH=<dev db> venv/bin/python nfl_points_lines_backtest.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from collections import defaultdict

import numpy as np

import nfl_feature_backtest as fb
import nfl_metrics as nm

DB = fb.DB
REPS = 5000
GROUPS = (("2011-2023", range(2011, 2024)), ("2024-2025", (2024, 2025)))
SEASONS = fb.SEASONS
phi = fb.phi


def stack2(rows, mcols=None, tcols=None):
    """game_id -> (M, sigma_M, T, sigma_T) for seasons 2011-2025."""
    out = {}
    for s in SEASONS[1:]:
        tr = [r for r in rows if r["season"] < s]
        te = [r for r in rows if r["season"] == s]
        res = {}
        for key, proj, act, cols in (("M", "proj_margin", "actual_margin", mcols),
                                     ("T", "proj_total", "actual_total", tcols)):
            def x(r):
                return [1.0, r[proj]] + (list(cols[r["game_id"]]) if cols else [])
            X = np.array([x(r) for r in tr])
            y = np.array([r[act] for r in tr])
            beta = fb.ols(X, y)
            sd = float(np.std(y - X @ beta, ddof=1))
            res[key] = ({r["game_id"]: float(np.dot(x(r), beta)) for r in te}, sd)
        for r in te:
            g = r["game_id"]
            out[g] = (res["M"][0][g], res["M"][1], res["T"][0][g], res["T"][1])
    return out


def v1_model(rows):
    out = {}
    for s in SEASONS[1:]:
        tr = [r for r in rows if r["season"] < s]
        sdt = float(np.std([r["actual_total"] - r["proj_total"] for r in tr], ddof=1))
        for r in (r for r in rows if r["season"] == s):
            out[r["game_id"]] = (r["proj_margin"], 13.295, r["proj_total"], sdt)
    return out


def ci(a, b):
    return nm.bootstrap_mean_diff_ci(a, b, reps=REPS)


def market_lines(g, mod):
    """Per-market grading of one model on game set g."""
    out = {}
    for name, line, act, k, sk in (("spread", "spread_line", "actual_margin", 0, 1),
                                   ("total", "total_line", "actual_total", 2, 3)):
        gg = [r for r in g if r[line] is not None]
        push = [r for r in gg if r[act] == float(r[line])]
        gg = [r for r in gg if r[act] != float(r[line])]
        y = [1 if r[act] > float(r[line]) else 0 for r in gg]
        q = [1.0 - phi((float(r[line]) - mod[r["game_id"]][k]) / mod[r["game_id"]][sk])
             for r in gg]
        bq = [(p - o) ** 2 for p, o in zip(q, y)]
        picks = [(1 if mod[r["game_id"]][k] > float(r[line]) else 0, o)
                 for r, o in zip(gg, y) if mod[r["game_id"]][k] != float(r[line])]
        hits = [1.0 if p == o else 0.0 for p, o in picks]
        out[name] = {"n": len(gg), "push": len(push), "bq": bq, "hits": hits,
                     "nopick": len(gg) - len(picks)}
    return out


def report(rows, models, base_name="B"):
    for gname, seasons in GROUPS:
        g = [r for r in rows if r["season"] in seasons and r["actual_margin"] is not None]
        print("== %s" % gname)
        lines = {k: market_lines(g, m) for k, m in models.items()}
        for k in models:
            for mk in ("spread", "total"):
                L = lines[k][mk]
                n = len(L["hits"])
                hr = sum(L["hits"]) / n
                _, lo, hi = ci(L["hits"], [0.0] * n)
                d = ci(L["bq"], [0.25] * len(L["bq"]))
                extra = ""
                if k != base_name:
                    e = ci(L["bq"], lines[base_name][mk]["bq"])
                    extra = " | Brier vs %s %+.4f [%+.4f,%+.4f]" % (base_name, *e)
                print("  %-4s %-6s n %4d push %3d nopick %2d | hit %.4f [%.4f,%.4f] | Brier "
                      "%.4f vs line(0.25) %+.4f [%+.4f,%+.4f]%s"
                      % (k, mk, L["n"], L["push"], L["nopick"], hr, lo, hi,
                         sum(L["bq"]) / len(L["bq"]), *d, extra))
            mm = [r for r in g if r["p_market"] is not None and r["outcome"] is not None]
            m = models[k]
            bw = [(phi(m[r["game_id"]][0] / m[r["game_id"]][1]) - r["outcome"]) ** 2 for r in mm]
            bk = [(r["p_market"] - r["outcome"]) ** 2 for r in mm]
            line = "  %-4s win    n %4d Brier %.4f vs moneyline %+.4f [%+.4f,%+.4f]" % (
                k, len(mm), sum(bw) / len(bw), *ci(bw, bk))
            if k != base_name:
                b = models[base_name]
                bb = [(phi(b[r["game_id"]][0] / b[r["game_id"]][1]) - r["outcome"]) ** 2
                      for r in mm]
                line += " | vs %s %+.4f [%+.4f,%+.4f]" % (base_name, *ci(bw, bb))
                em = [abs(m[r["game_id"]][0] - r["actual_margin"]) for r in g]
                eb = [abs(b[r["game_id"]][0] - r["actual_margin"]) for r in g]
                et = [abs(m[r["game_id"]][2] - r["actual_total"]) for r in g]
                ebt = [abs(b[r["game_id"]][2] - r["actual_total"]) for r in g]
                line += " | margin MAE vs %s %+.3f [%+.3f,%+.3f] total MAE %+.3f [%+.3f,%+.3f]" % (
                    base_name, *ci(em, eb), *ci(et, ebt))
            print(line)


# ---------------------------------------------------------------- QB adjustment

def qb_columns(con, rows, actual):
    agg = defaultdict(lambda: [0, 0.0])          # (season, week, team, qb) -> [n, sum]
    for s, w, t, q, n, e in con.execute(
            "SELECT season, week, posteam, passer_player_id, COUNT(*), SUM(epa) FROM nfl_pbp "
            "WHERE pass_attempt = 1 AND passer_player_id IS NOT NULL AND epa IS NOT NULL "
            "AND posteam IS NOT NULL AND season BETWEEN 2008 AND 2025 GROUP BY 1, 2, 3, 4"):
        agg[(s, w, t, q)] = [n, e]
    by_qb = defaultdict(list)                     # qb -> [(season, week, n, sum)]
    season_qb = defaultdict(lambda: [0, 0.0])     # (season, qb) -> [n, sum]
    for (s, w, t, q), (n, e) in agg.items():
        by_qb[q].append((s, w, n, e))
        season_qb[(s, q)][0] += n
        season_qb[(s, q)][1] += e

    by_team_week = defaultdict(list)              # (season, week, team) -> [(qb, n)]
    for (s, w, t, q), (n, e) in agg.items():
        by_team_week[(s, w, t)].append((q, n))

    def repl(S):
        win = range(S - 3, S) if S > 2010 else (2010,)
        n = sum(v[0] for (s, q), v in season_qb.items() if s in win and v[0] < 200)
        e = sum(v[1] for (s, q), v in season_qb.items() if s in win and v[0] < 200)
        return e / n
    R = {S: repl(S) for S in SEASONS}

    def rate(q, S, w):
        n, e = 0, 0.0
        for s, wk, nn, ee in by_qb.get(q, ()):
            if s in (S - 2, S - 1) or (s == S and wk < w):
                n += nn
                e += ee
        return (e + 200.0 * R[S]) / (n + 200.0)

    games = con.execute(
        "SELECT season, week, game_id, home_team, away_team, home_qb_id, away_qb_id "
        "FROM nfl_schedule WHERE game_type = 'REG' AND season BETWEEN 2010 AND 2025 "
        "ORDER BY season, week, game_id").fetchall()
    team_hist = defaultdict(list)                 # team -> [(season, week, qb)]
    inj = set()
    for s, w, t, g in con.execute(
            "SELECT season, week, team, gsis_id FROM injury_reports WHERE league = 'nfl' "
            "AND season >= 2024 AND report_status IN ('Out', 'Doubtful')"):
        inj.add((s, w, t, g))
    want = {r["game_id"] for r in rows}
    cols_m, cols_t, changes = {}, {}, {"expected_ne_prev": 0, "injury_replaced": 0, "n": 0}
    for s, w, gid, h, a, hq, aq in games:
        adj = {}
        for team, q_now in ((h, hq), (a, aq)):
            hist = team_hist[team][-8:]
            if not hist:
                adj[team] = 0.0
                continue
            dropq = defaultdict(int)
            for hs, hw, _ in hist:
                for q2, n2 in by_team_week.get((hs, hw, team), ()):
                    dropq[q2] += n2
            tot = sum(dropq.values())
            if tot == 0:
                adj[team] = 0.0
                continue
            base = sum(n * rate(q, s, w) for q, n in dropq.items()) / tot
            if actual:
                exp_q = q_now
            else:
                exp_q = hist[-1][2]
                if s >= 2024 and (s, w, team, exp_q) in inj:
                    others = [(n, q) for q, n in dropq.items() if q != exp_q]
                    exp_q = max(others)[1] if others else None
                    changes["injury_replaced"] += 1
            if gid in want and s >= 2011:
                changes["n"] += 1
                changes["expected_ne_prev"] += int(q_now != hist[-1][2])
            adj[team] = (rate(exp_q, s, w) if exp_q else R[s]) - base
        cols_m[gid] = [adj[h] - adj[a]]
        cols_t[gid] = [adj[h] + adj[a]]
        team_hist[h].append((s, w, hq))
        team_hist[a].append((s, w, aq))
    cols_m = fb._complete(rows, cols_m)
    return cols_m, cols_t, changes


# ---------------------------------------------------------------- injury adjustment

def injury_model(con, rows, B):
    load = {}
    for S in (2024, 2025):
        touch = defaultdict(lambda: defaultdict(float))   # (team, week) -> player -> touches
        passers = defaultdict(lambda: defaultdict(int))
        for w, t, rec, rus, pa, ra, ps in con.execute(
                "SELECT week, posteam, receiver_player_id, rusher_player_id, pass_attempt, "
                "rush_attempt, passer_player_id FROM nfl_pbp WHERE season = ? AND posteam IS NOT NULL",
                (S,)):
            if pa == 1 and rec:
                touch[(t, w)][rec] += 1
            if ra == 1 and rus:
                touch[(t, w)][rus] += 1
            if pa == 1 and ps:
                passers[(t, w)][ps] += 1
        listed = defaultdict(set)
        for w, t, g in con.execute(
                "SELECT week, team, gsis_id FROM injury_reports WHERE league = 'nfl' AND "
                "season = ? AND report_status IN ('Out', 'Doubtful')", (S,)):
            listed[(t, w)].add(g)
        for gid, w, h, a in con.execute(
                "SELECT game_id, week, home_team, away_team FROM nfl_schedule WHERE season = ? "
                "AND game_type = 'REG'", (S,)):
            v = {}
            for t in (h, a):
                tt, pp = defaultdict(float), defaultdict(int)
                for (t2, w2), d in touch.items():
                    if t2 == t and w2 < w:
                        for p, n in d.items():
                            tt[p] += n
                for (t2, w2), d in passers.items():
                    if t2 == t and w2 < w:
                        for p, n in d.items():
                            pp[p] += n
                tot = sum(tt.values())
                v[t] = 0.0 if tot == 0 else sum(
                    tt[p] for p in listed[(t, w)] if pp[p] < 10) / tot
            load[gid] = (v[h] - v[a], v[h] + v[a])
    out = dict(B)
    stats = {}
    for S, other in ((2024, 2025), (2025, 2024)):
        tr = [r for r in rows if r["season"] == other and r["game_id"] in load]
        cm = sum(load[r["game_id"]][0] * (r["actual_margin"] - B[r["game_id"]][0]) for r in tr) / \
            sum(load[r["game_id"]][0] ** 2 for r in tr)
        ct = sum(load[r["game_id"]][1] * (r["actual_total"] - B[r["game_id"]][2]) for r in tr) / \
            sum(load[r["game_id"]][1] ** 2 for r in tr)
        stats[S] = (cm, ct)
        for r in (r for r in rows if r["season"] == S):
            m, sm, t, st = B[r["game_id"]]
            lm, lt = load.get(r["game_id"], (0.0, 0.0))
            out[r["game_id"]] = (m + cm * lm, sm, t + ct * lt, st)
    nz = sum(1 for r in rows if r["season"] >= 2024 and load.get(r["game_id"], (0, 0))[1] > 0)
    return out, stats, nz


def main():
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    rows = [r for r in fb.base_rows(con) if r["actual_margin"] is not None]
    B = stack2(rows)
    mp, _ = fb.market_prior(con, rows)
    models = {"B": B, "v1": v1_model(rows), "MP": stack2(rows, mp)}
    qe_m, qe_t, ch_e = qb_columns(con, rows, actual=False)
    qa_m, qa_t, _ = qb_columns(con, rows, actual=True)
    print("QB expected-starter checks (graded rows):", ch_e)
    models["QBE"] = stack2(rows, qe_m, qe_t)
    models["QBA"] = stack2(rows, qa_m, qa_t)
    inj, stats, nz = injury_model(con, rows, B)
    print("injury coefficients (margin, total) by season:", stats,
          "| 2024-2025 games with any listed non-QB load:", nz)
    models["INJ"] = inj
    report(rows, models)
    return 0


if __name__ == "__main__":
    sys.exit(main())
