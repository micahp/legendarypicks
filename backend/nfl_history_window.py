#!/usr/bin/env python3
"""nfl_history_window.py -- history-window ablation on fixed test games.

Pre-registered in research/nfl/PREREG-nfl-history-window-2026-10-19.md
(commit a91d136f, before any run).

Arms (identical except the prior's history window):
  W=1           incumbent: final fit of S-1, no prior, then shrink
  W=2           recursive chain S-2 -> S-1
  W=3           recursive chain S-3 -> S-1
  all-available recursive chain 2010 -> S-1

Frozen v1 parameters for every arm:
  half_life 6.0, cap 14.0, cap_points None, prior_games 4.0, shrink 1/3, sigma 13.295

Primary 2013-2020; holdouts 2024 and 2025 scored separately. Weeks 2+, ties excluded and
counted. The only interval is week_block_bootstrap_mean_diff (this file), 2,000 reps, seed
20261019, blocks = (season, Monday of gameday week), game-count weighted.

Read-only dev DB. Writes only under research/nfl/history-window-2026-10-19/.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_backtest as nb  # noqa: E402
import nfl_metrics as nm  # noqa: E402
import nfl_ratings as nr  # noqa: E402
import nfl_ratings_data as nrd  # noqa: E402

DB = os.environ.get("LP_DB_PATH") or "/root/legendarypicks/backend/data/picks.dev.db"
OUT = os.path.join("research", "nfl", "history-window-2026-10-19")

FROZEN = {"half_life": 6.0, "cap": 14.0, "cap_points": None,
          "prior_games": 4.0, "shrink": 1.0 / 3.0, "sigma": 13.295}
ARMS = ["W1", "W2", "W3", "ALL"]
PRIMARY = list(range(2013, 2021))
HOLDOUTS = [2024, 2025]
SEED = 20261019
REPS = 2000
ELO_CODE = {"OAK": "LV"}

# The nine reversed-pair games named in the benchmark doc; kept for the report, not
# hard-coded into the join (the join accepts either order).
REVERSED_DOC = {"2010_08_DEN_SF", "2010_14_NYG_MIN", "2011_07_CHI_TB", "2012_08_NE_STL",
                "2013_04_PIT_MIN", "2013_08_SF_JAX", "2014_04_MIA_OAK", "2014_08_DET_ATL",
                "2014_10_DAL_JAX"}


def sha256_file(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def open_db():
    return sqlite3.connect("file:%s?mode=ro" % DB, uri=True)


# -- the registered interval ---------------------------------------------------------------

def week_block_bootstrap_mean_diff(loss_a, loss_b, blocks, reps=REPS, seed=SEED):
    """Paired mean difference mean(loss_a - loss_b), clustered on week blocks.

    Resamples blocks with replacement, weights each draw by its number of graded games, and
    returns (point, lo, hi, n_blocks, n_games). Point is the sample mean difference.
    """
    import random
    if len(loss_a) != len(loss_b) or len(loss_a) != len(blocks):
        raise ValueError("loss_a, loss_b and blocks must be the same length")
    diffs = [a - b for a, b in zip(loss_a, loss_b)]
    n = len(diffs)
    if n == 0:
        raise ValueError("empty")
    point = sum(diffs) / n
    by = defaultdict(list)
    for d, b in zip(diffs, blocks):
        by[b].append(d)
    keys = sorted(by)
    sums = {k: sum(by[k]) for k in keys}
    counts = {k: len(by[k]) for k in keys}
    rng = random.Random(seed)
    means = []
    for _ in range(reps):
        pick = [keys[rng.randrange(len(keys))] for _ in range(len(keys))]
        tot = sum(sums[k] for k in pick)
        cnt = sum(counts[k] for k in pick)
        means.append(tot / cnt)
    means.sort()
    lo = means[int(0.025 * reps)]
    hi = means[min(reps - 1, int(0.975 * reps))]
    return point, lo, hi, len(keys), n


# -- priors -------------------------------------------------------------------------------

def _season_fit(con, season, prior=None):
    f, _ = nrd.season_fit(con, season, prior=prior, half_life=FROZEN["half_life"],
                          cap=FROZEN["cap"], prior_games=FROZEN["prior_games"])
    return f


def build_prior(con, season, arm):
    """The registered recursive chain; see PREREG section 4."""
    first = 2010
    if arm == "W1":
        base = season - 1
        f = _season_fit(con, base)                      # no prior
        return nrd.prior_from_fit(f, shrink=FROZEN["shrink"])
    if arm == "W2":
        base = max(first, season - 2)
    elif arm == "W3":
        base = max(first, season - 3)
    elif arm == "ALL":
        base = first
    else:
        raise ValueError("unknown arm %r" % arm)
    f = _season_fit(con, base)                          # no prior at the base
    for t in range(base + 1, season):
        f = _season_fit(con, t, prior=nrd.prior_from_fit(f, shrink=FROZEN["shrink"]))
    return nrd.prior_from_fit(f, shrink=FROZEN["shrink"])


# -- backtest with an explicit prior (identical loop to nb.backtest_season) ----------------

def backtest_season_with_prior(con, season, prior, overrides=None):
    p = nb._params(overrides or {})
    sched = [r for r in nb._schedule(con, season) if r[5] is not None and r[6] is not None]
    if not sched:
        raise ValueError("no scored REG games for season %d" % season)
    scored = [(r[0], r[2], r[3], r[5], r[6], r[4]) for r in sched]
    teams = nrd.teams_in_season(con, season)
    out = []
    for w in sorted({r[0] for r in sched}):
        if w < 2:
            continue
        train = nb.training_games(scored, w, p["cap_points"])
        if not train:
            continue
        f = nr.fit(train, teams, prior=prior, half_life=p["half_life"], cap=p["cap"],
                   prior_games=p["prior_games"])
        for wk, gid, h, a, loc, hs, as_, spread, total_line, hml, aml in (
                (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10])
                for r in sched if r[0] == w):
            neutral = (loc or "").strip().lower() == "neutral"
            ph, pa = nr.expected_points(f, h, a, neutral)
            margin = float(hs) - float(as_)
            p_mkt = nm.devig_home_prob(hml, aml) if (hml is not None and aml is not None) else None
            out.append({
                "season": season, "week": w, "game_id": gid, "home": h, "away": a,
                "neutral": neutral, "proj_margin": ph - pa, "proj_total": ph + pa,
                "p_model": nr.win_probability(ph - pa, p["sigma"]), "p_market": p_mkt,
                "actual_margin": margin, "actual_total": float(hs) + float(as_),
                "outcome": 1 if margin > 0 else (0 if margin < 0 else None),
                "spread_line": spread, "total_line": total_line,
                "prior_used": prior is not None, "fit_games": len(train),
            })
    return out


# -- helpers ------------------------------------------------------------------------------

def gameday_map(con):
    return {r[0]: r[1] for r in con.execute(
        "SELECT game_id, gameday FROM nfl_schedule WHERE game_type='REG'")}


def block_of(row, day):
    d = date.fromisoformat(day[row["game_id"]])
    monday = d - timedelta(days=d.weekday())
    return "%d_%s" % (row["season"], monday.isoformat())


def elo_by_game(con):
    out = {}
    for d, t1, t2, p1 in con.execute(
            "SELECT date, team1, team2, elo_prob1 FROM nfl_elo_538 "
            "WHERE CAST(season AS INTEGER) BETWEEN 2010 AND 2020"):
        out[(d, ELO_CODE.get(t1, t1), ELO_CODE.get(t2, t2))] = float(p1)
    return out


def loss_vec(rows, key="p_model"):
    return [(r[key] - r["outcome"]) ** 2 for r in rows]


def logloss_vec(rows, key="p_model"):
    out = []
    for r in rows:
        p = min(max(r[key], 1e-12), 1 - 1e-12)
        out.append(-(r["outcome"] * math.log(p) + (1 - r["outcome"]) * math.log(1 - p)))
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    con = open_db()
    day = gameday_map(con)
    elo = elo_by_game(con)

    # 1. W=1 reproduction against the incumbent backtest_season
    repro = []
    for s in PRIMARY + HOLDOUTS:
        inc = [r for r in nb.backtest_season(con, s, FROZEN) if r["outcome"] is not None]
        prior1 = build_prior(con, s, "W1")
        mine = [r for r in backtest_season_with_prior(con, s, prior1, FROZEN)
                if r["outcome"] is not None]
        a = {r["game_id"]: r["p_model"] for r in inc}
        b = {r["game_id"]: r["p_model"] for r in mine}
        if set(a) != set(b):
            raise SystemExit("reproduction: game sets differ for %d" % s)
        md = max(abs(a[g] - b[g]) for g in a)
        repro.append({"season": s, "n": len(a), "max_abs_p_model_diff": md})
        print("reproduction %d: n=%d max|p_model diff| = %r" % (s, len(a), md))
        if md != 0.0:
            raise SystemExit("REPRODUCTION FAILED for %d: max diff %r" % (s, md))

    # 2. build the arms
    all_rows_raw = {}
    all_rows = {}
    for arm in ARMS:
        rows = []
        for s in PRIMARY + HOLDOUTS:
            prior = build_prior(con, s, arm)
            rows.extend(backtest_season_with_prior(con, s, prior, FROZEN))
        all_rows_raw[arm] = rows
        all_rows[arm] = [r for r in rows if r["outcome"] is not None]
        print("arm %-3s graded rows %d (ties %d)" % (
            arm, len(all_rows[arm]), sum(1 for r in rows if r["outcome"] is None)))

    # identical game sets across arms
    for s in PRIMARY + HOLDOUTS:
        sets = {a: {r["game_id"] for r in all_rows[a] if r["season"] == s} for a in ARMS}
        if len({frozenset(v) for v in sets.values()}) != 1:
            raise SystemExit("arm game sets differ for season %d" % s)

    # 3. scores and paired intervals
    def period_rows(arm, seasons):
        return [r for r in all_rows[arm] if r["season"] in seasons]

    periods = [("pooled_2013_2020", PRIMARY)]
    periods += [(str(s), [s]) for s in PRIMARY]
    periods += [("holdout_2024", [2024]), ("holdout_2025", [2025])]

    score_rows = []
    paired_rows = []
    for pname, seasons in periods:
        inc = period_rows("W1", seasons)
        blocks = [block_of(r, day) for r in inc]
        ties = 0
        for arm in ARMS:
            rs = period_rows(arm, seasons)
            by = {r["game_id"]: r for r in rs}
            inc_by = {r["game_id"]: r for r in inc}
            common = [g for g in inc_by if g in by]
            la = loss_vec([by[g] for g in common])
            lb = loss_vec([inc_by[g] for g in common])
            lla = logloss_vec([by[g] for g in common])
            llb = logloss_vec([inc_by[g] for g in common])
            bpt, blo, bhi, bblocks, bn = week_block_bootstrap_mean_diff(la, lb, blocks)
            lpt, llo, lhi, _, _ = week_block_bootstrap_mean_diff(lla, llb, blocks)
            score_rows.append({
                "period": pname, "arm": arm, "n": len(common),
                "blocks": bblocks, "ties": ties,
                "brier": sum(la) / len(la), "log_loss": sum(lla) / len(lla),
                "brier_vs_W1": bpt, "brier_lo": blo, "brier_hi": bhi,
                "logloss_vs_W1": lpt, "logloss_lo": llo, "logloss_hi": lhi,
            })
            paired_rows.append({"period": pname, "arm": arm, "metric": "brier",
                                "mean": bpt, "lo": blo, "hi": bhi,
                                "blocks": bblocks, "n": bn})
            paired_rows.append({"period": pname, "arm": arm, "metric": "log_loss",
                                "mean": lpt, "lo": llo, "hi": lhi,
                                "blocks": bblocks, "n": bn})
        ties = sum(1 for r in all_rows_raw["W1"]
                   if r["season"] in seasons and r["outcome"] is None)
        for row in score_rows:
            if row["period"] == pname:
                row["ties"] = ties

    # 4. benchmarks on the overlapping primary games
    primary = period_rows("W1", PRIMARY)
    ptot = []
    for r in primary:
        key = (day[r["game_id"]], r["home"], r["away"])
        if key in elo:
            pe = elo[key]
        elif (key[0], key[2], key[1]) in elo:
            pe = 1.0 - elo[(key[0], key[2], key[1])]
        else:
            continue
        if r["p_market"] is None:
            continue
        ptot.append((r, pe))
    bench = []
    if ptot:
        rows_b = [x[0] for x in ptot]
        bench = [
            {"rung": "538 Elo", "n": len(ptot),
             "brier": sum((pe - r["outcome"]) ** 2 for r, pe in ptot) / len(ptot),
             "source": "nfl_elo_538.elo_prob1 on the overlapping 2013-2020 games"},
            {"rung": "closing market", "n": len(ptot),
             "brier": sum((r["p_market"] - r["outcome"]) ** 2 for r in rows_b) / len(rows_b),
             "source": "de-vigged moneyline on the same overlapping games"},
        ]

    # 5. write artifacts
    import csv
    with open(os.path.join(OUT, "forecasts.csv"), "w", newline="") as fh:
        cols = ["arm", "season", "week", "game_id", "home", "away", "neutral", "p_model",
                "p_market", "outcome", "proj_margin", "proj_total", "fit_games"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for arm in ARMS:
            for r in all_rows[arm]:
                w.writerow({**r, "arm": arm})
    with open(os.path.join(OUT, "arm_scores.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(score_rows[0].keys()), lineterminator="\n")
        w.writeheader(); w.writerows(score_rows)
    with open(os.path.join(OUT, "paired.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(paired_rows[0].keys()), lineterminator="\n")
        w.writeheader(); w.writerows(paired_rows)
    with open(os.path.join(OUT, "benchmarks.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["rung", "n", "brier", "source"], lineterminator="\n")
        w.writeheader(); w.writerows(bench)

    manifest = {
        "prereg": "research/nfl/PREREG-nfl-history-window-2026-10-19.md",
        "prereg_commit": "a91d136f",
        "db": DB,
        "frozen": FROZEN,
        "arms": ARMS,
        "primary": PRIMARY,
        "holdouts": HOLDOUTS,
        "seed": SEED, "reps": REPS,
        "bootstrap": "week_block_bootstrap_mean_diff, (season, Monday gameday week) blocks",
        "reproduction": repro,
        "population": {p: len(period_rows("W1", s)) for p, s in periods},
        "files": {},
    }
    for name in ("forecasts.csv", "arm_scores.csv", "paired.csv", "benchmarks.csv"):
        path = os.path.join(OUT, name)
        manifest["files"][name] = {"sha256": sha256_file(path), "bytes": os.path.getsize(path)}
    with open(os.path.join(OUT, "MANIFEST.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)

    # 6. print the table
    print("\n%-18s %-4s %5s %5s %5s %8s %8s %22s" %
          ("period", "arm", "n", "blk", "ties", "brier", "logloss", "brier vs W1 [95%]"))
    for row in score_rows:
        print("%-18s %-4s %5d %5d %5d %8.4f %8.4f  %+8.4f [%+.4f, %+.4f]" % (
            row["period"], row["arm"], row["n"], row["blocks"], row["ties"],
            row["brier"], row["log_loss"], row["brier_vs_W1"], row["brier_lo"], row["brier_hi"]))
    print("\nbenchmarks (overlapping 2013-2020 games):")
    for b in bench:
        print("  %-15s n=%-4d brier %.4f" % (b["rung"], b["n"], b["brier"]))
    print("\nwrote %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
