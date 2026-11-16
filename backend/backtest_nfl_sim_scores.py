#!/usr/bin/env python3
"""backtest_nfl_sim_scores.py -- gates G1-G6 for nfl_sim's "history" scores option.

Rules and gates are fixed in nfl_sim_scores.py's docstring, committed (1e5fce6) before this script
was written. This script only measures; it reads the database read-only and writes nothing to it.

Usage:
  cd backend && nice -n 10 /root/legendarypicks/backend/venv/bin/python backtest_nfl_sim_scores.py \
      --out-json <scratch>/gates.json [--n-sims 2000] [--current 20000]

Prints a markdown report (and writes it with --out-md).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import statistics
import sys
import time

import numpy as np

import backtest_nfl_score_dist as bsd
import nfl_metrics as mt
import nfl_score_dist as nsd
import nfl_seeding as sd
import nfl_sim as ns
import nfl_sim_margin_source as msrc
import nfl_sim_scores as nss
import nfl_standings as st

TEST_SEASONS = tuple(range(2020, 2026))
CUTOFFS = (5, 12)
DRAWS = 20000
G1_SEED = 20261013


def actual_finals(con, season):
    """Sets of (home, away) pairs, totals and margins of REG finals 2010 .. season-1, straight from
    nfl_schedule (independent of the pool code)."""
    rows = con.execute("SELECT home_score, away_score FROM nfl_schedule WHERE game_type='REG' AND "
                       "season >= 2010 AND season < ? AND home_score IS NOT NULL AND "
                       "away_score IS NOT NULL", (season,)).fetchall()
    pairs = {(int(h), int(a)) for h, a in rows}
    return pairs, {h + a for h, a in pairs}, {h - a for h, a in pairs}


def truth(con, season):
    rows = con.execute("SELECT game_type, home_team, away_team FROM nfl_schedule WHERE season=? "
                       "AND game_type IN ('WC','DIV','CON','SB')", (season,)).fetchall()
    playoff = {t for r in rows for t in r[1:]}
    wc = {t for r in rows if r[0] == "WC" for t in r[1:]}
    div = {t for r in rows if r[0] == "DIV" for t in r[1:]}
    winners = {r[1] for r in rows if r[0] == "WC"} | (div - wc)
    if len(playoff) != 14 or len(winners) != 8:
        raise SystemExit("season %d: %d playoff teams, %d division winners" %
                         (season, len(playoff), len(winners)))
    return playoff, winners


# ---------------------------------------------------------------- G1, G2 (draws), G3
def per_game_draws(rows, con, v1_margin=None):
    """v1_margin: optional {game_id: v1 expected margin}; when given, the Brier of the v1 Normal on
    the same games is also reported (the elo-source trade-off, not gated)."""
    brier_v1 = []
    bins = [[0, 0, 0.0] for _ in range(10)]       # decisive draws, home draws, sum p * decisive
    ties = draws = 0
    t_sum = 0.0
    brier_hat, brier_norm = [], []
    tot_sum = tot_sq = 0.0
    tot_n = 0
    actual_totals = []
    cand_over, norm_over, over_ok = [], [], []
    invalid = []
    pool_check = {}
    for season in TEST_SEASONS:
        s = nss.build(con, season, ns.HISTORY_K, rows=rows)
        pairs_ok, totals_ok, margins_ok = actual_finals(con, season)
        rng = np.random.default_rng(G1_SEED + season)
        games = [r for r in rows if r["season"] == season]
        pool_check[season] = {"games": len(games), "tie_rate": s.t, "pool": s.info["pool_games"],
                              "pool_ties": s.info["pool_ties"]}
        for r in games:
            m, tot = r["eh"] - r["ea"], r["eh"] + r["ea"]
            p = s.p_home(m)
            u = rng.random(DRAWS)
            is_tie = u < s.t
            is_home = (~is_tie) & (u < s.t + (1.0 - s.t) * p)
            counts = {"T": int(is_tie.sum()), "H": int(is_home.sum())}
            counts["A"] = DRAWS - counts["T"] - counts["H"]
            hs_all, as_all = [], []
            for o in nss.OUTCOMES:
                if not counts[o]:
                    continue
                arr = np.array(s.pairs(m, tot, o), dtype=int)
                pick = arr[rng.integers(0, len(arr), size=counts[o])]
                hs_all.append(pick[:, 0])
                as_all.append(pick[:, 1])
            hs = np.concatenate(hs_all)
            as_ = np.concatenate(as_all)
            for h, a in set(zip(hs.tolist(), as_.tolist())):
                if h < 0 or a < 0 or (h, a) not in pairs_ok or (h + a) not in totals_ok or \
                        (h - a) not in margins_ok:
                    invalid.append((season, r["game_id"], h, a))
            dec = counts["H"] + counts["A"]
            b = min(int(p * 10), 9)
            bins[b][0] += dec
            bins[b][1] += counts["H"]
            bins[b][2] += p * dec
            ties += counts["T"]
            draws += DRAWS
            t_sum += s.t * DRAWS
            totals = hs + as_
            tot_sum += float(totals.sum())
            tot_sq += float((totals.astype(float) ** 2).sum())
            tot_n += DRAWS
            actual_totals.append(r["hs"] + r["as_"])
            if r["hs"] != r["as_"]:
                y = 1.0 if r["hs"] > r["as_"] else 0.0
                brier_hat.append((counts["H"] / dec - y) ** 2)
                brier_norm.append((p - y) ** 2)
                if v1_margin is not None:
                    brier_v1.append((nss.phi(v1_margin[r["game_id"]] / nsd.SIGMA_NORMAL) - y) ** 2)
            if r["total"] is not None and r["spread"] is not None:
                push = int((totals == r["total"]).sum())
                graded = DRAWS - push
                if graded:
                    cand_over.append(float((totals > r["total"]).sum()) / graded)
                    norm_over.append(nsd.normal_probabilities(
                        r["eh"], r["ea"], total=r["total"], total_sd=s.dist.resid_total_sd)["p_over"])
                    over_ok.append(1.0 if (r["hs"] + r["as_"]) > r["total"] else 0.0)
    g1_bins = []
    ok_a = True
    for i, (dec, home, psum) in enumerate(bins):
        if dec == 0:
            continue
        pbar = psum / dec
        rate = home / dec
        se = math.sqrt(pbar * (1 - pbar) / dec)
        z = (rate - pbar) / se if se else 0.0
        used = dec >= DRAWS
        if used and abs(z) > 4:
            ok_a = False
        g1_bins.append({"bin": "%.1f-%.1f" % (i / 10, (i + 1) / 10), "decisive_draws": dec,
                        "mean_p": pbar, "sim_rate": rate, "z": z, "gated": used})
    tbar = t_sum / draws
    t_se = math.sqrt(tbar * (1 - tbar) / draws)
    t_z = (ties / draws - tbar) / t_se
    ok_a = ok_a and abs(t_z) <= 4
    b_hat = sum(brier_hat) / len(brier_hat)
    b_norm = sum(brier_norm) / len(brier_norm)
    mean_sim = tot_sum / tot_n
    sd_sim = math.sqrt(tot_sq / tot_n - mean_sim ** 2)
    mean_act = statistics.fmean(actual_totals)
    sd_act = statistics.pstdev(actual_totals)
    over_c = bsd._calib_error(mt.calibration_bins(cand_over, over_ok))
    over_n = bsd._calib_error(mt.calibration_bins(norm_over, over_ok))
    g1 = {"bins": g1_bins, "tie_rate_draws": ties / draws, "tie_rate_expected": tbar, "tie_z": t_z,
          "pass_a": ok_a, "brier_sim": b_hat, "brier_normal": b_norm, "brier_games": len(brier_hat),
          "pass_b": b_hat <= b_norm + 0.0005, "games": len(actual_totals), "draws": draws}
    g1["pass"] = g1["pass_a"] and g1["pass_b"]
    if brier_v1:
        g1["brier_v1_normal_same_games"] = sum(brier_v1) / len(brier_v1)
    g3 = {"mean_sim": mean_sim, "mean_actual": mean_act, "sd_sim": sd_sim, "sd_actual": sd_act,
          "games": len(actual_totals), "over_games": len(over_ok),
          "over_sse_sim": over_c[0], "over_bins_sim": over_c[1], "over_sse_normal": over_n[0],
          "over_bins_normal": over_n[1],
          "over_bins": mt.calibration_bins(cand_over, over_ok)}
    g3["pass"] = (abs(mean_sim - mean_act) <= 1.0 and 0.90 <= sd_sim / sd_act <= 1.10 and
                  over_c[0] <= over_n[0])
    return g1, g3, {"invalid_pairs": invalid[:20], "invalid_count": len(invalid)}, pool_check


# ---------------------------------------------------------------- G5, G4, G6, G2 (sim games)
def invariants(teams, seeds):
    """Violations of the seeding invariants for one simulated season (empty list = clean)."""
    bad = []
    for conf, lst in seeds.items():
        codes = [c for _, c in lst]
        winners = codes[:4]
        members = [t for t in teams.values() if t.conference == conf]
        divs = {}
        for t in members:
            divs.setdefault(t.division, []).append(t)
        if sorted(teams[c].division for c in winners) != sorted(divs):
            bad.append((conf, "division winners not one per division"))
        for c in winners:
            best = max(t.pct for t in divs[teams[c].division])
            if teams[c].pct < best - 1e-12:
                bad.append((conf, "winner %s below division best" % c))
        p = [teams[c].pct for c in codes]
        if any(p[i] < p[i + 1] - 1e-12 for i in range(3)):
            bad.append((conf, "seeds 1-4 out of order"))
        if any(p[i] < p[i + 1] - 1e-12 for i in range(4, len(p) - 1)):
            bad.append((conf, "wild cards out of order"))
        rest = [t.pct for t in members if t.code not in codes]
        if rest and min(p[4:]) < max(rest) - 1e-12:
            bad.append((conf, "unseeded club above a wild card"))
    return bad


def seeds_plain(tmap, games, season):
    teams = st.build(tmap, games)
    n = sd.n_seeds_for(season)
    return tuple(tuple(sd.seeds_for_conference(teams, c, n_seeds=n, rng=None)) for c in ("AFC", "NFC"))


class Observer:
    def __init__(self, inp, finals, ppg, g6):
        self.inp = inp
        self.n_played = len(inp["played"])
        self.finals = finals
        self.ppg = ppg
        self.g6 = g6
        self.sim_games = self.sim_ties = 0
        self.invalid = []
        self.violations = []
        self.team_ppg = {}

    def __call__(self, games, teams, seeds):
        sim = games[self.n_played:]
        if self.finals is not None:
            pairs_ok, totals_ok, margins_ok = self.finals
            for g in sim:
                h, a = g[3], g[4]
                if not (isinstance(h, int) and isinstance(a, int)) or h < 0 or a < 0 or \
                        (h, a) not in pairs_ok or (h + a) not in totals_ok or (h - a) not in margins_ok:
                    self.invalid.append(g)
                if h == a:
                    self.sim_ties += 1
            self.sim_games += len(sim)
        v = invariants(teams, seeds)
        if v:
            self.violations.append(v)
        if self.ppg is not None:
            pts, gp = {}, {}
            for g in sim:
                for team, p in ((g[1], g[3]), (g[2], g[4])):
                    pts[team] = pts.get(team, 0.0) + p
                    gp[team] = gp.get(team, 0) + 1
            vals = [pts[t] / gp[t] for t in pts]
            self.ppg.setdefault("league", []).append(sum(pts.values()) / sum(gp.values()))
            self.ppg.setdefault("sd_teams", []).append(statistics.pstdev(vals))
            for t in pts:
                self.team_ppg.setdefault(t, []).append(pts[t] / gp[t])
        if self.g6 is not None:
            ties = [i for i, g in enumerate(sim) if g[3] == g[4]]
            if ties:
                self.g6["tie_seasons"] += 1
                base = seeds_plain(self.inp["tmap"], games, self.inp["season"])
                changed = field = False
                for side in (0, 1):
                    alt = list(games)
                    for i in ties:
                        g = alt[self.n_played + i]
                        alt[self.n_played + i] = (g[0], g[1], g[2], g[3] + (1 - side), g[4] + side)
                    s2 = seeds_plain(self.inp["tmap"], alt, self.inp["season"])
                    if s2 != base:
                        changed = True
                    if {c for conf in s2 for _, c in conf} != {c for conf in base for _, c in conf}:
                        field = True
                self.g6["seed_changed"] += 1 if changed else 0
                self.g6["field_changed"] += 1 if field else 0


def clip_ll(p, y, n):
    lo = 1.0 / (2 * n)
    p = min(max(p, lo), 1 - lo)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def playoff_backtest(con, rows, n, source="v1", pool_elo=None):
    res = {}
    g2 = {"games": 0, "ties": 0, "invalid": 0, "invalid_examples": []}
    g4 = {}
    g6 = {"seasons": 0, "tie_seasons": 0, "seed_changed": 0, "field_changed": 0,
          "violations": 0, "exceptions": 0}
    per_team = []
    m1 = {"S_v1": [], "S_elo": [], "S_stack": []}
    m3 = {"x": [], "y": []}
    for season in TEST_SEASONS:
        playoff, winners = truth(con, season)
        finals = actual_finals(con, season)
        for w in CUTOFFS:
            inps = {"placeholder": ns.inputs(con, season, as_of_week=w),
                    "history": ns.inputs(con, season, as_of_week=w, scores="history", pool=rows)}
            v1_hist = inps["history"]
            if source == "elo":
                inps["history"] = msrc.elo_inputs(con, inps["placeholder"], pool_elo)
            if w == 5:
                rem, tots = v1_hist["remaining"], v1_hist["remaining_totals"]
                m1["S_v1"].append(statistics.pstdev(msrc.expected_ppg(rem, tots).values()))
                elo_m = [g[4] for g in (inps["history"]["remaining"] if source == "elo" else
                                        msrc.elo_inputs(con, inps["placeholder"], pool_elo)["remaining"])]
                m1["S_elo"].append(statistics.pstdev(msrc.expected_ppg(rem, tots, elo_m).values()))
                m1["S_stack"].append(statistics.pstdev(
                    msrc.expected_ppg(rem, tots, msrc.stack_margins(con, v1_hist)).values()))
                exp_hist = msrc.expected_ppg(inps["history"]["remaining"],
                                             inps["history"]["remaining_totals"])
            if w == 5:
                real = {}
                for r in con.execute("SELECT home_team, away_team, home_score, away_score FROM "
                                     "nfl_schedule WHERE season=? AND game_type='REG' AND week>?",
                                     (season, w)):
                    for team, p in ((r[0], r[2]), (r[1], r[3])):
                        real.setdefault(team, []).append(p)
                vals = [statistics.fmean(v) for v in real.values()]
                g4.setdefault("real_league", []).append(
                    sum(sum(v) for v in real.values()) / sum(len(v) for v in real.values()))
                g4.setdefault("real_sd_teams", []).append(statistics.pstdev(vals))
            for opt, inp in inps.items():
                for tag, seed in (("A", 1000 + w), ("B", 50000 + w)):
                    ppg = {} if w == 5 else None
                    obs = Observer(inp, finals if opt == "history" else None, ppg,
                                   g6 if opt == "history" else None)
                    # An exception stops the harness, so finishing is the "no exception" evidence.
                    out = ns.run(inp, n, k=0.0, seed=seed, observe=obs)
                    conf_of = {t: c for t, (c, _) in inp["tmap"].items()}
                    ns.sanity(out, conf_of, n_seeds=sd.n_seeds_for(season))
                    pp = {t: v["p_playoffs"] for t, v in out["teams"].items()}
                    pdv = {t: v["p_division"] for t, v in out["teams"].items()}
                    res[(season, w, opt, tag)] = (pp, pdv)
                    if opt == "history":
                        g2["games"] += obs.sim_games
                        g2["ties"] += obs.sim_ties
                        g2["invalid"] += len(obs.invalid)
                        g2["invalid_examples"] += obs.invalid[:3]
                        g6["seasons"] += n
                    g6["violations"] += len(obs.violations)
                    if ppg is not None and tag == "B":
                        g4.setdefault(opt + "_sd_teams_B", []).append(statistics.fmean(ppg["sd_teams"]))
                    if ppg is not None and tag == "A":
                        if opt == "history":
                            for t, v in obs.team_ppg.items():
                                m3["x"].append(exp_hist[t])
                                m3["y"].append(statistics.fmean(v))
                        g4.setdefault(opt + "_league", []).append(statistics.fmean(ppg["league"]))
                        g4.setdefault(opt + "_sd_teams", []).append(statistics.fmean(ppg["sd_teams"]))
                        g4.setdefault(opt + "_across_runs_sd", []).append(statistics.fmean(
                            statistics.pstdev(v) for v in obs.team_ppg.values()))
            for t in res[(season, w, "history", "A")][0]:
                per_team.append((abs(res[(season, w, "history", "A")][0][t] -
                                     res[(season, w, "placeholder", "A")][0][t]),
                                 season, w, t, res[(season, w, "placeholder", "A")][0][t],
                                 res[(season, w, "history", "A")][0][t]))
            print("done %d w%d" % (season, w), file=sys.stderr, flush=True)
    metrics = {}
    for opt in ("placeholder", "history"):
        for tag in ("A", "B"):
            bp, bd, lp, ld, cnt = 0.0, 0.0, 0.0, 0.0, 0
            for season in TEST_SEASONS:
                playoff, winners = truth(con, season)
                for w in CUTOFFS:
                    pp, pdv = res[(season, w, opt, tag)]
                    for t in pp:
                        y1 = 1.0 if t in playoff else 0.0
                        y2 = 1.0 if t in winners else 0.0
                        bp += (pp[t] - y1) ** 2
                        bd += (pdv[t] - y2) ** 2
                        lp += clip_ll(pp[t], y1, n)
                        ld += clip_ll(pdv[t], y2, n)
                        cnt += 1
            metrics[(opt, tag)] = {"brier_playoffs": bp / cnt, "brier_division": bd / cnt,
                                   "ll_playoffs": lp / cnt, "ll_division": ld / cnt, "n": cnt}
    seed_max = {}
    for opt in ("placeholder", "history"):
        seed_max[opt] = max(abs(res[(s, w, opt, "A")][0][t] - res[(s, w, opt, "B")][0][t])
                            for s in TEST_SEASONS for w in CUTOFFS for t in res[(s, w, opt, "A")][0])
    g5 = {"metrics": {"%s/%s" % k: v for k, v in metrics.items()}, "per_team_max": sorted(per_team, reverse=True)[:5],
          "seed_to_seed_max": seed_max,
          "mean_abs_change": statistics.fmean(x[0] for x in per_team)}
    ok = True
    for key in ("brier_playoffs", "brier_division"):
        noise = max(abs(metrics[("history", "A")][key] - metrics[("history", "B")][key]),
                    abs(metrics[("placeholder", "A")][key] - metrics[("placeholder", "B")][key]))
        diff = metrics[("history", "A")][key] - metrics[("placeholder", "A")][key]
        bound = max(2 * noise, 0.001)
        g5[key] = {"diff": diff, "noise": noise, "bound": bound, "pass": diff <= bound}
        ok = ok and diff <= bound
    g5["pass"] = ok
    g2["tie_rate"] = g2["ties"] / g2["games"]
    g4_out = {k: statistics.fmean(v) for k, v in g4.items()}
    g4_out["per_season"] = g4
    g4_out["pass"] = (abs(g4_out["history_league"] - g4_out["real_league"]) <= 1.0 and
                      0.80 <= g4_out["history_sd_teams"] / g4_out["real_sd_teams"] <= 1.25)
    g4_out["ratio_A"] = g4_out["history_sd_teams"] / g4_out["real_sd_teams"]
    g4_out["ratio_B"] = g4_out["history_sd_teams_B"] / g4_out["real_sd_teams"]
    g4_out["M1"] = {k: statistics.fmean(v) for k, v in m1.items()}
    g4_out["M1"]["per_season"] = m1
    g4_out["M3_slope"] = msrc.ols_slope(m3["x"], m3["y"])
    g4_out["M3_predicted_ratio"] = math.sqrt(
        g4_out["M1"]["S_elo" if source == "elo" else "S_v1"] ** 2 +
        g4_out["history_across_runs_sd"] ** 2) / g4_out["real_sd_teams"]
    g6["pass"] = g6["exceptions"] == 0 and g6["violations"] == 0
    return g5, g2, g4_out, g6


def current(con, rows, n, seed=20261013):
    season = con.execute("SELECT MAX(season) FROM nfl_schedule WHERE game_type='REG'").fetchone()[0]
    p = ns.run(ns.inputs(con, season), n, seed=seed)
    inp_h = ns.inputs(con, season, scores="history", pool=rows)
    h = ns.run(inp_h, n, seed=seed)
    h2 = ns.run(inp_h, n, seed=seed + 1)
    teams = sorted(p["teams"], key=lambda t: -h["teams"][t]["p_playoffs"])
    table = [(t, p["teams"][t]["p_playoffs"], h["teams"][t]["p_playoffs"],
              p["teams"][t]["p_division"], h["teams"][t]["p_division"],
              p["teams"][t]["p_bye"], h["teams"][t]["p_bye"]) for t in teams]
    noise = max(abs(h["teams"][t]["p_playoffs"] - h2["teams"][t]["p_playoffs"]) for t in teams)
    return {"season": season, "through_week": inp_h["through_week"], "n": n, "table": table,
            "max_change": max(abs(r[1] - r[2]) for r in table), "seed_noise_max": noise,
            "flips_p": p["coin_flips"], "flips_h": h["coin_flips"]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=nsd.DEV_DB)
    ap.add_argument("--n-sims", type=int, default=2000)
    ap.add_argument("--current", type=int, default=20000)
    ap.add_argument("--source", choices=("v1", "elo"), default="v1",
                    help="expected-margin source for the history option (nfl_sim_margin_source)")
    ap.add_argument("--out-json", required=True)
    args = ap.parse_args(argv)
    con = sqlite3.connect("file:%s?mode=ro" % args.db, uri=True)
    t0 = time.time()
    rows = nss.pool_rows(con, range(2010, 2026))
    # The pool equals nfl_score_dist.load_history's rows for 2010-2023 (rehearsal CSV).
    hist, _ = nsd.load_history(None)
    mine = {r["game_id"]: r for r in rows}
    diffs = [max(abs(mine[h["game_id"]]["eh"] - h["eh"]), abs(mine[h["game_id"]]["ea"] - h["ea"]))
             for h in hist if h["game_id"] in mine]
    score_diff = sum(1 for h in hist if h["game_id"] in mine and
                     (mine[h["game_id"]]["hs"], mine[h["game_id"]]["as_"]) != (h["hs"], h["as_"]))
    equiv = {"history_rows": len(hist), "matched": len(diffs), "max_abs_diff": max(diffs),
             "score_mismatch": score_diff,
             "db_rows_2010_2023": sum(1 for r in rows if r["season"] <= 2023)}
    pool_elo = msrc.elo_pool_rows(con, rows)
    if args.source == "elo":
        v1_margin = {r["game_id"]: r["eh"] - r["ea"] for r in rows}
        g1, g3, g2a, pool_check = per_game_draws(pool_elo, con, v1_margin)
    else:
        g1, g3, g2a, pool_check = per_game_draws(rows, con)
    print("G1/G3 done %.0fs" % (time.time() - t0), file=sys.stderr, flush=True)
    g5, g2b, g4, g6 = playoff_backtest(con, rows, args.n_sims, args.source, pool_elo)
    print("G5 done %.0fs" % (time.time() - t0), file=sys.stderr, flush=True)
    g2 = {"draws": g2a, "sim": g2b}
    g2["pass"] = (g2a["invalid_count"] == 0 and g2b["invalid"] == 0 and
                  0.001 <= g2b["tie_rate"] <= 0.004)
    cur = current(con, rows, args.current) if args.current else None
    doc = {"source": args.source, "equivalence": equiv, "pool_check": pool_check, "G1": g1, "G2": g2, "G3": g3, "G4": g4,
           "G5": g5, "G6": g6, "current": cur, "elapsed": time.time() - t0,
           "all_pass": all(x["pass"] for x in (g1, g2, g3, g4, g5, g6))}
    with open(args.out_json, "w") as fh:
        json.dump(doc, fh, indent=1, default=str)
    print(json.dumps({k: (v.get("pass") if isinstance(v, dict) else v)
                      for k, v in doc.items() if k.startswith("G") or k == "all_pass"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
