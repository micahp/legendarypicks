#!/usr/bin/env python3
"""Historical profitability of the NHL pick hierarchy, with and without matchup regimes.

Phase 1-3 of the matchup-strategy brief. Nothing is deployed; this only measures.

Model: the frozen B7 v1 (Elo + rolling xG) arm on origin/dev, evaluated chronologically —
Elo is replayed game by game and the xG inputs are the pregame rolling columns, so no game
sees information from after its own start.

Market: SBR archive, 2018-19 → 2022-23. Opening prices are the primary evaluation; closing
prices are reported separately as a sensitivity check. There is no intraday timestamp in the
archive, so no claim of an executable fill is made anywhere.

Pick rule: exact replay of `model_pick()` (leeway-2 semantics) on the historical forecast:
  1. Vegas underdog (+1.5) with S = |puck| - favourite_margin > 1.0 → that side +1.5
  2. else the Vegas favourite ML when the model's favourite is the same team
  3. else a total: 5.5 when the projection is ≤ 6.0, 6.5 above; Over if projection > line
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

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
AUDIT = Path("/root/legendarypicks/research/nhl/kalshi-playoff-audit-2025-26")
CANONICAL = AUDIT / "canonical_games_v1_7cd2fc9a6e84470c.csv"
FEATURES = AUDIT / "pregame_rolling_features_v1_62dcceb77085bc59.csv"
MODEL = REPO / "research/nhl/prospective-2026-27/frozen_models_2026-27_v1.json"
SBR = Path("/root/lp-data/nhl-sbr/games_2018_2023.jsonl")

TEAM_ID = {"PHX": "ARI", "T.B": "TBL", "TB": "TBL", "N.J": "NJD", "L.A": "LAK", "LA": "LAK", "S.J": "SJS", "ATL": "WPG"}
NAME = {"anaheim":"ANA","arizona":"ARI","boston":"BOS","buffalo":"BUF","calgary":"CGY","carolina":"CAR","chicago":"CHI",
"colorado":"COL","columbus":"CBJ","dallas":"DAL","detroit":"DET","edmonton":"EDM","florida":"FLA","losangeles":"LAK",
"minnesota":"MIN","montreal":"MTL","nashville":"NSH","newjersey":"NJD","nyislanders":"NYI","nyrangers":"NYR","ottawa":"OTT",
"philadelphia":"PHI","pittsburgh":"PIT","sanjose":"SJS","seattlekraken":"SEA","stlouis":"STL","tampabay":"TBL","toronto":"TOR",
"utah":"UTA","utahhockeyclub":"UTA","vancouver":"VAN","vegas":"VGK","washington":"WSH","winnipeg":"WPG"}

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


def elo_replay(canon: list[dict], k: float = 10.0, hfa: float = 35.0) -> dict[int, dict]:
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


def standings_before(canon: list[dict]) -> dict[int, dict]:
    """Points percentage and goal differential as of the moment before each game."""
    pts, gp, gf, ga = defaultdict(int), defaultdict(int), defaultdict(int), defaultdict(int)
    out = {}
    for row in sorted(canon, key=lambda r: (r["game_date"], r["start_time_utc"], int(r["game_id"]))):
        h = TEAM_ID.get(row["home_team"], row["home_team"])
        a = TEAM_ID.get(row["away_team"], row["away_team"])
        gid = int(row["game_id"])

        def pct(t):
            return pts[t] / (2 * gp[t]) if gp[t] else float("nan")

        out[gid] = {"home_pct": pct(h), "away_pct": pct(a), "home_gp": gp[h], "away_gp": gp[a],
                    "home_gd": (gf[h] - ga[h]) / gp[h] if gp[h] else float("nan"),
                    "away_gd": (gf[a] - ga[a]) / gp[a] if gp[a] else float("nan")}
        hg, ag = int(row["home_goals_model_target"]), int(row["away_goals_model_target"])
        hw = hg > ag
        pts[h] += 2 if hw else 0
        pts[a] += 2 if not hw else 0
        # the losing side of a non-regulation game earns one point
        if str(row["last_period_type"]).upper() not in ("REG", "R", ""):
            pts[a if hw else h] += 1
        gp[h] += 1
        gp[a] += 1
        gf[h] += hg; ga[h] += ag
        gf[a] += ag; ga[a] += hg
    return out


def regime(pct: float, gp: int) -> str:
    if gp < 10 or math.isnan(pct):
        return "early"
    # League terciles of in-season points percentage (2-point wins): 0.536 / 0.579.
    # Fixed population constants, not fitted to the evaluation outcomes.
    if pct >= 0.579:
        return "strong"
    if pct <= 0.536:
        return "weak"
    return "mid"


def pair_regime(h: str, a: str) -> str:
    if "early" in (h, a):
        return "early"
    if h == a:
        return {"strong": "strong-strong", "weak": "weak-weak", "mid": "mid-mid"}[h]
    return "mixed"


def model_forecast(model: dict, elo: dict, features: dict, gid: int, key) -> dict | None:
    e = elo[gid]
    f = features.get(gid)
    if f is None:
        return None
    try:
        hx = math.log(max(float(f["home_rolling10_5v5_score_venue_xgf"]), .05))
        ax = math.log(max(float(f["away_rolling10_5v5_score_venue_xgf"]), .05))
        hd = math.log(max(float(f["home_rolling10_5v5_score_venue_xga"]), .05))
        ad = math.log(max(float(f["away_rolling10_5v5_score_venue_xga"]), .05))
    except (TypeError, ValueError):
        return None
    p = model["poisson_models"]["elo_xg"]
    c = p["coef"]
    mh = math.exp(p["intercept"] + c[0] * e["venue"] + c[1] * hx + c[2] * ad + c[3] * e["diff"])
    ma = math.exp(p["intercept"] + c[1] * ax + c[2] * hd + c[3] * -e["diff"])
    return {"mu_h": mh, "mu_a": ma, "margin": mh - ma, "total": mh + ma,
            "p_home": p_win(mh, ma, float(model["historical_home_shootout_win_rate"]))}


def pick(forecast: dict, game: dict) -> dict | None:
    home, away = game["home"], game["away"]
    puck = game.get("home_puck_line")
    if puck is None or abs(float(puck)) != 1.5:
        return None
    puck = float(puck)
    favourite = "home" if puck < 0 else "away"
    underdog = "away" if favourite == "home" else "home"
    fav_margin = forecast["margin"] if favourite == "home" else -forecast["margin"]
    s = abs(puck) - fav_margin
    if round(s + 0.0, 1) > 1.0:
        price_o = game[f"{underdog}_puck_open"]
        price_c = game[f"{underdog}_puck_close"]
        if price_o is None:
            return None
        return {"market": "spread", "side": underdog, "line": 1.5, "price_open": price_o, "price_close": price_c}
    model_fav = "home" if forecast["p_home"] >= 0.5 else "away"
    if model_fav == favourite:
        po = game[f"{favourite}_ml_open"]
        pc = game[f"{favourite}_ml_close"]
        if po is None:
            return None
        return {"market": "ml", "side": favourite, "line": None, "price_open": po, "price_close": pc}
    line = 5.5 if forecast["total"] <= 6.0 else 6.5
    side = "over" if forecast["total"] > line else "under"
    po = game.get("ou_open_price")
    pc = game.get("ou_close_price")
    if po is None:
        return None
    return {"market": "total", "side": side, "line": line, "price_open": po, "price_close": pc}


def settled(pick: dict, hs: int, as_: int) -> str:
    m, side, line = pick["market"], pick["side"], pick["line"]
    if m == "ml":
        win = (hs > as_) if side == "home" else (as_ > hs)
        return "win" if win else "loss"
    if m == "spread":
        mine, opp = (hs, as_) if side == "home" else (as_, hs)
        margin = mine + line - opp
        return "win" if margin > 1e-9 else ("push" if abs(margin) < 1e-9 else "loss")
    total = hs + as_
    if abs(total - line) < 1e-9:
        return "push"
    return "win" if ((total > line) == (side == "over")) else "loss"


def main() -> None:
    model = json.loads(MODEL.read_text())
    canon = list(csv.DictReader(CANONICAL.open(newline="", encoding="utf-8")))
    features = {int(r["game_id"]): r for r in csv.DictReader(FEATURES.open(newline="", encoding="utf-8"))}
    elo = elo_replay(canon)
    table = standings_before(canon)

    by_key = {}
    for r in canon:
        md = int(r["game_date"][5:7]) * 100 + int(r["game_date"][8:10])
        by_key[(int(r["season"]), md, TEAM_ID.get(r["home_team"], r["home_team"]),
                TEAM_ID.get(r["away_team"], r["away_team"]))] = r

    rows = []
    unmatched = 0
    for line in SBR.open():
        g = json.loads(line)
        h, a = tri(g["home"]["team"]), tri(g["away"]["team"])
        if not (h and a):
            unmatched += 1
            continue
        season = int(g["season"][:4])
        rec = by_key.get((season, int(g["date"]), h, a))
        if rec is None:
            unmatched += 1
            continue
        gid = int(rec["game_id"])
        fc = model_forecast(model, elo, features, gid, rec)
        st = table[gid]
        if fc is None:
            continue
        game = {"home": h, "away": a, "home_puck_line": g["home"].get("puck_line"),
                "home_ml_open": g["home"].get("ml_open"), "home_ml_close": g["home"].get("ml_close"),
                "away_ml_open": g["away"].get("ml_open"), "away_ml_close": g["away"].get("ml_close"),
                "home_puck_open": g["home"].get("puck_price"), "home_puck_close": g["home"].get("puck_price"),
                "away_puck_open": g["away"].get("puck_price"), "away_puck_close": g["away"].get("puck_price"),
                "ou_open_price": g["home"].get("ou_open_price"), "ou_close_price": g["home"].get("ou_close_price")}
        pk = pick(fc, game)
        if pk is None:
            continue
        hs, as_ = int(rec["home_goals_model_target"]), int(rec["away_goals_model_target"])
        res = settled(pk, hs, as_)
        rows.append(dict(season=season, game_id=gid, regime=pair_regime(regime(st["home_pct"], st["home_gp"]),
                                                                        regime(st["away_pct"], st["away_gp"])),
                         s=round(abs(float(game["home_puck_line"])) - (fc["margin"] if float(game["home_puck_line"]) < 0 else -fc["margin"]), 2),
                         **pk, result=res, hs=hs, as_=as_))

    print(f"matched games: {len(rows)}   unmatched sbr rows: {unmatched}")
    tot = len(rows)
    print(f"pick mix: " + ", ".join(f"{k}={v}" for k, v in sorted(
        {m: sum(1 for r in rows if r['market'] == m) for m in {r['market'] for r in rows}}.items())))

    def report(key_fn, title, price="price_open"):
        print("\n" + title + f"  (prices: {price})")
        print(f"{'group':<26}{'n':>5}{'W':>5}{'L':>5}{'P':>4}{'units':>9}{'ROI':>8}")
        groups = defaultdict(list)
        for r in rows:
            groups[key_fn(r)].append(r)
        for k in sorted(groups):
            rs = groups[k]
            w = sum(1 for r in rs if r["result"] == "win")
            l = sum(1 for r in rs if r["result"] == "loss")
            p = len(rs) - w - l
            units = sum(american(r[price]) if r["result"] == "win" else (-1.0 if r["result"] == "loss" else 0.0) for r in rs)
            staked = w + l
            roi = units / staked if staked else float("nan")
            label = " / ".join(k) if isinstance(k, tuple) else str(k)
            print(f"{label:<26}{len(rs):>5}{w:>5}{l:>5}{p:>4}{units:>9.2f}{roi:>8.1%}")

    report(lambda r: r["market"], "By market — all games")
    report(lambda r: (r["market"], r["regime"]), "By market × regime")
    report(lambda r: r["regime"], "By regime — all markets")
    report(lambda r: (r["market"], f"{r['season']}-{r['season'] + 1}"), "By market × season")
    report(lambda r: (r["market"], "2018-20", ) if r["season"] <= 2020 else (r["market"], "2020-23"),
           "Chronological split — early vs late seasons")
    report(lambda r: r["market"], "Closing-price sensitivity", price="price_close")


if __name__ == "__main__":
    main()
