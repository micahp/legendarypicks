#!/usr/bin/env python3
"""NHL special-teams experiment — pre-registered 2026-10-19.

Question: do opponent-adjusted, 5v5-separate PP/PK xG/60 rates improve
out-of-sample goal forecasts over the current 5v5-only input?

Baseline: B5 5v5-only Poisson, the frozen production convention.
Candidate: B5 + four score-venue-adjusted PP/PK xG/60 rate features.

Research only. Reads the DuckDB and the read-only audit CSVs. Writes results
next to this script. Touches nothing else.

Run:  python3 run_special_teams.py
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

HERE = Path(__file__).resolve().parent
AUDIT = Path("/root/legendarypicks/research/nhl/kalshi-playoff-audit-2025-26")
CANON = AUDIT / "canonical_games_v1_7cd2fc9a6e84470c.csv"
FEATS = AUDIT / "pregame_rolling_features_v1_62dcceb77085bc59.csv"
DB = "/root/nhl_database_2025-26-playoffs.duckdb"

TRAIN_FROM = 2008
EVAL_SEASONS = list(range(2019, 2026))
ALPHA = 0.01
CAP = 21
N_BOOT = 10_000
SEED = 20261019

# team-log code -> canonical key (same aliasing as the existing feature builder)
ALIAS = {"PHX": "ARI", "TBL": "T.B", "NJD": "N.J", "LAK": "L.A", "SJS": "S.J"}


def lograte(v) -> float:
    return math.log(max(float(v), 0.05))


def pmf(mu: float, cap: int = CAP) -> np.ndarray:
    mu = max(float(mu), 1e-9)
    ks = np.arange(cap)
    logp = -mu + ks * math.log(mu) - np.array([math.lgamma(k + 1) for k in ks])
    p = np.exp(logp)
    return p / p.sum()


def home_win_prob(mu_h: float, mu_a: float, so_home: float) -> float:
    m = np.outer(pmf(mu_h), pmf(mu_a))
    i, j = np.indices(m.shape)
    reg = float(m[i > j].sum())
    tie = float(np.trace(m))
    return reg + tie * so_home


def crps(p: np.ndarray, y: int) -> float:
    """Discrete CRPS / ranked probability score for a PMF on 0..K."""
    F = np.cumsum(p)
    ks = np.arange(len(p))
    return float(np.sum((F - (ks >= y).astype(float)) ** 2))


def load_games() -> list[dict]:
    canon = list(csv.DictReader(open(CANON)))
    feats = {int(r["game_id"]): r for r in csv.DictReader(open(FEATS))}
    games = []
    for c in canon:
        gid = int(c["game_id"])
        x = feats[gid]
        if x["required_features_complete"].lower() != "true":
            continue
        games.append({
            "game_id": gid, "season": int(c["season"]), "game_date": c["game_date"],
            "period": c["last_period_type"],
            "home_team": c["home_team"], "away_team": c["away_team"],
            "home_win": int(c["official_home_winner"]),
            "hg": int(c["home_goals_model_target"]), "ag": int(c["away_goals_model_target"]),
            "hx": x["home_rolling10_5v5_score_venue_xgf"], "hxga": x["home_rolling10_5v5_score_venue_xga"],
            "ax": x["away_rolling10_5v5_score_venue_xgf"], "axga": x["away_rolling10_5v5_score_venue_xga"],
        })
    games.sort(key=lambda r: (r["game_date"], r["game_id"]))
    return games


def build_st_features(games: list[dict]) -> dict:
    """Strictly-before-game rolling PP/PK xG/60 per team-game, keyed by (game_id, HOME/AWAY)."""
    con = duckdb.connect(DB, read_only=True)
    rows = con.execute("""
        SELECT gameId, gameDate, team, home_or_away, situation, iceTime,
               scoreVenueAdjustedxGoalsFor AS xgf, scoreVenueAdjustedxGoalsAgainst AS xga
        FROM teams_gamelogs
        WHERE situation IN ('5on4','4on5')
        ORDER BY gameDate, gameId, team
    """).fetchall()
    con.close()

    # game_id -> ISO date for EVERY canonical game (including games whose 5v5
    # features are incomplete, because those still sit in the rolling history).
    gdate = {int(c["game_id"]): c["game_date"] for c in csv.DictReader(open(CANON))}

    # pivot to one record per team-game
    per = defaultdict(dict)
    for gid, _gdate, team, ha, sit, ice, xgf, xga in rows:
        key = (int(gid), ALIAS.get(str(team), str(team)))
        d = per[key]
        d["date"] = str(gdate.get(int(gid), _gdate))
        d["ha"] = ha
        if sit == "5on4":
            d["xgf_pp"] = float(xgf); d["ice_pp"] = float(ice)
        else:
            d["xga_pk"] = float(xga); d["ice_pk"] = float(ice)

    # process team-games in date order; rolling window over prior games only
    order = sorted(per.items(), key=lambda kv: (kv[1]["date"], kv[0][0], kv[0][1]))
    history = defaultdict(list)   # team -> list of records
    out = {}
    for (gid, team), d in order:
        day = d["date"]
        prior = [x for x in history[team] if x["date"] < day][-10:]
        if len(prior) >= 5:
            ice_pp = sum(x["ice_pp"] for x in prior)
            ice_pk = sum(x["ice_pk"] for x in prior)
            pp_off = 60.0 * sum(x["xgf_pp"] for x in prior) / ice_pp if ice_pp > 0 else None
            pk_def = 60.0 * sum(x["xga_pk"] for x in prior) / ice_pk if ice_pk > 0 else None
        else:
            pp_off = pk_def = None
        out[(gid, d["ha"])] = (pp_off, pk_def)
        history[team].append(d)
    return out


def fit_arm(train: list[dict], model: str):
    X, y = [], []
    for r in train:
        hx, hxga = lograte(r["hx"]), lograte(r["hxga"])
        ax, axga = lograte(r["ax"]), lograte(r["axga"])
        if model == "b5":
            X.extend([[1.0, hx, axga], [0.0, ax, hxga]])
        elif model == "st":
            X.extend([[1.0, hx, axga, lograte(r["hpp"]), lograte(r["apk"])],
                      [0.0, ax, hxga, lograte(r["app"]), lograte(r["hpk"])]])
        else:
            raise ValueError(model)
        y.extend([r["hg"], r["ag"]])
    fitted = PoissonRegressor(alpha=ALPHA, max_iter=500, tol=1e-9).fit(np.asarray(X, float), np.asarray(y, float))
    return {"intercept": float(fitted.intercept_), "coef": [float(b) for b in fitted.coef_]}


def predict_arm(games: list[dict], model: str, params: dict):
    intercept = float(params["intercept"])
    beta = np.asarray(params["coef"], float)
    out = {}
    for r in games:
        hx, hxga = lograte(r["hx"]), lograte(r["hxga"])
        ax, axga = lograte(r["ax"]), lograte(r["axga"])
        if model == "b5":
            xh, xa = [1.0, hx, axga], [0.0, ax, hxga]
        else:
            xh = [1.0, hx, axga, lograte(r["hpp"]), lograte(r["apk"])]
            xa = [0.0, ax, hxga, lograte(r["app"]), lograte(r["hpk"])]
        out[r["game_id"]] = (math.exp(intercept + float(np.dot(xh, beta))),
                             math.exp(intercept + float(np.dot(xa, beta))))
    return out


def main() -> None:
    games = load_games()
    st = build_st_features(games)

    # merge ST features; keep only games with complete ST features in BOTH arms
    merged = []
    dropped = 0
    for g in games:
        h = st.get((g["game_id"], "HOME")); a = st.get((g["game_id"], "AWAY"))
        if not h or not a or None in h or None in a:
            dropped += 1
            continue
        g = {**g, "hpp": h[0], "hpk": h[1], "app": a[0], "apk": a[1]}
        merged.append(g)
    print(f"games loaded={len(games)} merged={len(merged)} dropped_no_st={dropped}", flush=True)

    # write the merged feature artifact
    art = HERE / "special_teams_merged_features.csv"
    cols = ["game_id", "season", "game_date", "home_team", "away_team", "home_win",
            "hg", "ag", "hx", "hxga", "ax", "axga", "hpp", "hpk", "app", "apk"]
    with art.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for g in merged:
            w.writerow({k: g[k] for k in cols})

    # walk-forward per evaluation season
    per_season = {}
    arms = ("b5", "st")
    for season in EVAL_SEASONS:
        evalg = [g for g in merged if g["season"] == season]
        train = [g for g in merged if TRAIN_FROM <= g["season"] < season]
        so_home = (sum(g["home_win"] for g in train if g.get("period") == "SO") /
                   max(1, sum(1 for g in train if g.get("period") == "SO")))
        params = {m: fit_arm(train, m) for m in arms}
        mus = {m: predict_arm(evalg, m, params[m]) for m in arms}
        per_season[season] = {"n": len(evalg), "train_n": len(train),
                              "params": params,
                              "games": [g["game_id"] for g in evalg]}
        print(f"  season {season}: n={len(evalg)} train={len(train)} "
              f"b5_coef={[round(c,4) for c in params['b5']['coef']]} "
              f"st_coef={[round(c,4) for c in params['st']['coef']]}", flush=True)

        # score each arm on this season's identical games
        for m in arms:
            rows = []
            for g in evalg:
                mh, ma = mus[m][g["game_id"]]
                p = home_win_prob(mh, ma, so_home)
                p = min(max(p, 1e-6), 1 - 1e-6)
                brier = (p - g["home_win"]) ** 2
                ll = -(g["home_win"] * math.log(p) + (1 - g["home_win"]) * math.log(1 - p))
                c_h = crps(pmf(mh), g["hg"]); c_a = crps(pmf(ma), g["ag"])
                rows.append({"game_id": g["game_id"], "season": season, "game_date": g["game_date"],
                             "brier": brier, "log_loss": ll,
                             "crps": (c_h + c_a) / 2.0,
                             "mae": (abs(mh - g["hg"]) + abs(ma - g["ag"])) / 2.0,
                             "p_home": p, "mu_h": mh, "mu_a": ma,
                             "hg": g["hg"], "ag": g["ag"], "y": g["home_win"]})
            per_season[season][m] = rows

    # --- Step A: emit per-game forecasts for auditability (no refit needed) ---
    # Columns: game_id, season, game_date, home_win, p_b5, p_st, plus the Poisson
    # goal means for each arm (mu_h_*, mu_a_*) which CRPS needs, and the observed
    # goal targets (home_goals, away_goals) which CRPS also needs. No feature or
    # future-information column is included; the outcome columns are the scored
    # ground truth, present by design.
    fc_rows = []
    for season in EVAL_SEASONS:
        b5_rows = {r["game_id"]: r for r in per_season[season]["b5"]}
        st_rows = {r["game_id"]: r for r in per_season[season]["st"]}
        for gid in sorted(b5_rows):
            r5, rs = b5_rows[gid], st_rows[gid]
            fc_rows.append({
                "game_id": gid, "season": season, "game_date": r5["game_date"],
                "home_win": r5["y"], "p_b5": r5["p_home"], "p_st": rs["p_home"],
                "mu_h_b5": r5["mu_h"], "mu_a_b5": r5["mu_a"],
                "mu_h_st": rs["mu_h"], "mu_a_st": rs["mu_a"],
                "home_goals": r5["hg"], "away_goals": r5["ag"],
            })
    fc_rows.sort(key=lambda r: (r["season"], r["game_date"], r["game_id"]))
    fc_path = HERE / "forecasts_st.csv"
    with fc_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["game_id", "season", "game_date", "home_win",
                                          "p_b5", "p_st", "mu_h_b5", "mu_a_b5",
                                          "mu_h_st", "mu_a_st", "home_goals", "away_goals"])
        w.writeheader(); w.writerows(fc_rows)
    print(f"wrote {fc_path} ({len(fc_rows)} rows)", flush=True)

    # aggregate deltas over the full evaluation window, clustered by game
    def collect(m):
        d = {}
        for season in EVAL_SEASONS:
            for r in per_season[season][m]:
                d[r["game_id"]] = r
        return d

    b5 = collect("b5"); stt = collect("st")
    ids = sorted(set(b5) & set(stt))
    print(f"matched evaluation games: {len(ids)}", flush=True)

    def mean(xs):
        xs = np.asarray(xs, dtype=float)
        return float(xs.mean()) if xs.size else float("nan")

    metrics = {}
    for key in ("brier", "log_loss", "crps", "mae"):
        a = np.array([b5[i][key] for i in ids])
        b = np.array([stt[i][key] for i in ids])
        delta = a - b  # positive = candidate better (lower loss)
        rng = np.random.default_rng(SEED)
        boots = np.empty(N_BOOT)
        n = len(delta)
        for it in range(N_BOOT):
            idx = rng.integers(0, n, n)
            boots[it] = delta[idx].mean()
        metrics[key] = {
            "b5": mean(a), "st": mean(b), "delta_b5_minus_st": mean(delta),
            "ci95_low": float(np.quantile(boots, 0.025)),
            "ci95_high": float(np.quantile(boots, 0.975)),
            "n": n,
        }

    # per-season delta summary
    season_deltas = {}
    for season in EVAL_SEASONS:
        m = per_season[season]
        ss = {}
        for key in ("brier", "log_loss", "crps"):
            a = np.array([r[key] for r in m["b5"]])
            b = np.array([r[key] for r in m["st"]])
            ss[key] = {"b5": mean(a), "st": mean(b), "delta": mean(a - b)}
        season_deltas[season] = ss

    # sign / stability of the ST coefficients across refits
    st_coefs = {s: per_season[s]["params"]["st"]["coef"] for s in EVAL_SEASONS}
    b5_coefs = {s: per_season[s]["params"]["b5"]["coef"] for s in EVAL_SEASONS}

    result = {
        "registered": "research/nhl/special-teams-preregistration-2026-10-19.md",
        "population": {"total_merged": len(merged), "dropped_no_st": dropped,
                       "eval_games": len(ids),
                       "by_season": {s: per_season[s]["n"] for s in EVAL_SEASONS}},
        "metrics": metrics,
        "per_season": season_deltas,
        "st_coef_by_season": st_coefs,
        "b5_coef_by_season": b5_coefs,
    }
    out = HERE / "results_special_teams.json"
    out.write_text(json.dumps(result, indent=1))
    print(json.dumps({k: metrics[k] for k in metrics}, indent=1))
    print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
