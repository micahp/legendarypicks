#!/usr/bin/env python3
"""CP1 baseline ladder for the special-teams experiment, on the identical games.

B0 constant 50%; B1 training home rate; B4 rolling-goals Poisson; B5 5v5 xG
Poisson; ST = candidate. Same 9,147 evaluation games, same fit convention.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
from sklearn.linear_model import PoissonRegressor

import run_special_teams as R

HERE = Path(__file__).resolve().parent
AUDIT = Path("/root/legendarypicks/research/nhl/kalshi-playoff-audit-2025-26")
FEATS = AUDIT / "pregame_rolling_features_v1_62dcceb77085bc59.csv"
ALPHA = 0.01


def pmf(mu, cap=21):
    mu = max(float(mu), 1e-9); ks = np.arange(cap)
    p = np.exp(-mu + ks * math.log(mu) - np.array([math.lgamma(k + 1) for k in ks]))
    return p / p.sum()


def crps(p, y):
    F = np.cumsum(p); ks = np.arange(len(p))
    return float(np.sum((F - (ks >= y).astype(float)) ** 2))


def main():
    games = R.load_games()
    st = R.build_st_features(games)
    feats = {int(r["game_id"]): r for r in csv.DictReader(open(FEATS))}
    merged = []
    for g in games:
        h = st.get((g["game_id"], "HOME")); a = st.get((g["game_id"], "AWAY"))
        if not h or not a or None in h or None in a:
            continue
        x = feats[g["game_id"]]
        merged.append({**g, "hpp": h[0], "hpk": h[1], "app": a[0], "apk": a[1],
                       "hgf": x["home_rolling10_goals_for"], "hga": x["home_rolling10_goals_against"],
                       "agf": x["away_rolling10_goals_for"], "aga": x["away_rolling10_goals_against"]})

    def fit_predict(train, evalg, kind):
        if kind == "b0":
            return {g["game_id"]: (2.5, 2.5) for g in evalg}
        if kind == "b1":
            # B1 = home/away goals from the training mean; winner prob from the
            # training home rate via a constant.
            return {g["game_id"]: (2.5, 2.5) for g in evalg}
        X, y = [], []
        for r in train:
            if kind == "b4":
                X.extend([[1.0, R.lograte(r["hgf"]), R.lograte(r["aga"])],
                          [0.0, R.lograte(r["agf"]), R.lograte(r["hga"])]])
            elif kind == "b5":
                X.extend([[1.0, R.lograte(r["hx"]), R.lograte(r["axga"])],
                          [0.0, R.lograte(r["ax"]), R.lograte(r["hxga"])]])
            elif kind == "st":
                X.extend([[1.0, R.lograte(r["hx"]), R.lograte(r["axga"]), R.lograte(r["hpp"]), R.lograte(r["apk"])],
                          [0.0, R.lograte(r["ax"]), R.lograte(r["hxga"]), R.lograte(r["app"]), R.lograte(r["hpk"])]])
            y.extend([r["hg"], r["ag"]])
        f = PoissonRegressor(alpha=ALPHA, max_iter=500, tol=1e-9).fit(np.asarray(X, float), np.asarray(y, float))
        out = {}
        for r in evalg:
            if kind == "b4":
                xh = [1.0, R.lograte(r["hgf"]), R.lograte(r["aga"])]
                xa = [0.0, R.lograte(r["agf"]), R.lograte(r["hga"])]
            elif kind == "b5":
                xh = [1.0, R.lograte(r["hx"]), R.lograte(r["axga"])]
                xa = [0.0, R.lograte(r["ax"]), R.lograte(r["hxga"])]
            else:
                xh = [1.0, R.lograte(r["hx"]), R.lograte(r["axga"]), R.lograte(r["hpp"]), R.lograte(r["apk"])]
                xa = [0.0, R.lograte(r["ax"]), R.lograte(r["hxga"]), R.lograte(r["app"]), R.lograte(r["hpk"])]
            out[r["game_id"]] = (math.exp(f.intercept_ + np.dot(xh, f.coef_)),
                                 math.exp(f.intercept_ + np.dot(xa, f.coef_)))
        return out

    per = {k: {"brier": [], "log_loss": [], "crps": []} for k in ("b0", "b1", "b4", "b5", "st")}
    for season in R.EVAL_SEASONS:
        evalg = [g for g in merged if g["season"] == season]
        train = [g for g in merged if R.TRAIN_FROM <= g["season"] < season]
        so = [g for g in train if g.get("period") == "SO"]
        so_home = sum(g["home_win"] for g in so) / len(so)
        q = sum(g["home_win"] for g in train) / len(train)
        for kind in ("b0", "b1", "b4", "b5", "st"):
            mus = fit_predict(train, evalg, kind)
            for g in evalg:
                mh, ma = mus[g["game_id"]]
                if kind == "b0":
                    p = 0.5
                elif kind == "b1":
                    p = q
                else:
                    p = min(max(R.home_win_prob(mh, ma, so_home), 1e-6), 1 - 1e-6)
                per[kind]["brier"].append((p - g["home_win"]) ** 2)
                per[kind]["log_loss"].append(-(g["home_win"] * math.log(p) + (1 - g["home_win"]) * math.log(1 - p)))
                per[kind]["crps"].append((crps(pmf(mh), g["hg"]) + crps(pmf(ma), g["ag"])) / 2)
    out = {}
    for kind in per:
        out[kind] = {m: float(np.mean(per[kind][m])) for m in ("brier", "log_loss", "crps")}
    print(json.dumps(out, indent=1))
    (HERE / "baseline_ladder_st.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
