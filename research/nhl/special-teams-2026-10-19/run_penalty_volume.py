#!/usr/bin/env python3
"""Penalty-opportunity volume on top of ST — pre-registered 2026-10-19.

Baseline: ST (the passing candidate), frozen exactly as in run_special_teams.py.
V1 (primary): ST + penalties drawn per 60.
V2 (exploratory): ST + penalties drawn and taken per 60.
Judge against ST. Same walk-forward harness, same frozen convention.

Pre-registration: special-teams-penalty-preregistration-2026-10-19.md (675ca38b).
"""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import duckdb
import numpy as np
from sklearn.linear_model import PoissonRegressor

import run_special_teams as R

HERE = Path(__file__).resolve().parent
ARMS = ("st", "v1", "v2")


def build_penalty_features() -> dict:
    """Strictly-before-game rolling penalties drawn/taken per 60, keyed by (game_id, HOME/AWAY).

    penaltiesAgainst = penalties drawn by the team (opponent committed them) -> PP opportunity.
    penaltiesFor     = penalties taken by the team -> PK opportunity.
    Same convention as the ST rates: 60 * sum / sum(iceTime_seconds).
    """
    con = duckdb.connect(R.DB, read_only=True)
    rows = con.execute("""
        SELECT gameId, team, home_or_away, penaltiesFor, penaltiesAgainst, iceTime
        FROM teams_gamelogs WHERE situation='all'
    """).fetchall()
    con.close()

    gdate = {int(c["game_id"]): c["game_date"] for c in csv.DictReader(open(R.CANON))}
    per = defaultdict(dict)
    for gid, team, ha, pf, pa, ice in rows:
        d = per[(int(gid), R.ALIAS.get(str(team), str(team)))]
        d["date"] = str(gdate.get(int(gid)))
        d["ha"] = ha
        d["pen_for"] = float(pf)       # taken by team
        d["pen_against"] = float(pa)   # drawn by team
        d["ice"] = float(ice)

    order = sorted(per.items(), key=lambda kv: (kv[1]["date"], kv[0][0], kv[0][1]))
    history = defaultdict(list)
    out = {}
    for (gid, team), d in order:
        prior = [x for x in history[team] if x["date"] < d["date"]][-10:]
        if len(prior) >= 5:
            ice = sum(x["ice"] for x in prior)
            drawn = 60.0 * sum(x["pen_against"] for x in prior) / ice if ice > 0 else None
            taken = 60.0 * sum(x["pen_for"] for x in prior) / ice if ice > 0 else None
        else:
            drawn = taken = None
        out[(gid, d["ha"])] = (drawn, taken)
        history[team].append(d)
    return out


def side_x(r: dict, model: str):
    hx, hxga = R.lograte(r["hx"]), R.lograte(r["hxga"])
    ax, axga = R.lograte(r["ax"]), R.lograte(r["axga"])
    st_h = [1.0, hx, axga, R.lograte(r["hpp"]), R.lograte(r["apk"])]
    st_a = [0.0, ax, hxga, R.lograte(r["app"]), R.lograte(r["hpk"])]
    if model == "st":
        return st_h, st_a
    if model == "v1":
        return st_h + [R.lograte(r["hdrawn"])], st_a + [R.lograte(r["adrawn"])]
    if model == "v2":
        return (st_h + [R.lograte(r["hdrawn"]), R.lograte(r["htaken"])],
                st_a + [R.lograte(r["adrawn"]), R.lograte(r["ataken"])])
    raise ValueError(model)


def fit_arm(train: list[dict], model: str):
    X, y = [], []
    for r in train:
        xh, xa = side_x(r, model)
        X.extend([xh, xa]); y.extend([r["hg"], r["ag"]])
    fitted = PoissonRegressor(alpha=R.ALPHA, max_iter=500, tol=1e-9).fit(
        np.asarray(X, float), np.asarray(y, float))
    return {"intercept": float(fitted.intercept_), "coef": [float(b) for b in fitted.coef_]}


def predict_arm(games: list[dict], model: str, params: dict):
    intercept = float(params["intercept"])
    beta = np.asarray(params["coef"], float)
    out = {}
    for r in games:
        xh, xa = side_x(r, model)
        out[r["game_id"]] = (math.exp(intercept + float(np.dot(xh, beta))),
                             math.exp(intercept + float(np.dot(xa, beta))))
    return out


