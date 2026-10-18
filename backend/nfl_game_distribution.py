#!/usr/bin/env python3
"""nfl_game_distribution.py -- the per-game NFL distribution, frozen at lock.

WHAT THE DISTRIBUTION IS (and what it is not)

  margin = final home score - final away score  ~ Normal(margin_mean, margin_sd)
  total  = final home score + final away score  ~ Normal(total_mean, total_sd)
  margin and total are independent.

From those two numbers, analytically and with no sampling:
  P(home wins)      = P(margin > 0)
  P(home covers X)  = P(margin > X)
  P(total over Y)   = P(total > Y)
  P(push)           = P(margin = X) is zero for half-point lines; on a whole-number line the
                      normal's point mass is zero too, so a whole line is treated as a tie-free
                      approximation and pushes are counted at grading time, never inside the model.

It is **not** a joint score distribution: home and away scores are not stored or drawn, the two
normals can imply negative scores, and the tails are thinner than a football score distribution
(scoring is discrete and skewed). Those are real defects and are stated in the results doc. The
object is what the model produces -- a margin point estimate, a total point estimate and their
residual spreads -- written down as a distribution instead of being left implicit.

REPRODUCIBILITY. The parameters are the whole object: no draws, no seed, no hidden state. Anyone
holding (margin_mean, margin_sd, total_mean, total_sd) regenerates exactly the same probabilities
months later.

FROZEN AT LOCK. One row per (game_id, model_version), written before kickoff by
`lock_nfl_game_distributions.py --write`, and never updated: the writer is INSERT OR IGNORE and the
script prints any row it refused to overwrite. Parameters used to fit the distribution are stored in
`params_json` with the play counts so the fit can be audited.

Usage (backtest, no writes):
  LP_DB_PATH=... python3 nfl_game_distribution.py --seasons 2023 2024 2025 [--write]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sqlite3
from collections import defaultdict

import numpy as np

import nfl_success_rate_backtest as bt
import nfl_team_quality as tq

METHOD = "gaussian_margin_and_total_independent"
TABLE = "nfl_game_distributions"
WEEKS = range(3, 19)
MIN_POOL = 200


def migrate(con):
    con.execute(
        "CREATE TABLE IF NOT EXISTS %s ("
        "league TEXT NOT NULL, game_id TEXT NOT NULL, season INTEGER NOT NULL, week INTEGER NOT NULL, "
        "model_version TEXT NOT NULL, margin_mean REAL NOT NULL, margin_sd REAL NOT NULL, "
        "total_mean REAL NOT NULL, total_sd REAL NOT NULL, method TEXT NOT NULL, "
        "line_snapshot_id INTEGER, locked_at TEXT, as_of TEXT, params_json TEXT, created_at TEXT, "
        "PRIMARY KEY (league, game_id, model_version))" % TABLE)
    con.commit()


def store(con, rows, commit=True):
    """INSERT OR IGNORE: a second write for the same (game, model_version) is refused, not overwritten."""
    migrate(con)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    inserted = refused = 0
    for r in rows:
        cur = con.execute(
            "INSERT OR IGNORE INTO %s (league, game_id, season, week, model_version, margin_mean, "
            "margin_sd, total_mean, total_sd, method, line_snapshot_id, locked_at, as_of, params_json, "
            "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)" % TABLE,
            ("nfl", r["game_id"], r["season"], r["week"], r["model_version"], r["margin_mean"],
             r["margin_sd"], r["total_mean"], r["total_sd"], METHOD, r.get("line_snapshot_id"),
             r.get("locked_at", now), r.get("as_of", now), json.dumps(r["params"], sort_keys=True), now))
        if cur.rowcount:
            inserted += 1
        else:
            refused += 1
    if commit:
        con.commit()
    return inserted, refused


def build(con, seasons, first_rating_season, verbose=True):
    """Walk-forward distributions for the games of `seasons`: every parameter from earlier games only."""
    agg, n_read = tq.load_plays(con, first_rating_season, max(seasons))
    rows, out = [], []
    for season in range(first_rating_season + 1, max(seasons) + 1):
        for week in WEEKS:
            gs = bt.games(con, season, week)
            if not gs:
                continue
            rat = tq.ratings_for(agg, season, week)
            for gid, home, away, hs, as_, spread, total in gs:
                rows.append({"season": season, "week": week, "game_id": gid, "home": home, "away": away,
                             "margin": hs - as_, "total": hs + as_, "rat": rat})
            if season not in seasons:
                continue
            pool = [r for r in rows if (r["season"], r["week"]) < (season, week)]
            if len(pool) < MIN_POOL:
                continue
            tgt = [r for r in rows if r["season"] == season and r["week"] == week]
            pm, sig_m, beta_m = bt.fit_predict(pool, "margin", "epa", tgt)
            pt, sig_t, beta_t = bt.fit_predict(pool, "total", "epa", tgt)
            for r, m, t in zip(tgt, pm, pt):
                out.append({
                    "game_id": r["game_id"], "season": season, "week": week,
                    "model_version": "nfl-epa-v2 distribution (K_T_ATT n/a, EPA only, sigma from the pool)",
                    "margin_mean": float(m), "margin_sd": float(sig_m),
                    "total_mean": float(t), "total_sd": float(sig_t),
                    "params": {
                        "fit_pool_games": len(pool),
                        "margin_features": ["intercept", "epa_pass_diff", "epa_rush_diff", "home"],
                        "margin_beta": [float(x) for x in beta_m],
                        "total_features": ["intercept", "epa_pass_sumdiff", "epa_rush_sumdiff"],
                        "total_beta": [float(x) for x in beta_t],
                        "halflife": tq.HALF_LIFE, "k_epa": tq.K_EPA,
                        "sd_form": "population", "plays_loaded": n_read}})
    if verbose:
        print("built %d distributions over seasons %s (plays loaded %d)" % (len(out), sorted(seasons), n_read))
    return out


def prob_over_normal(mean, sd, line):
    if sd <= 0:
        return 1.0 if mean > line else 0.0
    z = (mean - line) / sd
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seasons", type=int, nargs="+", required=True)
    ap.add_argument("--first-rating-season", type=int, default=None)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect(path if a.write else "file:%s?mode=ro" % path, uri=not a.write)
    rows = build(con, set(a.seasons), a.first_rating_season or (min(a.seasons) - 13))
    if not a.write:
        print("dry run: %d rows would be written (no --write)" % len(rows))
        return
    # FROZEN AT LOCK: a distribution for a game that has started is refused, and a game with an
    # unknown kickoff raises rather than writing something that cannot be guarded.
    import datetime as dt
    import check_nfl_schedule_scores as cs
    now = dt.datetime.now(dt.timezone.utc)
    keep, started = [], 0
    for r in rows:
        gd = con.execute("SELECT gameday, gametime FROM nfl_schedule WHERE game_id=?", (r["game_id"],)).fetchone()
        if gd is None or gd[0] is None:
            raise SystemExit("no gameday for %s; an unknown kickoff cannot be guarded" % r["game_id"])
        ko = cs.kickoff_utc(gd[0], gd[1])
        if ko <= now:
            started += 1
            continue
        keep.append(r)
    ins, ref = store(con, keep)
    print("wrote %d rows to %s, refused %d that already existed, refused %d for a game already started"
          % (ins, TABLE, ref, started))


if __name__ == "__main__":
    main()
