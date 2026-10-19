#!/usr/bin/env python3
"""nfl_proe_run.py -- run the already-registered PROE feature test.

Registration: backend/nfl_proe_feature.py (docstring, committed af96cbf6 on dev;
canonical ed96a861). This file adds nothing to the registration: it reproduces
the registered baselines first, then runs the two registered variants through
the unchanged nfl_feature_backtest stack and reports the registered KEEP rule.

Read-only on the dev DB (mode=ro). Writes only under
research/nfl/proe-2026-10-19/.

Registered interval: nfl_metrics.bootstrap_mean_diff_ci, paired games, 5,000
resamples, seed 20261009 (the helper's fixed seed), as nfl_feature_backtest.py
registers. A week-block clustered interval is also written, but it is a
secondary diagnostic only and is never folded into the verdict.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

import nfl_elo_replica as er
import nfl_feature_backtest as fb
import nfl_metrics as nm
import nfl_proe_feature as pf

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "research", "nfl", "proe-2026-10-19")
REGISTERED_REPS = fb.REPS          # 5,000
REGISTERED_SEED = 20261009         # nfl_metrics.bootstrap_mean_diff_ci default
CLUSTER_REPS = 2000
CLUSTER_SEED = 20261019
TOL = 5e-5 + 1e-12                 # published numbers are rounded to 4 decimals

# Published baselines: docs/RESULTS-nfl-features-vs-market-2026-10-11.md and
# docs/RESULTS-nfl-elo-and-era-2026-10-13.md.
PUBLISHED = {
    "B":      {"2011-2023": 0.2229, "2024": 0.2223, "2025": 0.2292},
    "v1":     {"2011-2023": 0.2231, "2024": 0.2210, "2025": 0.2288},
    "elo":    {"2011-2023": 0.2197, "2024": 0.2145, "2025": 0.2255},
    "market": {"2011-2023": 0.2104, "2024": 0.2001, "2025": 0.2137},
}


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def brier(ps, ys):
    return [(p - y) ** 2 for p, y in zip(ps, ys)]


def logloss(ps, ys):
    out = []
    for p, y in zip(ps, ys):
        q = min(max(float(p), 1e-15), 1.0 - 1e-15)
        out.append(-(y * math.log(q) + (1 - y) * math.log(1.0 - q)))
    return out


def week_block_bootstrap_mean_diff(loss_a, loss_b, blocks, reps=CLUSTER_REPS, seed=CLUSTER_SEED):
    """Paired mean difference mean(loss_a - loss_b), clustered on week blocks.

    Secondary diagnostic copied from the history-window runner. Resamples blocks
    with replacement, weights each draw by its number of graded games, and
    returns (point, lo, hi, n_blocks, n_games). Not the registered interval.
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


def gameday_map(con):
    return {g: d for g, d in con.execute(
        "SELECT game_id, gameday FROM nfl_schedule WHERE game_type='REG'") if d}


def block_of(row, day):
    d = day.get(row["game_id"])
    if d is None:
        return "%d_week_%d" % (row["season"], row["week"])
    dt = datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
    monday = dt - timedelta(days=dt.weekday())
    return "%d_%s" % (row["season"], monday.isoformat())


def exclusion_reason(r):
    if r["outcome"] is None:
        return "tie"
    if r["p_market"] is None:
        return "no_market"
    if r["spread_line"] is None:
        return "no_spread"
    return ""


def exclusions(rows, seasons):
    tot = [r for r in rows if r["season"] in seasons]
    ties = [r for r in tot if r["outcome"] is None]
    no_mkt = [r for r in tot if r["outcome"] is not None and r["p_market"] is None]
    no_spr = [r for r in tot if r["outcome"] is not None and r["p_market"] is not None
              and r["spread_line"] is None]
    graded = [r for r in tot if exclusion_reason(r) == ""]
    weeks = [r["week"] for r in graded]
    return {
        "total": len(tot), "ties": len(ties), "no_market": len(no_mkt),
        "no_spread": len(no_spr), "graded": len(graded),
        "week_min": min(weeks) if weeks else None, "week_max": max(weeks) if weeks else None,
    }


