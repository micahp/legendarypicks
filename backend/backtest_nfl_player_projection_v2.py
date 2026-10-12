"""backtest_nfl_player_projection_v2.py -- fit on 2024, grade on 2025 (Spec B section 5 gate).

PRE-REGISTERED with nfl_player_projection_v2.py before any 2025 number was computed.

  --fit   Walk-forward inside 2024 weeks 3 to 18 over the grids in the engine docstring. Prints the chosen
          constants. They are then copied into DEFAULTS by hand and committed BEFORE --run.
  --run   Walk-forward 2025 weeks 3 to 18 with the frozen constants. Run once per commit.

Eligible player-game: RB/WR/TE (FB counts as RB) who played the game (a log row exists) and has at least 3
games earlier in the same season (what Marcel-lite needs). Targets, receptions and receiving yards are graded
on all of them; carries and rushing yards on those with 1 or more carry in the earlier games.

Gate (the Spec B 5 wording): version 2 mean absolute error below Marcel-lite on BOTH receiving yards and
receptions, 2025 weeks 3 to 18. Paired player-game bootstrap, 2000 resamples, seed 7, 95% interval of
(MAE_v2 - MAE_marcel); the gate is passed only if the point difference is negative for both stats. The
interval is reported, not part of the rule. Diagnostics printed, not gated: bias, per-position MAE, MAE with
and without the injury-report redistribution on games where it fired, how often each rule fired, the
Marcel-lite variant over 2024+2025, and calibration of the simulated p10 to p90 band.
"""
import argparse
import itertools
import math
import os
import random
import sqlite3
import sys

import nfl_player_projection_v2 as eng

RECV_POS = ("RB", "WR", "TE")
HIST_WEEKS = range(3, 19)

H_GRID = (2.0, 4.0, 8.0)
KS_GRID = (1.0, 2.0, 3.0, 5.0, 8.0)
KT_GRID = (2.0, 4.0, 8.0)
KEFF_GRID = (10.0, 20.0, 40.0, 80.0, 160.0)
KTD_GRID = (20.0, 40.0, 80.0, 160.0, 320.0)


def connect():
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    return sqlite3.connect(path)


def eligible(hist, season, positions=RECV_POS):
    """(row, projection-inputs) for every graded player-game."""
    for (s, pid), rows in hist.by_player.items():
        if s != season:
            continue
        for i, r in enumerate(rows):
            if r.week in HIST_WEEKS and i >= 3 and r.pos in positions:
                yield r


def fit(hist):
    p = dict(eng.DEFAULTS)
    games = list(eligible(hist, 2024))
    print("2024 eligible player-games: %d" % len(games))
    best = None
    for h, ks, kt in itertools.product(H_GRID, KS_GRID, KT_GRID):
        q = dict(p, H=h, K_S=ks, K_T=kt)
        err, n = 0.0, 0
        for r in games:
            got = eng.opportunities(hist, 2024, r.week, r.pid, r.pos, r.team, r.opp, r.game_id, "tgt", q)
            if got is None:
                continue
            err += abs(got[0] - r.tgt)
            n += 1
        mae = err / n
        if best is None or mae < best[0]:
            best = (mae, h, ks, kt, n)
    print("volume  H=%s K_S=%s K_T=%s  target MAE %.4f over %d games" % (best[1], best[2], best[3], best[0], best[4]))
    p.update(H=best[1], K_S=best[2], K_T=best[3])

    def eff_sse(opp_col, stat_col, name, grid, positions):
        out = []
        for k in grid:
            sse, n = 0.0, 0
            for r in games_all:
                if r.pos not in positions or getattr(r, opp_col) <= 0:
                    continue
                rate = hist.eff(2024, r.week, r.pid, r.pos, opp_col, stat_col, k, None)
                sse += (getattr(r, stat_col) - getattr(r, opp_col) * rate) ** 2
                n += 1
            out.append((sse / n, k, n))
        b = min(out)
        print("%-8s K=%s  mean sq err %.4f over %d games" % (name, b[1], b[0], b[2]))
        return b[1]
    games_all = list(eligible(hist, 2024, positions=("QB", "RB", "WR", "TE")))
    p["K_CR"] = eff_sse("tgt", "rec", "K_CR", KEFF_GRID, RECV_POS)
    p["K_YPT"] = eff_sse("tgt", "rec_yds", "K_YPT", KEFF_GRID, RECV_POS)
    p["K_TDT"] = eff_sse("tgt", "rec_td", "K_TDT", KTD_GRID, RECV_POS)
    p["K_YPC"] = eff_sse("car", "rush_yds", "K_YPC", KEFF_GRID, ("QB", "RB", "WR", "TE"))
    p["K_TDC"] = eff_sse("car", "rush_td", "K_TDC", KTD_GRID, ("QB", "RB", "WR", "TE"))

    # OTHER: share of team targets going to players outside the candidate set, mean over team-weeks
    tot, n = 0.0, 0
    for (s, team), weeks in hist.team_weeks.items():
        if s != 2024:
            continue
        for w in sorted(weeks):
            if w < 3 or w > 18:
                continue
            cands = hist.candidates(2024, team, w)
            team_total = hist.team_game(2024, team, w, "tgt")
            if team_total <= 0:
                continue
            outside = sum(r.tgt for r in hist.by_team[(2024, team)][w] if r.pid not in cands)
            tot += outside / team_total
            n += 1
    p["OTHER"] = round(tot / n, 4)
    print("OTHER  %.4f over %d team-weeks" % (p["OTHER"], n))
    print("FROZEN", {k: p[k] for k in sorted(p)})
    return p


