#!/usr/bin/env python3
"""Run the frozen, season-blocked NHL goalie keep-rule research protocol."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib
import json
import math
import random
import subprocess
import sys
import warnings
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path

import numpy as np
import scipy.sparse as sp
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.exceptions import ConvergenceWarning
from sklearn.preprocessing import OneHotEncoder
from threadpoolctl import threadpool_limits


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
AUDIT_DIR = REPO / "research/nhl/newinfo-audit-2026-10-20"
sys.path.insert(0, str(AUDIT_DIR))
audit = importlib.import_module("audit_nhl_sources")

FEATURE_FILE = HERE / "goalie_features.csv"
SBR_FILE = REPO / "research/nhl/sbr-odds-archive-2026-10-19/games_2018_2023.jsonl.gz"
CANONICAL_FILE = audit.CANONICAL_FILE
SPEC_FILE = HERE / "MODEL-SPEC.md"
JOIN_FILE = HERE / "JOIN-AUDIT.md"
PREREG_FILE = HERE / "PREREG-GOALIE-KEEP.md"
PREDICTIONS_FILE = HERE / "oof_predictions.csv"
RESULTS_FILE = HERE / "RESULTS.md"

EVAL_SEASONS = (2019, 2020, 2021, 2022)
TRAIN_SEASON = 2018
FEATURE_NAMES = (
    "starter_last",
    "starter_games_trailing10",
    "starter_gsax_trailing10",
    "starter_savepct_trailing10",
    "team_goalie_gsax_trailing10",
    "starter_changed",
)
NUMERIC_NAMES = FEATURE_NAMES[1:]
CANDIDATES = {
    "A": (0.01, 1.50),
    "B": (0.01, 1.80),
    "C": (0.02, 1.50),
    "D": (0.02, 1.80),
}
BOOTSTRAP_ITERS = 5000
BOOTSTRAP_SEED = 20261020
EXPECTED = {
    "archive": 5132,
    "regular": 4872,
    "complete_features": 4765,
    "eligible": 4763,
    "training": 1254,
    "oof": 3509,
    "venue_reversed": 1,
    "scoreline_differences": 2,
    "winner_disagreements": 0,
    "underround_pairs": 3,
}
EXPECTED_SEASON = {
    2018: (1271, 1254),
    2019: (1082, 1064),
    2020: (868, 849),
    2021: (1312, 1289),
    2022: (339, 307),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        return list(reader)


def numeric(value: object, field: str, game_id: int) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field} for game {game_id}: {value!r}") from exc
    if not math.isfinite(result):
        raise ValueError(f"non-finite {field} for game {game_id}: {value!r}")
    return result


def is_present(value: object) -> bool:
    if value is None or str(value).strip() == "":
        return False
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid numeric source value: {value!r}") from exc
    if not math.isfinite(result):
        raise ValueError(f"non-finite numeric source value: {value!r}")
    return True


def integer_value(value: object, field: str, game_id: int) -> int:
    result = numeric(value, field, game_id)
    if not result.is_integer():
        raise ValueError(f"non-integer {field} for game {game_id}: {value!r}")
    return int(result)


def decimal_odds(american: object, game_id: int, side: str) -> float:
    price = numeric(american, f"{side} ml_open", game_id)
    if price == 0:
        raise ValueError(f"zero American odds for game {game_id}, {side}")
    return 1.0 + (price / 100.0 if price > 0 else 100.0 / abs(price))


def logit(probability: float) -> float:
    p = min(1.0 - 1e-6, max(1e-6, probability))
    return math.log(p / (1.0 - p))


def profit(side: str | None, row: dict) -> float:
    if side is None:
        return 0.0
    won = (row["y"] == 1 and side == "home") or (row["y"] == 0 and side == "away")
    if not won:
        return -1.0
    american = row[f"{side}_american"]
    return american / 100.0 if american > 0 else 100.0 / abs(american)


def read_inputs() -> tuple[list[dict], dict]:
    for path in (FEATURE_FILE, SBR_FILE, CANONICAL_FILE, SPEC_FILE, JOIN_FILE, PREREG_FILE):
        if not path.is_file():
            raise FileNotFoundError(f"required frozen input is missing: {path}")

    features = csv_rows(FEATURE_FILE)
    feature_by_id = {int(row["game_id"]): row for row in features}
    if len(feature_by_id) != len(features):
        raise ValueError("duplicate game_id in goalie feature CSV")

    captured = StringIO()
    with redirect_stdout(captured):
        sbr_rows, linked, _ = audit.load_crosswalk()
    crosswalk_output = captured.getvalue().strip()
    if set(feature_by_id) != set(linked):
        raise ValueError(
            "feature/crosswalk game_id sets differ: "
            f"feature_only={len(set(feature_by_id)-set(linked))} "
            f"crosswalk_only={len(set(linked)-set(feature_by_id))}"
        )

    regular_by_season = Counter()
    dates_by_season: dict[int, list[str]] = defaultdict(list)
    complete_by_season = Counter()
    eligible_rows: list[dict] = []
    season_rows: list[dict] = []
    feature_missing_ids: list[int] = []
    price_missing_ids: list[int] = []
    final_missing_ids: list[int] = []
    reversed_games: list[tuple] = []
    score_differences: list[tuple] = []
    winner_disagreements: list[tuple] = []
    underround_ids: list[int] = []

    if len(sbr_rows) != EXPECTED["archive"]:
        raise ValueError(f"SBR archive row count changed: {len(sbr_rows)}")

    for game_id, item in linked.items():
        canonical = item["canonical"]
        sbr = item["sbr"]
        season = int(canonical["season"])
        if int(canonical["game_type"]) != 2 or season not in EXPECTED_SEASON:
            continue
        regular_by_season[season] += 1
        dates_by_season[season].append(item["date"])
        feature = feature_by_id[game_id]
        for field in ("season", "game_date", "home_team", "away_team"):
            expected = str(canonical[field]) if field == "season" else canonical[field]
            if str(feature[field]) != str(expected):
                raise ValueError(
                    f"feature/canonical identity mismatch game={game_id} field={field}: "
                    f"{feature[field]!r} != {expected!r}"
                )

        sbr_home_name = sbr["home"]["team"]
        sbr_away_name = sbr["away"]["team"]
        if sbr_home_name not in audit.SBR_TEAM_CODES or sbr_away_name not in audit.SBR_TEAM_CODES:
            raise ValueError(f"unmapped SBR team identity for game {game_id}")
        sbr_home_codes = set(audit.SBR_TEAM_CODES[sbr_home_name])
        sbr_away_codes = set(audit.SBR_TEAM_CODES[sbr_away_name])
        canonical_home = canonical["home_team"]
        canonical_away = canonical["away_team"]
        if canonical_home in sbr_home_codes and canonical_away in sbr_away_codes:
            source_for_home, source_for_away = sbr["home"], sbr["away"]
            orientation = "aligned"
        elif canonical_home in sbr_away_codes and canonical_away in sbr_home_codes:
            source_for_home, source_for_away = sbr["away"], sbr["home"]
            orientation = "reversed"
            reversed_games.append((game_id, item["date"], sbr_home_name, sbr_away_name,
                                   canonical_home, canonical_away))
        else:
            raise ValueError(
                f"cannot align SBR teams to canonical identities for game {game_id}: "
                f"SBR={sbr_home_name}/{sbr_away_name}, canonical={canonical_home}/{canonical_away}"
            )

        y = integer_value(canonical["official_home_winner"], "official_home_winner", game_id)
        if y not in (0, 1):
            raise ValueError(f"invalid canonical official_home_winner for {game_id}: {y}")
        home_score = integer_value(canonical["official_home_score"], "official_home_score", game_id)
        away_score = integer_value(canonical["official_away_score"], "official_away_score", game_id)

        finals_present = is_present(source_for_home.get("final")) and is_present(source_for_away.get("final"))
        if not finals_present:
            final_missing_ids.append(game_id)
        else:
            sbr_home_score = integer_value(source_for_home["final"], "SBR home final", game_id)
            sbr_away_score = integer_value(source_for_away["final"], "SBR away final", game_id)
            if sbr_home_score == sbr_away_score:
                raise ValueError(f"tied SBR final for completed game {game_id}")
            sbr_winner = 1 if sbr_home_score > sbr_away_score else 0
            if sbr_winner != y:
                winner_disagreements.append((game_id, item["date"], sbr_winner, y))
            if (sbr_home_score, sbr_away_score) != (home_score, away_score):
                score_differences.append((game_id, item["date"], canonical_home, canonical_away,
                                          sbr_home_score, sbr_away_score, home_score, away_score,
                                          sbr_winner, y))

        open_present = is_present(source_for_home.get("ml_open")) and is_present(source_for_away.get("ml_open"))
        if not open_present:
            price_missing_ids.append(game_id)

        feature_complete = all(
            is_present(feature[f"{side}_{name}"])
            for side in ("home", "away")
            for name in FEATURE_NAMES
        )
        if not feature_complete:
            feature_missing_ids.append(game_id)
            continue
        complete_by_season[season] += 1

        if not open_present or not finals_present:
            continue
        if winner_disagreements and winner_disagreements[-1][0] == game_id:
            continue

        home_decimal = decimal_odds(source_for_home["ml_open"], game_id, "home")
        away_decimal = decimal_odds(source_for_away["ml_open"], game_id, "away")
        home_american = numeric(source_for_home["ml_open"], "home ml_open", game_id)
        away_american = numeric(source_for_away["ml_open"], "away ml_open", game_id)
        p_home_raw, p_away_raw = 1.0 / home_decimal, 1.0 / away_decimal
        total = p_home_raw + p_away_raw
        p_market_home = p_home_raw / total
        p_market_away = p_away_raw / total
        if total < 1.0 - 1e-10:
            underround_ids.append(game_id)

        row = {
            "game_id": game_id,
            "season": season,
            "season_label": item["season_label"],
            "game_date": item["date"],
            "home_team": canonical_home,
            "away_team": canonical_away,
            "sbr_home_team": sbr_home_name,
            "sbr_away_team": sbr_away_name,
            "sbr_orientation": orientation,
            "y": y,
            "home_score": home_score,
            "away_score": away_score,
            "home_decimal": home_decimal,
            "away_decimal": away_decimal,
            "home_american": home_american,
            "away_american": away_american,
            "p_market_home": p_market_home,
            "p_market_away": p_market_away,
            "home_starter_last": str(feature["home_starter_last"]),
            "away_starter_last": str(feature["away_starter_last"]),
        }
        for side in ("home", "away"):
            for name in NUMERIC_NAMES:
                row[f"{side}_{name}"] = numeric(feature[f"{side}_{name}"], f"{side}_{name}", game_id)
        season_rows.append(row)
        eligible_rows.append(row)

    if winner_disagreements:
        raise ValueError(f"SBR/canonical moneyline winner disagreements: {winner_disagreements}")
    if regular_by_season != Counter({s: v[0] for s, v in EXPECTED_SEASON.items()}):
        raise ValueError(f"regular-season counts changed: {dict(regular_by_season)}")
    eligible_by_season = Counter(row["season"] for row in eligible_rows)
    complete_expected = {2018: 1254, 2019: 1064, 2020: 851, 2021: 1289, 2022: 307}
    if dict(complete_by_season) != complete_expected:
        raise ValueError(f"complete-feature counts changed: {dict(complete_by_season)}")
    if dict(eligible_by_season) != {s: v[1] for s, v in EXPECTED_SEASON.items()}:
        raise ValueError(f"eligible counts changed: {dict(eligible_by_season)}")

    eval_count = sum(eligible_by_season[s] for s in EVAL_SEASONS)
    facts = {
        "crosswalk_output": crosswalk_output,
        "archive_rows": len(sbr_rows),
        "linked_ids": len(linked),
        "regular_by_season": dict(sorted(regular_by_season.items())),
        "date_bounds_by_season": {
            season: (min(values), max(values)) for season, values in sorted(dates_by_season.items())
        },
        "complete_by_season": dict(sorted(complete_by_season.items())),
        "eligible_by_season": dict(sorted(eligible_by_season.items())),
        "regular_total": sum(regular_by_season.values()),
        "complete_total": sum(complete_by_season.values()),
        "eligible_total": len(eligible_rows),
        "training_total": eligible_by_season[TRAIN_SEASON],
        "oof_total": eval_count,
        "feature_missing_ids": sorted(feature_missing_ids),
        "price_missing_ids": sorted(price_missing_ids),
        "final_missing_ids": sorted(final_missing_ids),
        "reversed_games": reversed_games,
        "score_differences": score_differences,
        "winner_disagreements": winner_disagreements,
        "underround_ids": sorted(underround_ids),
        "regular_rows": season_rows,
        "eligible_rows": eligible_rows,
    }
    checks = {
        "archive": facts["archive_rows"],
        "regular": facts["regular_total"],
        "complete_features": facts["complete_total"],
        "eligible": facts["eligible_total"],
        "training": facts["training_total"],
        "oof": facts["oof_total"],
        "venue_reversed": len(reversed_games),
        "scoreline_differences": len(score_differences),
        "winner_disagreements": len(winner_disagreements),
        "underround_pairs": len(underround_ids),
    }
    for name, expected in EXPECTED.items():
        if checks[name] != expected:
            raise ValueError(f"frozen expected {name}={expected}, observed {checks[name]}")
    fixed_ids = {
        "price_missing_ids": [2020020316],
        "final_missing_ids": [2020020371],
        "underround_ids": [2021020034, 2021020906, 2021020945],
    }
    for name, expected in fixed_ids.items():
        if facts[name] != expected:
            raise ValueError(f"frozen expected {name}={expected}, observed {facts[name]}")
    if facts["date_bounds_by_season"][2022] != ("2022-10-11", "2022-11-27"):
        raise ValueError(f"partial final-season date span changed: {facts['date_bounds_by_season'][2022]}")
    if facts["reversed_games"] != [
        (2019020740, "2020-01-17", "Pittsburgh", "Detroit", "DET", "PIT")
    ]:
        raise ValueError(f"venue reversal identity changed: {facts['reversed_games']}")
    expected_score_differences = [
        (2020020003, "2021-01-13", "TOR", "MTL", 1, 0, 5, 4, 1, 1),
        (2021020682, "2022-01-17", "BUF", "DET", 0, 1, 2, 3, 0, 0),
    ]
    if facts["score_differences"] != expected_score_differences:
        raise ValueError(f"SBR/canonical scoreline difference set changed: {facts['score_differences']}")
    return eligible_rows, facts


def print_audit(facts: dict) -> None:
    print("FROZEN INPUT AUDIT — no fitting performed")
    print(f"archive={facts['archive_rows']} crosswalk_ids={facts['linked_ids']} unmatched=0")
    print(
        f"regular={facts['regular_total']} complete_features={facts['complete_total']} "
        f"eligible={facts['eligible_total']} training_only={facts['training_total']} "
        f"oof={facts['oof_total']}"
    )
    print("season start_year regular complete_features eligible role")
    for season, regular in facts["regular_by_season"].items():
        role = "training only" if season == TRAIN_SEASON else "OOF evaluation"
        print(
            f"{season} {regular} {facts['complete_by_season'][season]} "
            f"{facts['eligible_by_season'][season]} {role}"
        )
    print(f"feature_incomplete_regular_games={len(facts['feature_missing_ids'])}")
    print(f"missing_open_pair_ids={facts['price_missing_ids']}")
    print(f"missing_final_pair_ids={facts['final_missing_ids']}")
    print(f"venue_reversals={facts['reversed_games']}")
    print(f"scoreline_differences={facts['score_differences']}")
    print(f"winner_disagreements={len(facts['winner_disagreements'])}")
    print(f"underround_eligible_ids={facts['underround_ids']}")
    print(f"date_bounds_by_season={facts['date_bounds_by_season']}")


def model() -> LogisticRegression:
    return LogisticRegression(
        penalty="l2", C=1.0, solver="lbfgs", fit_intercept=True,
        class_weight=None, max_iter=2000, tol=1e-8, random_state=0,
    )


def market_matrix(rows: list[dict]) -> np.ndarray:
    return np.asarray([[logit(row["p_market_home"])] for row in rows], dtype=np.float64)


def goalie_matrix(rows: list[dict], encoders: tuple[OneHotEncoder, OneHotEncoder] | None = None):
    numeric_values = np.asarray(
        [[row[f"{side}_{name}"] for side in ("home", "away") for name in NUMERIC_NAMES]
         for row in rows],
        dtype=np.float64,
    )
    if not np.isfinite(numeric_values).all():
        raise ValueError("eligible goalie numeric matrix contains non-finite values")
    categories = [
        np.asarray([[row[f"{side}_starter_last"]] for row in rows], dtype=object)
        for side in ("home", "away")
    ]
    if encoders is None:
        fitted = []
        encoded = []
        for values in categories:
            encoder = OneHotEncoder(handle_unknown="ignore", sparse_output=True, dtype=np.float64)
            encoded.append(encoder.fit_transform(values))
            fitted.append(encoder)
        encoders = (fitted[0], fitted[1])
    else:
        encoded = [encoder.transform(values) for encoder, values in zip(encoders, categories)]
    dense = np.column_stack((market_matrix(rows), numeric_values))
    return sp.hstack((sp.csr_matrix(dense), encoded[0], encoded[1]), format="csr"), encoders


def score_fold(train: list[dict], held: list[dict]) -> dict[int, dict[str, float]]:
    y_train = np.asarray([row["y"] for row in train], dtype=np.int8)
    if len(set(y_train.tolist())) != 2:
        raise ValueError("training fold does not contain both outcome classes")
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        raw_model = model().fit(market_matrix(train), y_train)
        full_train, encoders = goalie_matrix(train)
        full_model = model().fit(full_train, y_train)
    raw_prob = raw_model.predict_proba(market_matrix(held))[:, 1]
    full_test, _ = goalie_matrix(held, encoders)
    full_prob = full_model.predict_proba(full_test)[:, 1]
    if not np.isfinite(raw_prob).all() or not np.isfinite(full_prob).all():
        raise ValueError("non-finite predicted probability")
    if ((raw_prob <= 0) | (raw_prob >= 1) | (full_prob <= 0) | (full_prob >= 1)).any():
        raise ValueError("predicted probability outside the open unit interval")
    return {
        row["game_id"]: {"p_market_calibrated_home": float(p0), "p_goalie_home": float(p1)}
        for row, p0, p1 in zip(held, raw_prob, full_prob)
    }


def market_control_side(row: dict) -> str | None:
    ev = {
        "home": row["p_market_home"] * row["home_decimal"] - 1.0,
        "away": row["p_market_away"] * row["away_decimal"] - 1.0,
    }
    best = max(("home", "away"), key=lambda side: ev[side])
    return best if ev[best] > 0.0 else None


def select_side(row: dict, prediction: dict, candidate: str) -> str | None:
    edge_cut, min_price = CANDIDATES[candidate]
    p = prediction["p_goalie_home"]
    choices = []
    for side, p_model, p_market in (
        ("home", p, row["p_market_home"]),
        ("away", 1.0 - p, row["p_market_away"]),
    ):
        price = row[f"{side}_decimal"]
        if p_model - p_market >= edge_cut and price >= min_price and p_model * price - 1.0 > 0:
            choices.append(side)
    if len(choices) > 1:
        raise ValueError(f"both sides selected for game {row['game_id']} by candidate {candidate}")
    return choices[0] if choices else None


def choose_candidate(history: list[dict]) -> tuple[str, dict]:
    if not history:
        return "D", {"reason": "initial fold; no prior OOF games"}
    market_sides = {row["game_id"]: market_control_side(row) for row in history}
    eligible = []
    diagnostics = {}
    for name in ("A", "B", "C", "D"):
        decisions = {row["game_id"]: select_side(row, row["prediction"], name) for row in history}
        bets = sum(side is not None for side in decisions.values())
        candidate_units = sum(profit(decisions[row["game_id"]], row) for row in history)
        market_units = sum(profit(market_sides[row["game_id"]], row) for row in history)
        score = (candidate_units - market_units) / len(history)
        diagnostics[name] = {"bets": bets, "paired_units_per_game": score}
        if bets >= 200:
            eligible.append((score, CANDIDATES[name][0], CANDIDATES[name][1], name))
    if not eligible:
        return "D", {"reason": "no candidate had 200 prior OOF bets", "candidates": diagnostics}
    chosen = max(eligible)
    return chosen[3], {"reason": "highest prior paired units per eligible game", "candidates": diagnostics}


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def log_loss(y: np.ndarray, p: np.ndarray) -> float:
    safe = np.clip(p, 1e-12, 1.0 - 1e-12)
    return float(-np.mean(y * np.log(safe) + (1.0 - y) * np.log(1.0 - safe)))


def block_interval(rows: list[dict], value_fn, iters: int = BOOTSTRAP_ITERS) -> tuple[float, float]:
    seasons = sorted({row["season"] for row in rows})
    if len(seasons) < 2:
        raise ValueError("season-block interval needs at least two evaluation blocks")
    blocks = {season: [row for row in rows if row["season"] == season] for season in seasons}
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    sampled = rng.choice(seasons, size=(iters, len(seasons)), replace=True)
    draws = np.empty(iters, dtype=np.float64)
    for i, sample in enumerate(sampled):
        values = [value for season in sample for value in value_fn(blocks[int(season)])]
        draws[i] = float(np.mean(values))
    low, high = np.percentile(draws, [5, 95])
    return float(low), float(high)


def roi_interval(bets: list[dict]) -> tuple[float, float] | None:
    seasons = sorted({row["season"] for row in bets})
    if len(seasons) < 2:
        return None
    blocks = {season: [row for row in bets if row["season"] == season] for season in seasons}
    rng = random.Random(BOOTSTRAP_SEED)
    draws = []
    for _ in range(BOOTSTRAP_ITERS):
        units = 0.0
        staked = 0
        for season in (rng.choice(seasons) for _ in seasons):
            for row in blocks[season]:
                units += row["candidate_profit"]
                staked += 1
        if staked:
            draws.append(units / staked)
    draws.sort()
    if not draws:
        return None
    return round(draws[int(0.05 * len(draws))], 3), round(draws[int(0.95 * len(draws)) - 1], 3)


def fmt(value: float | None, places: int = 6) -> str:
    return "N/A" if value is None else f"{value:.{places}f}"


def evaluate(rows: list[dict], facts: dict) -> tuple[list[dict], str]:
    all_scored = []
    history: list[dict] = []
    folds: list[dict] = []
    fold_lines = []
    for season in EVAL_SEASONS:
        train = [row for row in rows if row["season"] < season]
        held = [row for row in rows if row["season"] == season]
        if not train or not held:
            raise ValueError(f"empty fold train/test: season={season}, train={len(train)}, held={len(held)}")
        preds = score_fold(train, held)
        candidate, selection = choose_candidate(history)
        current = []
        for row in held:
            scored = dict(row)
            scored["prediction"] = preds[row["game_id"]]
            scored["selected_rule"] = candidate
            scored["selected_side"] = select_side(scored, scored["prediction"], candidate)
            if scored["selected_side"] is None:
                scored["selected_edge"] = None
                scored["selected_price"] = None
                scored["selected_ev"] = None
            else:
                side = scored["selected_side"]
                p_model = scored["prediction"]["p_goalie_home"] if side == "home" else 1.0 - scored["prediction"]["p_goalie_home"]
                scored["selected_edge"] = p_model - scored[f"p_market_{side}"]
                scored["selected_price"] = scored[f"{side}_decimal"]
                scored["selected_ev"] = p_model * scored["selected_price"] - 1.0
            scored["market_control_side"] = market_control_side(scored)
            scored["candidate_profit"] = profit(scored["selected_side"], scored)
            scored["market_profit"] = profit(scored["market_control_side"], scored)
            scored["candidate_bet"] = scored["selected_side"] is not None
            current.append(scored)
        history.extend(current)
        all_scored.extend(current)
        folds.append({
            "season": season,
            "train_games": len(train),
            "held_games": len(held),
            "selected_rule": candidate,
            "selection": selection,
        })
        fold_lines.append(
            f"| {season}-{str(season + 1)[2:]} | {len(train)} | {len(held)} | {candidate} | "
            f"{selection['reason']}" + (
                " — " + "; ".join(
                    f"{name}: {result['bets']} bets, delta={result['paired_units_per_game']:+.6f} units/game"
                    for name, result in selection.get("candidates", {}).items()
                ) if selection.get("candidates") else ""
            ) + " |"
        )

    if len(all_scored) != 3509 or len({row["game_id"] for row in all_scored}) != 3509:
        raise ValueError(f"unexpected OOF row/id count: rows={len(all_scored)}")

    y = np.asarray([row["y"] for row in all_scored], dtype=np.float64)
    p_market = np.asarray([row["p_market_home"] for row in all_scored], dtype=np.float64)
    p_calibrated = np.asarray([row["prediction"]["p_market_calibrated_home"] for row in all_scored])
    p_goalie = np.asarray([row["prediction"]["p_goalie_home"] for row in all_scored])
    metrics = {
        "raw market": (brier(y, p_market), log_loss(y, p_market)),
        "market-only logistic": (brier(y, p_calibrated), log_loss(y, p_calibrated)),
        "goalie logistic": (brier(y, p_goalie), log_loss(y, p_goalie)),
    }
    brier_delta = metrics["goalie logistic"][0] - metrics["raw market"][0]
    brier_ci = block_interval(
        all_scored,
        lambda block: [
            (row["prediction"]["p_goalie_home"] - row["y"]) ** 2
            - (row["p_market_home"] - row["y"]) ** 2
            for row in block
        ],
    )
    delta = sum(row["candidate_profit"] - row["market_profit"] for row in all_scored) / len(all_scored)
    delta_ci = block_interval(
        all_scored,
        lambda block: [row["candidate_profit"] - row["market_profit"] for row in block],
    )
    bets = [row for row in all_scored if row["candidate_bet"]]
    roi = sum(row["candidate_profit"] for row in bets) / len(bets) if bets else None
    roi_ci = roi_interval(bets)
    units = sum(row["candidate_profit"] for row in all_scored)
    market_bets = sum(row["market_control_side"] is not None for row in all_scored)
    market_units = sum(row["market_profit"] for row in all_scored)

    per_season = []
    for season in EVAL_SEASONS:
        block = [row for row in all_scored if row["season"] == season]
        block_bets = [row for row in block if row["candidate_bet"]]
        block_units = sum(row["candidate_profit"] for row in block)
        block_market_units = sum(row["market_profit"] for row in block)
        block_market_bets = sum(row["market_control_side"] is not None for row in block)
        per_season.append(
            f"| {season}-{str(season + 1)[2:]} | {len(block)} | {block[0]['selected_rule']} | "
            f"{len(block_bets)} | {len(block_bets)/len(block):.3%} | {block_units:+.3f} | "
            f"{(block_units/len(block_bets)) if block_bets else float('nan'):+.3%} | "
            f"{block_market_bets} | {block_market_units:+.3f} | "
            f"{(block_units-block_market_units)/len(block):+.6f} |"
        )
    if len(bets) < 200:
        verdict = "INCONCLUSIVE: fewer than 200 aggregate OOF bets."
    elif roi_ci is not None and roi_ci[0] > 0 and delta_ci[0] > 0 and brier_ci[1] < 0:
        verdict = "ADOPT keep rule for further research only; the preregistered research conditions are met. This is not production approval."
    elif (roi_ci is not None and roi_ci[1] < 0) or delta_ci[1] < 0 or brier_ci[0] > 0:
        verdict = "DISCARD keep rule under this preregistration; at least one registered adverse interval criterion is met."
    else:
        verdict = "INCONCLUSIVE: neither the adoption nor discard conditions are met."

    model_inputs = (
        (FEATURE_FILE, "goalie_features.csv"),
        (SBR_FILE, "../sbr-odds-archive-2026-10-19/games_2018_2023.jsonl.gz"),
        (CANONICAL_FILE, "canonical_games_v1_7cd2fc9a6e84470c.csv (canonical game table)"),
        (PREREG_FILE, "PREREG-GOALIE-KEEP.md"),
        (SPEC_FILE, "MODEL-SPEC.md"),
        (JOIN_FILE, "JOIN-AUDIT.md"),
        (Path(__file__).resolve(), "run_goalie_keep.py"),
    )
    hash_lines = "\n".join(f"- `{label}`: `{sha256(path)}`" for path, label in model_inputs)
    roi_ci_text = "N/A (<2 bet-bearing seasons)" if roi_ci is None else f"[{roi_ci[0]:+.1%}, {roi_ci[1]:+.1%}]"
    report = f"""# NHL goalie keep-rule walk-forward results

