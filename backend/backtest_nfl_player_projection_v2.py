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


def diagnose_bias(hist, season=2025):
    """Where does the negative bias come from? PRE-REGISTERED 2026-10-13 before it was run. Measures only.

    Over `season` weeks 3 to 18, every team-game (team, week) with an earlier game:
      volume   projected team targets and carries (team_volume, frozen K_T) minus actual. Mean = volume bias.
      absorbed share of the team's projected targets and carries (engine shares, v2.0 rule) held by
               candidates who are neither removed by the report nor in the game's box score: the share
               the status doc's hypothesis says is lost to unavailable but unreported players.
      shares   sum of projected shares of the players who did log, against their actual summed share.
    The player-level bias decomposes as roughly volume bias x share + volume x share bias; both printed.
    """
    p = dict(eng.DEFAULTS)
    for col in ("tgt", "car"):
        vb, absorbed, proj_sh, act_sh, n = 0.0, 0.0, 0.0, 0.0, 0
        for (s, team), weeks in sorted(hist.team_weeks.items()):
            if s != season:
                continue
            for w in sorted(weeks):
                if w < 3 or w > 18:
                    continue
                rows = hist.by_team[(s, team)][w]
                gid, opp = rows[0].game_id, rows[0].opp
                vol = hist.team_volume(s, team, opp, w, col, p["K_T"])
                actual = hist.team_game(s, team, w, col)
                if vol is None or actual <= 0:
                    continue
                cands = hist.candidates(s, team, w)
                removed = hist.out_before(s, gid, team)
                played = {r.pid for r in rows}
                shares = {}
                for j, jp in cands.items():
                    if j in removed:
                        continue
                    got = hist.share_v20(s, w, team, j, jp, col, p, gid, {})
                    if got is not None:
                        shares[j] = got[0]
                vb += vol - actual
                absorbed += sum(v for j, v in shares.items() if j not in played)
                proj_sh += sum(v for j, v in shares.items() if j in played)
                act_sh += sum(getattr(r, col) for r in rows if r.pid in shares) / actual
                n += 1
        print("%s %s team-games %d: volume bias %+.3f per team-game; absorbed share %.4f; "
              "projected share of players who logged %.4f vs actual %.4f" % (
                  season, col, n, vb / n, absorbed / n, proj_sh / n, act_sh / n))


def fit_plog(hist, season=2024):
    """P_LOG by (k, last), PRE-REGISTERED with History.p_log. Prints the table to freeze."""
    counts = {}
    for (s, team), weeks in hist.team_weeks.items():
        if s != season:
            continue
        for w in sorted(weeks):
            if w < 3 or w > 18:
                continue
            rows = hist.by_team[(s, team)][w]
            gid = rows[0].game_id
            removed = hist.out_before(s, gid, team)
            played = {r.pid for r in rows}
            for j in hist.candidates(s, team, w):
                if j in removed:
                    continue
                key = "%d%d" % tuple(int(x) for x in hist.recent_form(s, team, w, j))
                c = counts.setdefault(key, [0, 0])
                c[0] += j in played
                c[1] += 1
    table = {}
    for key in sorted(counts):
        logged, n = counts[key]
        table[key] = round(logged / n, 3)
        print("P_LOG %s %s: %d of %d logged = %.3f" % (season, key, logged, n, logged / n))
    print("FROZEN P_LOG", table)
    return table


def fit_script(hist, season=2024):
    """B_tgt and B_car, PRE-REGISTERED in nfl_game_script.py. Least squares without intercept of
    (actual / projected team volume - 1) on the team's projected margin, weeks 3 to 18."""
    p = dict(eng.DEFAULTS)
    out = {}
    for col in ("tgt", "car"):
        sxy = sxx = 0.0
        n = 0
        for (s, team), weeks in hist.team_weeks.items():
            if s != season:
                continue
            for w in sorted(weeks):
                if w < 3 or w > 18:
                    continue
                rows = hist.by_team[(s, team)][w]
                m = hist.margins.get((s, rows[0].game_id, team))
                vol = hist.team_volume(s, team, rows[0].opp, w, col, p["K_T"])
                if m is None or not vol:
                    continue
                y = hist.team_game(s, team, w, col) / vol - 1.0
                sxy += m * y
                sxx += m * m
                n += 1
        out[col] = sxy / sxx
        print("B_%s season %s: %+.5f per point of margin over %d team-games" % (col, season, out[col], n))
    return out


