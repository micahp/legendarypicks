#!/usr/bin/env python3
"""Corrected historical profitability of the NHL pick hierarchy, with matchup regimes.

Revision 2 of the Phase 1-3 brief. The v1 harness (commit f3d53766) is kept in git history and
its numbers are retained in RESULTS.md as a superseded diagnostic. This revision fixes:

1. Look-ahead in the score model. v1 applied the 2026-fitted B7 v1 coefficients to 2018-19
   games. Every evaluation season here is forecast by coefficients refit on seasons strictly
   before it, using the same architecture (independent Poisson on team goals, ridge alpha 0.01,
   features: home indicator, log rolling-10 5v5 score-venue xGF/xGA, pregame Elo difference) and
   the same walk-forward Elo replay. The shootout tie rate is refit per fold too.
2. Standings never resetting. Standings state resets at every season boundary, so regime labels
   describe each team's actual season-to-date record. v1 also scored shootout games off the tied
   model target, which awarded the win to the wrong side.
3. Settlement on the wrong score. Moneyline settles from `official_home_winner`; puck line and
   totals settle from `*_goals_model_target`, the score at the end of overtime, excluding the
   shootout-deciding goal. Verified on the data: every non-shootout target equals the official
   score, and every shootout target is tied while the official score carries the extra goal.
4. The fake closing puck-line price. The archive carries a single `puck_price`; v1 copied it into
   both open and close. Closing sensitivity is reported only where a genuinely distinct closing
   quote exists (moneyline), and the puck line is marked not-available.
5. Side-specific total prices. v1 always used the home side's over/under quote; the selected
   side's own quote is used now.
6. Silent row loss. Every SBR row is accounted for exactly once in a reconciliation chain.

Pick rule (unchanged from v1, an exact replay of the production `model_pick()`):
  1. Vegas underdog (+1.5) with S = |puck| - favourite_margin > 1.0 -> that side +1.5
  2. else the Vegas favourite ML when the model's favourite is the same team
  3. else a total: 5.5 when the projection is <= 6.0, 6.5 above; Over if projection > line

Market: SBR archive, 2018-19 -> 2022-23. Opening prices are primary. The archive has no intraday
timestamp, so nothing here claims an executable fill.
"""
from __future__ import annotations

import csv
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import PoissonRegressor

HERE = Path(__file__).resolve().parent
AUDIT = Path("/root/legendarypicks/research/nhl/kalshi-playoff-audit-2025-26")
CANONICAL = AUDIT / "canonical_games_v1_7cd2fc9a6e84470c.csv"
FEATURES = AUDIT / "pregame_rolling_features_v1_62dcceb77085bc59.csv"
SBR = Path("/root/lp-data/nhl-sbr/games_2018_2023.jsonl")
FROZEN = HERE.parents[0] / "prospective-2026-27" / "frozen_models_2026-27_v1.json"
RESULTS_JSON = HERE / "results_corrected.json"

ALPHA = 0.01
EVAL_SEASONS = (2018, 2019, 2020, 2021, 2022)
THRESHOLD_SEASON = 2017          # strength cuts frozen on 2008-09..2017-18
MIN_GP = 10

TEAM_ID = {"PHX": "ARI", "T.B": "TBL", "TB": "TBL", "N.J": "NJD", "L.A": "LAK", "LA": "LAK",
           "S.J": "SJS", "ATL": "WPG"}
NAME = {"anaheim":"ANA","arizona":"ARI","boston":"BOS","buffalo":"BUF","calgary":"CGY","carolina":"CAR",
        "chicago":"CHI","colorado":"COL","columbus":"CBJ","dallas":"DAL","detroit":"DET","edmonton":"EDM",
        "florida":"FLA","losangeles":"LAK","minnesota":"MIN","montreal":"MTL","nashville":"NSH",
        "newjersey":"NJD","nyislanders":"NYI","nyrangers":"NYR","ottawa":"OTT","philadelphia":"PHI",
        "pittsburgh":"PIT","sanjose":"SJS","seattlekraken":"SEA","stlouis":"STL","tampabay":"TBL",
        "toronto":"TOR","utah":"UTA","utahhockeyclub":"UTA","vancouver":"VAN","vegas":"VGK",
        "washington":"WSH","winnipeg":"WPG","seattle":"SEA","arizonas":"ARI"}

