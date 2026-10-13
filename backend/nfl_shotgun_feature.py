#!/usr/bin/env python3
"""nfl_shotgun_feature.py -- does a team's shotgun rate add to frozen v1? Same harness, same rules.

Idea (Micah's friend, 2026-10-13): the league moved from under center to shotgun (shotgun share of
plays 28.8% in 2010, 50.3% in 2025; counted in nfl_pbp), which changed how the game is played.
Plumbing is `nfl_feature_backtest.py` unchanged: this file only registers features with its
`@feature` decorator and runs its `stack` and `report`. Every shared rule there applies (graded
set, 2011-2023 pooled, 2024, 2025, KEEP rule, 5,000 paired resamples, no parameter chosen by
looking at a result).

PRE-REGISTERED (written 2026-10-13 before the first run of this file)

shotgun_rate: per team, the share of its offensive plays (pass or rush attempts) with shotgun = 1,
over its last 8 team games strictly before the game (the window may cross a season boundary, as in
the pressure features), shrunk toward the league rate with a prior of 200 plays:
    rate = (shotgun_plays + 200 x league) / (plays + 200)
league = the same share pooled over every team-game of the SAME season strictly before the game.
Because the league level moves from year to year, the league term is same-season, so the column
measures a team against the league of its own year and not against history. Column = home rate
minus away rate. A game with no same-season league history cannot occur (the base rows start at
week 2); a missing column raises. No expected sign is registered; the keep rule does not need one.

epa_plus_shotgun: epa_units (kept earlier, +0.0019) and shotgun_rate as two columns in one stack.
Answers whether shotgun adds on top of the one own-data feature that met the keep rule.

stacked_all (EXPLORATORY, not a keep test, never to be adopted from this run): every dev-harness
own-data feature that was not market-derived (epa_units, special_teams, venue_conditions,
pressure_matchup, sack_matchup, share_absence) plus shotgun_rate, as columns in one stack. It is an
upper bound on what stacking everything could do, with the multiple-testing caveat that choosing
the combination after seeing the singles inflates it. Reported with the same intervals.

Usage: LP_DB_PATH=<dev db> venv/bin/python nfl_shotgun_feature.py --feature <name>
"""
from __future__ import annotations

import argparse
import bisect
import sqlite3
import sys

import nfl_feature_backtest as fb

WIN = 8
K = 200


def _team_games(con):
    """{team: sorted [(season, week, game_id, plays, shotgun_plays)]}, plus the league cumulative
    by season in (week, game_id) order, both from nfl_pbp by the team that had the ball."""
    per_team, per_season = {}, {}
    q = ("SELECT season, week, game_id, posteam, SUM(pass_attempt = 1 OR rush_attempt = 1), "
         "SUM((pass_attempt = 1 OR rush_attempt = 1) AND shotgun = 1) FROM nfl_pbp "
         "WHERE season BETWEEN 2010 AND 2025 AND posteam IS NOT NULL "
         "GROUP BY season, week, game_id, posteam")
    for s, w, g, t, pl, sg in con.execute(q):
        rec = (int(s), int(w), g, pl or 0, sg or 0)
        per_team.setdefault(t, []).append(rec)
        per_season.setdefault(int(s), []).append(rec)
    for t in per_team:
        per_team[t].sort()
    cum = {}
    for s, recs in per_season.items():
        recs.sort()
        c = [(0, 0)]
        for r in recs:
            c.append((c[-1][0] + r[3], c[-1][1] + r[4]))
        cum[s] = ([(r[0], r[1], r[2]) for r in recs], c)
    return per_team, cum


def shotgun_columns(con, rows):
    per_team, cum = _team_games(con)
    keys = {t: [(r[0], r[1], r[2]) for r in v] for t, v in per_team.items()}
    cols = {}
    for r in rows:
        s, w = int(r["season"]), int(r["week"])
        cutoff = (s, w, "")
        lkeys, lc = cum[s]
        i = bisect.bisect_left(lkeys, cutoff)
        lplays, lsg = lc[i]
        if lplays == 0:
            raise ValueError("no same-season league history before %s" % r["game_id"])
        league = lsg / float(lplays)

        def rate(team):
            ks = keys[team]
            j = bisect.bisect_left(ks, cutoff)
            win = per_team[team][max(0, j - WIN):j]
            plays = sum(x[3] for x in win)
            sg = sum(x[4] for x in win)
            return (sg + K * league) / (plays + K)
        cols[r["game_id"]] = [rate(r["home"]) - rate(r["away"])]
    return cols


@fb.feature
def shotgun_rate(con, rows):
    return fb._complete(rows, shotgun_columns(con, rows)), None


def _join(*parts):
    out = {}
    for p in parts:
        for k, v in p.items():
            out[k] = out.get(k, []) + list(v)
    return out


@fb.feature
def epa_plus_shotgun(con, rows):
    a, _ = fb.epa_units(con, rows)
    return fb._complete(rows, _join(a, shotgun_columns(con, rows))), None


@fb.feature
def stacked_all(con, rows):
    parts = [fb.epa_units(con, rows)[0], fb.special_teams(con, rows)[0],
             fb.venue_conditions(con, rows)[0], fb.pressure_matchup(con, rows)[0],
             fb.sack_matchup(con, rows)[0], fb.share_absence(con, rows)[0],
             shotgun_columns(con, rows)]
    return fb._complete(rows, _join(*parts)), None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--feature", required=True, choices=["shotgun_rate", "epa_plus_shotgun", "stacked_all"])
    a = ap.parse_args(argv)
    con = sqlite3.connect("file:%s?mode=ro" % fb.DB, uri=True)
    rows = fb.base_rows(con)
    base = fb.stack(rows)
    cols, sigma_fn = fb.FEATURES[a.feature](con, rows)
    fb.report(rows, base, fb.stack(rows, cols, sigma_fn), a.feature)
    return 0


if __name__ == "__main__":
    sys.exit(main())
