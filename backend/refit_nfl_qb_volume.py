#!/usr/bin/env python3
"""refit_nfl_qb_volume.py -- pick the attempt shrinkage on fit seasons, and fix the level separately.

Two independent problems were found in section 6 of the results doc:

  dispersion   team_volume regresses toward the league mean with K_T = 8 pseudo-games, so with one to four
               games behind a team the projection is nearly the league mean for everyone and cannot rank
               anybody. AUC rises monotonically as K_T falls.
  level        the projection is 6.7% low, and the bias is unchanged across the whole K_T sweep, so it lives in
               the level the shrinkage pulls toward rather than in the amount of shrinkage.

K_T was fitted on 2024 by minimising the MAE of projected receiver targets. MAE is minimised by shrinking toward
the conditional median, so that objective picks heavy shrinkage by construction. This fits K_T on the fit
seasons under two objectives and compares them:

  mae          mean absolute error of projected team attempts
  auc          AUC of the projected attempts against a predetermined threshold, the fit-season median team
               attempts. No sportsbook quotes exist across the fit seasons, so a fixed threshold is the only
               discrimination measure available historically, and it is predetermined rather than fitted.

The level correction is fitted separately, on the fit seasons, and the two are evaluated together on 2026, which
neither saw. The pass-attempts market is then re-scored and the market increment re-run, because that is the
market the change touches.

Read-only. Usage: LP_DB_PATH=... python3 refit_nfl_qb_volume.py --fit-seasons 2013 ... 2021 --season 2026
"""
import argparse
import os
import sqlite3
import zlib
from collections import defaultdict

import grade_nfl_prop_probabilities as g
from audit_nfl_passing_projections import pregame_leader
from measure_nfl_prop_discrimination import auc, logloss, brier

KT_GRID = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0)
# K_T 0.0 is not representable: `reg` computes (total + k_t * league) / (n + k_t), which is 0/0 when a team has
# no earlier games. The grid therefore starts at 0.25, which still collapses to the league mean at n = 0.


def team_games(hist, seasons, max_week=18):
    """(season, team, week, opp, projected_at, actual) for every team-game in these seasons, at each K_T.

    max_week matters more than it looks. Shrinkage binds hardest where a team has one to four games behind it,
    which is weeks 2 to 5, and that is the only regime props exist in. A K_T selected over all weeks is
    dominated by mid and late season games where the same constant barely shrinks at all.
    """
    out = []
    for (season, team), by_week in hist.by_team.items():
        if season not in seasons:
            continue
        for week, wrows in by_week.items():
            if week < 2 or week > max_week or not wrows:
                continue
            opp = wrows[0].opp
            actual = sum(r.att for r in wrows)
            if actual <= 0:
                continue
            proj = {kt: hist.team_volume(season, team, opp, week, "att", kt) for kt in KT_GRID}
            if any(v is None for v in proj.values()):
                continue
            out.append((season, team, week, opp, proj, actual))
    return out