CAP = 15
VALS = np.arange(CAP + 1)
LOGF = np.array([math.lgamma(int(v) + 1) for v in VALS])


def tri(name: str) -> str | None:
    return NAME.get(re.sub(r"[^a-z]", "", str(name).lower()))


def pmf(mu: float) -> np.ndarray:
    mu = max(1e-9, float(mu))
    p = np.exp(VALS * math.log(mu) - mu - LOGF)
    return p / p.sum()


def p_win(mh: float, ma: float, tie_home: float) -> float:
    j = np.outer(pmf(mh), pmf(ma))
    return float(np.tril(j, -1).sum() + np.trace(j) * tie_home)


def american(price: float) -> float:
    """Profit per 1 unit staked."""
    return price / 100.0 if price > 0 else 100.0 / abs(price)


def load_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------------

def elo_replay(canon: list[dict], k: float = 10.0, hfa: float = 35.0) -> dict[int, dict]:
    """Walk-forward Elo. Each game only ever sees ratings from games already played."""
    ratings = defaultdict(lambda: 1500.0)
    out = {}
    by_day = defaultdict(list)
    for row in canon:
        by_day[row["game_date"]].append(row)
    for day in sorted(by_day):
        updates = []
        for row in sorted(by_day[day], key=lambda x: (x["start_time_utc"], int(x["game_id"]))):
            h = TEAM_ID.get(row["home_team"], row["home_team"])
            a = TEAM_ID.get(row["away_team"], row["away_team"])
            venue = 0.0 if str(row["neutral_site"]).lower() == "true" else hfa
            rh, ra = ratings[h], ratings[a]
            p = 1.0 / (1.0 + 10.0 ** (-((rh - ra + venue) / 400.0)))
            out[int(row["game_id"])] = {"diff": (rh - ra) / 400.0, "venue": float(venue > 0)}
            updates.append((h, a, int(row["official_home_winner"]) - p))
        for h, a, resid in updates:
            ratings[h] += k * resid
            ratings[a] -= k * resid
    return out


def load_games(canon: list[dict], features: dict[int, dict]) -> list[dict]:
    """Feature-complete games, typed and sorted chronologically."""
    games = []
    for c in canon:
        gid = int(c["game_id"])
        f = features.get(gid)
        if f is None or str(f.get("required_features_complete", "")).lower() != "true":
            continue
        games.append({
            "game_id": gid,
            "season": int(c["season"]),
            "game_date": c["game_date"],
            "start_time_utc": c["start_time_utc"],
            "home_team": TEAM_ID.get(c["home_team"], c["home_team"]),
            "away_team": TEAM_ID.get(c["away_team"], c["away_team"]),
            "home_goals": int(c["home_goals_model_target"]),
            "away_goals": int(c["away_goals_model_target"]),
            "official_home_winner": int(c["official_home_winner"]),
            "last_period_type": c["last_period_type"].upper(),
            "neutral_site": c["neutral_site"],
            "xgf_h": float(f["home_rolling10_5v5_score_venue_xgf"]),
            "xga_h": float(f["home_rolling10_5v5_score_venue_xga"]),
            "xgf_a": float(f["away_rolling10_5v5_score_venue_xgf"]),
            "xga_a": float(f["away_rolling10_5v5_score_venue_xga"]),
            "gf10_h": float(f["home_rolling10_goals_for"]),
            "ga10_h": float(f["home_rolling10_goals_against"]),
            "gf10_a": float(f["away_rolling10_goals_for"]),
            "ga10_a": float(f["away_rolling10_goals_against"]),
        })
    games.sort(key=lambda r: (r["game_date"], r["start_time_utc"], r["game_id"]))
    return games


