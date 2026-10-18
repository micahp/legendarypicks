#!/usr/bin/env python3
"""audit_nfl_passing_projections.py -- is the passing failure volume, efficiency, or distribution?

The v2 prop grade selects the quarterback who led his team in attempts in the FINISHED game
(`max(team_rows, key=att)` over that week's box scores). That is post-game information, so the research
population is partly selected on the outcome and cannot represent pregame forecasting. This rebuilds the
population from pregame information only: a quarterback-game qualifies when he led his team in attempts over
the games BEFORE the target week.

For that population it measures the three failure modes separately, because they need different fixes:

  volume        projected attempts against actual attempts
  efficiency    projected completion rate and projected yards per completion against actual
  outcome       projected passing yards against actual, and the P(over) Brier against the market

It also reports how many player-games the population change moves, so the size of the look-ahead is visible.

Read-only. Usage: LP_DB_PATH=... python3 audit_nfl_passing_projections.py --season 2026
"""
import argparse
import os
import sqlite3
import zlib
from collections import defaultdict

import grade_nfl_prop_probabilities as g

PASSING = ("passing_yards", "pass_attempts", "pass_completions", "passing_touchdowns")
N_SIMS = 4000


def pregame_leader(hist, season, team, week):
    """Re-exported from the grader, which now owns the population definition."""
    return g.pregame_leader(hist, season, team, week)


def postgame_leader(hist, season, team, week):
    """What the current grader uses: most attempts in the target game itself."""
    rows = hist.by_team[(season, team)].get(week, [])
    if not rows:
        return None
    return max(rows, key=lambda x: (x.att, -x.pid)).pid


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

    rows = []
    moved = 0
    for (season, team), by_week in hist.by_team.items():
        if season != a.season:
            continue
        for week, wrows in by_week.items():
            if week < 2 or week not in final_weeks:
                continue
            pre = pregame_leader(hist, season, team, week)
            post = postgame_leader(hist, season, team, week)
            if pre != post:
                moved += 1
            for r in wrows:
                if r.pos != "QB" or r.att <= 0:
                    continue
                rows.append((r, pre == r.pid, post == r.pid))

    print("season %d: %d quarterback-games in weeks %s" % (
        a.season, len(rows), sorted({r.week for r, _p, _q in rows})))
    print("team-weeks where the pregame lead passer differs from the post-game one: %d" % moved)

    for label, idx in (("pregame population (this audit)", 1), ("post-game population (the grader)", 2)):
        pop = [r for r, p, q in rows if (p if idx == 1 else q)]
        if not pop:
            continue
        proj = {}
        for r in pop:
            v = g.eng.project_qb(hist, a.season, r.week, r.pid, r.team, r.opp, r.game_id)
            proj[(r.game_id, r.pid)] = v
        keep = [r for r in pop if proj.get((r.game_id, r.pid)) is not None
                and proj[(r.game_id, r.pid)]["att"] > 0]
        n = len(keep)
        print("\n== %s: %d quarterback-games with a projection ==" % (label, n))
        if not n:
            continue
        print("  %-22s %10s %10s %10s" % ("component", "projected", "actual", "MAE"))
        for nm, pfn, afn in (
                ("attempts", lambda v, r: v["att"], lambda r: r.att),
                ("completion rate", lambda v, r: v["cmp"] / v["att"], lambda r: r.cmp / r.att if r.att else 0),
                ("yards per completion", lambda v, r: v["pass_yds"] / v["cmp"] if v["cmp"] else 0,
                 lambda r: r.pass_yds / r.cmp if r.cmp else 0),
                ("passing yards", lambda v, r: v["pass_yds"], lambda r: r.pass_yds)):
            ps = [pfn(proj[(r.game_id, r.pid)], r) for r in keep]
            ac = [afn(r) for r in keep]
            mae = sum(abs(p - x) for p, x in zip(ps, ac)) / n
            print("  %-22s %10.3f %10.3f %10.3f" % (nm, sum(ps) / n, sum(ac) / n, mae))

    # item-level: does the population change move the P(over) result?
    items, skipped = g.collect(con, a.season)
    by_key = {}
    for r, p, q in rows:
        by_key[(r.game_id, r.pid)] = (p, q)
    # The draws depend only on the player-game, not on the line, so they are computed once and reused across
    # every alternate line on that game. Without this the audit recomputes 4,000 simulations per item.
    draws_cache = {}

    def draws_for(gid, pid):
        key = (gid, pid)
        if key in draws_cache:
            return draws_cache[key]
        r = next((x for x in hist.by_player.get((a.season, pid), []) if x.game_id == gid), None)
        out = None
        if r is not None:
            v = g.eng.project_qb(hist, a.season, r.week, r.pid, r.team, r.opp, r.game_id)
            if v is not None and v["att"] > 0:
                seed = zlib.crc32(("%s|%d|qb" % (gid, pid)).encode()) & 0xffff
                out = (g.eng.simulate_qb(v["att"], v["cmp"] / v["att"],
                                         v["pass_yds"] / v["cmp"] if v["cmp"] > 0 else 0.0,
                                         v["pass_td"] / v["att"], n=N_SIMS, seed=seed), r)
        draws_cache[key] = out
        return out

    for label, idx in (("pregame", 1), ("post-game", 2)):
        graded = []
        for gid, pid, market, book, line, p_mkt, book_hit in items:
            if market not in PASSING:
                continue
            week = int(gid.split("_")[1])
            if week < 2 or week not in final_weeks:
                continue
            flags = by_key.get((gid, pid))
            if flags is None or not flags[idx - 1]:
                continue
            got = draws_for(gid, pid)
            if got is None:
                continue
            draws, r = got
            idx_ = g.PASSING[market][0]
            attr = g.PASSING[market][1]
            p_ours = sum(1 for d in draws if d[idx_] > line) / len(draws)
            actual = getattr(r, attr)
            graded.append({"over": 1 if actual > line else 0, "p_ours": p_ours, "p_market": p_mkt,
                           "game_id": gid, "player_id": pid, "market": market})
        if not graded:
            continue
        n = len(graded)
        pg = len({(x["game_id"], x["player_id"]) for x in graded})
        b_o = sum((x["p_ours"] - x["over"]) ** 2 for x in graded) / n
        b_m = sum((x["p_market"] - x["over"]) ** 2 for x in graded) / n
        print("\n  P(over), passing markets, %s population: %d items on %d player-games" % (label, n, pg))
        print("    Brier ours %.4f  market %.4f  (constant 0.5 = 0.2500)" % (b_o, b_m))


if __name__ == "__main__":
    main()