def evaluate(rows, kt):
    pa = [r[4][kt] for r in rows]
    aa = [r[5] for r in rows]
    n = len(rows)
    mae = sum(abs(p - x) for p, x in zip(pa, aa)) / n
    return pa, aa, mae


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fit-seasons", type=int, nargs="+", required=True)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--fit-max-week", type=int, default=5,
                    help="restrict the fit to this week and earlier, matching the regime props exist in")
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    seasons = sorted(set(a.fit_seasons) | {a.season, a.season - 1})
    hist = g.eng.History.load(con, seasons)

    def kt_table(rows, label):
        print("\n== K_T by objective, %s ==" % label)
        print("  %6s %10s %10s %10s %10s" % ("K_T", "MAE", "sd proj", "sd actual", "AUC"))
        out = {}
        for kt in KT_GRID:
            pa, aa, mae = evaluate(rows, kt)
            pairs = [(p, 1 if x > thr else 0) for p, x in zip(pa, aa)]
            out[kt] = (mae, auc(pairs), pa, aa)
            print("  %6.1f %10.3f %10.3f %10.3f %10.4f" % (
                kt, mae, (sum((v - sum(pa) / len(pa)) ** 2 for v in pa) / (len(pa) - 1)) ** 0.5,
                (sum((v - sum(aa) / len(aa)) ** 2 for v in aa) / (len(aa) - 1)) ** 0.5, out[kt][1]))
        bm = min(KT_GRID, key=lambda k: out[k][0])
        ba = max(KT_GRID, key=lambda k: out[k][1])
        print("  MAE picks K_T %.2f (MAE %.3f); AUC picks K_T %.2f (AUC %.4f)" % (
            bm, out[bm][0], ba, out[ba][1]))
        return out, bm, ba

    fit_all = team_games(hist, set(a.fit_seasons))
    fit = team_games(hist, set(a.fit_seasons), a.fit_max_week)
    thr = sorted(r[5] for r in fit)[len(fit) // 2]
    print("fit seasons %s: %d team-games over all weeks, %d in weeks 2 to %d" % (
        a.fit_seasons, len(fit_all), len(fit), a.fit_max_week))
    print("predetermined discrimination threshold (median team attempts, weeks 2 to %d): %.1f" % (
        a.fit_max_week, thr))
    kt_table(fit_all, "all fit weeks")
    res, best_mae, best_auc = kt_table(fit, "fit weeks 2 to %d, the regime props live in" % a.fit_max_week)
    if best_mae != best_auc:
        print("  NOTE: the two objectives disagree in this regime, so the choice matters")

    print("\n== the level, in the same week regime ==")
    for label, rows_ in (("all fit weeks", fit_all), ("fit weeks 2 to %d" % a.fit_max_week, fit)):
        pa, aa, _ = evaluate(rows_, best_auc)
        print("  %-22s mean projected %.3f, mean actual %.3f, ratio %.4f, shift %+.3f" % (
            label, sum(pa) / len(pa), sum(aa) / len(aa), (sum(pa) / len(pa)) / (sum(aa) / len(aa)),
            (sum(pa) - sum(aa)) / len(pa)))
    pa8, aa8, _ = evaluate(fit, best_auc)
    mult = (sum(aa8) / len(aa8)) / (sum(pa8) / len(pa8))
    add = (sum(aa8) - sum(pa8)) / len(pa8)
    m_mae = sum(abs(p * mult - x) for p, x in zip(pa8, aa8)) / len(pa8)
    a_mae = sum(abs(p + add - x) for p, x in zip(pa8, aa8)) / len(pa8)
    print("  fit MAE in that regime: none %.3f, multiplicative %.3f, additive %.3f" % (
        res[best_auc][0], m_mae, a_mae))
    level = "mult" if m_mae <= a_mae else "add"
    print("  using the %s correction, factor %.4f, shift %+.3f" % (level, mult, add))

    def apply_level(v):
        return v * mult if level == "mult" else v + add

    # ---- 2026, held out from both fits ----
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
            for r in wrows:
                if r.pid != pre or r.att <= 0:
                    continue
                share = min(1.0, hist.raw_share(a.season, r.pid, "QB", r.week, "att",
                                                dict(g.eng.DEFAULTS, **g.eng.QB_DEFAULTS), None)[0])
                recs.append({"pid": r.pid, "team": team, "opp": r.opp, "week": week, "game_id": r.game_id,
                             "act": r.att, "share": share,
                             "proj": {kt: hist.team_volume(a.season, team, r.opp, week, "att", kt)
                                      for kt in KT_GRID}})
    print("\n== 2026, held out: %d pregame quarterback-games ==" % len(recs))
    print("  %-34s %9s %8s %10s %10s" % ("variant", "bias", "MAE", "sd proj", "AUC"))
    variants = []
    for kt in sorted({8.0, best_auc, best_mae}):
        for lv in (False, True):
            pa = [(apply_level(r["proj"][kt]) if lv else r["proj"][kt]) * r["share"] for r in recs]
            aa = [r["act"] for r in recs]
            pairs = [(p, 1 if x > thr else 0) for p, x in zip(pa, aa)]
            nm = "K_T %.1f%s" % (kt, " + level" if lv else "")
            variants.append((nm, kt, lv))
            print("  %-34s %+9.3f %8.3f %10.3f %10.4f" % (
                nm, (sum(pa) - sum(aa)) / len(pa), sum(abs(p - x) for p, x in zip(pa, aa)) / len(pa),
                (sum((v - sum(pa) / len(pa)) ** 2 for v in pa) / (len(pa) - 1)) ** 0.5, auc(pairs)))

    # ---- the affected market: pass attempts, re-scored, then the market increment ----
    items, _sk = g.collect(con, a.season)
    att_items = [it for it in items if it[2] == "pass_attempts"]
    by_key = {(r["game_id"], r["pid"]): r for r in recs}
    # `collect` returns every posted line regardless of week; only the items whose player-game is in the
    # pregame population and has a settled week can be scored, so the scored count is reported separately.
    att_scorable = []
    for it in att_items:
        r = by_key.get((it[0], it[1]))
        if r is None:
            continue
        row = next((x for x in hist.by_player.get((a.season, it[1]), []) if x.game_id == it[0]), None)
        if row is not None:
            att_scorable.append((it, r, row))
    print("\n== pass-attempts market: %d of %d posted items are scorable, on %d player-games ==" % (
        len(att_scorable), len(att_items), len({(it[0][0], it[0][1]) for it in att_scorable})))
    print("  %-34s %8s %8s %8s" % ("variant", "Brier", "logloss", "AUC"))
    scorable = {}
    draw_cache = {}
    for nm, kt, lv in variants:
        graded = []
        for (gid, pid, market, book, line, p_mkt, book_hit), r, row in att_scorable:
            # The draws depend on the player-game and the variant, not on the line, so they are computed once
            # and reused across every alternate line posted on that game.
            ck = (nm, gid, pid)
            if ck not in draw_cache:
                base = apply_level(r["proj"][kt]) if lv else r["proj"][kt]
                mean_att = base * r["share"]
                if mean_att <= 0:
                    draw_cache[ck] = None
                else:
                    p = dict(g.eng.DEFAULTS, **g.eng.QB_DEFAULTS)
                    cmp_rate = hist.eff(a.season, row.week, pid, "QB", "att", "cmp", p["K_CMP"], None)
                    ypc = hist.eff(a.season, row.week, pid, "QB", "att", "pass_yds", p["K_YPA"], None)
                    td_rate = hist.eff(a.season, row.week, pid, "QB", "att", "pass_td", p["K_PTD"], None)
                    seed = zlib.crc32(("%s|%d|qb" % (gid, pid)).encode()) & 0xffff
                    draw_cache[ck] = g.eng.simulate_qb(mean_att, cmp_rate, ypc, td_rate, n=4000, seed=seed)
            draws = draw_cache[ck]
            if draws is None:
                continue
            p_ours = sum(1 for d in draws if d[3] > line) / len(draws)
            graded.append({"over": 1 if row.att > line else 0, "p_ours": p_ours, "p_market": p_mkt,
                           "line": line, "book": book, "game_id": gid, "player_id": pid,
                           "week": int(gid.split("_")[1])})
        scorable[nm] = graded
        print("  %-34s %8.4f %8.4f %8.4f" % (
            nm, brier(graded, "p_ours"), logloss(graded, "p_ours"), auc([(x["p_ours"], x["over"]) for x in graded])))
    print("  (constant 0.5 scores Brier 0.2500)")

    # paired, clustered, on the identical items, so the change is not a difference of two populations
    if "K_T 4.0" in scorable and "K_T 8.0" in scorable:
        from measure_nfl_prop_discrimination import cluster_boot
        idx = {}
        for x in scorable["K_T 8.0"]:
            idx[(x["game_id"], x["player_id"], x["book"], x["line"])] = {"over": x["over"],
                                                                        "p8": x["p_ours"], "p4": None}
        for x in scorable["K_T 4.0"]:
            k = (x["game_id"], x["player_id"], x["book"], x["line"])
            if k in idx:
                idx[k]["p4"] = x["p_ours"]
        both = [dict(v, game_id=k[0], player_id=k[1]) for k, v in idx.items() if v["p4"] is not None]
        print("\n  paired on %d identical items, %d player-games:" % (
            len(both), len({(x["game_id"], x["player_id"]) for x in both})))
        for nm, fn in (("Brier", lambda s, f: brier(s, f)), ("logloss", lambda s, f: logloss(s, f))):
            obs, lo, hi = cluster_boot(both, lambda s: fn(s, "p8") - fn(s, "p4"), 200)
            print("    %-8s K_T 8.0 minus K_T 4.0: %+.5f  clustered 95%% [%+.5f, %+.5f]" % (
                nm, obs, lo, hi))
        print("    (positive means the current K_T 8.0 is better; negative means the refit is)")

    print("\n== the market increment on the affected market, forward only ==")
    print("  %-34s %10s %10s %12s" % ("ours variant", "logloss mkt", "logloss stk", "increment"))
    from measure_nfl_prop_discrimination import fit_logistic, sigmoid, logit
    for nm, _kt, _lv in variants:
        rows_ = scorable[nm]
        stack = []
        for held in sorted({x["week"] for x in rows_}):
            tr = [x for x in rows_ if x["week"] < held]
            te = [x for x in rows_ if x["week"] == held]
            if len(tr) < 200 or not te:
                continue
            for x in tr + te:
                x["l_market"] = logit(x["p_market"])
                x["l_ours"] = logit(x["p_ours"])
            wm = fit_logistic([[1.0, x["l_market"]] for x in tr], [x["over"] for x in tr])
            ws = fit_logistic([[1.0, x["l_market"], x["l_ours"]] for x in tr], [x["over"] for x in tr])
            for x in te:
                x["s_mkt"] = sigmoid(wm[0] + wm[1] * x["l_market"])
                x["s_stk"] = sigmoid(ws[0] + ws[1] * x["l_market"] + ws[2] * x["l_ours"])
                x["coef_ours"] = ws[2]
            stack.extend(te)
        if not stack:
            continue
        print("  %-34s %10.4f %10.4f %+12.5f" % (
            nm, logloss(stack, "s_mkt"), logloss(stack, "s_stk"),
            logloss(stack, "s_mkt") - logloss(stack, "s_stk")))
    print("  (positive increment means adding ours improves on the market alone)")


if __name__ == "__main__":
    main()