def standings_before(games: list[dict]) -> dict[int, dict]:
    """Season-to-date standings immediately before each game. Resets at every season boundary."""
    out = {}
    season = None
    state = None

    def fresh():
        return {"pts": defaultdict(int), "gp": defaultdict(int),
                "gf": defaultdict(int), "ga": defaultdict(int)}

    ordered = sorted(games, key=lambda r: (r["season"], r["game_date"], r["start_time_utc"], r["game_id"]))
    for row in ordered:
        if row["season"] != season:
            season = row["season"]
            state = fresh()
        pts, gp, gf, ga = state["pts"], state["gp"], state["gf"], state["ga"]
        h, a = row["home_team"], row["away_team"]

        def block(t):
            played = gp[t]
            return {
                "gp": played,
                "pts": pts[t],
                "pct": pts[t] / (2 * played) if played else float("nan"),
                "gf": gf[t],
                "ga": ga[t],
                "gd": (gf[t] - ga[t]) / played if played else float("nan"),
            }

        out[row["game_id"]] = {"home": block(h), "away": block(a), "season": season}

        # 2 for a win, 1 for an overtime or shootout loss.
        hw = row["official_home_winner"] == 1
        pts[h] += 2 if hw else 0
        pts[a] += 2 if not hw else 0
        if row["last_period_type"] in ("OT", "SO"):
            pts[a if hw else h] += 1
        # GF/GA exclude the shootout-deciding goal, matching league standings.
        gp[h] += 1
        gp[a] += 1
        gf[h] += row["home_goals"]
        ga[h] += row["away_goals"]
        gf[a] += row["away_goals"]
        ga[a] += row["home_goals"]
    return out


# --------------------------------------------------------------------------------------------
# Model: refit per evaluation season on prior seasons, then forecast the held-out season
# --------------------------------------------------------------------------------------------

def design(rows: list[dict], elo: dict[int, dict]) -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for r in rows:
        d = elo[r["game_id"]]["diff"]
        hx, ad = math.log(max(r["xgf_h"], .05)), math.log(max(r["xga_a"], .05))
        ax, hd = math.log(max(r["xgf_a"], .05)), math.log(max(r["xga_h"], .05))
        X.extend([[1.0, hx, ad, d], [0.0, ax, hd, -d]])
        y.extend([r["home_goals"], r["away_goals"]])
    return np.asarray(X, dtype=float), np.asarray(y, dtype=float)


def fit_fold(train: list[dict], elo: dict[int, dict]) -> dict:
    if not train:
        raise RuntimeError("empty training fold")
    X, y = design(train, elo)
    fitted = PoissonRegressor(alpha=ALPHA, max_iter=500, tol=1e-9).fit(X, y)
    ties = [r for r in train if r["home_goals"] == r["away_goals"]]
    if not ties:
        raise RuntimeError("no shootout ties in training fold")
    return {"intercept": float(fitted.intercept_), "coef": [float(v) for v in fitted.coef_],
            "tie_home": sum(r["official_home_winner"] for r in ties) / len(ties),
            "n_games": len(train), "n_team_rows": int(len(y)),
            "train_seasons": [min(r["season"] for r in train), max(r["season"] for r in train)]}


def forecast(fold: dict, elo: dict[int, dict], game: dict) -> dict:
    c = fold["coef"]
    e = elo[game["game_id"]]
    base = fold["intercept"]
    mh = math.exp(base + c[0] * e["venue"] + c[1] * math.log(max(game["xgf_h"], .05))
                  + c[2] * math.log(max(game["xga_a"], .05)) + c[3] * e["diff"])
    ma = math.exp(base + c[1] * math.log(max(game["xgf_a"], .05))
                  + c[2] * math.log(max(game["xga_h"], .05)) + c[3] * -e["diff"])
    return {"mu_h": mh, "mu_a": ma, "margin": mh - ma, "total": mh + ma,
            "p_home": p_win(mh, ma, fold["tie_home"])}


# --------------------------------------------------------------------------------------------
# Regime classification
# --------------------------------------------------------------------------------------------

def terciles(values: list[float]) -> dict:
    arr = np.asarray([v for v in values if not math.isnan(v)], dtype=float)
    return {"lo": float(np.quantile(arr, 1 / 3)), "hi": float(np.quantile(arr, 2 / 3))}


