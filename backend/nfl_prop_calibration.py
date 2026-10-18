#!/usr/bin/env python3
"""nfl_prop_calibration.py -- forward-only Platt recalibration of v2's P(over), as its own model.

Two model names exist and are never silently swapped:

  v2        the raw engine's P(over), unchanged.
  v2-platt  the same number passed through a two-parameter logistic map fitted on the weeks BEFORE the
            week being served. A week with no earlier week to fit on (the first week props exist) is served
            raw and labelled `raw_no_map`, never quietly calibrated.

The map is refitted every week on every graded item in the earlier weeks of the same season, on the corrected
pregame population (`grade_nfl_prop_probabilities.grade`, population='pregame'). Fitting on items means an
alternate line on the same player-game counts more than once, which is deliberate: the served quantity is an
item-level probability and the map is scored on items. The record grades v2-platt on exactly the items it
served, in the weeks it served them.

The parameters live in `nfl_prop_calibration` so the reader can apply the same map at serving time:

  season, week, model_version, a, b, n_items, n_player_games, fitted_at_utc

Read-only unless `--write` is passed. Usage:

  LP_DB_PATH=... python3 fit_nfl_prop_calibration.py --season 2026 [--write] [--json maps.json]
"""
import argparse
import datetime as dt
import json
import math
import os
import sqlite3
from collections import defaultdict

import grade_nfl_prop_probabilities as g

EPS = 1e-6
TABLE = "nfl_prop_calibration"


def logit(p):
    p = min(max(p, EPS), 1.0 - EPS)
    return math.log(p / (1.0 - p))


def sigmoid(z):
    if z >= 0:
        e = math.exp(-z)
        return 1.0 / (1.0 + e)
    e = math.exp(z)
    return e / (1.0 + e)


def fit_platt(pairs):
    """Two-parameter logistic recalibration by Newton's method. pairs = [(p, y)] -> (a, b)."""
    a, b = 1.0, 0.0
    xs = [(logit(p), y) for p, y in pairs]
    for _ in range(200):
        ga = gb = haa = hab = hbb = 0.0
        for x, y in xs:
            q = sigmoid(a * x + b)
            r = q - y
            w = q * (1.0 - q)
            ga += r * x
            gb += r
            haa += w * x * x
            hab += w * x
            hbb += w
        det = haa * hbb - hab * hab
        if abs(det) < 1e-12:
            break
        da = (hbb * ga - hab * gb) / det
        db = (haa * gb - hab * ga) / det
        a -= da
        b -= db
        if abs(da) < 1e-10 and abs(db) < 1e-10:
            break
    return a, b


def apply_map(a, b, p):
    return sigmoid(a * logit(p) + b)


def forward_maps(con, season, population="pregame", min_items=200, graded=None):
    """{week: (a, b, n_items, n_player_games)} fitted on every earlier graded week of the season.

    Only weeks that themselves have graded items appear. The map the job stores for the week it is about to
    serve is `map_for_week`, which does not require that week to have outcomes yet.
    """
    if graded is None:
        graded, _skipped, _disagree = g.grade(con, season, population=population)
    by_week = defaultdict(list)
    for it in graded:
        by_week[int(it["game_id"].split("_")[1])].append(it)
    weeks = sorted(by_week)
    maps = {}
    for w in weeks:
        train = [it for ww in weeks if ww < w for it in by_week[ww]]
        if len(train) < min_items:
            continue
        a, b = fit_platt([(it["p_ours"], it["over"]) for it in train])
        maps[w] = (a, b, len(train), len({(it["game_id"], it["player_id"]) for it in train}))
    return maps, weeks, graded


def map_for_week(con, season, week, population="pregame", min_items=200, graded=None):
    """The map to serve `week`: fitted on every graded item in weeks < week. None when there is not enough."""
    if graded is None:
        graded, _skipped, _disagree = g.grade(con, season, population=population)
    train = [it for it in graded if int(it["game_id"].split("_")[1]) < week]
    if len(train) < min_items:
        return None
    a, b = fit_platt([(it["p_ours"], it["over"]) for it in train])
    return a, b, len(train), len({(it["game_id"], it["player_id"]) for it in train})


def ensure_table(con):
    con.execute("CREATE TABLE IF NOT EXISTS %s ("
                "season INTEGER NOT NULL, week INTEGER NOT NULL, model_version TEXT NOT NULL, "
                "a REAL NOT NULL, b REAL NOT NULL, n_items INTEGER, n_player_games INTEGER, "
                "fitted_at_utc TEXT, PRIMARY KEY (season, week, model_version))" % TABLE)
    con.commit()


def store(con, season, maps, model="v2-platt"):
    ensure_table(con)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    for week, (a, b, n_items, n_pgs) in sorted(maps.items()):
        con.execute("INSERT OR REPLACE INTO %s (season, week, model_version, a, b, n_items, n_player_games, "
                    "fitted_at_utc) VALUES (?,?,?,?,?,?,?,?)" % TABLE,
                    (season, week, model, a, b, n_items, n_pgs, now))
    con.commit()
    return now


def read(con, season, week, model="v2-platt"):
    """(a, b) for the week, or None when no map exists (the raw fallback)."""
    try:
        row = con.execute("SELECT a, b FROM %s WHERE season=? AND week=? AND model_version=?" % TABLE,
                          (season, week, model)).fetchone()
    except sqlite3.OperationalError:
        return None
    return (row[0], row[1]) if row else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--population", choices=("pregame", "postgame"), default="pregame")
    ap.add_argument("--min-items", type=int, default=200)
    ap.add_argument("--week", type=int, help="also fit and store the map for this serving week")
    ap.add_argument("--write", action="store_true", help="write the maps to nfl_prop_calibration")
    ap.add_argument("--json", help="write the maps to this JSON file")
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    ro = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    maps, weeks, graded = forward_maps(ro, a.season, a.population, a.min_items)
    print("season %d, population %s: graded weeks %s, %d items"
          % (a.season, a.population, weeks, len(graded)))
    if not maps:
        print("no week has %d earlier items; every served number would be raw" % a.min_items)
    for w in weeks:
        if w in maps:
            aa, bb, n, pgs = maps[w]
            print("  week %d: a %.5f  b %+.5f  (fitted on %d items, %d player-games)" % (w, aa, bb, n, pgs))
        else:
            print("  week %d: NO MAP (served raw, labelled raw_no_map)" % w)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump({str(w): [v[0], v[1]] for w, v in maps.items()}, fh, indent=2, sort_keys=True)
        print("wrote %s" % a.json)
    serving = None
    if a.week is not None:
        serving = map_for_week(ro, a.season, a.week, a.population, a.min_items, graded=graded)
        if serving is None:
            print("week %d: no earlier graded items, the raw number is served and labelled raw_no_map" % a.week)
        else:
            print("serving week %d: a %.5f  b %+.5f  (fitted on %d earlier items, %d player-games)"
                  % (a.week, serving[0], serving[1], serving[2], serving[3]))
            maps[a.week] = serving
    if a.write:
        con = sqlite3.connect(path)
        now = store(con, a.season, maps)
        con.close()
        print("wrote %d maps to %s at %s" % (len(maps), TABLE, now))


if __name__ == "__main__":
    main()