def scores(rows, base, feat, seasons, day):
    g = [r for r in fb.graded(rows) if r["season"] in seasons]
    ys = [r["outcome"] for r in g]
    bb = brier([base[r["game_id"]][1] for r in g], ys)
    bf = brier([feat[r["game_id"]][1] for r in g], ys)
    bk = brier([r["p_market"] for r in g], ys)
    bv = brier([r["p_model"] for r in g], ys)
    lb = logloss([base[r["game_id"]][1] for r in g], ys)
    lf = logloss([feat[r["game_id"]][1] for r in g], ys)
    lk = logloss([r["p_market"] for r in g], ys)
    lv = logloss([r["p_model"] for r in g], ys)
    eb = [abs(base[r["game_id"]][0] - r["actual_margin"]) for r in g]
    ef = [abs(feat[r["game_id"]][0] - r["actual_margin"]) for r in g]
    es = [abs(float(r["spread_line"]) - r["actual_margin"]) for r in g]

    d_fb = nm.bootstrap_mean_diff_ci(bf, bb, reps=REGISTERED_REPS, seed=REGISTERED_SEED)
    d_fk = nm.bootstrap_mean_diff_ci(bf, bk, reps=REGISTERED_REPS, seed=REGISTERED_SEED)
    d_bk = nm.bootstrap_mean_diff_ci(bb, bk, reps=REGISTERED_REPS, seed=REGISTERED_SEED)
    m_fb = nm.bootstrap_mean_diff_ci(ef, eb, reps=REGISTERED_REPS, seed=REGISTERED_SEED)

    blocks = [block_of(r, day) for r in g]
    c_fb = week_block_bootstrap_mean_diff(bf, bb, blocks)
    c_ll = week_block_bootstrap_mean_diff(lf, lb, blocks)
    c_mfb = week_block_bootstrap_mean_diff(ef, eb, blocks)

    return {
        "g": g, "n": len(g),
        "brier_v1": mean(bv), "brier_B": mean(bb), "brier_F": mean(bf), "brier_mkt": mean(bk),
        "logloss_v1": mean(lv), "logloss_B": mean(lb), "logloss_F": mean(lf), "logloss_mkt": mean(lk),
        "brier_fb": d_fb, "brier_fk": d_fk, "brier_bk": d_bk,
        "logloss_fb": nm.bootstrap_mean_diff_ci(lf, lb, reps=REGISTERED_REPS, seed=REGISTERED_SEED),
        "margin_mae_B": mean(eb), "margin_mae_F": mean(ef), "margin_mae_spread": mean(es),
        "margin_fb": m_fb,
        "cluster": {
            "brier": c_fb, "logloss": c_ll, "margin": c_mfb,
            "blocks": c_fb[3], "games": c_fb[4],
            "key": "(season, Monday gameday week)",
        },
        "pair_rows": list(zip(g, bb, bf, lb, lf, eb, ef, blocks)),
    }