def team_volume_check(hist, p, season=2025):
    """Team-level MAE of projected targets and carries with and without the script factor (gate part a)."""
    for col in ("tgt", "car"):
        e0 = e1 = 0.0
        n = 0
        for (s, team), weeks in hist.team_weeks.items():
            if s != season:
                continue
            for w in sorted(weeks):
                if w < 3 or w > 18:
                    continue
                rows = hist.by_team[(s, team)][w]
                vol = hist.team_volume(s, team, rows[0].opp, w, col, p["K_T"])
                if vol is None:
                    continue
                f = eng.script_factor(hist, s, rows[0].game_id, team, col, p)
                actual = hist.team_game(s, team, w, col)
                e0 += abs(vol - actual)
                e1 += abs(vol * f - actual)
                n += 1
        print("team %s %s, %d team-games: MAE without script %.3f, with %.3f" % (col, season, n, e0 / n, e1 / n))


QB_GRID = (40.0, 80.0, 160.0, 320.0, 640.0)


def qb_games(hist, season):
    """Graded QB player-games, as pre-registered in the engine: weeks 3 to 18, 3+ earlier games this season,
    and the team's attempt leader in that game."""
    for (s, pid), rows in hist.by_player.items():
        if s != season:
            continue
        for i, r in enumerate(rows):
            if r.pos != "QB" or r.week not in HIST_WEEKS or i < 3 or r.att <= 0:
                continue
            team_rows = hist.by_team[(s, r.team)][r.week]
            if max(x.att for x in team_rows) == r.att and max(team_rows, key=lambda x: (x.att, -x.pid)).pid == pid:
                yield r


def fit_qb(hist, season=2024):
    """K_CMP, K_YPA, K_PTD on the pre-registered grid, then R_ATT and G_PASS by method of moments."""
    games = list(qb_games(hist, season))
    print("%d QB player-games in %d" % (len(games), season))
    ks = {}
    for stat, k in eng.PASSING[1]:
        best = None
        for kv in QB_GRID:
            sse = sum((getattr(r, stat) - r.att * hist.eff(season, r.week, r.pid, "QB", "att", stat, kv, None)) ** 2
                      for r in games)
            if best is None or sse < best[0]:
                best = (sse, kv)
        ks[k] = best[1]
        print("%s = %s (mean sq err %.3f)" % (k, best[1], best[0] / len(games)))
    p = dict(eng.DEFAULTS, **ks)
    num = den = ysq = ysum = ypc_n = ypc_d = 0.0
    for r in games:
        v = eng.project_qb(hist, season, r.week, r.pid, r.team, r.opp, r.game_id, p)
        if v is None:
            continue
        mu = v["att"]
        num += mu * mu
        den += (r.att - mu) ** 2 - mu
        if r.cmp > 0 and v["cmp"] > 0:
            ypc = v["pass_yds"] / v["cmp"]
            ysq += (r.pass_yds - r.cmp * ypc) ** 2
            ysum += r.cmp
            ypc_n += r.pass_yds
            ypc_d += r.cmp
    r_att = num / den if den > 0 else 1e6
    mean_ypc = ypc_n / ypc_d
    g = mean_ypc ** 2 / (ysq / ysum)
    print("R_ATT = %.2f  G_PASS = %.2f (mean yards per completion %.2f)" % (r_att, g, mean_ypc))
    print("FROZEN QB", dict(ks, R_ATT=round(r_att, 2), G_PASS=round(g, 2)))