def build_thresholds(games: list[dict], standings: dict[int, dict]) -> dict:
    """Strength cuts frozen on seasons <= THRESHOLD_SEASON only: no evaluation-season information."""
    hist = [g for g in games if g["season"] <= THRESHOLD_SEASON]
    pct, gd, xgd = [], [], []
    for g in hist:
        for side in ("home", "away"):
            b = standings[g["game_id"]][side]
            if b["gp"] < MIN_GP:
                continue
            pct.append(b["pct"])
            gd.append(b["gd"])
            xgd.append((g["xgf_h"] - g["xga_h"]) if side == "home" else (g["xgf_a"] - g["xga_a"]))

    def moments(v):
        a = np.asarray(v, dtype=float)
        return float(a.mean()), float(a.std())

    m_pct, s_pct = moments(pct)
    m_gd, s_gd = moments(gd)
    m_xg, s_xg = moments(xgd)

    def z(p, g, x=None):
        if x is None:
            return ((p - m_pct) / s_pct + (g - m_gd) / s_gd) / 2.0
        return ((p - m_pct) / s_pct + (g - m_gd) / s_gd + (x - m_xg) / s_xg) / 3.0

    goals_vals, xg_vals = [], []
    for g in hist:
        for side in ("home", "away"):
            b = standings[g["game_id"]][side]
            if b["gp"] < MIN_GP:
                continue
            x = (g["xgf_h"] - g["xga_h"]) if side == "home" else (g["xgf_a"] - g["xga_a"])
            goals_vals.append(z(b["pct"], b["gd"]))
            xg_vals.append(z(b["pct"], b["gd"], x))

    return {
        # v1's fixed league terciles of points percentage, kept for comparability of the rerun.
        "points": {"lo": 0.536, "hi": 0.579},
        "goals": terciles(goals_vals),
        "goals_xg": terciles(xg_vals),
        "moments": {"pct": [m_pct, s_pct], "gd": [m_gd, s_gd], "xgd": [m_xg, s_xg]},
        "frozen_on": f"seasons <= {THRESHOLD_SEASON}",
    }


def strength(value: float, cuts: dict) -> str:
    if value is None or math.isnan(value):
        return "early"
    if value >= cuts["hi"]:
        return "strong"
    if value <= cuts["lo"]:
        return "weak"
    return "mid"


def pair(h: str, a: str) -> str:
    if "early" in (h, a):
        return "early"
    if h == a:
        return {"strong": "strong-strong", "weak": "weak-weak", "mid": "mid-mid"}[h]
    return "mixed"


def regimes(game: dict, st: dict, thresholds: dict) -> dict:
    m = thresholds["moments"]
    hb, ab = st["home"], st["away"]
    if hb["gp"] < MIN_GP or ab["gp"] < MIN_GP:
        return {"points": "early", "goals": "early", "goals_xg": "early"}
    z_g = lambda b: ((b["pct"] - m["pct"][0]) / m["pct"][1] + (b["gd"] - m["gd"][0]) / m["gd"][1]) / 2.0
    z_x = lambda b, x: ((b["pct"] - m["pct"][0]) / m["pct"][1] + (b["gd"] - m["gd"][0]) / m["gd"][1]
                        + (x - m["xgd"][0]) / m["xgd"][1]) / 3.0
    xh, xa = game["xgf_h"] - game["xga_h"], game["xgf_a"] - game["xga_a"]
    return {
        "points": pair(strength(hb["pct"], thresholds["points"]), strength(ab["pct"], thresholds["points"])),
        "goals": pair(strength(z_g(hb), thresholds["goals"]), strength(z_g(ab), thresholds["goals"])),
        "goals_xg": pair(strength(z_x(hb, xh), thresholds["goals_xg"]),
                         strength(z_x(ab, xa), thresholds["goals_xg"])),
    }


# --------------------------------------------------------------------------------------------
# Pick rule and settlement
# --------------------------------------------------------------------------------------------

