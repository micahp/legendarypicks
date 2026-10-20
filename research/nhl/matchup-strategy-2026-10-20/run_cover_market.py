"""Does any model of two-goal margins beat the quoted -1.5 price?

Joins the walk-forward B7 (Elo + xG Poisson) cover probability to the SBR puck-line
prices on the same games, then on identical games compares:

  1. Brier: raw model vs isotonic-recalibrated model vs the no-vig market implied
     probability (de-vigged from both puck prices) vs the constant base rate.
  2. Selective -1.5 trading: EV threshold tuned on prior seasons only, evaluated
     out of sample, with a season-clustered 90% CI.

No production code is touched.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from sklearn.isotonic import IsotonicRegression

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import backtest_matchup_strategy as bt  # noqa: E402


def dec(american_price: float) -> float:
    return 1.0 + (american_price / 100.0 if american_price > 0 else 100.0 / abs(american_price))


def devig_pair(p1: float, p2: float) -> tuple[float, float]:
    q1, q2 = 1.0 / dec(p1), 1.0 / dec(p2)
    return q1 / (q1 + q2), q2 / (q1 + q2)


def cover_probs(fc: dict) -> tuple[float, float]:
    """(P(home -1.5), P(away -1.5)) from the independent Poisson score matrix."""
    m = np.outer(bt.pmf(fc["mu_h"]), bt.pmf(fc["mu_a"]))
    i, j = np.indices(m.shape)
    return float(m[i - j >= 2].sum()), float(m[i - j <= -2].sum())


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def clustered_roi_ci(rows: list[dict], iters: int = 5000, seed: int = 11) -> tuple[float, float]:
    by_season: dict[int, list[float]] = {}
    for r in rows:
        by_season.setdefault(r["season"], []).append(r["u"])
    seasons = list(by_season)
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(iters):
        pick = rng.choice(seasons, size=len(seasons), replace=True)
        vals = [v for s in pick for v in by_season[s]]
        out.append(sum(vals) / len(vals))
    lo, hi = np.percentile(out, [5, 95])
    return float(lo), float(hi)


def build() -> list[dict]:
    canon = bt.load_csv(bt.CANONICAL)
    features = {int(r["game_id"]): r for r in bt.load_csv(bt.FEATURES)}
    games = bt.load_games(canon, features)
    elo = bt.elo_replay(canon)

    folds = {}
    for season in bt.EVAL_SEASONS:
        folds[season] = bt.fit_fold([g for g in games if g["season"] <= season - 1], elo)
        print(f"fold {season}: intercept={folds[season]['intercept']:.4f} "
              f"coef={[round(c, 4) for c in folds[season]['coef']]}", flush=True)

    by_key = {}
    for c in canon:
        gid = int(c["game_id"])
        f = features.get(gid)
        md = int(c["game_date"][5:7]) * 100 + int(c["game_date"][8:10])
        by_key[(int(c["season"]), md, bt.TEAM_ID.get(c["home_team"], c["home_team"]),
                bt.TEAM_ID.get(c["away_team"], c["away_team"]))] = gid
    game_by_id = {g["game_id"]: g for g in games}

    rows = []
    sbr = [json.loads(line) for line in bt.SBR.open()]
    for g in sbr:
        h, a = bt.tri(g["home"]["team"]), bt.tri(g["away"]["team"])
        if not (h and a):
            continue
        season = int(g["season"][:4])
        gid = by_key.get((season, int(g["date"]), h, a))
        if gid is None or gid not in game_by_id or season not in folds:
            continue
        rec = game_by_id[gid]
        fc = bt.forecast(folds[season], elo, rec)

        hp = g["home"].get("puck_line")
        hp_price, ap_price = g["home"].get("puck_price"), g["away"].get("puck_price")
        hml = g["home"].get("ml_open")
        if hp is None or hp_price is None or ap_price is None or hml is None:
            continue
        if abs(float(hp)) != 1.5:
            continue
        fav_home = float(hp) < 0
        fav_price = hp_price if fav_home else ap_price
        dog_price = ap_price if fav_home else hp_price

        ph_c, pa_c = cover_probs(fc)
        p_model = ph_c if fav_home else pa_c
        p_ml_fav = fc["p_home"] if fav_home else 1.0 - fc["p_home"]
        p_mkt_fav, _ = devig_pair(fav_price, dog_price)

        hg, ag = g["home"]["final"], g["away"]["final"]
        if hg is None or ag is None:
            continue
        margin = hg - ag if fav_home else ag - hg
        y = int(margin >= 2)

        rows.append({
            "game_id": gid, "season": season, "fav_home": fav_home,
            "p_model": p_model, "p_ml_fav": p_ml_fav, "p_mkt": p_mkt_fav,
            "fav_price": float(fav_price), "dog_price": float(dog_price),
            "y": y, "margin": int(margin),
        })
    return rows


def main() -> None:
    rows = build()
    print(f"matched games with a -1.5 puck line and both prices: {len(rows)}", flush=True)
    seasons = sorted({r["season"] for r in rows})
    print("by season:", {s: sum(1 for r in rows if r["season"] == s) for s in seasons})

    y = np.array([r["y"] for r in rows], float)
    p_model = np.array([r["p_model"] for r in rows], float)
    p_mkt = np.array([r["p_mkt"] for r in rows], float)

    # --- walk-forward recalibration: isotonic on all prior seasons only ---
    p_cal = np.full(len(rows), np.nan)
    for s in seasons:
        train = [r for r in rows if r["season"] < s]
        if len(train) < 200:
            continue
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        iso.fit([r["p_model"] for r in train], [r["y"] for r in train])
        idx = [i for i, r in enumerate(rows) if r["season"] == s]
        p_cal[idx] = iso.predict([rows[i]["p_model"] for i in idx])
        for i, v in zip(idx, p_cal[idx]):
            rows[i]["p_cal"] = float(v)

    have = ~np.isnan(p_cal)
    print("\nBRIER on games with a prior-season calibration fit (n=%d)" % have.sum())
    const = np.full(len(rows), y[~np.isnan(p_cal)].mean())
    for name, p in (("raw B7", p_model), ("isotonic-recalibrated", p_cal),
                    ("no-vig market", p_mkt), ("constant base rate", const)):
        print(f"  {name:<26}{brier(p[have], y[have]):.4f}")

    # discrimination
    for name, p in (("raw B7", p_model), ("isotonic", p_cal), ("market", p_mkt)):
        print(f"  {name:<26}mean p {p[have].mean():.4f}  observed {y[have].mean():.4f}")

    # --- selective -1.5 trading, threshold tuned on prior seasons only ---
    def simulate(pkey: str, edges: tuple[float, ...], p_label: str) -> None:
        picks = []
        for s in seasons:
            train = [r for r in rows if r["season"] < s and r.get(pkey) is not None
                     and not np.isnan(r[pkey])]
            if len(train) < 200:
                continue
            best, best_units = 0.0, -1e9
            for e in edges:
                u = [((bt.american(r["fav_price"]) if r["y"] else -1.0))
                     for r in train if r[pkey] * dec(r["fav_price"]) - 1.0 >= e]
                if len(u) >= 50 and sum(u) > best_units:
                    best, best_units = e, sum(u)
            if best_units == -1e9:
                best = edges[-1]
            for r in rows:
                if r["season"] != s or np.isnan(r[pkey]):
                    continue
                if r[pkey] * dec(r["fav_price"]) - 1.0 >= best:
                    u = bt.american(r["fav_price"]) if r["y"] else -1.0
                    picks.append({**r, "u": u, "edge_threshold": best})
        if not picks:
            print(f"\n{p_label}: no bets")
            return
        units = sum(p["u"] for p in picks)
        roi = units / len(picks)
        lo, hi = clustered_roi_ci(picks)
        wins = sum(p["y"] for p in picks)
        print(f"\n{p_label}: {len(picks)} bets ({100.0*len(picks)/len(rows):.1f}% of games)  "
              f"{wins}-{len(picks)-wins}  {units:+.2f}u  ROI {100*roi:+.2f}%  "
              f"season-clustered 90% CI [{100*lo:+.1f}%, {100*hi:+.1f}%]")
        for s in seasons:
            sp = [p for p in picks if p["season"] == s]
            if sp:
                su = sum(p["u"] for p in sp)
                print(f"    {s}-{str(s+1)[2:]}: {len(sp):4d} bets  {su:+7.2f}u  {100*su/len(sp):+6.2f}%")

    simulate("p_model", (0.0, 0.02, 0.05, 0.08, 0.12), "SELECTIVE -1.5, raw B7")
    simulate("p_cal", (0.0, 0.02, 0.05, 0.08, 0.12), "SELECTIVE -1.5, isotonic-recalibrated B7")
    simulate("p_mkt", (0.0, 0.02, 0.05, 0.08), "CONTROL: selective -1.5 using the market's own no-vig probability")

    # does the model beat the price at all? fixed edge buckets, no tuning
    print("\nFIXED-EDGE BUCKETS, raw B7 (no threshold tuning)")
    for lo_e, hi_e in ((-1.0, 0.0), (0.0, 0.02), (0.02, 0.05), (0.05, 0.10), (0.10, 9.0)):
        sel = [r for r in rows if lo_e <= r["p_model"] * dec(r["fav_price"]) - 1.0 < hi_e]
        if not sel:
            continue
        u = sum(bt.american(r["fav_price"]) if r["y"] else -1.0 for r in sel)
        print(f"  EV [{lo_e:+.2f},{hi_e:+.2f}): {len(sel):4d} bets  {u:+7.2f}u  {100*u/len(sel):+6.2f}%")


if __name__ == "__main__":
    main()