def run_qb(hist, season=2025):
    p = dict(eng.DEFAULTS, **eng.QB_DEFAULTS)
    games = sorted(qb_games(hist, season), key=lambda r: (r.week, r.pid))
    cols = {st: [] for st in ("att", "cmp", "pass_yds", "pass_td")}
    band = {st: [0, 0, 0] for st in cols}
    for i, r in enumerate(games):
        v = eng.project_qb(hist, season, r.week, r.pid, r.team, r.opp, r.game_id, p)
        if v is None:
            continue
        ms = {st: eng.marcel(hist, season, r.week, r.pid, st) for st in cols}
        if any(m is None for m in ms.values()):
            continue
        for st in cols:
            cols[st].append((getattr(r, st), v[st], ms[st]))
        draws = eng.simulate_qb(v["att"], v["cmp"] / v["att"] if v["att"] else 0.0,
                                v["pass_yds"] / v["cmp"] if v["cmp"] else 0.0,
                                v["pass_td"] / v["att"] if v["att"] else 0.0, n=1000, seed=i)
        for idx, st in ((3, "att"), (0, "cmp"), (1, "pass_yds"), (2, "pass_td")):
            q = eng.summarize(draws, idx)
            actual = getattr(r, st)
            band[st][0] += actual < q["p10"]
            band[st][1] += q["p10"] <= actual <= q["p90"]
            band[st][2] += actual > q["p90"]
    print("2025 QB player-games graded: %d" % len(cols["att"]))
    print("%-9s %5s %8s %8s %8s   %s" % ("stat", "n", "MAE v2", "MAE m1", "bias v2", "v2 - marcel [95% CI]"))
    verdict = {}
    for st, rows in cols.items():
        n = len(rows)
        d = [abs(v - a) - abs(m - a) for a, v, m in rows]
        lo, hi = bootstrap_diff(d)
        verdict[st] = sum(d) / n
        print("%-9s %5d %8.3f %8.3f %+8.3f   %+.3f [%+.3f, %+.3f]" % (
            st, n, sum(abs(v - a) for a, v, m in rows) / n, sum(abs(m - a) for a, v, m in rows) / n,
            sum(v - a for a, v, m in rows) / n, sum(d) / n, lo, hi))
    print("GATE (pass_yds and att both lower than Marcel-lite): %s" % (
        "PASS" if verdict["pass_yds"] < 0 and verdict["att"] < 0 else "FAIL"))
    for st, (b, inside, a) in band.items():
        n = b + inside + a
        print("band %-9s inside %.1f%%  below p10 %.1f%%  above p90 %.1f%%" % (st, 100.0 * inside / n, 100.0 * b / n, 100.0 * a / n))