**Run date:** {date.today().isoformat()}<br>
**Protocol:** signed `PREREG-GOALIE-KEEP.md`, frozen learner `MODEL-SPEC.md`<br>
**Learner:** scikit-learn {sklearn.__version__}; two logistic fits per evaluation fold; one process / one numerical-library thread.

## Frozen input hashes

{hash_lines}

## Denominators and season coverage

There are **4,763 eligible regular-season games** in the combined registered population. This includes **1,254 training-only games from 2018-19**. The separate out-of-fold evaluation denominator is **3,509 games** across four blocks. The final block is the **partial 2022-23 archive slice of 339 games, dated 2022-10-11 through 2022-11-27**; 307 eligible rows in that seven-week slice are included in OOF evaluation. It is not a complete season holdout.

Before metrics, the eligibility audit excludes **107** regular-season games under the six-feature complete-case rule, **one** feature-complete game without both opening prices (`2020020316`), and **one** feature-complete game without both final scores (`2020020371`). These are separate game IDs; none is treated as a pass or loss.

## Fold-level rule selection

| Evaluation block | Prior eligible training rows | OOF games | Selected candidate | Selection basis |
| --- | ---: | ---: | --- | --- |
{chr(10).join(fold_lines)}

## Predictor quality

All predictors are scored on the same 3,509 OOF games against canonical home winner. No AUC is reported.