def main() -> None:
    games = R.load_games()
    st = R.build_st_features(games)
    pen = build_penalty_features()

    # Start from the exact ST merged population (same 23,002 games, then 9,147 eval).
    merged = []
    st_missing = pen_missing = 0
    for g in games:
        h = st.get((g["game_id"], "HOME")); a = st.get((g["game_id"], "AWAY"))
        if not h or not a or None in h or None in a:
            st_missing += 1; continue
        hp = pen.get((g["game_id"], "HOME")); ap = pen.get((g["game_id"], "AWAY"))
        if not hp or not ap or None in hp or None in ap:
            pen_missing += 1; continue
        merged.append({**g, "hpp": h[0], "hpk": h[1], "app": a[0], "apk": a[1],
                       "hdrawn": hp[0], "htaken": hp[1], "adrawn": ap[0], "ataken": ap[1]})
    print(f"games loaded={len(games)} merged={len(merged)} "
          f"dropped_no_st={st_missing} dropped_no_pen={pen_missing}", flush=True)
    if pen_missing:
        raise SystemExit(f"population changed: {pen_missing} ST games lack penalty features; "
                         "preregistration requires identical graded games")

    # walk-forward, all arms on the same games
    per_season = {}
    for season in R.EVAL_SEASONS:
        evalg = [g for g in merged if g["season"] == season]
        train = [g for g in merged if R.TRAIN_FROM <= g["season"] < season]
        so = [g for g in train if g.get("period") == "SO"]
        so_home = sum(g["home_win"] for g in so) / len(so)
        params = {m: fit_arm(train, m) for m in ARMS}
        mus = {m: predict_arm(evalg, m, params[m]) for m in ARMS}
        per_season[season] = {"n": len(evalg), "params": params}
        print(f"  season {season}: n={len(evalg)} "
              f"st={[round(c,4) for c in params['st']['coef']]} "
              f"v1={[round(c,4) for c in params['v1']['coef']]} "
              f"v2={[round(c,4) for c in params['v2']['coef']]}", flush=True)
        for m in ARMS:
            rows = []
            for g in evalg:
                mh, ma = mus[m][g["game_id"]]
                p = min(max(R.home_win_prob(mh, ma, so_home), 1e-6), 1 - 1e-6)
                rows.append({"game_id": g["game_id"], "season": season, "game_date": g["game_date"],
                             "brier": (p - g["home_win"]) ** 2,
                             "log_loss": -(g["home_win"] * math.log(p) + (1 - g["home_win"]) * math.log(1 - p)),
                             "crps": (R.crps(R.pmf(mh), g["hg"]) + R.crps(R.pmf(ma), g["ag"])) / 2,
                             "mae": (abs(mh - g["hg"]) + abs(ma - g["ag"])) / 2,
                             "p": p, "mu_h": mh, "mu_a": ma,
                             "hg": g["hg"], "ag": g["ag"], "y": g["home_win"]})
            per_season[season][m] = rows

    # per-game forecasts artifact
    fc = []
    for season in R.EVAL_SEASONS:
        dicts = {m: {r["game_id"]: r for r in per_season[season][m]} for m in ARMS}
        for gid in sorted(dicts["st"]):
            s, v1, v2 = dicts["st"][gid], dicts["v1"][gid], dicts["v2"][gid]
            fc.append({"game_id": gid, "season": season, "game_date": s["game_date"],
                       "home_win": s["y"], "p_st": s["p"], "p_v1": v1["p"], "p_v2": v2["p"],
                       "mu_h_st": s["mu_h"], "mu_a_st": s["mu_a"],
                       "mu_h_v1": v1["mu_h"], "mu_a_v1": v1["mu_a"],
                       "mu_h_v2": v2["mu_h"], "mu_a_v2": v2["mu_a"],
                       "home_goals": s["hg"], "away_goals": s["ag"]})
    fc.sort(key=lambda r: (r["season"], r["game_date"], r["game_id"]))
    with (HERE / "forecasts_penalty.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fc[0].keys()))
        w.writeheader(); w.writerows(fc)

    # aggregate deltas vs ST, clustered by game
    def collect(m):
        d = {}
        for season in R.EVAL_SEASONS:
            for r in per_season[season][m]:
                d[r["game_id"]] = r
        return d

    stt = collect("st")
    ids = sorted(stt)
    n = len(ids)
    print(f"matched evaluation games: {n}", flush=True)

    def metrics(candidate):
        c = collect(candidate)
        out = {}
        for key in ("brier", "log_loss", "crps", "mae"):
            a = np.array([stt[i][key] for i in ids])
            b = np.array([c[i][key] for i in ids])
            delta = a - b
            rng = np.random.default_rng(R.SEED)
            boots = np.empty(R.N_BOOT)
            for it in range(R.N_BOOT):
                idx = rng.integers(0, n, n)
                boots[it] = delta[idx].mean()
            out[key] = {"st": float(a.mean()), "candidate": float(b.mean()),
                        "delta_st_minus_candidate": float(delta.mean()),
                        "ci95_low": float(np.quantile(boots, 0.025)),
                        "ci95_high": float(np.quantile(boots, 0.975)), "n": n}
        return out

    result = {
        "registered": "research/nhl/special-teams-penalty-preregistration-2026-10-19.md",
        "population": {"merged": len(merged), "eval_games": n,
                       "by_season": {s: per_season[s]["n"] for s in R.EVAL_SEASONS}},
        "v1": metrics("v1"),
        "v2": metrics("v2"),
        "coef_by_season": {m: {s: per_season[s]["params"][m]["coef"] for s in R.EVAL_SEASONS}
                           for m in ARMS},
    }
    (HERE / "results_penalty_volume.json").write_text(json.dumps(result, indent=1))
    for m in ("v1", "v2"):
        print(f"\n=== {m} vs ST ===")
        for key in ("brier", "log_loss", "crps"):
            r = result[m][key]
            print(f"  {key:9}: ST={r['st']:.9f} {m}={r['candidate']:.9f} "
                  f"delta={r['delta_st_minus_candidate']:+.9f} "
                  f"CI=[{r['ci95_low']:+.9f}, {r['ci95_high']:+.9f}]")
    print(f"\nwrote {HERE/'results_penalty_volume.json'} and forecasts_penalty.csv")


if __name__ == "__main__":
    main()
