#!/usr/bin/env python3
"""nfl_backfill_features.py -- features built on the 2026-10-11 history backfill
(nfl_hist_injuries, nfl_hist_snap_counts, nfl_hist_depth_charts, nfl_hist_player_ids,
nfl_elo_538), graded against the closing moneyline, spread and total. Read-only on the DB.

PRE-REGISTERED 2026-10-11, committed before any run of this file. Plan:
docs/PLAN-nfl-data-backfill-2026-10-11.md.

Shared machinery: nfl_points_lines_backtest (stack2, report: margin and total stacks fitted on
seasons before S; cover and over Brier against the line's 0.5, hit rates, pushes counted; win
Brier against the de-vigged moneyline; paired bootstraps of 5,000). Groups: 2011-2023
(development), 2024 (confirmation), 2025 (second look; it was v1's holdout).

QBI (QB with injury-aware expected starter)
- Expected starter for (S, w, team) = the team's starter (schedule qb id) in its previous REG
  game. If that QB is listed Out or Doubtful in nfl_hist_injuries for (S, w, team), he is
  replaced by the unique QB1 of the depth chart labelled week w other than him, else the unique
  QB2 of that chart other than him, else replacement level R(S).
  Why this rule: on 2011-2023 it names the actual starter in 90.87% of team-games, against
  88.64% for the previous starter alone and 90.31% for depth-chart QB1 alone (measured on
  starter identity only, before any outcome or line was looked at). The depth chart labelled w
  is used, not w + 1: label w + 1 matches actual starters better, but its publication time is
  not recorded and the starter-change test cannot rule out that it is written after game w.
- QB rate, team baseline and replacement level exactly as QBE in nfl_points_lines_backtest
  (200-dropback shrink toward R(S), last 8 team games, columns adj_h - adj_a and adj_h + adj_a).

AVAIL (snap-weighted availability, 2013 onward)
- Listed: nfl_hist_injuries REG rows for (S, w, team) with report_status Out or Doubtful and
  position not QB. gsis_id -> pfr_id through nfl_hist_player_ids; unmapped listings counted.
- A listed player's offensive share = mean of offense_pct over the team's last 4 REG games
  before (S, w) that have snap rows (0 for a game he has no row in); defensive share the same
  with defense_pct. Team load_off = sum of offensive shares, load_def = sum of defensive.
- Columns: margin [off_h - off_a, def_h - def_a]; total [off_h + off_a, def_h + def_a].
  A team with no snap history (before 2013) gets 0; the count of such team-games is printed.

OWN = QBI + AVAIL + epa_units (nfl_feature_backtest, margin only). OWN_MP = OWN + market_prior.

Keep rule (per term): pooled 2011-2023 win Brier (F - B) interval entirely below zero, and the
2024 point difference not above zero. "Beats the line" means: cover (or over) Brier minus 0.25
interval entirely below zero, or win Brier minus moneyline interval entirely below zero.

ELO538 benchmark: FiveThirtyEight's archived elo_prob1 (team1 = home), REG games 2011-2020,
joined on season and home/away codes; win Brier against the moneyline and against B on the
games that join. Unjoined games are counted.

FTN tendencies are NOT tested: FTN starts in 2022, leaving one development season (2023) to
grade after one season of training. Stated, not run.

Usage: LP_DB_PATH=<dev db> venv/bin/python nfl_backfill_features.py
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict

import numpy as np

import nfl_feature_backtest as fb
import nfl_metrics as nm
import nfl_points_lines_backtest as plb
from team_codes import normalize

plb.GROUPS = (("2011-2023", range(2011, 2024)), ("2024", (2024,)), ("2025", (2025,)))
SEASONS = fb.SEASONS
OUT = ("Out", "Doubtful")


def qbi_columns(con, rows):
    agg = defaultdict(lambda: [0, 0.0])
    for s, w, t, q, n, e in con.execute(
            "SELECT season, week, posteam, passer_player_id, COUNT(*), SUM(epa) FROM nfl_pbp "
            "WHERE pass_attempt = 1 AND passer_player_id IS NOT NULL AND epa IS NOT NULL "
            "AND posteam IS NOT NULL AND season BETWEEN 2008 AND 2025 GROUP BY 1, 2, 3, 4"):
        agg[(s, w, t, q)] = [n, e]
    by_qb, season_qb, by_tw = defaultdict(list), defaultdict(lambda: [0, 0.0]), defaultdict(list)
    for (s, w, t, q), (n, e) in agg.items():
        by_qb[q].append((s, w, n, e))
        season_qb[(s, q)][0] += n
        season_qb[(s, q)][1] += e
        by_tw[(s, w, t)].append((q, n))

    def repl(S):
        win = range(S - 3, S) if S > 2010 else (2010,)
        v = [x for (s, q), x in season_qb.items() if s in win and x[0] < 200]
        return sum(x[1] for x in v) / sum(x[0] for x in v)
    R = {S: repl(S) for S in SEASONS}

    def rate(q, S, w):
        n, e = 0, 0.0
        for s, wk, nn, ee in by_qb.get(q, ()):
            if s in (S - 2, S - 1) or (s == S and wk < w):
                n += nn
                e += ee
        return (e + 200.0 * R[S]) / (n + 200.0)

    inj = {(s, w, t, g) for s, w, t, g in con.execute(
        "SELECT season, week, team, gsis_id FROM nfl_hist_injuries WHERE game_type = 'REG' "
        "AND report_status IN ('Out', 'Doubtful')")}
    depth = defaultdict(set)
    for s, w, t, d, g in con.execute(
            "SELECT season, week, club_code, depth_team, gsis_id FROM nfl_hist_depth_charts "
            "WHERE game_type = 'REG' AND position = 'QB' AND depth_team IN ('1', '2')"):
        depth[(s, w, t, str(d))].add(g)
    games = con.execute(
        "SELECT season, week, game_id, home_team, away_team, home_qb_id, away_qb_id "
        "FROM nfl_schedule WHERE game_type = 'REG' AND season BETWEEN 2010 AND 2025 "
        "ORDER BY season, week, game_id").fetchall()
    hist = defaultdict(list)
    cm, ct = {}, {}
    stats = defaultdict(int)
    for s, w, gid, h, a, hq, aq in games:
        adj = {}
        for team, q_now in ((h, hq), (a, aq)):
            last = hist[team][-8:]
            if not last:
                adj[team] = 0.0
                stats["no_history"] += 1
                continue
            dq = defaultdict(int)
            for hs, hw, _ in last:
                for q2, n2 in by_tw.get((hs, hw, team), ()):
                    dq[q2] += n2
            tot = sum(dq.values())
            if tot == 0:
                adj[team] = 0.0
                stats["no_dropbacks"] += 1
                continue
            base = sum(n * rate(q, s, w) for q, n in dq.items()) / tot
            exp_q = last[-1][2]
            if (s, w, team, exp_q) in inj:
                stats["prev_starter_listed_out"] += 1
                c1 = depth.get((s, w, team, "1"), set()) - {exp_q}
                c2 = depth.get((s, w, team, "2"), set()) - {exp_q}
                exp_q = next(iter(c1)) if len(c1) == 1 else (
                    next(iter(c2)) if len(c2) == 1 else None)
                if exp_q is None:
                    stats["replaced_by_R"] += 1
            if s >= 2011:
                stats["team_games_2011_on"] += 1
                stats["expected_is_actual"] += int(exp_q == q_now)
            adj[team] = (rate(exp_q, s, w) if exp_q else R[s]) - base
        cm[gid] = [adj[h] - adj[a]]
        ct[gid] = [adj[h] + adj[a]]
        hist[h].append((s, w, hq))
        hist[a].append((s, w, aq))
    print("QBI checks:", dict(stats))
    return fb._complete(rows, cm), ct


def avail_columns(con, rows):
    g2p = {}
    for g, p in con.execute("SELECT gsis_id, pfr_id FROM nfl_hist_player_ids "
                            "WHERE gsis_id IS NOT NULL AND pfr_id IS NOT NULL"):
        g2p[g] = p
    snaps = defaultdict(dict)            # (team, season, week) -> pfr -> (off, def)
    for s, w, t, p, o, d in con.execute(
            "SELECT season, week, team, pfr_player_id, offense_pct, defense_pct "
            "FROM nfl_hist_snap_counts WHERE game_type = 'REG'"):
        snaps[(t, s, w)][p] = (o or 0.0, d or 0.0)
    team_games = defaultdict(list)
    for (t, s, w) in snaps:
        team_games[t].append((s, w))
    for t in team_games:
        team_games[t].sort()
    listed = defaultdict(list)
    unmapped = mapped = 0
    for s, w, t, g in con.execute(
            "SELECT season, week, team, gsis_id FROM nfl_hist_injuries WHERE game_type = 'REG' "
            "AND report_status IN ('Out', 'Doubtful') AND COALESCE(position, '') != 'QB'"):
        p = g2p.get(g)
        if p is None:
            unmapped += 1
            continue
        mapped += 1
        listed[(s, w, t)].append(p)
    cm, ct = {}, {}
    no_snaps = 0
    for s, w, gid, h, a in con.execute(
            "SELECT season, week, game_id, home_team, away_team FROM nfl_schedule "
            "WHERE game_type = 'REG' AND season BETWEEN 2010 AND 2025"):
        load = {}
        for t in (h, a):
            prev = [x for x in team_games.get(t, ()) if x < (s, w)][-4:]
            if not prev:
                load[t] = (0.0, 0.0)
                no_snaps += 1
                continue
            lo = ld = 0.0
            for p in listed.get((s, w, t), ()):
                lo += sum(snaps[(t,) + x].get(p, (0.0, 0.0))[0] for x in prev) / len(prev)
                ld += sum(snaps[(t,) + x].get(p, (0.0, 0.0))[1] for x in prev) / len(prev)
            load[t] = (lo, ld)
        cm[gid] = [load[h][0] - load[a][0], load[h][1] - load[a][1]]
        ct[gid] = [load[h][0] + load[a][0], load[h][1] + load[a][1]]
    print("AVAIL checks: listed non-QB rows mapped %d, unmapped %d (no pfr id); team-games "
          "with no snap history %d" % (mapped, unmapped, no_snaps))
    return fb._complete(rows, cm), ct


def elo_benchmark(con, rows, B):
    elo = {}
    for season, neutral, t1, t2, p in con.execute(
            "SELECT season, neutral, team1, team2, elo_prob1 FROM nfl_elo_538 "
            "WHERE playoff = '0' AND CAST(season AS INTEGER) BETWEEN 2011 AND 2020"):
        elo[(int(season), normalize("nfl", t1), normalize("nfl", t2))] = float(p)
    g = [r for r in rows if 2011 <= r["season"] <= 2020 and r["p_market"] is not None
         and r["outcome"] is not None]
    j = [r for r in g if (r["season"], r["home"], r["away"]) in elo]
    print("ELO538: graded games 2011-2020 %d, joined %d, unjoined %d" % (len(g), len(j), len(g) - len(j)))
    y = [r["outcome"] for r in j]
    be = [(elo[(r["season"], r["home"], r["away"])] - o) ** 2 for r, o in zip(j, y)]
    bk = [(r["p_market"] - o) ** 2 for r, o in zip(j, y)]
    bb = [(plb.phi(B[r["game_id"]][0] / B[r["game_id"]][1]) - o) ** 2 for r, o in zip(j, y)]
    print("  Brier elo %.4f market %.4f B %.4f | elo-market %+.4f [%+.4f,%+.4f] | "
          "B-elo %+.4f [%+.4f,%+.4f]" % (sum(be) / len(be), sum(bk) / len(bk), sum(bb) / len(bb),
                                          *nm.bootstrap_mean_diff_ci(be, bk, reps=5000),
                                          *nm.bootstrap_mean_diff_ci(bb, be, reps=5000)))


def join(rows, *cols):
    """Concatenate column dicts for every base row (base rows start at week 2; a feature dict
    may hold extra week 1 games). A base row missing from any dict raises KeyError."""
    return {r["game_id"]: sum((list(c[r["game_id"]]) for c in cols), []) for r in rows}


def main():
    con = sqlite3.connect("file:%s?mode=ro" % fb.DB, uri=True)
    rows = [r for r in fb.base_rows(con) if r["actual_margin"] is not None]
    B = plb.stack2(rows)
    qm, qt = qbi_columns(con, rows)
    am, at = avail_columns(con, rows)
    em, _ = fb.epa_units(con, rows)
    mp, _ = fb.market_prior(con, rows)
    elo_benchmark(con, rows, B)
    models = {"B": B, "QBI": plb.stack2(rows, qm, qt), "AVAIL": plb.stack2(rows, am, at),
              "OWN": plb.stack2(rows, join(rows, qm, am, em), join(rows, qt, at)),
              "OWNMP": plb.stack2(rows, join(rows, qm, am, em, mp), join(rows, qt, at))}
    plb.report(rows, models)
    return 0


if __name__ == "__main__":
    sys.exit(main())