def pick(fc: dict, game: dict) -> tuple[dict | None, str]:
    """Exact replay of the production cascade. Returns (pick, reason_when_none)."""
    puck = game.get("home_puck_line")
    if puck is None:
        return None, "no_puck_line"
    puck = float(puck)
    if abs(puck) != 1.5:
        return None, "puck_line_not_1.5"
    favourite = "home" if puck < 0 else "away"
    underdog = "away" if favourite == "home" else "home"
    fav_margin = fc["margin"] if favourite == "home" else -fc["margin"]
    s = abs(puck) - fav_margin
    game["s"] = round(s, 2)
    if round(s + 0.0, 1) > 1.0:
        price = game[f"{underdog}_puck_open"]
        if price is None:
            return None, "no_puck_price"
        return {"market": "spread", "side": underdog, "line": 1.5, "price_open": price,
                "price_close": None}, ""
    model_fav = "home" if fc["p_home"] >= 0.5 else "away"
    if model_fav == favourite:
        price = game[f"{favourite}_ml_open"]
        if price is None:
            return None, "no_ml_price"
        return {"market": "ml", "side": favourite, "line": None, "price_open": price,
                "price_close": game[f"{favourite}_ml_close"]}, ""
    line = 5.5 if fc["total"] <= 6.0 else 6.5
    side = "over" if fc["total"] > line else "under"
    price = game[f"{side}_ou_open"]
    if price is None:
        return None, "no_total_price"
    return {"market": "total", "side": side, "line": line, "price_open": price,
            "price_close": game[f"{side}_ou_close"]}, ""


def settled(pk: dict, *, home_goals: int, away_goals: int, official_home_winner: int) -> str:
    """Book settlement. ML includes overtime and the shootout; spread and totals end at OT."""
    m, side, line = pk["market"], pk["side"], pk["line"]
    if m == "ml":
        win = (official_home_winner == 1) if side == "home" else (official_home_winner == 0)
        return "win" if win else "loss"
    if m == "spread":
        mine, opp = (home_goals, away_goals) if side == "home" else (away_goals, home_goals)
        margin = mine + line - opp
        return "win" if margin > 1e-9 else ("push" if abs(margin) < 1e-9 else "loss")
    total = home_goals + away_goals
    if abs(total - line) < 1e-9:
        return "push"
    return "win" if ((total > line) == (side == "over")) else "loss"


def settled_legacy(pk: dict, home_goals: int, away_goals: int) -> str:
    """v1 settlement, kept only to attribute its error: ML graded off the shootout-excluded target."""
    m, side, line = pk["market"], pk["side"], pk["line"]
    if m == "ml":
        win = (home_goals > away_goals) if side == "home" else (away_goals > home_goals)
        return "win" if win else "loss"
    if m == "spread":
        mine, opp = (home_goals, away_goals) if side == "home" else (away_goals, home_goals)
        margin = mine + line - opp
        return "win" if margin > 1e-9 else ("push" if abs(margin) < 1e-9 else "loss")
    total = home_goals + away_goals
    if abs(total - line) < 1e-9:
        return "push"
    return "win" if ((total > line) == (side == "over")) else "loss"


# --------------------------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------------------------

