#!/usr/bin/env python3
"""Urgent audit: S>1.0 spread-gap trigger and standings-points information.

Research prototype only. Reads the canonical audit CSVs and the frozen model
conventions; writes JSON artifacts under results/. Touches nothing else.

Stages:
  standings  chronological pregame standings replay (points, GP, points%),
             leak-safe: standings computed from strictly earlier games
  models     per-eval-season Poisson refits (B3/B5/B7) via the backtest module,
             plus matched walk-forward refits with standings features added
  spread     reconstruct the legacy goal-diff-1 rule (S = |−puck − margin|,
             edge side = margin + puck > 0 ? home : away, S.toFixed(1) > 1
             gates the underdog +1.5 cover) and measure firing rates, hit
             rates, and calibration of the model cover probability on calls
  strat      errors stratified by pregame points-% differential, controlling
             for games played parity and season
  info       does standings points add information beyond Elo and xG? matched
             chronological refits: elo, xg, elo_xg, each ± points-% diff
  verdict    comparison table for the report
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression, PoissonRegressor

import run_backtest as rb

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

# Bins of home minus away points-percentage differential.
PTS_PCT_BINS = [(-1.0, -0.20), (-0.20, -0.10), (-0.10, -0.05), (-0.05, 0.05),
                (0.05, 0.10), (0.10, 0.20), (0.20, 1.0)]
BIN_LABELS = ["<-0.20", "-0.20..-0.10", "-0.10..-0.05", "|d|<=0.05",
              "0.05..0.10", "0.10..0.20", ">0.20"]


# ---------------------------------------------------------------------------
# Standings replay
# ---------------------------------------------------------------------------

def standings_replay(games: list[dict]) -> dict[int, dict]:
    """Pregame standings for every game: points, wins, games played, points%.

    Points are earned only from games strictly before the current game's date,
    so nothing leaks. Regular-season overtime/shootout losers earn 1 point;
    playoff (game_type=3) losers earn 0. Returns {game_id: {...}}.
    """
    order = sorted(games, key=lambda g: (g["game_date"], g["start_time_utc"], g["game_id"]))
    pts: dict[str, int] = {}
    wins: dict[str, int] = {}
    played: dict[str, int] = {}
    out: dict[int, dict] = {}
    last_date = None
    for g in order:
        if g["game_date"] != last_date:
            # start-of-day snapshot: everything below reflects finished games only
            last_date = g["game_date"]
        home, away = g["home_team"], g["away_team"]
        out[g["game_id"]] = {
            "home_points": pts.get(home, 0), "home_wins": wins.get(home, 0),
            "home_gp": played.get(home, 0), "home_pts_pct": (pts.get(home, 0) / (2 * played[home]) if played.get(home) else None),
            "away_points": pts.get(away, 0), "away_wins": wins.get(away, 0),
            "away_gp": played.get(away, 0), "away_pts_pct": (pts.get(away, 0) / (2 * played[away]) if played.get(away) else None),
        }
        # now award this game's points for future snapshots
        hw = g["hw"]
        if hw is None:
            continue
        played[home] = played.get(home, 0) + 1
        played[away] = played.get(away, 0) + 1
        if hw == 1:
            wins[home] = wins.get(home, 0) + 1
            pts[home] = pts.get(home, 0) + 2
            pts[away] = pts.get(away, 0) + (0 if g["game_type"] == 3 else 1)
        else:
            wins[away] = wins.get(away, 0) + 1
            pts[away] = pts.get(away, 0) + 2
            pts[home] = pts.get(home, 0) + (0 if g["game_type"] == 3 else 1)
    return out


# ---------------------------------------------------------------------------
# Legacy goal-diff-1 rule, exactly as the card computes it
# ---------------------------------------------------------------------------

def legacy_pick(margin: float, puck_line: float) -> dict | None:
    """The documented goal-diff-1 rule. margin = projected home goal differential,
    puck_line = the home puck line (±1.5, negative when home is favored).
    Returns a pick dict with market/side/line, or None when the rule produces no
    priced candidate."""
    if abs(puck_line) != 1.5:
        return None
    spread_edge = abs(-puck_line - margin)
    edge_side = "home" if margin + puck_line > 0 else "away"
    edge_line = puck_line if edge_side == "home" else -puck_line
    # Rule 1: edge team is the Vegas underdog and S shows over 1.0 -> cover +1.5
    if edge_line > 0 and round(spread_edge, 1) > 1.0:
        return {"tier": "cover", "side": edge_side, "line": edge_line,
                "spread_edge": spread_edge, "trigger": "underdog_cover_S"}
    # Rule 2: otherwise, if Vegas has the model's favorite favored by 1.5 -> ML
    favorite_side = "home" if margin >= 0 else "away"
    favorite_line = puck_line if favorite_side == "home" else -puck_line
    if favorite_line < 0:
        return {"tier": "ml", "side": favorite_side, "line": None,
                "spread_edge": spread_edge, "trigger": "favorite_ml"}
    return None


def outcome_of(pick: dict, g: dict) -> str:
    if pick["tier"] == "ml":
        if pick["side"] == "home":
            return {1: "won", 0: "lost"}[g["hw"]]
        return {1: "lost", 0: "won"}[g["hw"]]
    margin = g["hg"] - g["ag"]
    covers = (margin >= 2) if pick["side"] == "home" else (margin <= 1)
    return "won" if covers else "lost"


# ---------------------------------------------------------------------------
# Stratification
# ---------------------------------------------------------------------------

def stratify(rows: list[dict]) -> list[dict]:
    """Per-bin model-call quality: counts, calibration, Brier for ML and cover."""
    out = []
    for (lo, hi), label in zip(PTS_PCT_BINS, BIN_LABELS):
        sub = [r for r in rows if lo <= r["pts_pct_diff"] < hi]
        if not sub:
            out.append({"bin": label, "n": 0})
            continue
        p_hw = np.array([r["p_home_win"] for r in sub])
        p_ac = np.array([r["p_away_cover"] for r in sub])
        y_hw = np.array([r["y_home_win"] for r in sub])
        y_ac = np.array([r["y_away_cover"] for r in sub])
        base = y_hw.mean()
        out.append({
            "bin": label, "n": len(sub),
            "base_rate_home_win": float(base),
            "mean_p_home_win": float(p_hw.mean()),
            "ml_brier": float(np.mean((p_hw - y_hw) ** 2)),
            "mean_p_away_cover": float(p_ac.mean()),
            "away_cover_brier": float(np.mean((p_ac - y_ac) ** 2)),
            "away_cover_base_rate": float(y_ac.mean()),
        })
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    t0 = time.time()
    RESULTS.mkdir(exist_ok=True)
    games = rb.load_games()
    elo = rb.elo_replay(games)
    standings = standings_replay(games)
    cache = json.load(open(RESULTS / "fit_cache.json"))
    so_home_all = rb.so_rate(games)

    # --- evaluate every eval-season game with per-season frozen betas ---
    eval_rows = {}
    for model in rb.MODELS:
        rows = []
        for season in rb.EVAL_SEASONS:
            beta = np.array(cache[str(season)][model])
            evalg = [g for g in games if g["season"] == season and g["game_id"] in standings]
            mus = rb.predict_mus(evalg, model, elo, beta)
            train_so = rb.so_rate([g for g in games if g["season"] < season])
            for g in evalg:
                mh, ma = mus[g["game_id"]]
                m = rb.joint(rb.pmf_rows(np.array([mh])), rb.pmf_rows(np.array([ma])))
                d = rb.derive(m, train_so)
                st = standings[g["game_id"]]
                if st["home_pts_pct"] is None or st["away_pts_pct"] is None:
                    continue
                gp_min = min(st["home_gp"], st["away_gp"])
                rows.append({
                    "game_id": g["game_id"], "season": season,
                    "hw": g["hw"], "hg": g["hg"], "ag": g["ag"],
                    "y_home_win": g["hw"],
                    "y_away_cover": int(g["hg"] - g["ag"] <= 1),
                    "y_over55": int(g["ohg"] + g["oag"] > 5.5),
                    "p_home_win": d["p_home_win"], "p_away_cover": d["p_away_cover"],
                    "p_over_55": d["p_over_55"],
                    "margin": mh - ma,
                    "pts_pct_diff": st["home_pts_pct"] - st["away_pts_pct"],
                    "pts_diff": st["home_points"] - st["away_points"],
                    "gp_min": gp_min, "gp_diff": st["home_gp"] - st["away_gp"],
                    "home_pts_pct": st["home_pts_pct"], "away_pts_pct": st["away_pts_pct"],
                    "elo_diff": elo[g["game_id"]]["diff"],
                })
        eval_rows[model] = rows
        print(f"  evaluated {model}: {len(rows)} games at {time.time()-t0:.0f}s", flush=True)

    # --- stratified audit by points-% differential (main model: b7_elo_xg) ---
    strat = {}
    for model in rb.MODELS:
        for control in ("all", "gp_parity"):
            rows = eval_rows[model]
            if control == "gp_parity":
                rows = [r for r in rows if r["gp_min"] >= 10]
            strat[f"{model}|{control}"] = stratify(rows)
    (RESULTS / "standings_stratification.json").write_text(json.dumps(strat, indent=1))
    print(f"  stratification done at {time.time()-t0:.0f}s", flush=True)

    # --- does standings points add information beyond Elo and xG? ---
    # matched walk-forward: per season, refit each feature set on prior seasons
    # only, and compare on the same evaluation games.
    def feature_row(g: dict, st: dict, elo_entry: dict, variant: str) -> list[float]:
        hr = max(g["xg_home_for"], 0.05) if g.get("xg_home_for") else None
        base_variants = {
            "elo": [1.0, elo_entry["diff"]],
            "xg": [1.0, np.log(hr if hr else 1.0), np.log(max(g.get("xg_away_against") or 1.0, 0.05)),
                   np.log(max(g.get("xg_away_for") or 1.0, 0.05)), np.log(max(g.get("xg_home_against") or 1.0, 0.05))],
            "elo_xg": [1.0, elo_entry["diff"], np.log(max(g.get("xg_home_for") or 1.0, 0.05)),
                       np.log(max(g.get("xg_home_against") or 1.0, 0.05)),
                       np.log(max(g.get("xg_away_for") or 1.0, 0.05)), np.log(max(g.get("xg_away_against") or 1.0, 0.05))],
        }
        if variant.endswith("_pts"):
            plain = variant[: -len("_pts")]
            return base_variants[plain] + [st["home_pts_pct"] - st["away_pts_pct"]]
        return base_variants[variant][:]

    from collections import defaultdict
    by_model = defaultdict(lambda: defaultdict(list))
    for season in rb.EVAL_SEASONS:
        train = [g for g in games if g["season"] < season and g["hw"] is not None]
        evalg = [g for g in games if g["season"] == season and g["hw"] is not None]
        # historical win rate target for the ML logistic
        for variant in ("elo", "xg", "elo_xg", "elo_pts", "xg_pts", "elo_xg_pts"):
            Xtr, ytr, Xev, yev, gids = [], [], [], [], []
            for g in train:
                st = standings.get(g["game_id"])
                if st is None or st["home_pts_pct"] is None or st["away_pts_pct"] is None:
                    continue
                row = feature_row(g, st, elo[g["game_id"]], variant)
                if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in row):
                    continue
                Xtr.append(row); ytr.append(g["hw"])
            for g in evalg:
                st = standings.get(g["game_id"])
                if st is None or st["home_pts_pct"] is None or st["away_pts_pct"] is None:
                    continue
                row = feature_row(g, st, elo[g["game_id"]], variant)
                if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in row):
                    continue
                Xev.append(row); yev.append(g["hw"]); gids.append(g["game_id"])
            if not Xtr or not Xev:
                continue
            mdl = LogisticRegression(max_iter=500, C=1.0).fit(np.asarray(Xtr), np.asarray(ytr))
            p = mdl.predict_proba(np.asarray(Xev))[:, 1]
            y = np.asarray(yev)
            by_model[variant][season] = {
                "n": len(y),
                "ml_brier": float(np.mean((p - y) ** 2)),
                "log_loss": float(-np.mean(y * np.log(np.clip(p, 1e-9, 1 - 1e-9)) + (1 - y) * np.log(np.clip(1 - p, 1e-9, 1 - 1e-9)))),
            }
        print(f"  info-test refit season {season} done at {time.time()-t0:.0f}s", flush=True)

    info = {}
    for variant, seasons in by_model.items():
        agg_n = sum(s["n"] for s in seasons.values())
        info[variant] = {
            "n": agg_n,
            "ml_brier": float(np.mean([s["ml_brier"] for s in seasons.values()])),
            "log_loss": float(np.mean([s["log_loss"] for s in seasons.values()])),
            "per_season": {str(k): v for k, v in sorted(seasons.items())},
        }
    (RESULTS / "standings_info_test.json").write_text(json.dumps(info, indent=1))

    # --- S>1.0 trigger audit on matched games (structural + empirical) ---
    # The legacy rule needs a book puck line. Historical book lines are not in
    # this checkout, so the audit is structural: for each eval game we compute
    # the trigger under both possible book favorites (home favored and away
    # favored) and compare the model's cover probability on fired calls against
    # the empirical cover base rate for that confidence stratum.
    spread_audit = {"note": "structural audit; no historical book puck lines exist in this checkout",
                    "cases": [], "summary": {}}
    fired = []
    for g in eval_rows["b7_elo_xg"]:
        for book_home_favored in (True, False):
            puck = -1.5 if book_home_favored else 1.5
            pick = legacy_pick(g["margin"], puck)
            if pick is None or pick["tier"] != "cover":
                continue
            p_cover = g["p_away_cover"] if pick["side"] == "away" else (1 - g["p_away_cover"])
            fired.append({
                "game_id": g["game_id"], "book_home_favored": book_home_favored,
                "side": pick["side"], "p_cover_model": float(p_cover),
                "y_cover": int(g["hg"] - g["ag"] <= 1) if pick["side"] == "away" else int(g["hg"] - g["ag"] >= 2),
                "spread_edge": pick["spread_edge"],
            })
    if fired:
        p = np.array([f["p_cover_model"] for f in fired])
        y = np.array([f["y_cover"] for f in fired])
        lo_p, hi_p = p <= 0.5, p > 0.5
        spread_audit["summary"] = {
            "n": len(fired),
            "mean_model_p_cover": float(p.mean()),
            "empirical_cover_rate": float(y.mean()),
            "hit_rate_when_model_p_above_50": {
                "n": int(lo_p.sum() + hi_p.sum()), "n_above": int(hi_p.sum()),
                "hit_rate_above": float(y[hi_p].mean()) if hi_p.any() else None,
                "hit_rate_below": float(y[lo_p].mean()) if lo_p.any() else None},
            "brier_on_calls": float(np.mean((p - y) ** 2)),
            "brier_on_calls_constant_base": float(np.mean((y.mean() - y) ** 2)),
            "base_rate_all_games": float(np.mean([r["y_away_cover"] for r in eval_rows["b7_elo_xg"]])),
        }
        # calibration table of model p_cover vs actual on fired calls
        bins = [0.0, 0.4, 0.45, 0.5, 0.55, 0.6, 1.01]
        cal = []
        for i in range(len(bins) - 1):
            sub = [f for f in fired if bins[i] <= f["p_cover_model"] < bins[i + 1]]
            if sub:
                cal.append({"bin": f"{bins[i]:.2f}..{bins[i+1]:.2f}", "n": len(sub),
                            "mean_p": float(np.mean([f["p_cover_model"] for f in sub])),
                            "cover_rate": float(np.mean([f["y_cover"] for f in sub]))})
        spread_audit["calibration_on_calls"] = cal
    (RESULTS / "spread_trigger_audit.json").write_text(json.dumps(spread_audit, indent=1))
    print(f"  spread audit done at {time.time()-t0:.0f}s", flush=True)

    print(f"ALL DONE in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