| Predictor | Brier | Log loss | Δ Brier vs raw market |
| --- | ---: | ---: | ---: |
| Raw no-vig opening market | {metrics['raw market'][0]:.6f} | {metrics['raw market'][1]:.6f} | 0.000000 |
| Market-only logistic diagnostic | {metrics['market-only logistic'][0]:.6f} | {metrics['market-only logistic'][1]:.6f} | {metrics['market-only logistic'][0]-metrics['raw market'][0]:+.6f} |
| Goalie logistic | {metrics['goalie logistic'][0]:.6f} | {metrics['goalie logistic'][1]:.6f} | {brier_delta:+.6f} |

Goalie-model `ΔBrier` 90% season-block interval: **[{brier_ci[0]:+.6f}, {brier_ci[1]:+.6f}]**.

## Frozen keep-rule policy

| OOF block | Eligible games | Candidate | Bets | Selection rate | Net units | ROI | Market-control bets | Market-control units | Paired units/game vs market control |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(per_season)}
| **Aggregate** | **{len(all_scored)}** | sequential | **{len(bets)}** | **{len(bets)/len(all_scored):.3%}** | **{units:+.3f}** | **{(roi if roi is not None else float('nan')):+.3%}** | **{market_bets}** | **{market_units:+.3f}** | **{delta:+.6f}** |

