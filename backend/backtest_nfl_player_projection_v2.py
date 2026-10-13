"""backtest_nfl_player_projection_v2.py -- fit on 2024, grade on 2025 (Spec B section 5 gate).

PRE-REGISTERED with nfl_player_projection_v2.py before any 2025 number was computed.

  --fit   Walk-forward inside 2024 weeks 3 to 18 over the grids in the engine docstring. Prints the chosen
          constants. They are then copied into DEFAULTS by hand and committed BEFORE --run.
  --vs-espn  PRE-REGISTERED 2026-10-12 before it was run. On the 2025 player-games in the --run sample for
          which ESPN's weekly projection (player_projections, model_version 'espn-weekly', captured 2026-10-12
          for the 400 most-owned RB/WR/TE) exists: MAE of v2, Marcel-lite (this season) and ESPN on the SAME
          player-games, for receptions, receiving yards, targets and receiving TDs, with a paired bootstrap
          95% interval of MAE(v2) - MAE(ESPN). No gate. Two things bias it and are stated, not corrected:
          the sample is ESPN's most-owned players, and ESPN's number is an expectation that includes the chance
          the player sits, while v2 and Marcel-lite are conditional on playing and scored only on games played.
          Whether ESPN's stored weekly value for a past week is what it showed before kickoff is unverified.
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


def fit_nmu(hist, season=2024):
    """Spec B 4.3 next-man-up split, PRE-REGISTERED 2026-10-13 before it was run.

    Case: a team-game in `season`, weeks 3 to 18, where the injury report removes (Out or Doubtful) the
    candidate with the highest base share in his position group, and 2 or more other candidates of that
    group played the game. Base shares are the engine's raw_share for every candidate (the removed ones
    included), scaled by (1 - OTHER) / their sum: what each would have got with everyone playing.
    For each remaining group player who played: gain = actual share - scaled base share. The next man up
    is the remaining player with the highest base share. NMU_<col> = sum of the next man up's gains /
    sum of the group's gains, over all cases. Reported beside it: the fraction plain proportional
    redistribution would give him (his base / the group's base), averaged over the same cases.
    Fitted on 2024 only for the 2025 gate; the value on 2025 cases alone is printed as a stability check and
    not used. Slice gate: the Spec B 5 gate above, run once on 2025 with the frozen NMU. The slice is kept only
    if the gate passes and target MAE on player-games where the redistribution fired is not above the
    previous engine's (1.595, docs/RESULTS-player-projection-v2-2026-10-12.md).
    """
    p = dict(eng.DEFAULTS)
    out = {}
    for col in ("tgt", "car"):
        g_nmu = g_all = 0.0
        prop, cases = [], 0
        for (s, team), weeks in hist.team_weeks.items():
            if s != season:
                continue
            for w in sorted(weeks):
                if w < 3 or w > 18:
                    continue
                rows = hist.by_team[(s, team)][w]
                gid = rows[0].game_id
                cands = hist.candidates(s, team, w)
                removed = hist.out_before(s, gid, team) & set(cands)
                if not removed:
                    continue
                base = {j: hist.raw_share(s, j, jp, w, col, p, None)[0] for j, jp in cands.items()}
                b_tot = sum(base.values())
                tt = hist.team_game(s, team, w, col)
                if b_tot <= 0 or tt <= 0:
                    continue
                played = {r.pid: getattr(r, col) / tt for r in rows}
                for g in {cands[x] for x in removed}:
                    group = [j for j in cands if cands[j] == g]
                    top = max(group, key=lambda j: (base[j], -j))
                    if top not in removed:
                        continue
                    rest = sorted((j for j in group if j not in removed and j in played),
                                  key=lambda j: (-base[j], j))
                    if len(rest) < 2:
                        continue
                    scale = (1.0 - p["OTHER"]) / b_tot
                    gains = {j: played[j] - base[j] * scale for j in rest}
                    g_nmu += gains[rest[0]]
                    g_all += sum(gains.values())
                    r_base = sum(base[j] for j in rest)
                    if r_base > 0:
                        prop.append(base[rest[0]] / r_base)
                    cases += 1
        frac = g_nmu / g_all if g_all > 0 else None
        out[col] = frac
        print("NMU_%s season %s: %d cases, fitted %.3f, group gain %.4f, proportional would give %.3f" % (
            col, season, cases, frac if frac is not None else float("nan"), g_all,
            sum(prop) / len(prop) if prop else float("nan")))
    return out


def bootstrap_diff(diffs, seed=7, n=2000):
    rng = random.Random(seed)
    m = len(diffs)
    means = sorted(sum(diffs[rng.randrange(m)] for _ in range(m)) / m for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def run(hist_with, hist_plain, overrides=None):
    p = dict(eng.DEFAULTS, **(overrides or {}))
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


def vs_espn(con, hist):
    p = dict(eng.DEFAULTS)
    espn = {}
    for gid, pid, stat, mean in con.execute(
            "SELECT game_id, player_id, stat, mean FROM player_projections WHERE season=2025 "
            "AND model_version='espn-weekly' AND scenario='base'"):
        espn[(gid, pid, stat)] = mean
    cells = {st: [] for st in ("rec", "rec_yds", "tgt", "rec_td")}
    for r in sorted(eligible(hist, 2025), key=lambda r: (r.week, r.pid)):
        v2 = eng.project(hist, 2025, r.week, r.pid, r.pos, r.team, r.opp, r.game_id, p)
        if v2 is None:
            continue
        for st in cells:
            e = espn.get((r.game_id, r.pid, st))
            m = eng.marcel(hist, 2025, r.week, r.pid, st)
            if e is not None and m is not None and st in v2:
                cells[st].append((getattr(r, st), v2[st], m, e))
    print("%-8s %5s %8s %8s %8s   %-26s %s" % ("stat", "n", "MAE v2", "MAE m1", "MAE espn", "v2 - espn [95% CI]", "m1 - espn"))
    for st, rows in cells.items():
        if not rows:
            continue
        n = len(rows)
        mae = lambda i: sum(abs(x[i] - x[0]) for x in rows) / n
        d_v2 = [abs(x[1] - x[0]) - abs(x[3] - x[0]) for x in rows]
        lo, hi = bootstrap_diff(d_v2)
        print("%-8s %5d %8.3f %8.3f %8.3f   %+7.3f [%+.3f, %+.3f]    %+.3f" % (
            st, n, mae(1), mae(2), mae(3), mae(1) - mae(3), lo, hi, mae(2) - mae(3)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--fit-dist", action="store_true")
    ap.add_argument("--run-dist", action="store_true")
    ap.add_argument("--vs-espn", action="store_true")
    ap.add_argument("--fit-nmu", action="store_true")
    ap.add_argument("--redist", choices=("v2.0", "4.3"), help="redistribution rule for --run (default: engine's)")
    a = ap.parse_args()
    con = connect()
    if a.fit:
        fit(eng.History.load(con, [2024]))
    if a.fit_nmu:
        fit_nmu(eng.History.load(con, [2024]))
        fit_nmu(eng.History.load(con, [2024, 2025]), season=2025)
    if a.fit_dist:
        fit_dist(eng.History.load(con, [2024]))
    if a.vs_espn:
        vs_espn(con, eng.History.load(con, [2024, 2025]))
    if a.run_dist:
        run_dist(eng.History.load(con, [2024, 2025]))
    if a.run:
        with_report = eng.History.load(con, [2024, 2025])
        plain = eng.History(with_report.rows, {})
        run(with_report, plain, {"REDIST": a.redist} if a.redist else None)


if __name__ == "__main__":
    main()