def write_csv(path, rows, fields):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    os.makedirs(OUT, exist_ok=True)
    con = sqlite3.connect("file:%s?mode=ro" % fb.DB, uri=True)
    rows = fb.base_rows(con)
    day = gameday_map(con)

    base = fb.stack(rows)
    elo = fb.stack(rows, er.elo_diff(con, rows)[0])

    print("== baseline reproduction ==")
    reproduced = {}
    for name, seasons in fb.GROUPS:
        g = [r for r in fb.graded(rows) if r["season"] in seasons]
        ys = [r["outcome"] for r in g]
        got = {
            "B": mean(brier([base[r["game_id"]][1] for r in g], ys)),
            "v1": mean(brier([r["p_model"] for r in g], ys)),
            "elo": mean(brier([elo[r["game_id"]][1] for r in g], ys)),
            "market": mean(brier([r["p_market"] for r in g], ys)),
        }
        reproduced[name] = got
        for k in PUBLISHED:
            if abs(got[k] - PUBLISHED[k][name]) > TOL:
                raise SystemExit(
                    "BASELINE MISMATCH %s %s: reproduced %.6f, published %.4f"
                    % (k, name, got[k], PUBLISHED[k][name]))
        print("  %-9s n=%4d  B %.6f (pub %.4f)  v1 %.6f  Elo %.6f (pub %.4f)  mkt %.6f"
              % (name, len(g), got["B"], PUBLISHED["B"][name], got["v1"], got["elo"],
                 PUBLISHED["elo"][name], got["market"]))

    variants = [
        ("proe_net", base, pf.proe_net(con, rows)[0], "stack B"),
        ("elo_plus_proe", elo, pf.elo_plus_proe(con, rows)[0], "Elo stack"),
    ]

    all_scores = {}
    feat_stacks = {}
    paired_rows = []
    for vname, baseline, cols, bname in variants:
        feat = fb.stack(rows, cols)
        feat_stacks[vname] = feat
        all_scores[vname] = {}
        print("\n== %s (F = %s + columns, B = %s) ==" % (vname, bname, bname))
        for gname, seasons in fb.GROUPS:
            s = scores(rows, baseline, feat, seasons, day)
            all_scores[vname][gname] = s
            pt, lo, hi = s["brier_fb"]
            cpt, clo, chi, cblocks, _ = s["cluster"]["brier"]
            print("  %-9s n=%4d B %.4f F %.4f | F-B %+.4f [%+.4f,%+.4f] (reg) "
                  "| clustered %+.4f [%+.4f,%+.4f] %d blocks"
                  % (gname, s["n"], s["brier_B"], s["brier_F"], pt, lo, hi,
                     cpt, clo, chi, cblocks))
            print("  %-9s        logloss B %.4f F %.4f | F-B %+.4f [%+.4f,%+.4f] "
                  "| margin MAE B %.3f F %.3f | F-mkt %+.4f | B-mkt %+.4f"
                  % ("", s["logloss_B"], s["logloss_F"], *s["logloss_fb"],
                     s["margin_mae_B"], s["margin_mae_F"], s["brier_fk"][0], s["brier_bk"][0]))
            for (r, bb, bf, lb, lf, eb, ef, blk) in s["pair_rows"]:
                paired_rows.append({
                    "variant": vname, "group": gname, "game_id": r["game_id"],
                    "season": r["season"], "week": r["week"], "block": blk,
                    "outcome": r["outcome"], "brier_B": bb, "brier_F": bf,
                    "brier_diff": bf - bb, "logloss_B": lb, "logloss_F": lf,
                    "logloss_diff": lf - lb, "margin_abs_B": eb, "margin_abs_F": ef,
                    "margin_diff": ef - eb,
                })

    # KEEP rule, registered: pooled 2011-2023 interval entirely below zero AND
    # 2024 and 2025 point differences not above zero.
    verdict = {}
    for vname in all_scores:
        pooled = all_scores[vname]["2011-2023"]
        p24 = all_scores[vname]["2024"]["brier_fb"][0]
        p25 = all_scores[vname]["2025"]["brier_fb"][0]
        hi = pooled["brier_fb"][2]
        kept = (hi < 0) and (p24 <= 0) and (p25 <= 0)
        verdict[vname] = {
            "pooled_point": pooled["brier_fb"][0], "pooled_lo": pooled["brier_fb"][1],
            "pooled_hi": hi, "p2024": p24, "p2025": p25, "kept": kept,
            "reason": ("pooled upper bound %.6f is not below zero; 2024 point %+.6f; "
                       "2025 point %+.6f" % (hi, p24, p25)),
        }

    # forecasts.csv: every scored-season row, including exclusions.
    frows = []
    for r in rows:
        if r["season"] < 2011:
            continue
        frows.append({
            "game_id": r["game_id"], "season": r["season"], "week": r["week"],
            "home": r["home"], "away": r["away"], "outcome": r["outcome"],
            "actual_margin": r["actual_margin"], "spread_line": r["spread_line"],
            "p_v1": r["p_model"], "p_B": base[r["game_id"]][1],
            "p_elo": elo[r["game_id"]][1],
            "p_proe_net": None, "p_elo_plus_proe": None, "p_market": r["p_market"],
            "graded": 1 if exclusion_reason(r) == "" else 0,
            "exclusion": exclusion_reason(r),
        })
    # Fill the feature probabilities from the exact stacks scored above.
    for row in frows:
        row["p_proe_net"] = feat_stacks["proe_net"][row["game_id"]][1]
        row["p_elo_plus_proe"] = feat_stacks["elo_plus_proe"][row["game_id"]][1]

    # arm_scores.csv
    arows = []
    for vname in all_scores:
        for gname, _ in fb.GROUPS:
            s = all_scores[vname][gname]
            arows.append({
                "variant": vname, "group": gname, "n": s["n"],
                "brier_v1": s["brier_v1"], "brier_B": s["brier_B"], "brier_F": s["brier_F"],
                "brier_mkt": s["brier_mkt"],
                "brier_diff": s["brier_fb"][0], "brier_lo": s["brier_fb"][1],
                "brier_hi": s["brier_fb"][2],
                "brier_cluster_pt": s["cluster"]["brier"][0],
                "brier_cluster_lo": s["cluster"]["brier"][1],
                "brier_cluster_hi": s["cluster"]["brier"][2],
                "brier_blocks": s["cluster"]["blocks"],
                "logloss_v1": s["logloss_v1"], "logloss_B": s["logloss_B"],
                "logloss_F": s["logloss_F"], "logloss_mkt": s["logloss_mkt"],
                "logloss_diff": s["logloss_fb"][0], "logloss_lo": s["logloss_fb"][1],
                "logloss_hi": s["logloss_fb"][2],
                "logloss_cluster_pt": s["cluster"]["logloss"][0],
                "logloss_cluster_lo": s["cluster"]["logloss"][1],
                "logloss_cluster_hi": s["cluster"]["logloss"][2],
                "margin_mae_B": s["margin_mae_B"], "margin_mae_F": s["margin_mae_F"],
                "margin_mae_spread": s["margin_mae_spread"],
                "margin_diff": s["margin_fb"][0], "margin_lo": s["margin_fb"][1],
                "margin_hi": s["margin_fb"][2],
                "margin_cluster_pt": s["cluster"]["margin"][0],
                "margin_cluster_lo": s["cluster"]["margin"][1],
                "margin_cluster_hi": s["cluster"]["margin"][2],
                "F_minus_market": s["brier_fk"][0], "F_minus_market_lo": s["brier_fk"][1],
                "F_minus_market_hi": s["brier_fk"][2],
                "B_minus_market": s["brier_bk"][0], "B_minus_market_lo": s["brier_bk"][1],
                "B_minus_market_hi": s["brier_bk"][2],
                "kept": int(verdict[vname]["kept"]),
            })

    # per_season.csv
    srows = []
    for vname, baseline, cols, _ in variants:
        feat = feat_stacks[vname]
        for season in range(2011, 2026):
            s = scores(rows, baseline, feat, (season,), day)
            srows.append({
                "variant": vname, "season": season, "n": s["n"],
                "brier_B": s["brier_B"], "brier_F": s["brier_F"],
                "brier_diff": s["brier_fb"][0],
                "logloss_B": s["logloss_B"], "logloss_F": s["logloss_F"],
                "logloss_diff": s["logloss_fb"][0],
                "margin_mae_B": s["margin_mae_B"], "margin_mae_F": s["margin_mae_F"],
            })

    # exclusions.csv
    erows = []
    for gname, seasons in fb.GROUPS:
        e = exclusions(rows, seasons)
        e["group"] = gname
        e["season"] = "all"
        erows.append(e)
        for season in seasons:
            e = exclusions(rows, (season,))
            e["group"] = gname
            e["season"] = season
            erows.append(e)

    files = {}
    write_csv(os.path.join(OUT, "forecasts.csv"), frows,
              ["game_id", "season", "week", "home", "away", "outcome", "actual_margin",
               "spread_line", "p_v1", "p_B", "p_elo", "p_proe_net", "p_elo_plus_proe",
               "p_market", "graded", "exclusion"])
    write_csv(os.path.join(OUT, "paired.csv"), paired_rows,
              ["variant", "group", "game_id", "season", "week", "block", "outcome",
               "brier_B", "brier_F", "brier_diff", "logloss_B", "logloss_F",
               "logloss_diff", "margin_abs_B", "margin_abs_F", "margin_diff"])
    write_csv(os.path.join(OUT, "arm_scores.csv"), arows,
              ["variant", "group", "n", "brier_v1", "brier_B", "brier_F", "brier_mkt",
               "brier_diff", "brier_lo", "brier_hi", "brier_cluster_pt",
               "brier_cluster_lo", "brier_cluster_hi", "brier_blocks", "logloss_v1",
               "logloss_B", "logloss_F", "logloss_mkt", "logloss_diff", "logloss_lo",
               "logloss_hi", "logloss_cluster_pt", "logloss_cluster_lo",
               "logloss_cluster_hi", "margin_mae_B", "margin_mae_F", "margin_mae_spread",
               "margin_diff", "margin_lo", "margin_hi", "margin_cluster_pt",
               "margin_cluster_lo", "margin_cluster_hi", "F_minus_market",
               "F_minus_market_lo", "F_minus_market_hi", "B_minus_market",
               "B_minus_market_lo", "B_minus_market_hi", "kept"])
    write_csv(os.path.join(OUT, "per_season.csv"), srows,
              ["variant", "season", "n", "brier_B", "brier_F", "brier_diff",
               "logloss_B", "logloss_F", "logloss_diff", "margin_mae_B", "margin_mae_F"])
    write_csv(os.path.join(OUT, "exclusions.csv"), erows,
              ["group", "season", "total", "ties", "no_market", "no_spread", "graded",
               "week_min", "week_max"])

    for name in ("forecasts.csv", "paired.csv", "arm_scores.csv",
                 "per_season.csv", "exclusions.csv"):
        files[name] = sha256(os.path.join(OUT, name))

    reg_sha = sha256(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "nfl_proe_feature.py"))
    man = {
        "task": "PROE feature test, already registered; no re-registration",
        "base_commit": "fbd1dad6e1c9600c5360536c8d4201f0645222ff",
        "registration": {
            "file": "backend/nfl_proe_feature.py",
            "sha256": reg_sha,
            "canonical_commit": "ed96a861ad1702b18d346fd166ef94ab7f45d1ec",
            "dev_history_commit": "af96cbf6383c4f153a49430d93ef9a7d7b14cec7",
            "unchanged": True,
        },
        "db": {"path": fb.DB, "mode": "ro"},
        "population": {g: exclusions(rows, s) for g, s in fb.GROUPS},
        "baselines": {"published": PUBLISHED, "reproduced": reproduced},
        "interval": {
            "registered": {
                "helper": "nfl_metrics.bootstrap_mean_diff_ci",
                "unit": "paired games (no block key)",
                "reps": REGISTERED_REPS, "seed": REGISTERED_SEED,
                "alpha": 0.05,
            },
            "secondary_clustered": {
                "helper": "week_block_bootstrap_mean_diff (copied from the history-window runner)",
                "block_key": "(season, Monday gameday week)",
                "reps": CLUSTER_REPS, "seed": CLUSTER_SEED,
                "weighting": "game-count weighted",
                "note": "secondary only; not part of the registered keep rule",
            },
        },
        "keep_rule": ("pooled 2011-2023 registered interval of Brier(F)-Brier(B) entirely "
                      "below zero AND the 2024 and 2025 point differences not above zero"),
        "results": {v: {g: {k: all_scores[v][g][k] for k in
                            ("n", "brier_B", "brier_F", "brier_fb", "logloss_B", "logloss_F",
                             "logloss_fb", "margin_mae_B", "margin_mae_F", "margin_fb",
                             "brier_fk", "brier_bk")} for g, _ in fb.GROUPS}
                    for v in all_scores},
        "verdict": verdict,
        "files": files,
        "commands": {
            "baselines": "LP_DB_PATH=<dev db> venv/bin/python nfl_feature_backtest.py --feature base",
            "proe_net": "LP_DB_PATH=<dev db> venv/bin/python nfl_proe_feature.py --feature proe_net",
            "elo_plus_proe": "LP_DB_PATH=<dev db> venv/bin/python nfl_proe_feature.py --feature elo_plus_proe",
            "artifacts": "LP_DB_PATH=<dev db> venv/bin/python nfl_proe_run.py",
        },
    }
    with open(os.path.join(OUT, "MANIFEST.json"), "w") as fh:
        json.dump(man, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print("\n== keep rule (registered) ==")
    for v in verdict:
        print("  %-14s kept=%s  pooled [%+.4f,%+.4f]  2024 %+.4f  2025 %+.4f"
              % (v, verdict[v]["kept"], verdict[v]["pooled_lo"], verdict[v]["pooled_hi"],
                 verdict[v]["p2024"], verdict[v]["p2025"]))
    print("\nwrote %s" % OUT)


if __name__ == "__main__":
    main()
