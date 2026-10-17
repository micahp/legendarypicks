#!/usr/bin/env python3
"""Prospective *research* candidate: NFL player-prop v2 + forward-only pooled Platt.

This is NOT a production route and NOT a calibrated stat distribution. It learns a
line-specific map of P(over), using ONLY prior weeks' settled items. It uses a
pregame QB population and only paired odds captured before scheduled kickoff.
It does NOT prove the stored player projections or injury reports were
historically captured before kickoff. That requires a separate snapshot audit.

Read-only by default:
  LP_DB_PATH=/abs/picks.dev.db python3 nfl_prop_forward_platt_candidate.py --season 2026
  ... --json-report /tmp/forward-platt-report.json --csv /tmp/forward-platt-graded.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sqlite3
from collections import Counter, defaultdict

import calibrate_nfl_prop_probabilities as cal
import grade_nfl_prop_probabilities as grader
import measure_nfl_prop_discrimination as metrics

MODEL_ID = "nfl-player-props-v2-forward-platt-v1"
MIN_TRAIN_ITEMS = 500  # fixed before scoring the candidate, not selected on holdout scores


def train(prior, held_week, min_items=MIN_TRAIN_ITEMS):
    """Fit only on games in weeks strictly before held_week. Never read market odds as features."""
    older = [r for r in prior if r["week"] < held_week]
    if len(older) < min_items:
        return None
    a, b = cal.fit_platt([(r["p_ours"], r["over"]) for r in older])
    if not all(math.isfinite(x) for x in (a, b)) or a <= 0:
        raise ValueError("invalid or nonmonotonic Platt fit in week %s: %.5g, %.5g" % (held_week, a, b))
    return {"model_id": MODEL_ID, "slope": a, "intercept": b,
            "train_through_week": max(r["week"] for r in older),
            "train_items": len(older),
            "train_player_games": len({(r["game_id"], r["player_id"]) for r in older})}


def apply(probability, fitted):
    """Raw probability preserved when no earlier-week training sample exists."""
    if fitted is None:
        return probability
    if not 0 <= probability <= 1:
        raise ValueError("probability outside [0, 1]")
    return cal.sigmoid(fitted["slope"] * cal.logit(probability) + fitted["intercept"])


def candidate_rows(graded, min_items=MIN_TRAIN_ITEMS):
    """Return candidate predictions and per-week fitted snapshots; caller owns raw rows."""
    rows = [dict(r, week=int(r["game_id"].split("_")[1])) for r in graded]
    if len(rows) != len({(r["game_id"], r["player_id"], r["market"], r["book"], r["line"]) for r in rows}):
        raise ValueError("duplicate (game,player,market,book,line) entries")
    fits = {}
    for week in sorted({r["week"] for r in rows}):
        fits[week] = train(rows, week, min_items)
        for r in rows:
            if r["week"] == week:
                r["p_forward"] = apply(r["p_ours"], fits[week])
                r["calibrated"] = fits[week] is not None
    return rows, fits


def paired_boot(rows, better_field, worse_field, func, boots):
    """Positive difference means better_field improves the proper score."""
    if len({(r["game_id"], r["player_id"]) for r in rows}) < 2:
        return None
    obs, lo, hi = metrics.cluster_boot(
        rows, lambda s: func(s, worse_field) - func(s, better_field), boots)
    return {"delta": obs, "ci95": [lo, hi], "established": lo is not None and lo > 0}


def fit_market_stack(rows, min_items=MIN_TRAIN_ITEMS):
    """Forward refit of market-only against market + candidate; no trained data from held week.

    Use prior calibrated candidate predictions, not in-sample maps calculated using the
    outcome we intend to train the stack on. Early raw fallback weeks are excluded.
    """
    results = []
    for held in sorted({r["week"] for r in rows}):
        train_rows = [r for r in rows if r["week"] < held and r["calibrated"]]
        test = [r for r in rows if r["week"] == held and r["calibrated"]]
        if len(train_rows) < min_items or not test:
            continue
        y = [r["over"] for r in train_rows]
        m = metrics.fit_logistic([[1.0, metrics.logit(r["p_market"])] for r in train_rows], y)
        stk = metrics.fit_logistic(
            [[1.0, metrics.logit(r["p_market"]), metrics.logit(r["p_forward"])] for r in train_rows], y)
        for r in test:
            q = dict(r)
            q["p_mkt_refit"] = metrics.sigmoid(m[0] + m[1] * metrics.logit(r["p_market"]))
            q["p_stack"] = metrics.sigmoid(
                stk[0] + stk[1] * metrics.logit(r["p_market"]) +
                stk[2] * metrics.logit(r["p_forward"]))
            results.append(q)
    return results


def summarize(rows, boots):
    if not rows:
        return None
    groups = len({(r["game_id"], r["player_id"]) for r in rows})
    ans = {"items": len(rows), "player_games": groups, "weeks": sorted({r["week"] for r in rows}),
           "scores": {}}
    for field in ("p_ours", "p_forward", "p_market"):
        ans["scores"][field] = {
            "brier": metrics.brier(rows, field),
            "logloss": metrics.logloss(rows, field),
            "auc": metrics.auc([(r[field], r["over"]) for r in rows])
        }
    ans["platt_vs_raw_brier"] = paired_boot(rows, "p_forward", "p_ours", metrics.brier, boots)
    ans["platt_vs_raw_logloss"] = paired_boot(rows, "p_forward", "p_ours", metrics.logloss, boots)
    ans["platt_vs_market_brier"] = paired_boot(rows, "p_forward", "p_market", metrics.brier, boots)
    return ans


def evaluate(graded, skipped=None, boots=400, min_items=MIN_TRAIN_ITEMS):
    rows, fits = candidate_rows(graded, min_items)
    calibrated = [r for r in rows if r["calibrated"]]
    results = {
        "model_id": MODEL_ID,
        "scope": "research_only_not_prospective_locked",
        "qb_selector": "pregame_prior_attempts",
        "quotes": "paired_pregame_timezone_aware",
        "stat_distributions_calibrated": False,
        "input_items": len(rows),
        "uncalibrated_items": len(rows) - len(calibrated),
        "excluded": skipped or {},
        "fits": {str(w): f for w, f in fits.items()},
        "overall": summarize(calibrated, boots),
        "by_market": {m: summarize([r for r in calibrated if r["market"] == m], boots)
                      for m in sorted({r["market"] for r in rows})},
    }
    stacked = fit_market_stack(rows, min_items)
    results["market_increment"] = {"items": len(stacked),
                                    "player_games": len({(r["game_id"], r["player_id"]) for r in stacked}),
                                    "weeks": sorted({r["week"] for r in stacked}),
                                    "market_refit": None, "stack": None,
                                    "logloss_improvement": None, "brier_improvement": None}
    if stacked:
        results["market_increment"].update({
            "market_refit": {"brier": metrics.brier(stacked, "p_mkt_refit"),
                             "logloss": metrics.logloss(stacked, "p_mkt_refit")},
            "stack": {"brier": metrics.brier(stacked, "p_stack"),
                      "logloss": metrics.logloss(stacked, "p_stack")},
            "logloss_improvement": paired_boot(stacked, "p_stack", "p_mkt_refit", metrics.logloss, boots),
            "brier_improvement": paired_boot(stacked, "p_stack", "p_mkt_refit", metrics.brier, boots)})
    results["candidate_state"] = "research_candidate_not_promoted"
    results["reasons_not_promoted"] = [
        "Actual pre-kickoff projection and injury input snapshots not independently verified",
        "Conditional-on-played subset remains observed-participation selection",
        "Cannot claim independent market increment without positive paired clustered interval",
    ]
    return results, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--boot", type=int, default=400)
    ap.add_argument("--json-report", help="optional JSON results output")
    ap.add_argument("--csv", help="optional scored-rows output")
    args = ap.parse_args(argv)
    if args.boot < 20:
        ap.error("--boot must be >=20")
    path = os.environ.get("LP_DB_PATH")
    if not path:
        ap.error("LP_DB_PATH required")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        graded, skipped, disagree = grader.grade(
            con, args.season, pregame_only=True, qb_selection="pregame")
    finally:
        con.close()
    if not graded:
        raise SystemExit("No valid pregame quote pairs/player-games to grade; no model result issued")
    output, rows = evaluate(graded, skipped, args.boot)
    output["book_settlement_disagreements"] = disagree
    print(json.dumps(output, indent=2, sort_keys=True))
    if args.json_report:
        with open(args.json_report, "w") as f:
            json.dump(output, f, indent=2, sort_keys=True)
    if args.csv:
        with open(args.csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    main()
