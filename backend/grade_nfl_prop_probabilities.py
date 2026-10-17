#!/usr/bin/env python3
"""grade_nfl_prop_probabilities.py -- Spec B section 5, props: grade our P(over) on settled NFL props.

PRE-REGISTERED 2026-10-13, committed before it was run. Read-only: prints, and writes a CSV only if asked.

Population. Props on the dev DB exist for the 2026 season only (none for 2025), so the projection is the version 2
engine run walk-forward for 2026: each player-game from games before its week and that game's final injury
report, constants as frozen (fitted on 2024), i.e. what the job would have produced, recomputed now. It is not a
captured pre-kickoff number; the captured comparison starts with the weekly job.
  weeks      2026 regular season, weeks 2 to the last week with a final score.
  markets    receiving_yards, receptions, targets (receivers: RB, WR, TE); passing_yards, pass_attempts,
             pass_completions, passing_touchdowns (quarterbacks, only in games where he led his team in attempts,
             the population the passing gate was graded on).
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
import datetime as dt
import os
import sqlite3
import zlib

import nfl_player_projection_v2 as eng
import player_splits
import check_nfl_schedule_scores as schedule_times

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


def _captured_utc(value):
    """Only explicitly timezone-aware timestamps can qualify as pregame quotes."""
    if not value:
        return None
    try:
        stamp = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        return None
    return stamp.astimezone(dt.timezone.utc)


def pregame_lead_qb(hist, season, team, week):
    """Prior games only; do not consult this game's pass-attempt total."""
    attempts = {}
    for w, rows in hist.by_team[(season, team)].items():
        if w >= week:
            continue
        for row in rows:
            if row.pos == "QB" and row.att > 0:
                attempts[row.pid] = attempts.get(row.pid, 0) + row.att
    return max(sorted(attempts), key=lambda pid: attempts[pid]) if attempts else None


def collect(con, season, pregame_only=False, max_pair_skew_seconds=1800):
    """Quotes per (game, player, market, book, line); optionally require timestamped pregame pairs.

    Legacy mode preserves published retrospective studies. Prospective candidate mode
    excludes missing/naive/post-kickoff captures and badly asynchronous two-sided prices.
    Returned items are the same seven-tuples as before, so existing graders still work.
    """
    markets = tuple(RECEIVING) + tuple(PASSING)
    rows = con.execute(
        "SELECT p.game_id, p.player_id, p.market, p.source, p.line, p.side, p.odds, p.captured_at, r.hit "
        "FROM props p JOIN prop_games g ON g.id = p.game_id LEFT JOIN prop_results r ON r.prop_id = p.id "
        "WHERE g.league = 'nfl' AND p.market IN (%s) AND p.source IN (%s) AND p.odds IS NOT NULL"
        % (",".join("?" * len(markets)), ",".join("?" * len(BOOKS))), markets + BOOKS).fetchall()
    nfl = player_splits.prop_game_nfl_ids(con, {r[0] for r in rows})
    kickoffs = {}
    if pregame_only:
        for gid, gameday, gametime in con.execute(
                "SELECT game_id, gameday, gametime FROM nfl_schedule "
                "WHERE season=? AND game_type='REG'", (season,)):
            if gameday and gametime:
                kickoffs[gid] = schedule_times.kickoff_utc(gameday, gametime)
    latest = {}
    skipped = {"whole_line": 0, "one_side": 0, "quote_time_unknown": 0,
               "quote_after_kickoff": 0, "schedule_time_unknown": 0, "quotes_unpaired_clock": 0}
    for pg, pid, market, book, line, side, odds, cap, hit in rows:
        gid = nfl.get(pg)
        if gid is None or not gid.startswith("%d_" % season):
            continue
        if pregame_only:
            kickoff = kickoffs.get(gid)
            if kickoff is None:
                skipped["schedule_time_unknown"] += 1
                continue
            stamp = _captured_utc(cap)
            if stamp is None:
                skipped["quote_time_unknown"] += 1
                continue
            if stamp >= kickoff:
                skipped["quote_after_kickoff"] += 1
                continue
        key = (gid, pid, market, book, float(line), side)
        if key not in latest or (cap or "") > (latest[key][0] or ""):
            latest[key] = (cap, odds, hit)
    items = []
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
        if pregame_only:
            over_t, under_t = _captured_utc(cap), _captured_utc(under[0])
            if abs((over_t - under_t).total_seconds()) > max_pair_skew_seconds:
                skipped["quotes_unpaired_clock"] += 1
                continue
        items.append((gid, pid, market, book, line, devig(odds, under[1]), hit))
    return items, skipped


class Projector(object):
    def __init__(self, hist):
        self.hist = hist
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
            v = eng.project_qb(self.hist, season, row.week, row.pid, row.team, row.opp, row.game_id)
            if v is not None and v["att"] > 0:
                out = eng.simulate_qb(v["att"], v["cmp"] / v["att"], v["pass_yds"] / v["cmp"] if v["cmp"] > 0 else 0.0,
                                      v["pass_td"] / v["att"], n=N_SIMS, seed=seed)
        self.cache[key] = out
        return out


def grade(con, season, hist=None, pregame_only=False, qb_selection="postgame"):
    hist = hist or eng.History.load(con, [season - 1, season])
    final_weeks = {w for (w,) in con.execute(
        "SELECT DISTINCT week FROM nfl_schedule WHERE season=? AND game_type='REG' AND home_score IS NOT NULL",
        (season,))}
    if qb_selection not in ("pregame", "postgame"):
        raise ValueError("qb_selection must be pregame or postgame")
    items, skipped = collect(con, season, pregame_only=pregame_only)
    skipped.update({"not_played": 0, "week": 0, "no_projection": 0, "not_lead_passer": 0, "position": 0})
    proj = Projector(hist)
    pregame_qbs = {}
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
            if qb_selection == "pregame":
                key = (season, row.team, week)
                if key not in pregame_qbs:
                    pregame_qbs[key] = pregame_lead_qb(hist, *key)
                chosen = pregame_qbs[key]
            else:
                team_rows = hist.by_team[(season, row.team)][row.week]
                chosen = max(team_rows, key=lambda x: (x.att, -x.pid)).pid
            if chosen != pid:
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
        graded.append({"game_id": gid, "player_id": pid, "market": market, "book": book, "line": line,
                       "p_ours": p_ours, "p_market": p_mkt, "actual": actual, "over": outcome,
                       "group": "passing" if kind == "qb" else "receiving"})
    return graded, skipped, disagree


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
    ap.add_argument("--csv")
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    graded, skipped, disagree = grade(con, a.season)
    print("excluded: %s; our outcome disagrees with the book's settlement on %d graded items" % (skipped, disagree))
    report(graded, "all")
    for group in ("receiving", "passing"):
        report([g for g in graded if g["group"] == group], group)
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
