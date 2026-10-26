#!/usr/bin/env python3
"""Walk-forward NHL moneyline selectivity against the SBR market.

The B7 replay, canonical feature loader, team mapping, American odds conversion,
and book settlement are reused from the audited matchup harness. All fitting,
calibration, threshold selection, and uncertainty shrinkage are fit using seasons
strictly before the season being predicted. Opening and closing quotes are scored
as separate hypothetical price sets; neither has a verified executable timestamp.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import date as calendar_date
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
HARNESS_DIR = REPO / "research/nhl/matchup-strategy-2026-10-20"
SBR_GZIP = REPO / "research/nhl/sbr-odds-archive-2026-10-19/games_2018_2023.jsonl.gz"
sys.path.insert(0, str(HARNESS_DIR))
import backtest_matchup_strategy as bt  # noqa: E402


SEASONS = tuple(bt.EVAL_SEASONS)
POLICY_SEASONS = SEASONS[2:]  # 2018 warm-up, 2019 policy-tuning season
BOOTSTRAP_ITERS = 5000
BOOTSTRAP_SEED = 20261020
CALIBRATION_C = 1.0
FEATURE_MODEL_C = 0.1
SHRINK_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
EV_THRESHOLD_GRID = tuple(float(round(float(x), 3)) for x in np.arange(0.0, 0.1001, 0.005))
MIN_TUNING_BETS = 50
QUOTE_NAMES = ("open", "close")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def mmdd(date: str) -> int:
    return int(date[5:7]) * 100 + int(date[8:10])


def sbr_iso_date(season: int, source_date: object) -> str:
    value = int(source_date)
    month, day = divmod(value, 100)
    year = season if month >= 10 else season + 1
    return calendar_date(year, month, day).isoformat()


def print_season_coverage(label: str, dates_by_season: dict[int, list[str]],
                          seasons: list[int] | tuple[int, ...]) -> None:
    print(f"\nSEASON COVERAGE ({label})")
    print("season n first_date last_date")
    for season in seasons:
        dates = sorted(dates_by_season.get(season, []))
        if not dates:
            raise RuntimeError(f"season coverage is empty for {season}")
        print(f"{season}-{str(season + 1)[2:]} {len(dates)} {dates[0]} {dates[-1]}")


def price_is_valid(price: object) -> bool:
    try:
        value = float(price)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and value != 0.0


def decimal_odds(american_price: float) -> float:
    price = float(american_price)
    if not math.isfinite(price) or price == 0.0:
        raise ValueError(f"invalid American odds: {american_price!r}")
    return 1.0 + (price / 100.0 if price > 0 else 100.0 / abs(price))


def devig(home_price: float, away_price: float) -> tuple[float, float]:
    q_home = 1.0 / decimal_odds(home_price)
    q_away = 1.0 / decimal_odds(away_price)
    total = q_home + q_away
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("invalid two-sided moneyline market")
    return q_home / total, q_away / total


def logit(probability: float) -> float:
    p = min(1.0 - 1e-6, max(1e-6, float(probability)))
    return math.log(p / (1.0 - p))


def load_sbr() -> list[dict]:
    rows = []
    with gzip.open(SBR_GZIP, "rt", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                raise RuntimeError(f"blank line in SBR archive at line {line_no}")
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON in SBR archive line {line_no}") from exc
    if not rows:
        raise RuntimeError("SBR archive is empty")
    return rows


def make_canonical_index(canon: list[dict]) -> dict[tuple[int, int, str, str], dict]:
    index = {}
    for row in canon:
        key = (
            int(row["season"]),
            mmdd(row["game_date"]),
            bt.TEAM_ID.get(row["home_team"], row["home_team"]),
            bt.TEAM_ID.get(row["away_team"], row["away_team"]),
        )
        if key in index:
            raise RuntimeError(f"duplicate canonical join key: {key}")
        index[key] = row
    return index


def make_game_row(c: dict, f: dict, fc: dict, elo_row: dict, sbr: dict,
                  sbr_home: str, sbr_away: str, orientation: str) -> dict:
    canonical_home = bt.TEAM_ID.get(c["home_team"], c["home_team"])
    canonical_away = bt.TEAM_ID.get(c["away_team"], c["away_team"])
    sbr_sides = {sbr_home: sbr["home"], sbr_away: sbr["away"]}
    if canonical_home not in sbr_sides or canonical_away not in sbr_sides:
        raise RuntimeError("matched game does not contain both canonical teams")

    # Prices follow team identity, not the source row's home/away orientation.
    home_side = sbr_sides[canonical_home]
    away_side = sbr_sides[canonical_away]
    xg_home_log = math.log(max(float(f["home_rolling10_5v5_score_venue_xgf"]), 0.05))
    xga_home_log = math.log(max(float(f["home_rolling10_5v5_score_venue_xga"]), 0.05))
    xg_away_log = math.log(max(float(f["away_rolling10_5v5_score_venue_xgf"]), 0.05))
    xga_away_log = math.log(max(float(f["away_rolling10_5v5_score_venue_xga"]), 0.05))
    xg_matchup_delta = (xg_home_log + xga_away_log) - (xg_away_log + xga_home_log)
    goal_form_delta = (
        float(f["home_rolling10_goals_for"]) - float(f["home_rolling10_goals_against"])
        - float(f["away_rolling10_goals_for"]) + float(f["away_rolling10_goals_against"])
    )
    y = int(c["official_home_winner"])
    if y not in (0, 1):
        raise RuntimeError(f"invalid canonical official_home_winner for {c['game_id']}: {y}")

    row = {
        "game_id": int(c["game_id"]),
        "season": int(c["season"]),
        "game_date": c["game_date"],
        "start_time_utc": c["start_time_utc"],
        "home_team": canonical_home,
        "away_team": canonical_away,
        "orientation": orientation,
        "p_b7": float(fc["p_home"]),
        "y": y,
        "official_home_winner": y,
        "home_goals": int(c["official_home_score"]),
        "away_goals": int(c["official_away_score"]),
        # These inputs are pregame rolling features / pregame Elo only. The current
        # game's official score is used solely for settlement and the outcome label.
        "elo_diff": float(elo_row["diff"]),
        "venue": float(elo_row["venue"]),
        "xg_matchup_delta": xg_matchup_delta,
        "goal_form_delta": goal_form_delta,
        "home_ml_open": home_side.get("ml_open"),
        "away_ml_open": away_side.get("ml_open"),
        "home_ml_close": home_side.get("ml_close"),
        "away_ml_close": away_side.get("ml_close"),
        "sbr_final_missing": home_side.get("final") is None or away_side.get("final") is None,
    }
    return row


def reconcile_sbr_results(sbr: dict, c: dict, sbr_home: str, sbr_away: str) -> bool:
    """Return whether the SBR final is missing; fail on any available winner disagreement."""
    sbr_hg, sbr_ag = sbr["home"].get("final"), sbr["away"].get("final")
    if sbr_hg is None or sbr_ag is None:
        return True
    sbr_hg, sbr_ag = int(float(sbr_hg)), int(float(sbr_ag))
    if sbr_hg == sbr_ag:
        raise RuntimeError(f"tied completed SBR final for game {c['game_id']}")
    sbr_winner = sbr_home if sbr_hg > sbr_ag else sbr_away
    canonical_home = bt.TEAM_ID.get(c["home_team"], c["home_team"])
    canonical_away = bt.TEAM_ID.get(c["away_team"], c["away_team"])
    canonical_winner = canonical_home if int(c["official_home_winner"]) == 1 else canonical_away
    if sbr_winner != canonical_winner:
        raise RuntimeError(
            f"SBR/canonical winner mismatch game={c['game_id']} "
            f"SBR={sbr_winner} canonical={canonical_winner}"
        )
    return False


def build_rows() -> tuple[list[dict], Counter, Counter]:
    canon = bt.load_csv(bt.CANONICAL)
    feature_rows = bt.load_csv(bt.FEATURES)
    features = {int(row["game_id"]): row for row in feature_rows}
    if len(features) != len(feature_rows):
        raise RuntimeError("duplicate game_id in pregame feature file")
    feature_complete_eval = [
        row for row in feature_rows
        if row["required_features_complete"].lower() == "true"
        and int(row["season"]) in SEASONS
    ]
    feature_date_violations = [
        row for row in feature_complete_eval
        if not row.get("home_max_feature_source_date")
        or not row.get("away_max_feature_source_date")
        or row["home_max_feature_source_date"] >= row["game_date"]
        or row["away_max_feature_source_date"] >= row["game_date"]
    ]
    print(
        f"PREGAME FEATURE SOURCE CHECK: checked={len(feature_complete_eval)} "
        f"source_date_on_or_after_game_date={len(feature_date_violations)}"
    )
    if feature_date_violations:
        raise RuntimeError(
            "pregame feature source-date violation: "
            + ", ".join(row["game_id"] for row in feature_date_violations[:10])
        )
    canonical = make_canonical_index(canon)
    canonical_by_id = {int(row["game_id"]): row for row in canon}
    if len(canonical_by_id) != len(canon):
        raise RuntimeError("duplicate game_id in canonical game file")

    games = bt.load_games(canon, features)
    game_by_id = {game["game_id"]: game for game in games}
    elo = bt.elo_replay(canon)
    folds, forecasts = {}, {}
    for season in SEASONS:
        train = [game for game in games if game["season"] < season]
        if not train:
            raise RuntimeError(f"empty prior-season B7 fold for {season}")
        fold = bt.fit_fold(train, elo)
        folds[season] = fold
        held_out = [game for game in games if game["season"] == season]
        for game in held_out:
            forecasts[game["game_id"]] = bt.forecast(fold, elo, game)
        print(
            f"B7 fold {season}-{str(season + 1)[2:]}: "
            f"train_games={fold['n_games']} train_seasons={fold['train_seasons'][0]}-"
            f"{fold['train_seasons'][1]} forecasts={len(held_out)} "
            f"coef={[round(v, 5) for v in fold['coef']]} tie_home={fold['tie_home']:.5f}"
        )

    sbr_rows = load_sbr()
    recon = Counter(sbr_rows=len(sbr_rows))
    matched = []
    seen_game_ids = set()
    season_counts = Counter()
    season_dates = defaultdict(list)
    for item in sbr_rows:
        season = int(str(item["season"])[:4])
        season_counts[season] += 1
        sbr_date = sbr_iso_date(season, item["date"])
        season_dates[season].append(sbr_date)
        sbr_home, sbr_away = bt.tri(item["home"].get("team")), bt.tri(item["away"].get("team"))
        if not sbr_home or not sbr_away:
            recon["team_unmapped"] += 1
            continue
        date = int(item["date"])
        exact_key = (season, date, sbr_home, sbr_away)
        reverse_key = (season, date, sbr_away, sbr_home)
        c = canonical.get(exact_key)
        orientation = "exact"
        if c is None:
            c = canonical.get(reverse_key)
            orientation = "reversed"
        if c is None:
            recon["no_canonical_match"] += 1
            continue
        if orientation == "reversed":
            recon["orientation_reversed_and_aligned"] += 1
        gid = int(c["game_id"])
        if gid in seen_game_ids:
            raise RuntimeError(f"duplicate SBR row matched canonical game_id={gid}")
        seen_game_ids.add(gid)
        if gid not in game_by_id:
            recon["no_complete_pregame_features"] += 1
            continue
        fc = forecasts.get(gid)
        if fc is None:
            recon["no_walkforward_forecast"] += 1
            continue
        if reconcile_sbr_results(item, c, sbr_home, sbr_away):
            recon["sbr_final_missing"] += 1
        else:
            recon["sbr_final_winners_checked"] += 1
        row = make_game_row(c, features[gid], fc, elo[gid], item,
                            sbr_home, sbr_away, orientation)
        row["sbr_game_date"] = sbr_date
        matched.append(row)
        recon["matched_with_forecast"] += 1

    accounted = sum(
        recon[key]
        for key in (
            "team_unmapped", "no_canonical_match", "no_complete_pregame_features",
            "no_walkforward_forecast", "matched_with_forecast",
        )
    )
    if accounted != len(sbr_rows):
        raise RuntimeError(f"SBR reconciliation failed: accounted={accounted}, source={len(sbr_rows)}")
    if recon["team_unmapped"] or recon["no_canonical_match"] or recon["no_walkforward_forecast"]:
        raise RuntimeError(f"unresolved SBR join/forecast gaps: {dict(recon)}")
    print_season_coverage("SBR archive rows", season_dates, sorted(season_counts))
    return matched, recon, season_counts


def make_quote_rows(rows: list[dict], quote: str) -> tuple[list[dict], Counter]:
    out, missing = [], Counter()
    h_key, a_key = f"home_ml_{quote}", f"away_ml_{quote}"
    for row in rows:
        hp, ap = row[h_key], row[a_key]
        if not price_is_valid(hp) or not price_is_valid(ap):
            missing[row["season"]] += 1
            continue
        p_home, p_away = devig(float(hp), float(ap))
        out.append({
            **row,
            "quote": quote,
            "home_price": float(hp),
            "away_price": float(ap),
            "home_decimal": decimal_odds(float(hp)),
            "away_decimal": decimal_odds(float(ap)),
            "market_home": p_home,
            "market_away": p_away,
            "market_overround": (1.0 / decimal_odds(float(hp))
                                 + 1.0 / decimal_odds(float(ap))) - 1.0,
        })
    return out, missing


def model_matrix(rows: list[dict], include_b7: bool, include_features: bool) -> np.ndarray:
    matrix = []
    for row in rows:
        values = [logit(row["market_home"])]
        if include_b7:
            values.append(logit(row["p_b7"]))
        if include_features:
            values.extend((row["elo_diff"], row["xg_matchup_delta"],
                           row["goal_form_delta"], row["venue"]))
        matrix.append(values)
    result = np.asarray(matrix, dtype=float)
    if result.ndim != 2 or not np.isfinite(result).all():
        raise RuntimeError("non-finite predictor matrix")
    return result


def fit_binary_model(x: np.ndarray, y: np.ndarray, c_value: float) -> object:
    if len(y) == 0 or len(set(int(v) for v in y)) != 2:
        raise RuntimeError("logistic fit requires both outcome classes")
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=c_value, max_iter=2000, solver="lbfgs", random_state=0),
    )
    model.fit(x, y)
    return model


def positive_probability(model: object, x: np.ndarray) -> np.ndarray:
    classes = list(model[-1].classes_)
    if 1 not in classes:
        raise RuntimeError(f"fitted model has no home-win class: {classes}")
    return model.predict_proba(x)[:, classes.index(1)]


def forecast_probabilities(rows: list[dict], quote: str) -> dict[int, dict]:
    by_season: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_season[row["season"]].append(row)
    predictions = {}
    for season in SEASONS:
        train = [row for row in rows if row["season"] < season]
        held = by_season.get(season, [])
        if not train:
            continue
        y_train = np.asarray([row["y"] for row in train], dtype=int)
        b7_calibrator = fit_binary_model(
            np.asarray([[logit(row["p_b7"])] for row in train], dtype=float),
            y_train,
            CALIBRATION_C,
        )
        x_market_features = model_matrix(train, include_b7=False, include_features=True)
        x_market_b7 = model_matrix(train, include_b7=True, include_features=False)
        x_full = model_matrix(train, include_b7=True, include_features=True)
        feature_model = fit_binary_model(x_market_features, y_train, FEATURE_MODEL_C)
        b7_market_model = fit_binary_model(x_market_b7, y_train, FEATURE_MODEL_C)
        full_model = fit_binary_model(x_full, y_train, FEATURE_MODEL_C)
        p_base = float(y_train.mean())
        if not held:
            continue
        p_cal = positive_probability(
            b7_calibrator,
            np.asarray([[logit(row["p_b7"])] for row in held], dtype=float),
        )
        p_feature = positive_probability(
            feature_model, model_matrix(held, include_b7=False, include_features=True)
        )
        p_market_b7 = positive_probability(
            b7_market_model, model_matrix(held, include_b7=True, include_features=False)
        )
        p_full = positive_probability(
            full_model, model_matrix(held, include_b7=True, include_features=True)
        )
        for row, cal, feature, market_b7, full in zip(
            held, p_cal, p_feature, p_market_b7, p_full
        ):
            predictions[row["game_id"]] = {
                "p_cal_b7": float(cal),
                "p_market_features": float(feature),
                "p_market_b7": float(market_b7),
                "p_full": float(full),
                "p_base": p_base,
                "train_n": len(train),
                "train_seasons": (min(r["season"] for r in train), max(r["season"] for r in train)),
            }
        train_range = f"{min(r['season'] for r in train)}-{max(r['season'] for r in train)}"
        print(
            f"Probability fold quote={quote} season={season}: train_n={len(train)} "
            f"train_seasons={train_range} held_out={len(held)} "
            f"C_cal={CALIBRATION_C:g} C_feature_models={FEATURE_MODEL_C:g}"
        )
    return predictions


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def log_loss(y: np.ndarray, p: np.ndarray) -> float:
    safe = np.clip(p, 1e-12, 1.0 - 1e-12)
    return float(-np.mean(y * np.log(safe) + (1.0 - y) * np.log(1.0 - safe)))


def predictor_report(rows: list[dict], predictions: dict[int, dict], quote: str) -> None:
    scored = [row for row in rows if row["season"] > SEASONS[0] and row["game_id"] in predictions]
    if not scored:
        raise RuntimeError(f"no prior-calibrated prediction rows for {quote}")
    y = np.asarray([row["y"] for row in scored], dtype=float)
    names = (
        ("raw B7", lambda r, p: r["p_b7"]),
        ("prior-only logistic B7", lambda r, p: p["p_cal_b7"]),
        ("no-vig market", lambda r, p: r["market_home"]),
        ("prior base rate", lambda r, p: p["p_base"]),
        ("market + team features", lambda r, p: p["p_market_features"]),
        ("market + B7", lambda r, p: p["p_market_b7"]),
        ("market + B7 + team features", lambda r, p: p["p_full"]),
    )
    market_p = np.asarray([row["market_home"] for row in scored], dtype=float)
    print(
        f"\nPREDICTOR QUALITY quote={quote} n={len(scored)} "
        f"season_counts=" + ",".join(
            f"{s}-{str(s + 1)[2:]}:{sum(r['season'] == s for r in scored)}"
            for s in sorted({r["season"] for r in scored})
        )
    )
    print(f"{'predictor':<30}{'Brier':>10}{'logloss':>10}{'Δ Brier vs market':>20}")
    market_brier = brier(y, market_p)
    for name, getter in names:
        p = np.asarray([getter(row, predictions[row["game_id"]]) for row in scored], dtype=float)
        print(f"{name:<30}{brier(y, p):>10.6f}{log_loss(y, p):>10.6f}{brier(y, p)-market_brier:>20.6f}")


def favorite_side(row: dict) -> str:
    return "home" if row["home_decimal"] <= row["away_decimal"] else "away"


def policy_side(row: dict, p_model_home: float, shrink: float,
                ev_threshold: float) -> tuple[str | None, float, float]:
    p_home = (1.0 - shrink) * p_model_home + shrink * row["market_home"]
    ev_home = p_home * row["home_decimal"] - 1.0
    ev_away = (1.0 - p_home) * row["away_decimal"] - 1.0
    if ev_home == ev_away:
        return None, ev_home, ev_away
    side, best_ev = ("home", ev_home) if ev_home > ev_away else ("away", ev_away)
    # Strictly clear the tuned EV margin after shrinking toward the market.
    return (side if best_ev > ev_threshold else None), ev_home, ev_away


def realized(row: dict, side: str | None) -> tuple[str | None, float]:
    if side is None:
        return None, 0.0
    price = row[f"{side}_price"]
    result = bt.settled(
        {"market": "ml", "side": side, "line": None},
        home_goals=row["home_goals"],
        away_goals=row["away_goals"],
        official_home_winner=row["official_home_winner"],
    )
    if result == "win":
        return result, bt.american(price)
    if result == "loss":
        return result, -1.0
    raise RuntimeError(f"unexpected moneyline settlement: {result}")


def tune_policy(history: list[dict], quote: str, season: int) -> dict:
    if not history:
        return {"shrink": 1.0, "threshold": 0.0, "train_bets": 0,
                "train_units": 0.0, "train_units_per_game": 0.0, "fallback": "no_history"}
    min_bets = max(MIN_TUNING_BETS, math.ceil(0.02 * len(history)))
    best = None
    for shrink in SHRINK_GRID:
        for threshold in EV_THRESHOLD_GRID:
            units = 0.0
            bets = 0
            for row in history:
                side, _, _ = policy_side(row, row["p_full"], shrink, threshold)
                if side is not None:
                    _, profit = realized(row, side)
                    units += profit
                    bets += 1
            if bets < min_bets:
                continue
            score = units / len(history)
            candidate = (score, threshold, shrink, bets, units)
            if best is None or candidate[:3] > best[:3]:
                best = candidate
    if best is None or best[0] <= 0.0:
        return {"shrink": 1.0, "threshold": 0.0, "train_bets": 0,
                "train_units": 0.0, "train_units_per_game": 0.0,
                "min_tuning_bets": min_bets, "fallback": "no_positive_training_rule"}
    score, threshold, shrink, bets, units = best
    return {"shrink": shrink, "threshold": threshold, "train_bets": bets,
            "train_units": units, "train_units_per_game": score,
            "min_tuning_bets": min_bets, "fallback": None}


def max_drawdown(records: list[tuple[dict, float]]) -> float:
    cumulative = peak = drawdown = 0.0
    for _, units in sorted(records, key=lambda item: (
        item[0]["game_date"], item[0]["start_time_utc"], item[0]["game_id"]
    )):
        cumulative += units
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    return drawdown


def metrics(rows: list[dict], decisions: dict[int, str | None]) -> dict:
    bets, wins, losses = 0, 0, 0
    units = 0.0
    records = []
    favorite_bets = underdog_bets = 0
    for row in rows:
        side = decisions[row["game_id"]]
        result, profit = realized(row, side)
        records.append((row, profit))
        if side is None:
            continue
        bets += 1
        units += profit
        wins += result == "win"
        losses += result == "loss"
        if side == favorite_side(row):
            favorite_bets += 1
        else:
            underdog_bets += 1
    return {
        "games": len(rows),
        "bets": bets,
        "passes": len(rows) - bets,
        "wins": int(wins),
        "losses": int(losses),
        "units": units,
        "roi": units / bets if bets else None,
        "selection_rate": bets / len(rows) if rows else None,
        "favorite_bets": favorite_bets,
        "underdog_bets": underdog_bets,
        "max_drawdown": max_drawdown(records),
        "records": records,
    }


def make_policy_decisions(rows: list[dict], predictions: dict[int, dict], quote: str,
                          score_seasons: tuple[int, ...]) -> tuple[dict[int, str | None], dict[int, dict]]:
    by_season = defaultdict(list)
    for row in rows:
        if row["season"] in score_seasons and row["game_id"] in predictions:
            by_season[row["season"]].append({**row, **predictions[row["game_id"]]})
    decisions, settings = {}, {}
    for season in score_seasons:
        history = [
            {**row, **predictions[row["game_id"]]}
            for row in rows
            if row["season"] < season and row["season"] >= SEASONS[1]
            and row["game_id"] in predictions
        ]
        config = tune_policy(history, quote, season)
        settings[season] = config
        current = by_season.get(season, [])
        for row in current:
            side, _, _ = policy_side(
                row, row["p_full"], config["shrink"], config["threshold"]
            )
            decisions[row["game_id"]] = side
        train_seasons = sorted({r["season"] for r in history})
        train_range = (
            f"{train_seasons[0]}-{train_seasons[-1]}" if train_seasons else "none"
        )
        print(
            f"POLICY FREEZE quote={quote} eval_season={season}: "
            f"tune_seasons={train_range} tune_games={len(history)} "
            f"min_tuning_bets={config.get('min_tuning_bets', 0)} "
            f"shrink_to_market={config['shrink']:.2f} EV_threshold={config['threshold']:.3f} "
            f"tune_bets={config['train_bets']} tune_units={config['train_units']:+.3f} "
            f"tune_units_per_game={config['train_units_per_game']:+.6f} "
            f"fallback={config['fallback']} scored_games={len(current)}"
        )
    return decisions, settings


def control_decisions(rows: list[dict], control: str) -> dict[int, str | None]:
    decisions = {}
    for row in rows:
        fav = favorite_side(row)
        if control == "always favorite":
            decisions[row["game_id"]] = fav
        elif control == "always underdog":
            decisions[row["game_id"]] = "away" if fav == "home" else "home"
        elif control == "market no-vig":
            ev_home = row["market_home"] * row["home_decimal"] - 1.0
            ev_away = row["market_away"] * row["away_decimal"] - 1.0
            best_side, best_ev = ("home", ev_home) if ev_home >= ev_away else ("away", ev_away)
            # A no-vig predictor cannot beat its own price when the quoted pair has
            # positive overround. A few archived open pairs are underround; retain
            # those source values and expose the resulting control bets explicitly.
            decisions[row["game_id"]] = best_side if best_ev > 1e-10 else None
        else:
            raise ValueError(control)
    return decisions


def paired_delta_ci(rows: list[dict], decisions: dict[int, str | None],
                    market_decisions: dict[int, str | None]) -> tuple[float, float]:
    by_season = defaultdict(list)
    for row in rows:
        side = decisions[row["game_id"]]
        _, candidate_profit = realized(row, side)
        _, market_profit = realized(row, market_decisions[row["game_id"]])
        by_season[row["season"]].append(candidate_profit - market_profit)
    seasons = sorted(by_season)
    if len(seasons) < 2:
        raise RuntimeError("paired season-clustered interval requires at least two seasons")
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = np.empty(BOOTSTRAP_ITERS, dtype=float)
    for i in range(BOOTSTRAP_ITERS):
        sampled = rng.choice(seasons, size=len(seasons), replace=True)
        total = count = 0
        for season in sampled:
            total += sum(by_season[int(season)])
            count += len(by_season[int(season)])
        draws[i] = total / count
    low, high = np.percentile(draws, [5, 95])
    return float(low), float(high)


def report_policy(rows: list[dict], predictions: dict[int, dict], quote: str) -> dict:
    score_rows = [row for row in rows if row["season"] in POLICY_SEASONS]
    decisions, settings = make_policy_decisions(rows, predictions, quote, POLICY_SEASONS)
    strategies = {"selective policy": decisions}
    for name in ("always favorite", "always underdog", "market no-vig"):
        strategies[name] = control_decisions(score_rows, name)

    underround_rows = [row for row in score_rows if row["market_overround"] < -1e-10]
    if underround_rows:
        print(f"\nUNDERROUND POLICY AUDIT quote={quote} rows={len(underround_rows)}")
        print("  date matchup open_or_close_prices overround candidate_side/result/units market_side/result/units")
        candidate_audit, market_audit = [], []
        for row in underround_rows:
            candidate_side = decisions[row["game_id"]]
            market_side = strategies["market no-vig"][row["game_id"]]
            candidate_result, candidate_units = realized(row, candidate_side)
            market_result, market_units = realized(row, market_side)
            if candidate_side is not None:
                candidate_audit.append((candidate_result, candidate_units))
            if market_side is not None:
                market_audit.append((market_result, market_units))
            print(
                f"  {row['game_date']} {row['home_team']}-{row['away_team']} "
                f"{row['home_price']:+.0f}/{row['away_price']:+.0f} "
                f"{row['market_overround']:+.6f} "
                f"{candidate_side or 'pass'}/{candidate_result or 'pass'}/{candidate_units:+.3f} "
                f"{market_side or 'pass'}/{market_result or 'pass'}/{market_units:+.3f}"
            )
        candidate_wins = sum(result == "win" for result, _ in candidate_audit)
        candidate_losses = sum(result == "loss" for result, _ in candidate_audit)
        market_wins = sum(result == "win" for result, _ in market_audit)
        market_losses = sum(result == "loss" for result, _ in market_audit)
        print(
            f"  aggregate candidate_bets={len(candidate_audit)} "
            f"record={candidate_wins}-{candidate_losses} "
            f"units={sum(units for _, units in candidate_audit):+.3f}; "
            f"market_bets={len(market_audit)} record={market_wins}-{market_losses} "
            f"units={sum(units for _, units in market_audit):+.3f}"
        )

    print(f"\nPOLICY RESULTS quote={quote} scored_seasons={','.join(map(str, POLICY_SEASONS))}")
    print(f"{'strategy':<23}{'games':>7}{'bets':>7}{'W-L':>11}{'units':>11}{'ROI':>10}{'select':>10}{'fav/dog':>11}{'maxDD':>10}")
    overall = {}
    for name, chosen in strategies.items():
        result = metrics(score_rows, chosen)
        overall[name] = result
        roi = "N/A" if result["roi"] is None else f"{100*result['roi']:+.2f}%"
        print(
            f"{name:<23}{result['games']:>7}{result['bets']:>7}"
            f"{(str(result['wins'])+'-'+str(result['losses'])):>11}"
            f"{result['units']:>+11.2f}{roi:>10}"
            f"{100*result['selection_rate']:>9.2f}%"
            f"{(str(result['favorite_bets'])+'/'+str(result['underdog_bets'])):>11}"
            f"{result['max_drawdown']:>10.2f}"
        )

    market_decisions = strategies["market no-vig"]
    market_bets = overall["market no-vig"]["bets"]

    print(f"\nPER-SEASON RESULTS quote={quote}")
    print(f"{'season':<11}{'strategy':<23}{'games':>7}{'bets':>7}{'W-L':>11}{'units':>11}{'ROI':>10}{'select':>10}{'maxDD':>10}{'shrink/EV':>16}")
    for season in POLICY_SEASONS:
        season_rows = [r for r in score_rows if r["season"] == season]
        if not season_rows:
            continue
        for name, chosen in strategies.items():
            season_result = metrics(season_rows, chosen)
            roi = "N/A" if season_result["roi"] is None else f"{100*season_result['roi']:+.2f}%"
            config_label = ""
            if name == "selective policy":
                cfg = settings[season]
                config_label = f"{cfg['shrink']:.2f}/{cfg['threshold']:.3f}"
            print(
                f"{season}-{str(season+1)[2:]:<7}{name:<23}{season_result['games']:>7}"
                f"{season_result['bets']:>7}"
                f"{(str(season_result['wins'])+'-'+str(season_result['losses'])):>11}"
                f"{season_result['units']:>+11.2f}{roi:>10}"
                f"{100*season_result['selection_rate']:>9.2f}%"
                f"{season_result['max_drawdown']:>10.2f}{config_label:>16}"
            )

    policy = overall["selective policy"]
    active_bets = [
        {"season": row["season"], "result": realized(row, decisions[row["game_id"]])[0],
         "price_open": row[f"home_price"] if decisions[row["game_id"]] == "home"
         else row[f"away_price"]}
        for row in score_rows if decisions[row["game_id"]] is not None
    ]
    active_bets = [r for r in active_bets if r["result"] in ("win", "loss")]
    roi_ci = bt.clustered_roi_ci(
        active_bets, iters=BOOTSTRAP_ITERS, seed=BOOTSTRAP_SEED
    ) if active_bets else None
    market = overall["market no-vig"]
    delta = (policy["units"] - market["units"]) / policy["games"] if policy["games"] else float("nan")
    delta_ci = paired_delta_ci(score_rows, decisions, market_decisions)
    active_seasons = sorted({row["season"] for row in active_bets})
    ci_text = "N/A (<2 bet-bearing seasons)" if roi_ci is None else f"[{100*roi_ci[0]:+.1f}%, {100*roi_ci[1]:+.1f}%]"
    print(
        f"\nUNCERTAINTY quote={quote}: policy_ROI_CI90={ci_text} "
        f"method=existing season-cluster bootstrap resampling {len(active_seasons)} "
        f"bet-bearing seasons, {BOOTSTRAP_ITERS} resamples, seed={BOOTSTRAP_SEED}; "
        f"active_seasons={active_seasons}"
    )
    print(
        f"PAIRED DELTA quote={quote} vs market no-vig policy "
        f"(market bets={market_bets}/{market['games']}): "
        f"{100*delta:+.3f} percentage-points of profit per eligible game "
        f"(units/game={delta:+.6f}); 90% season-cluster CI "
        f"[{100*delta_ci[0]:+.3f}, {100*delta_ci[1]:+.3f}] pp/game; "
        f"{BOOTSTRAP_ITERS} paired season-cluster resamples, seed={BOOTSTRAP_SEED}"
    )
    return {
        "overall": overall,
        "settings": settings,
        "roi_ci": roi_ci,
        "delta": delta,
        "delta_ci": delta_ci,
        "score_rows": score_rows,
    }


def verdict(primary: dict) -> str:
    policy = primary["overall"]["selective policy"]
    roi = policy["roi"]
    roi_ci = primary["roi_ci"]
    delta, delta_ci = primary["delta"], primary["delta_ci"]
    if roi is not None and roi > 0 and roi_ci is not None and roi_ci[0] > 0:
        if delta > 0 and delta_ci[0] > 0:
            return "ADOPT_CANDIDATE"
        if delta > 0 and delta_ci[0] <= 0:
            return "INCONCLUSIVE"
    if roi is not None and roi > 0 and (roi_ci is None or roi_ci[0] <= 0):
        return "INCONCLUSIVE"
    return "NOT_ADOPTED"


def main() -> None:
    required = (SBR_GZIP, bt.CANONICAL, bt.FEATURES, HARNESS_DIR / "backtest_matchup_strategy.py")
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("required study input missing: " + ", ".join(missing))
    print("INPUTS")
    for path in required:
        print(f"  {path} sha256={sha256(path)}")
    print(
        f"CONFIG: seasons={SEASONS}; policy_score_seasons={POLICY_SEASONS}; "
        f"quotes=open,close; bootstrap_iters={BOOTSTRAP_ITERS}; seed={BOOTSTRAP_SEED}; "
        f"CI=90%; calibration_C={CALIBRATION_C}; feature_model_C={FEATURE_MODEL_C}; "
        f"shrink_grid={SHRINK_GRID}; EV_threshold_grid={EV_THRESHOLD_GRID}; "
        f"minimum_tuning_bets={MIN_TUNING_BETS}"
    )

    rows, recon, season_counts = build_rows()
    print("\nPOPULATION RECONCILIATION")
    for key in (
        "sbr_rows", "team_unmapped", "no_canonical_match", "orientation_reversed_and_aligned",
        "no_complete_pregame_features", "no_walkforward_forecast", "matched_with_forecast",
        "sbr_final_winners_checked", "sbr_final_winner_mismatch", "sbr_final_missing",
    ):
        print(f"  {key}={recon[key]}")
    print("  source_rows_by_season=" + ",".join(f"{s}:{season_counts[s]}" for s in sorted(season_counts)))
    print("  rows_with_forecast_by_season=" + ",".join(
        f"{s}:{sum(r['season'] == s for r in rows)}" for s in sorted({r['season'] for r in rows})
    ))

    quote_rows, predictions = {}, {}
    for quote in QUOTE_NAMES:
        quote_rows[quote], missing = make_quote_rows(rows, quote)
        if not quote_rows[quote]:
            raise RuntimeError(f"no complete {quote} moneyline quote rows")
        print(
            f"\nQUOTE COVERAGE {quote}: complete_two_sided_prices={len(quote_rows[quote])} "
            f"missing_price_rows_by_season=" + ",".join(
                f"{s}:{missing[s]}" for s in sorted(missing) if missing[s] > 0
            )
        )
        print("  complete_quote_rows_by_season=" + ",".join(
            f"{s}:{sum(r['season'] == s for r in quote_rows[quote])}"
            for s in sorted({r["season"] for r in quote_rows[quote]})
        ))
        overrounds = np.asarray([row["market_overround"] for row in quote_rows[quote]], dtype=float)
        underround = [row for row in quote_rows[quote] if row["market_overround"] < -1e-10]
        print(
            f"  source_price_integrity: underround_pairs={len(underround)} "
            f"overround_min={overrounds.min():+.6f} overround_max={overrounds.max():+.6f}"
        )
        if underround:
            print("  underround_source_rows=" + json.dumps([
                {
                    "season": row["season"], "date": row["game_date"],
                    "home": row["home_team"], "away": row["away_team"],
                    "home_price": row["home_price"], "away_price": row["away_price"],
                    "overround": round(row["market_overround"], 6),
                }
                for row in underround
            ], sort_keys=True))
        predictions[quote] = forecast_probabilities(quote_rows[quote], quote)
        predictor_report(quote_rows[quote], predictions[quote], quote)

    open_policy_dates = defaultdict(list)
    for row in quote_rows["open"]:
        if row["season"] in POLICY_SEASONS:
            open_policy_dates[row["season"]].append(row["sbr_game_date"])
    print_season_coverage(
        "opening-price policy score rows from SBR", open_policy_dates, POLICY_SEASONS
    )

    primary = report_policy(quote_rows["open"], predictions["open"], "open")
    open_screened = [row for row in quote_rows["open"] if row["market_overround"] >= -1e-10]
    if len(open_screened) != len(quote_rows["open"]):
        excluded = len(quote_rows["open"]) - len(open_screened)
        print(
            f"\nOPEN PRICE-INTEGRITY SENSITIVITY: refit all expanding models and policy "
            f"after excluding {excluded} underround pairs; retained_games={len(open_screened)}"
        )
        screened_predictions = forecast_probabilities(open_screened, "open-screened")
        predictor_report(open_screened, screened_predictions, "open-screened")
        screened = report_policy(open_screened, screened_predictions, "open-screened")
        print(f"SCREENED OPEN SENSITIVITY VERDICT: {verdict(screened)}")
    _closing = report_policy(quote_rows["close"], predictions["close"], "close")
    final_verdict = verdict(primary)
    print(f"\nVERDICT (primary quote=open): {final_verdict}")
    print(
        "CAVEAT: SBR open/close archives have no timestamped pregame execution record; "
        "these are quoted-price historical sensitivities, not verified fills."
    )


if __name__ == "__main__":
    with threadpool_limits(limits=1):
        main()
