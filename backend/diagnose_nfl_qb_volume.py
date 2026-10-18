#!/usr/bin/env python3
"""diagnose_nfl_qb_volume.py -- where does the quarterback attempt error live?

The passing audit established that attempts are under-projected by about 6.7% while completion rate and yards
per completion are unbiased. A uniform level shift cannot fix that on its own: it moves every forecast without
reordering anything, so it cannot improve discrimination. What matters is which quarterbacks and which game
situations carry the largest errors, and whether the error is a compression (high projections too low, low
ones too high) or an idiosyncratic per-player effect.

`project_qb` computes `att = team_volume('att') * raw_share(QB, 'att')`, so the error splits into a team-volume
part and a share part. This reports both, then stratifies the total error by projected level, by games of
history, by week and by quarterback, all on the pregame-only population from
`audit_nfl_passing_projections.pregame_leader`.

Read-only. Usage: LP_DB_PATH=... python3 diagnose_nfl_qb_volume.py --season 2026
"""
import argparse
import math
import os
import sqlite3
from collections import defaultdict

import grade_nfl_prop_probabilities as g
from audit_nfl_passing_projections import pregame_leader


def ols_slope(xs, ys, clusters):
    """Slope of y on x with a cluster-robust standard error."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None, None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    by = defaultdict(float)
    for x, y, c in zip(xs, ys, clusters):
        by[c] += (x - mx) * (y - my - b * (x - mx))
    G = len(by)
    if G < 2:
        return b, None
    var = G / (G - 1.0) * sum(v * v for v in by.values()) / sxx ** 2
    return b, 1.96 * math.sqrt(var)


def sd(v):
    m = sum(v) / len(v)
    return (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5 if len(v) > 1 else 0.0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int, required=True)
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    hist = g.eng.History.load(con, [a.season - 1, a.season])
    final_weeks = {w for (w,) in con.execute(
        "SELECT DISTINCT week FROM nfl_schedule WHERE season=? AND game_type='REG' AND home_score IS NOT NULL",
        (a.season,))}

    recs = []
    for (season, team), by_week in hist.by_team.items():
        if season != a.season:
            continue
        for week, wrows in by_week.items():
            if week < 2 or week not in final_weeks:
                continue
            pre = pregame_leader(hist, season, team, week)
            if pre is None:
                continue
            team_att = sum(r.att for r in wrows)
            for r in wrows:
                if r.pid != pre or r.att <= 0:
                    continue
                v = g.eng.project_qb(hist, a.season, r.week, r.pid, r.team, r.opp, r.game_id)
                if v is None or v["att"] <= 0:
                    continue
                vol = hist.team_volume(a.season, r.team, r.opp, r.week, "att",
                                       g.eng.DEFAULTS["K_T"])
                share = min(1.0, hist.raw_share(a.season, r.pid, "QB", r.week, "att",
                                                dict(g.eng.DEFAULTS, **g.eng.QB_DEFAULTS), None)[0])
                hist_prior = len([x for x in hist.by_player.get((a.season, r.pid), []) if x.week < week])
                recs.append({"pid": r.pid, "week": week, "team": r.team, "opp": r.opp, "game_id": r.game_id,
                             "proj_att": v["att"], "act_att": r.att,
                             "proj_vol": vol, "act_vol": team_att,
                             "proj_share": share, "act_share": (r.att / team_att) if team_att else 0.0,
                             "hist": hist_prior})
    n = len(recs)
    print("season %d, pregame lead passers with a projection: %d quarterback-games" % (a.season, n))
    if not n:
        return
    pa = [r["proj_att"] for r in recs]
    aa = [r["act_att"] for r in recs]
    print("\n== the total, and whether it is compressed ==")
    print("  projected mean %.3f  sd %.3f" % (sum(pa) / n, sd(pa)))
    print("  actual    mean %.3f  sd %.3f" % (sum(aa) / n, sd(aa)))
    print("  bias %+.3f (%.1f%%), MAE %.3f" % (
        (sum(pa) - sum(aa)) / n, 100 * (sum(pa) / sum(aa) - 1), sum(abs(p - x) for p, x in zip(pa, aa)) / n))
    b, hw = ols_slope(pa, aa, [r["game_id"] for r in recs])
    print("  slope of actual on projected %s%s" % (
        "%.3f" % b if b is not None else "n/a",
        "" if hw is None else " clustered 95%% +/- %.3f" % hw))
    print("  (slope 1 = no compression. Above 1 means high projections are too low and low ones too high,")
    print("   which is a dispersion problem, not a level problem, and only that can move discrimination.)")

    print("\n== the decomposition: team volume against quarterback share ==")
    for nm, pk, ak in (("team attempts", "proj_vol", "act_vol"), ("qb share", "proj_share", "act_share")):
        ps = [r[pk] for r in recs]
        acs = [r[ak] for r in recs]
        bb, hh = ols_slope(ps, acs, [r["game_id"] for r in recs])
        print("  %-14s projected %.3f (sd %.3f)  actual %.3f (sd %.3f)  bias %+.3f  MAE %.3f  slope %s" % (
            nm, sum(ps) / n, sd(ps), sum(acs) / n, sd(acs), (sum(ps) - sum(acs)) / n,
            sum(abs(p - x) for p, x in zip(ps, acs)) / n, "%.3f" % bb if bb is not None else "n/a"))

    print("\n== error by projected level (quintiles of projected attempts) ==")
    srt = sorted(recs, key=lambda r: r["proj_att"])
    q = max(1, n // 5)
    print("  %-18s %5s %9s %9s %9s" % ("quintile", "n", "proj", "actual", "bias"))
    for i in range(5):
        sub = srt[i * q:(i + 1) * q] if i < 4 else srt[4 * q:]
        if not sub:
            continue
        print("  %-18s %5d %9.2f %9.2f %+9.2f" % (
            "%.1f to %.1f" % (sub[0]["proj_att"], sub[-1]["proj_att"]), len(sub),
            sum(x["proj_att"] for x in sub) / len(sub), sum(x["act_att"] for x in sub) / len(sub),
            sum(x["proj_att"] - x["act_att"] for x in sub) / len(sub)))

    print("\n== error by games of history available ==")
    print("  %-14s %5s %9s %9s %9s" % ("games", "n", "proj", "actual", "bias"))
    for lo, hi in ((0, 3), (4, 7), (8, 12), (13, 99)):
        sub = [r for r in recs if lo <= r["hist"] <= hi]
        if len(sub) < 5:
            continue
        print("  %-14s %5d %9.2f %9.2f %+9.2f" % (
            "%d to %d" % (lo, hi), len(sub), sum(x["proj_att"] for x in sub) / len(sub),
            sum(x["act_att"] for x in sub) / len(sub),
            sum(x["proj_att"] - x["act_att"] for x in sub) / len(sub)))

    print("\n== error by week ==")
    print("  %-6s %5s %9s %9s %9s" % ("week", "n", "proj", "actual", "bias"))
    for w in sorted({r["week"] for r in recs}):
        sub = [r for r in recs if r["week"] == w]
        if len(sub) < 3:
            continue
        print("  %-6d %5d %9.2f %9.2f %+9.2f" % (
            w, len(sub), sum(x["proj_att"] for x in sub) / len(sub),
            sum(x["act_att"] for x in sub) / len(sub),
            sum(x["proj_att"] - x["act_att"] for x in sub) / len(sub)))

    byq = defaultdict(list)
    for r in recs:
        byq[r["pid"]].append(r)
    rows = [(pid, len(v), sum(x["proj_att"] - x["act_att"] for x in v) / len(v)) for pid, v in byq.items()
            if len(v) >= 3]
    rows.sort(key=lambda t: t[2])
    names = {pid: nm for pid, nm in con.execute("SELECT id, name FROM players")}
    print("\n== most over-projected quarterbacks (min 3 games) ==")
    for pid, k, e in rows[-6:][::-1]:
        print("  %-24s n %d  mean error %+.2f" % (names.get(pid, pid), k, e))
    print("== most under-projected ==")
    for pid, k, e in rows[:6]:
        print("  %-24s n %d  mean error %+.2f" % (names.get(pid, pid), k, e))
    print("  (each quarterback here has only 3 or 4 games, and one game's attempts vary with sd 9.7, so a")
    print("   four-game mean error has a standard error near 4.9. The rank order is not reliable at this n.)")

    # ---- the tradeoff the fitted constant is making ----
    print("\n== K_T sweep: what the shrinkage constant buys and what it costs ==")
    print("  K_T is the pseudo-game constant in team_volume, fitted by minimising MAE. MAE is minimised by")
    print("  shrinking toward the conditional median, so the fitted value trades dispersion for point accuracy.")
    items, _sk = g.collect(con, a.season)
    att_items = [it for it in items if it[2] == "pass_attempts"]
    actual_by_key = {(r["game_id"], r["pid"]): r["act_att"] for r in recs}
    print("\n  %6s %9s %8s %10s %10s %8s %8s" % (
        "K_T", "bias", "MAE", "sd proj", "sd actual", "AUC", "n items"))
    for KT in (0.0, 1.0, 2.0, 4.0, 8.0, 16.0):
        pa2 = []
        for r in recs:
            v2 = hist.team_volume(a.season, r["team"], r["opp"], r["week"], "att", KT)
            pa2.append((v2 or 0.0) * r["proj_share"])
        aa2 = [r["act_att"] for r in recs]
        pairs = []
        for gid, pid, market, book, line, p_mkt, book_hit in att_items:
            act = actual_by_key.get((gid, pid))
            if act is None:
                continue
            v2 = hist.team_volume(a.season, next(r["team"] for r in recs if r["game_id"] == gid and r["pid"] == pid),
                                  next(r["opp"] for r in recs if r["game_id"] == gid and r["pid"] == pid),
                                  next(r["week"] for r in recs if r["game_id"] == gid and r["pid"] == pid),
                                  "att", KT)
            sh = next(r["proj_share"] for r in recs if r["game_id"] == gid and r["pid"] == pid)
            pairs.append(((v2 or 0.0) * sh, 1 if act > line else 0))
        from measure_nfl_prop_discrimination import auc as _auc
        print("  %6.1f %+9.3f %8.3f %10.3f %10.3f %8.4f %8d" % (
            KT, (sum(pa2) - sum(aa2)) / n, sum(abs(p - x) for p, x in zip(pa2, aa2)) / n,
            sd(pa2), sd(aa2), (_auc(pairs) or 0.0), len(pairs)))
    print("  (the AUC column ranks quarterbacks by their projected attempts against the settled attempt line.)")


if __name__ == "__main__":
    main()