def consistency(hist, points, season=2025, out_path=None):
    """Spec B 4.6 team consistency gap. PRE-REGISTERED 2026-10-13 as a measurement; nothing is forced or gated.

    For every team-game of `season`, weeks 3 to 18: project (engine defaults) every candidate the report does
    not remove, for receiving and rushing, conditional on playing, and sum per team: yards (receiving + rushing)
    and TDs (receiving + rushing). Shares of those candidates sum to 1 - OTHER by construction, so the sum is a
    team total. Beside it: SPEC A version 1's projected points for the team (walk-forward) and the actual points.
    Reported: mean of each; gap = SPEC A points - 7 x projected TDs (field goals, passing-only TDs to non-skill
    players, defensive scores and extra-point misses all live in the gap); correlation across team-games of
    projected TDs with SPEC A points and with actual points, and of SPEC A points with actual points. Rows go to
    `out_path` as CSV, one per team-game.
    """
    import csv
    p = dict(eng.DEFAULTS)
    rows_out = []
    for (s, team), weeks in sorted(hist.team_weeks.items()):
        if s != season:
            continue
        for w in sorted(weeks):
            if w < 3 or w > 18:
                continue
            rows = hist.by_team[(s, team)][w]
            gid, opp = rows[0].game_id, rows[0].opp
            pts = points.get((s, gid, team))
            if pts is None:
                continue
            removed = hist.out_before(s, gid, team)
            yds = tds = 0.0
            for j, jp in hist.candidates(s, team, w).items():
                if j in removed:
                    continue
                v = eng.project(hist, s, w, j, jp, team, opp, gid, p)
                if v is None:
                    continue
                yds += v.get("rec_yds", 0.0) + v.get("rush_yds", 0.0)
                tds += v.get("rec_td", 0.0) + v.get("rush_td", 0.0)
            act_yds = sum(r.rec_yds + r.rush_yds for r in rows)
            act_tds = sum(r.rec_td + r.rush_td for r in rows)
            rows_out.append({"season": s, "week": w, "team": team, "game_id": gid,
                             "proj_yds": round(yds, 1), "proj_tds": round(tds, 3), "speca_points": round(pts[0], 2),
                             "actual_points": pts[1], "actual_skill_yds": act_yds, "actual_skill_tds": act_tds,
                             "gap": round(pts[0] - 7.0 * tds, 2)})
    n = len(rows_out)

    def mean(k):
        return sum(r[k] for r in rows_out) / n

    def corr(a, b):
        ma, mb = mean(a), mean(b)
        cov = sum((r[a] - ma) * (r[b] - mb) for r in rows_out)
        va = sum((r[a] - ma) ** 2 for r in rows_out)
        vb = sum((r[b] - mb) ** 2 for r in rows_out)
        return cov / (va * vb) ** 0.5 if va > 0 and vb > 0 else float("nan")
    if n < 3:
        print("%d team-games: too few for a summary" % n)
        return rows_out
    gaps = sorted(r["gap"] for r in rows_out)
    print("%d team-games, %d weeks 3 to 18" % (n, season))
    for k in ("proj_yds", "actual_skill_yds", "proj_tds", "actual_skill_tds", "speca_points", "actual_points", "gap"):
        print("  mean %-17s %.2f" % (k, mean(k)))
    print("  gap sd %.2f, p10 %.2f, p90 %.2f" % (
        (sum((g - mean("gap")) ** 2 for g in gaps) / (n - 1)) ** 0.5, gaps[n // 10], gaps[(9 * n) // 10]))
    print("  corr(proj TDs, SPEC A points) %.3f   corr(proj TDs, actual points) %.3f   "
          "corr(SPEC A points, actual points) %.3f   corr(proj yds, SPEC A points) %.3f" % (
              corr("proj_tds", "speca_points"), corr("proj_tds", "actual_points"),
              corr("speca_points", "actual_points"), corr("proj_yds", "speca_points")))
    if out_path:
        with open(out_path, "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows_out[0]))
            wr.writeheader()
            wr.writerows(rows_out)
        print("  per team-game rows: %s" % out_path)
    return rows_out


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
    ap.add_argument("--diagnose-bias", action="store_true")
    ap.add_argument("--fit-plog", action="store_true")
    ap.add_argument("--fit-script", action="store_true")
    ap.add_argument("--fit-qb", action="store_true")
    ap.add_argument("--consistency", metavar="CSV", help="Spec B 4.6 gap report for 2025; per team-game rows to CSV")
    ap.add_argument("--run-qb", action="store_true")
    ap.add_argument("--script", action="store_true", help="--run with SPEC A margins and SCRIPT_2024 (not the default)")
    ap.add_argument("--plog", action="store_true", help="--run with P_LOG_2024 (not the default)")
    ap.add_argument("--redist", choices=("v2.0", "4.3"), help="redistribution rule for --run (default: engine's)")
    a = ap.parse_args()
    con = connect()
    if a.fit:
        fit(eng.History.load(con, [2024]))
    if a.consistency:
        import nfl_game_script as gs
        consistency(eng.History.load(con, [2024, 2025]), gs.points_walk_forward(con, [2025]),
                    out_path=a.consistency)
    if a.fit_qb:
        fit_qb(eng.History.load(con, [2024]))
    if a.run_qb:
        run_qb(eng.History.load(con, [2024, 2025]))
    if a.fit_script:
        import nfl_game_script as gs
        h = eng.History.load(con, [2024, 2025])
        h.margins = gs.margins_walk_forward(con, [2024, 2025])
        fit_script(h)
        fit_script(h, season=2025)
    if a.fit_plog:
        fit_plog(eng.History.load(con, [2024]))
        fit_plog(eng.History.load(con, [2024, 2025]), season=2025)
    if a.diagnose_bias:
        diagnose_bias(eng.History.load(con, [2024, 2025]))
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
        over = {}
        if a.script:
            import nfl_game_script as gs
            with_report.margins = plain.margins = gs.margins_walk_forward(con, [2024, 2025])
            over.update(eng.SCRIPT_2024)
            team_volume_check(with_report, dict(eng.DEFAULTS, **over))
        if a.redist:
            over["REDIST"] = a.redist
        if a.plog:
            over["P_LOG"] = eng.P_LOG_2024
        run(with_report, plain, over)


if __name__ == "__main__":
    main()