- Goalie-rule one-unit ROI: {roi_ci_text} (5,000 resamples; seed 20261020).
- Paired policy delta: {delta:+.6f} units per eligible game; 90% season-block interval [{delta_ci[0]:+.6f}, {delta_ci[1]:+.6f}].
- Market no-vig control: {market_bets} bets / {len(all_scored)} games; net units {market_units:+.3f}.
- Market no-vig control ROI: {(market_units/market_bets) if market_bets else float('nan'):+.3%}.
- Goalie policy total: {len(bets)} bets / {len(all_scored)} games; net units {units:+.3f}.

## Registered stopping decision

**{verdict}**

The verdict applies only to the frozen research candidate and this historical opening-quote archive. Four blocks, including one short partial season, provide coarse uncertainty estimates. This result is not approval to deploy.

## Join and source disclosures

See `JOIN-AUDIT.md` for the complete identity reconciliation, venue reversal, exclusions, scoreline differences, and separate training/evaluation denominators. Underround opening pairs retained in the eligible population: {len(facts['underround_ids'])}.

## Per-game out-of-fold predictions

`oof_predictions.csv` contains every one of the 3,509 eligible evaluation rows, including passes, the selected candidate, market-control decision, target, raw and fitted probabilities, and settled units.
"""
    return all_scored, report


def write_outputs(scored: list[dict], report: str) -> None:
    fields = [
        "game_id", "season_label", "game_date", "home_team", "away_team", "sbr_home_team",
        "sbr_away_team", "sbr_orientation", "y", "home_score", "away_score",
        "home_decimal", "away_decimal", "p_market_home", "p_market_away",
        "home_american", "away_american",
        "p_market_calibrated_home", "p_market_calibrated_away", "p_goalie_home", "p_goalie_away",
        "selected_rule", "selected_side", "selected_edge", "selected_decimal", "selected_ev",
        "market_control_side", "selected_units", "market_control_units",
    ]
    fields.extend(f"{side}_{name}" for side in ("home", "away") for name in FEATURE_NAMES)
    with PREDICTIONS_FILE.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in sorted(scored, key=lambda x: (x["season"], x["game_date"], x["game_id"])):
            prediction = row["prediction"]
            writer.writerow({
                "game_id": row["game_id"], "season_label": row["season_label"],
                "game_date": row["game_date"], "home_team": row["home_team"],
                "away_team": row["away_team"], "sbr_home_team": row["sbr_home_team"],
                "sbr_away_team": row["sbr_away_team"], "sbr_orientation": row["sbr_orientation"],
                "y": row["y"], "home_score": row["home_score"], "away_score": row["away_score"],
                "home_decimal": format(row["home_decimal"], ".12g"),
                "away_decimal": format(row["away_decimal"], ".12g"),
                "home_american": format(row["home_american"], ".12g"),
                "away_american": format(row["away_american"], ".12g"),
                "p_market_home": format(row["p_market_home"], ".12g"),
                "p_market_away": format(row["p_market_away"], ".12g"),
                "p_market_calibrated_home": format(prediction["p_market_calibrated_home"], ".12g"),
                "p_market_calibrated_away": format(1.0-prediction["p_market_calibrated_home"], ".12g"),
                "p_goalie_home": format(prediction["p_goalie_home"], ".12g"),
                "p_goalie_away": format(1.0-prediction["p_goalie_home"], ".12g"),
                "selected_rule": row["selected_rule"], "selected_side": row["selected_side"] or "pass",
                "selected_edge": "" if row["selected_edge"] is None else format(row["selected_edge"], ".12g"),
                "selected_decimal": "" if row["selected_price"] is None else format(row["selected_price"], ".12g"),
                "selected_ev": "" if row["selected_ev"] is None else format(row["selected_ev"], ".12g"),
                "market_control_side": row["market_control_side"] or "pass",
                "selected_units": format(row["candidate_profit"], ".12g"),
                "market_control_units": format(row["market_profit"], ".12g"),
                **{
                    f"{side}_{name}": row[f"{side}_{name}"]
                    if name == "starter_last" else format(row[f"{side}_{name}"], ".12g")
                    for side in ("home", "away") for name in FEATURE_NAMES
                },
            })
    RESULTS_FILE.write_text(report, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--audit-only", action="store_true", help="verify joins and denominators without fitting")
    action.add_argument("--fit", action="store_true", help="run the frozen walk-forward once")
    args = parser.parse_args()

    rows, facts = read_inputs()
    print_audit(facts)
    if args.audit_only:
        return
    if PREDICTIONS_FILE.exists() or RESULTS_FILE.exists():
        raise FileExistsError("refusing to rerun or overwrite existing OOF outputs")
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO, check=True,
        text=True, capture_output=True,
    ).stdout
    if status.strip():
        raise RuntimeError("--fit requires a clean worktree so the protocol is frozen before fitting")
    if "APPROVED BY MICAH: 2026-10-20" not in PREREG_FILE.read_text(encoding="utf-8"):
        raise RuntimeError("signed preregistration approval line is missing")
    if "Frozen:** 2026-10-20" not in SPEC_FILE.read_text(encoding="utf-8"):
        raise RuntimeError("dated frozen model specification is missing")
    print(
        f"FIT CONFIG: sklearn={sklearn.__version__}; seasons={EVAL_SEASONS}; "
        f"C=1.0; solver=lbfgs; L2; threads=1; bootstrap={BOOTSTRAP_ITERS}; "
        f"seed={BOOTSTRAP_SEED}; eligible_train={facts['training_total']}; oof={facts['oof_total']}"
    )
    with threadpool_limits(limits=1):
        scored, report = evaluate(rows, facts)
    write_outputs(scored, report)
    print(f"WROTE {PREDICTIONS_FILE} rows={len(scored)}")
    print(f"WROTE {RESULTS_FILE}")


if __name__ == "__main__":
    main()