def main() -> None:
    args = set(sys.argv[1:])
    model_mode = "frozen" if "--frozen" in args else "walkforward"
    settle_mode = "legacy" if "--legacy-settlement" in args else "book"
    label = f"{model_mode}/{settle_mode}"

    canon = load_csv(CANONICAL)
    features = {int(r["game_id"]): r for r in load_csv(FEATURES)}
    games = load_games(canon, features)
    elo = elo_replay(canon)
    standings = standings_before(games)
    thresholds = build_thresholds(games, standings)

    folds, forecasts = {}, {}
    if model_mode == "frozen":
        frozen = json.loads(FROZEN.read_text())
        p = frozen["poisson_models"]["elo_xg"]
        fold = {"intercept": p["intercept"], "coef": p["coef"],
                "tie_home": frozen["historical_home_shootout_win_rate"],
                "n_games": frozen["fit_rows"]["feature_complete_games"],
                "n_team_rows": p["n_team_rows"],
                "train_seasons": [2008, 2025]}
        folds["all"] = fold
        forecasts = {g["game_id"]: forecast(fold, elo, g) for g in games}
        print(f"frozen model: fit through 2025-26, applied to all {len(games)} games")
    else:
        for season in EVAL_SEASONS:
            train = [g for g in games if g["season"] <= season - 1]
            fold = fit_fold(train, elo)
            folds[season] = fold
            held_out = [g for g in games if g["season"] == season]
            forecasts.update({g["game_id"]: forecast(fold, elo, g) for g in held_out})
            print(f"fold {season}-{str(season + 1)[2:]}: train {fold['train_seasons'][0]}-"
                  f"{fold['train_seasons'][1]} n={fold['n_games']} "
                  f"intercept={fold['intercept']:.4f} coef={[round(c, 4) for c in fold['coef']]} "
                  f"tie_home={fold['tie_home']:.4f} -> held-out {len(held_out)}")

    by_key = {}
    for c in canon:
        gid = int(c["game_id"])
        f = features.get(gid)
        md = int(c["game_date"][5:7]) * 100 + int(c["game_date"][8:10])
        by_key[(int(c["season"]), md, TEAM_ID.get(c["home_team"], c["home_team"]),
                TEAM_ID.get(c["away_team"], c["away_team"]))] = {
            "game_id": gid,
            "complete": f is not None and str(f.get("required_features_complete", "")).lower() == "true",
        }
    game_by_id = {g["game_id"]: g for g in games}

    recon = defaultdict(int)
    rule = defaultdict(int)
    rows = []
    sbr = [json.loads(line) for line in SBR.open()]
    recon["sbr_rows"] = len(sbr)

    for g in sbr:
        h, a = tri(g["home"]["team"]), tri(g["away"]["team"])
        if not (h and a):
            recon["team_unmapped"] += 1
            continue
        season = int(g["season"][:4])
        hit = by_key.get((season, int(g["date"]), h, a))
        if hit is None:
            if (season, int(g["date"]), a, h) in by_key:
                recon["orientation_mismatch"] += 1
            else:
                recon["no_canonical_match"] += 1
            continue
        gid = hit["game_id"]
        rec = game_by_id.get(gid)
        if rec is None or not hit["complete"]:
            recon["no_features"] += 1
            continue
        fc = forecasts.get(gid)
        if fc is None:
            recon["no_walkforward_forecast"] += 1
            continue
        game = {
            "home": h, "away": a,
            "home_puck_line": g["home"].get("puck_line"),
            "home_ml_open": g["home"].get("ml_open"), "home_ml_close": g["home"].get("ml_close"),
            "away_ml_open": g["away"].get("ml_open"), "away_ml_close": g["away"].get("ml_close"),
            "home_puck_open": g["home"].get("puck_price"), "away_puck_open": g["away"].get("puck_price"),
            "over_ou_open": g["home"].get("ou_open_price"), "under_ou_open": g["away"].get("ou_open_price"),
            "over_ou_close": g["home"].get("ou_close_price"), "under_ou_close": g["away"].get("ou_close_price"),
        }
        puck = game["home_puck_line"]
        if puck is not None and abs(float(puck)) == 1.5:
            fav = "home" if float(puck) < 0 else "away"
            fav_margin = fc["margin"] if fav == "home" else -fc["margin"]
            s = abs(float(puck)) - fav_margin
            model_fav = "home" if fc["p_home"] >= 0.5 else "away"
            if round(s + 0.0, 1) > 1.0:
                rule["spread_branch"] += 1
            elif model_fav == fav:
                rule["ml_branch"] += 1
            else:
                rule["total_branch"] += 1

        pk, reason = pick(fc, game)
        if pk is None:
            recon[f"no_pick:{reason}"] += 1
            continue
        res = (settled(pk, home_goals=rec["home_goals"], away_goals=rec["away_goals"],
                       official_home_winner=rec["official_home_winner"])
               if settle_mode == "book"
               else settled_legacy(pk, rec["home_goals"], rec["away_goals"]))
        r = dict(season=season, game_id=gid, home_team=h, away_team=a, **pk, result=res,
                 home_goals=rec["home_goals"], away_goals=rec["away_goals"], s=game.get("s"))
        r.update({f"regime_{k}": v for k, v in regimes(rec, standings[gid], thresholds).items()})
        r["regime"] = r["regime_points"]
        rows.append(r)

    recon["graded"] = len(rows)
    print("\nRECONCILIATION")
    keys = ("sbr_rows", "team_unmapped", "no_canonical_match", "orientation_mismatch", "no_features",
            "no_walkforward_forecast", "no_pick:no_puck_line", "no_pick:puck_line_not_1.5",
            "no_pick:no_puck_price", "no_pick:no_ml_price", "no_pick:no_total_price", "graded")
    for k in keys:
        print(f"  {k:<28}{recon[k]:>6}")
    accounted = (recon["team_unmapped"] + recon["no_canonical_match"] + recon["orientation_mismatch"]
                 + recon["no_features"] + recon["no_walkforward_forecast"]
                 + sum(v for k, v in recon.items() if k.startswith("no_pick:")) + recon["graded"])
    print(f"  {'sum':<28}{accounted:>6}  (must equal {recon['sbr_rows']})")
    assert accounted == recon["sbr_rows"], "reconciliation failed"

    print("\nRULE BRANCHES (matched, |puck| = 1.5)")
    for k in ("spread_branch", "ml_branch", "total_branch"):
        print(f"  {k:<20}{rule[k]:>6}")

    fits = {str(s): dict(f) for s, f in folds.items()}

    def report(key_fn, title, price="price_open"):
        print("\n" + title + f"  (prices: {price})")
        print(f"{'group':<28}{'n':>6}{'W':>6}{'L':>6}{'P':>4}{'units':>10}{'ROI':>8}")
        groups = defaultdict(list)
        for r in rows:
            if r[price] is None:
                continue
            groups[key_fn(r)].append(r)
        out = {}
        for k in sorted(groups):
            rs = groups[k]
            w = sum(1 for r in rs if r["result"] == "win")
            l = sum(1 for r in rs if r["result"] == "loss")
            p = len(rs) - w - l
            units = sum(american(r[price]) if r["result"] == "win"
                        else (-1.0 if r["result"] == "loss" else 0.0) for r in rs)
            staked = w + l
            roi = units / staked if staked else float("nan")
            label = " / ".join(k) if isinstance(k, tuple) else str(k)
            print(f"{label:<28}{len(rs):>6}{w:>6}{l:>6}{p:>4}{units:>10.2f}{roi:>8.1%}")
            out[label] = {"n": len(rs), "w": w, "l": l, "push": p, "units": round(units, 2),
                          "roi": round(roi, 4) if staked else None}
        return out

    tables = {}
    tables["market"] = report(lambda r: r["market"], "By market — all games")
    for variant in ("points", "goals", "goals_xg"):
        tables[f"{variant}:market_regime"] = report(
            lambda r, v=variant: (r["market"], r[f"regime_{v}"]), f"By market x regime — {variant}")
    tables["market_season"] = report(
        lambda r: (r["market"], f"{r['season']}-{str(r['season'] + 1)[2:]}"), "By market x season")
    tables["ml_closing"] = report(lambda r: r["market"],
                                  "Closing sensitivity (distinct quotes only)", price="price_close")

    cells = defaultdict(int)
    for r in rows:
        cells[(r["market"], r["regime_points"])] += 1
    print(f"\nmatchup cells sum: {sum(cells.values())} of {len(rows)} graded rows")
    assert sum(cells.values()) == len(rows)

    out_path = RESULTS_JSON if label == "walkforward/book" else HERE / f"results_{model_mode}_{settle_mode}.json"
    out_path.write_text(json.dumps({
        "generated_by": "backtest_matchup_strategy.py (revision 2)",
        "mode": label,
        "folds": fits,
        "thresholds": thresholds,
        "reconciliation": dict(recon),
        "rule_branches": dict(rule),
        "tables": tables,
        "rows": len(rows),
    }, indent=2) + "\n")
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