def bootstrap_diff(diffs, seed=7, n=2000):
    rng = random.Random(seed)
    m = len(diffs)
    means = sorted(sum(diffs[rng.randrange(m)] for _ in range(m)) / m for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def run(hist_with, hist_plain):
    p = dict(eng.DEFAULTS)
    games = sorted(eligible(hist_with, 2025), key=lambda r: (r.week, r.pid))
    print("2025 eligible player-games (RB/WR/TE, week 3 to 18, 3+ earlier games): %d" % len(games))
    stats = (("tgt", "tgt"), ("rec", "rec"), ("rec_yds", "rec_yds"), ("rec_td", "rec_td"),
             ("car", "car"), ("rush_yds", "rush_yds"), ("rush_td", "rush_td"))
    cols = {s: [] for s, _ in stats}
    rules = {}
    for r in games:
        v2 = eng.project(hist_with, 2025, r.week, r.pid, r.pos, r.team, r.opp, r.game_id, p)
        if v2 is None:
            continue
        v2_plain = eng.project(hist_plain, 2025, r.week, r.pid, r.pos, r.team, r.opp, r.game_id, p)
        for rule in v2["_rules"].values():
            rules[rule] = rules.get(rule, 0) + 1
        fired = "proportional" in v2["_rules"].values() or "observed_blend" in v2["_rules"].values()
        for stat, attr in stats:
            if stat not in v2:
                continue
            m1 = eng.marcel(hist_with, 2025, r.week, r.pid, attr)
            m2 = eng.marcel(hist_with, 2025, r.week, r.pid, attr, both_seasons=True)
            if m1 is None:
                continue
            cols[stat].append({"r": r, "actual": getattr(r, attr), "v2": v2[stat], "m1": m1, "m2": m2,
                               "plain": (v2_plain or {}).get(stat), "fired": fired})
    print("redistribution rules fired (player-game x opportunity type):", rules)
    print()
    print("%-9s %6s %8s %8s %8s %8s   %-28s %s" % ("stat", "n", "MAE v2", "MAE m1", "MAE m2", "bias v2",
                                                  "v2 - marcel(2025) [95% CI]", "gate"))
    verdicts = {}
    for stat, _ in stats:
        rows = cols[stat]
        if not rows:
            continue
        n = len(rows)
        mae = lambda key: sum(abs(x[key] - x["actual"]) for x in rows) / n
        m_v2, m_m1 = mae("v2"), mae("m1")
        m_m2 = sum(abs(x["m2"] - x["actual"]) for x in rows if x["m2"] is not None) / max(
            1, sum(1 for x in rows if x["m2"] is not None))
        bias = sum(x["v2"] - x["actual"] for x in rows) / n
        diffs = [abs(x["v2"] - x["actual"]) - abs(x["m1"] - x["actual"]) for x in rows]
        lo, hi = bootstrap_diff(diffs)
        verdicts[stat] = m_v2 - m_m1
        print("%-9s %6d %8.3f %8.3f %8.3f %+8.3f   %+7.3f [%+.3f, %+.3f]" % (
            stat, n, m_v2, m_m1, m_m2, bias, m_v2 - m_m1, lo, hi))
    print()
    passed = verdicts.get("rec_yds", 1) < 0 and verdicts.get("rec", 1) < 0
    print("GATE (rec_yds and rec both lower than Marcel-lite, 2025 wk 3-18): %s" % ("PASS" if passed else "FAIL"))
    print()
    print("per position, MAE v2 vs Marcel-lite (2025):")
    for stat in ("rec", "rec_yds", "rush_yds"):
        for pos in RECV_POS:
            rows = [x for x in cols[stat] if x["r"].pos == pos]
            if rows:
                print("  %-9s %-3s n=%-5d v2 %.3f  marcel %.3f" % (
                    stat, pos, len(rows), sum(abs(x["v2"] - x["actual"]) for x in rows) / len(rows),
                    sum(abs(x["m1"] - x["actual"]) for x in rows) / len(rows)))
    print()
    print("redistribution, games where an Out/Doubtful teammate changed the shares (targets):")
    fired = [x for x in cols["tgt"] if x["fired"] and x["plain"] is not None]
    if fired:
        print("  n=%d  MAE with the injury report %.3f   MAE ignoring it %.3f   Marcel %.3f" % (
            len(fired), sum(abs(x["v2"] - x["actual"]) for x in fired) / len(fired),
            sum(abs(x["plain"] - x["actual"]) for x in fired) / len(fired),
            sum(abs(x["m1"] - x["actual"]) for x in fired) / len(fired)))
    return cols


def fit_dist(hist):
    """Method of moments on 2024 projections: NB dispersion R for targets, gamma shape G for yards per reception."""
    p = dict(eng.DEFAULTS)
    num = den = 0.0
    ysq = ysum = 0.0
    for r in eligible(hist, 2024):
        v = eng.project(hist, 2024, r.week, r.pid, r.pos, r.team, r.opp, r.game_id, p)
        if v is None or "tgt" not in v:
            continue
        mu = v["tgt"]
        num += mu * mu
        den += (r.tgt - mu) ** 2 - mu
        if r.rec > 0 and v["rec"] > 0:
            ypr = v["rec_yds"] / v["rec"]
            ysq += (r.rec_yds - r.rec * ypr) ** 2
            ysum += r.rec
    big_r = num / den if den > 0 else 1e6
    var_rec = ysq / ysum          # per-reception variance of yards
    big_g = 11.0 ** 2 / var_rec
    print("DIST R=%.2f (over-dispersion of targets)  G=%.2f (gamma shape; mean 11 yd, var %.1f)" % (big_r, big_g, var_rec))
    return {"R": round(big_r, 2), "G": round(big_g, 2)}


def run_dist(hist):
    p = dict(eng.DEFAULTS)
    games = sorted(eligible(hist, 2025), key=lambda r: (r.week, r.pid))
    below = above = inside = n = 0
    below_r = above_r = inside_r = 0
    for i, r in enumerate(games):
        v = eng.project(hist, 2025, r.week, r.pid, r.pos, r.team, r.opp, r.game_id, p)
        if v is None or "tgt" not in v or v["tgt"] <= 0:
            continue
        c = v["rec"] / v["tgt"]
        ypr = v["rec_yds"] / v["rec"] if v["rec"] > 0 else 0.0
        d = v["rec_td"] / v["tgt"]
        draws = eng.simulate(v["tgt"], c, ypr, d, n=1000, seed=i)
        ys = eng.summarize(draws, 1)
        rs = eng.summarize(draws, 0)
        n += 1
        below += r.rec_yds < ys["p10"]
        above += r.rec_yds > ys["p90"]
        inside += ys["p10"] <= r.rec_yds <= ys["p90"]
        below_r += r.rec < rs["p10"]
        above_r += r.rec > rs["p90"]
        inside_r += rs["p10"] <= r.rec <= rs["p90"]
    print("2025 p10-p90 band, n=%d" % n)
    print("  receiving yards: inside %.1f%%  below p10 %.1f%%  above p90 %.1f%%  (targets 80 / 10 / 10)" % (
        100.0 * inside / n, 100.0 * below / n, 100.0 * above / n))
    print("  receptions:      inside %.1f%%  below p10 %.1f%%  above p90 %.1f%%" % (
        100.0 * inside_r / n, 100.0 * below_r / n, 100.0 * above_r / n))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--fit-dist", action="store_true")
    ap.add_argument("--run-dist", action="store_true")
    a = ap.parse_args()
    con = connect()
    if a.fit:
        fit(eng.History.load(con, [2024]))
    if a.fit_dist:
        fit_dist(eng.History.load(con, [2024]))
    if a.run_dist:
        run_dist(eng.History.load(con, [2024, 2025]))
    if a.run:
        with_report = eng.History.load(con, [2024, 2025])
        plain = eng.History(with_report.rows, {})
        run(with_report, plain)


if __name__ == "__main__":
    main()
