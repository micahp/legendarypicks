#!/usr/bin/env python3
"""Frozen, append-only prospective NHL forecasts and evaluation artifacts."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import math
import os
import re
import statistics
import time
import urllib.parse
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import PoissonRegressor

HERE = Path(__file__).resolve().parent
AUDIT = HERE.parent / "kalshi-playoff-audit-2025-26"
CANONICAL = AUDIT / "canonical_games_v1_7cd2fc9a6e84470c.csv"
FEATURES = AUDIT / "pregame_rolling_features_v1_62dcceb77085bc59.csv"
BASELINE_PATH = AUDIT / "run_baseline_ladder.py"
MODEL_PATH = HERE / "frozen_models_2026-27_v1.json"
LEDGER = HERE / "forecasts.jsonl"
MARKETS_LEDGER = HERE / "market_quotes.jsonl"
RESULTS_LEDGER = HERE / "official_results.jsonl"
SCORE_DISTRIBUTIONS = HERE / "score_distributions.jsonl"
MANIFEST = HERE / "prospective_session.json"
CACHE = Path(os.environ.get("NHL_PROSPECTIVE_CACHE", str(HERE / ".cache")))
KALSHI = "https://external-api.kalshi.com/trade-api/v2"
NHL = "https://api-web.nhle.com/v1"
MONEYPUCK = "https://moneypuck.com/moneypuck/playerData/careers/gameByGame/regular/teams"
USER_AGENT = "LegendaryPicks-NHL-prospective-research/1.0"
MODELS = ("B3_elo", "B5_xg_poisson", "B7_elo_xg_poisson")
TEAM_ID = {"PHX": "ARI", "T.B": "TBL", "TB": "TBL", "N.J": "NJD", "L.A": "LAK", "LA": "LAK", "S.J": "SJS", "ATL": "WPG"}
KALSHI_NAME = {
    "ANA": "Anaheim", "BOS": "Boston", "BUF": "Buffalo", "CGY": "Calgary", "CAR": "Carolina",
    "CHI": "Chicago", "COL": "Colorado", "CBJ": "Columbus", "DAL": "Dallas", "DET": "Detroit",
    "EDM": "Edmonton", "FLA": "Florida", "LAK": "Los Angeles", "MIN": "Minnesota", "MTL": "Montreal",
    "NSH": "Nashville", "NJD": "New Jersey", "NYI": "New York", "NYR": "New York", "OTT": "Ottawa",
    "PHI": "Philadelphia", "PIT": "Pittsburgh", "SJS": "San Jose", "SEA": "Seattle", "STL": "St. Louis",
    "TBL": "Tampa Bay", "TOR": "Toronto", "UTA": "Utah", "VAN": "Vancouver", "VGK": "Vegas",
    "WPG": "Winnipeg", "WSH": "Washington",
}


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(value: dt.datetime | None = None) -> str:
    return (value or utcnow()).astimezone(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def json_bytes(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        for row in rows:
            f.write(json_bytes(row))
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def append_forecasts(rows: list[dict]) -> None:
    """Serialize writers and enforce one complete frozen model set per game."""
    lock_path = HERE / ".forecast-ledger.lock"
    lock_path.touch(exist_ok=True)
    with lock_path.open("r+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        existing = {(int(r["game_id"]), r["model_name"]) for r in read_jsonl(LEDGER)}
        incoming = [(int(r["game_id"]), r["model_name"]) for r in rows]
        if len(incoming) != len(set(incoming)) or any(item in existing for item in incoming):
            raise RuntimeError("A forecast for this game/model version already exists; ledger is immutable")
        append_jsonl(LEDGER, rows)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def request_bytes(url: str, headers: dict | None = None, timeout: int = 45) -> tuple[bytes, dict]:
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    req = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read()
            return body, {"status": response.status, "headers": dict(response.headers.items()), "url": url}
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return b"", {"status": 304, "headers": dict(exc.headers.items()), "url": url}
        raise


def fetch_json(url: str) -> tuple[dict, dict, bytes]:
    body, meta = request_bytes(url)
    value = json.loads(body)
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected JSON object from {url}")
    meta["response_sha256"] = sha_bytes(body)
    meta["retrieved_at_utc"] = iso()
    return value, meta, body


def load_baseline():
    spec = importlib.util.spec_from_file_location("nhl_locked_baseline", BASELINE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def load_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def team_key(team: str) -> str:
    return TEAM_ID.get(team, team)


def elo_predictions_all(canon: list[dict], k: int = 10, hfa: float = 35) -> tuple[dict, dict]:
    """Replay canonical outcomes, including games without xG features."""
    ratings = defaultdict(lambda: 1500.0)
    predictions = {}
    dates = defaultdict(list)
    for row in canon:
        dates[row["game_date"]].append(row)
    for day in sorted(dates):
        updates = []
        for row in sorted(dates[day], key=lambda x: (x["start_time_utc"], int(x["game_id"]))):
            hid, aid = team_key(row["home_team"]), team_key(row["away_team"])
            venue = 0.0 if str(row["neutral_site"]).lower() == "true" else hfa
            rh, ra = ratings[hid], ratings[aid]
            p = 1.0 / (1.0 + 10.0 ** (-((rh - ra + venue) / 400.0)))
            gid = int(row["game_id"])
            predictions[gid] = {"prob": p, "home_elo": rh, "away_elo": ra, "diff": (rh - ra) / 400.0,
                                "home_venue": float(venue > 0)}
            updates.append((hid, aid, int(row["official_home_winner"]) - p))
        for hid, aid, residual in updates:
            change = k * residual
            ratings[hid] += change
            ratings[aid] -= change
    return predictions, dict(ratings)


def make_elo_xg_matrix(rows: list[dict], elo: dict) -> tuple[np.ndarray, np.ndarray, list[tuple[int, str]]]:
    X, y, keys = [], [], []
    for row in rows:
        d = elo[int(row["game_id"])]["diff"]
        X.extend([
            [1.0, math.log(max(float(row["home_rolling10_5v5_score_venue_xgf"]), .05)),
             math.log(max(float(row["away_rolling10_5v5_score_venue_xga"]), .05)), d],
            [0.0, math.log(max(float(row["away_rolling10_5v5_score_venue_xgf"]), .05)),
             math.log(max(float(row["home_rolling10_5v5_score_venue_xga"]), .05)), -d],
        ])
        y.extend([int(row["home_goals_model_target"]), int(row["away_goals_model_target"])])
        keys.extend([(int(row["game_id"]), "home"), (int(row["game_id"]), "away")])
    return np.asarray(X), np.asarray(y), keys


def fit_frozen() -> dict:
    if sha_file(CANONICAL) != "7cd2fc9a6e84470c177b704aa56ba328ad67522698244ce1f182ddcb9e439f52":
        raise RuntimeError("Canonical artifact hash changed; frozen training inputs require review")
    if sha_file(FEATURES) != "62dcceb77085bc59fcad3ca9a0a981e0e462909cd09815cde98e45b7e9caf458":
        raise RuntimeError("Rolling-feature artifact hash changed; frozen training inputs require review")
    baseline = load_baseline()
    canon = load_csv(CANONICAL)
    all_elo, _ = elo_predictions_all(canon)
    games = baseline.load_data()
    training = [r for r in games if int(r["season"]) <= 2025]
    if not training:
        raise RuntimeError("No feature-complete training games through 2025-26")

    fits = {}
    for name in ("elo", "xg", "elo_xg"):
        if name == "elo":
            X, y, _ = baseline.make_side_dataset(training, "elo", all_elo)
        elif name == "xg":
            X, y, _ = baseline.make_side_dataset(training, "xg", all_elo)
        else:
            X, y, _ = make_elo_xg_matrix(training, all_elo)
        fitted = PoissonRegressor(alpha=0.01, max_iter=500, tol=1e-9).fit(X, y)
        fits[name] = {"intercept": float(fitted.intercept_), "coef": [float(v) for v in fitted.coef_],
                      "feature_count": int(X.shape[1]), "n_team_rows": int(len(y))}
    ties = [r for r in training if int(r["home_goals_model_target"]) == int(r["away_goals_model_target"])]
    if not ties:
        raise RuntimeError("No shootout tie targets available to estimate tie-break rate")
    tie_home = sum(int(r["official_home_winner"]) for r in ties) / len(ties)
    elo_probs = all_elo
    model = {
        "model_version": "nhl-prospective-2026-27-v1",
        "frozen_at_utc": iso(),
        "specification": {
            "B3_elo": {"role": "moneyline incumbent and Elo-only score distribution", "elo_k": 10, "home_ice_elo": 35,
                       "score_poisson_alpha": 0.01},
            "B5_xg_poisson": {"role": "xG score baseline", "features": "rolling last-ten 5v5 score-venue-adjusted xGF/xGA", "alpha": 0.01},
            "B7_elo_xg_poisson": {"role": "unified score challenger", "features": "B5 xG features plus pregame Elo rating difference", "alpha": 0.01},
            "training_seasons": "2008-09 through 2025-26, feature-complete rows, canonical historical files",
            "target": "regulation plus overtime team goals; shootout deciding goal excluded",
            "probability_handling": "independent Poisson score mass; tied target mass resolved with historical home shootout win rate",
            "regulation_win_probability": "not estimated by v1; regulation-only target is not present in frozen training table",
        },
        "input_hashes": {"canonical_games_sha256": sha_file(CANONICAL), "pregame_features_sha256": sha_file(FEATURES),
                         "baseline_code_sha256": sha_file(BASELINE_PATH)},
        "fit_rows": {"feature_complete_games": len(training), "by_season": {}},
        "historical_home_shootout_win_rate": float(tie_home),
        "poisson_models": fits,
        "source_compatibility": {
            "historical_xg": "MoneyPuck-derived historical feature snapshot v1; original xG release version not versioned in source table",
            "live_xg": "MoneyPuck 2026-27 team game-by-game source; MoneyPuck states its xG model was rebuilt for 2026-27; version mismatch remains an explicit limitation",
            "commercial_rights": "Unresolved; research use only pending permission for commercial use",
        },
    }
    counts = defaultdict(int)
    for row in training:
        counts[int(row["season"])] += 1
    model["fit_rows"]["by_season"] = {str(k): v for k, v in sorted(counts.items())}
    model["model_sha256"] = sha_bytes(json_bytes(model))
    return model


def init_session() -> dict:
    if not MODEL_PATH.exists():
        raise RuntimeError("Frozen model file missing; run `freeze` first")
    model = json.loads(MODEL_PATH.read_text())
    if MANIFEST.exists():
        raise RuntimeError(f"Session already initialized at {MANIFEST}; it is write-once")
    manifest = {"session_version": "nhl-prospective-session-v1", "started_at_utc": iso(),
                "model_version": model["model_version"], "model_sha256": sha_file(MODEL_PATH),
                "canonical_games_sha256": model["input_hashes"]["canonical_games_sha256"],
                "pregame_features_sha256": model["input_hashes"]["pregame_features_sha256"],
                "classification": "A game is prospective only when its immutable forecast timestamp is after this start and before NHL startTimeUTC."}
    MANIFEST.write_bytes(json_bytes(manifest))
    return manifest


def get_session() -> dict:
    if not MANIFEST.exists():
        return init_session()
    return json.loads(MANIFEST.read_text())


def live_schedule(now: dt.datetime, horizon_hours: float) -> tuple[list[dict], dict]:
    url = f"{NHL}/schedule/{now.date().isoformat()}"
    payload, meta, _ = fetch_json(url)
    horizon = now + dt.timedelta(hours=horizon_hours)
    games = []
    for day in payload.get("gameWeek", []):
        for game in day.get("games", []):
            start = dt.datetime.fromisoformat(game["startTimeUTC"].replace("Z", "+00:00")).astimezone(dt.timezone.utc)
            if now < start <= horizon and game.get("gameType") == 2 and game.get("gameState") in {"FUT", "PRE", "OFF"}:
                games.append({"game_id": int(game["id"]), "season": int(str(game.get("season", 20262027))[:4]),
                              "game_date": game.get("gameDate", day.get("date")), "start_time_utc": iso(start),
                              "home_team": game["homeTeam"]["abbrev"], "away_team": game["awayTeam"]["abbrev"],
                              "neutral_site": bool(game.get("neutralSite", False)), "schedule_state": game.get("gameState")})
    games.sort(key=lambda r: (r["start_time_utc"], r["game_id"]))
    if len({g["game_id"] for g in games}) != len(games):
        raise RuntimeError("NHL schedule returned duplicate game IDs")
    meta["regular_season_start_date"] = payload.get("regularSeasonStartDate")
    return games, meta


def week_cache(start_date: dt.date) -> tuple[dict, dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"nhl_schedule_{start_date.isoformat()}.json"
    today = utcnow().date()
    # Finalized prior weeks are immutable. Refresh the active week every run.
    if path.exists() and (start_date + dt.timedelta(days=7) < today):
        body = path.read_bytes()
        value = json.loads(body)
        return value["payload"], value["meta"]
    url = f"{NHL}/schedule/{start_date.isoformat()}"
    payload, meta, raw = fetch_json(url)
    cache_value = {"payload": payload, "meta": meta, "raw_sha256": sha_bytes(raw)}
    path.write_bytes(json_bytes(cache_value))
    return payload, meta


def current_results(now: dt.datetime, season_start: str) -> tuple[list[dict], list[dict]]:
    start = dt.date.fromisoformat(season_start)
    cursor = start
    results, evidence = [], []
    while cursor <= now.date():
        payload, meta = week_cache(cursor)
        evidence.append({"week_start": cursor.isoformat(), "url": meta["url"], "response_sha256": meta.get("response_sha256"),
                         "retrieved_at_utc": meta.get("retrieved_at_utc")})
        for day in payload.get("gameWeek", []):
            for game in day.get("games", []):
                if game.get("gameType") != 2 or game.get("gameState") not in {"OFF", "FINAL"}:
                    continue
                if not game.get("homeTeam", {}).get("score") and game.get("homeTeam", {}).get("score") != 0:
                    raise RuntimeError(f"Final game {game.get('id')} has no published home score")
                results.append({"game_id": int(game["id"]), "game_date": game.get("gameDate", day.get("date")),
                                "start_time_utc": game["startTimeUTC"], "home_team": game["homeTeam"]["abbrev"],
                                "away_team": game["awayTeam"]["abbrev"], "home_goals": int(game["homeTeam"]["score"]),
                                "away_goals": int(game["awayTeam"]["score"]), "game_state": game["gameState"]})
        cursor += dt.timedelta(days=7)
    dedup = {r["game_id"]: r for r in results}
    return sorted(dedup.values(), key=lambda r: (r["game_date"], r["start_time_utc"], r["game_id"])), evidence


def live_elo(canon: list[dict], season_results: list[dict], k=10, hfa=35) -> tuple[dict, dict]:
    _, ratings = elo_predictions_all(canon, k, hfa)
    existing_ids = {int(r["game_id"]) for r in canon}
    for game in sorted(season_results, key=lambda r: (r["start_time_utc"], r["game_id"])):
        if int(game["game_id"]) in existing_ids:
            continue
        home, away = team_key(game["home_team"]), team_key(game["away_team"])
        rh, ra = ratings.get(home, 1500.0), ratings.get(away, 1500.0)
        expected = 1.0 / (1.0 + 10.0 ** (-((rh - ra + hfa) / 400.0)))
        residual = int(game["home_goals"] > game["away_goals"]) - expected
        ratings[home] = rh + k * residual
        ratings[away] = ra - k * residual
    return {}, ratings


def read_team_csv(team: str, asof: dt.datetime) -> tuple[list[dict], dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"moneypuck_team_{team}.csv"
    url = f"{MONEYPUCK}/{urllib.parse.quote(team, safe='')}.csv"
    headers = {}
    if path.exists():
        cached_meta_path = path.with_suffix(".json")
        if cached_meta_path.exists():
            cached_meta = json.loads(cached_meta_path.read_text())
            fetched = dt.datetime.fromisoformat(cached_meta["captured_at_utc"].replace("Z", "+00:00"))
            if (asof - fetched).total_seconds() < 1800:
                return parse_team_csv(path), cached_meta
            if cached_meta.get("last_modified"):
                headers["If-Modified-Since"] = cached_meta["last_modified"]
    body, meta = request_bytes(url, headers=headers, timeout=60)
    if meta["status"] == 304 and path.exists():
        cached_meta = json.loads(path.with_suffix(".json").read_text())
        cached_meta["last_checked_at_utc"] = iso(asof)
        path.with_suffix(".json").write_bytes(json_bytes(cached_meta))
        return parse_team_csv(path), cached_meta
    if meta["status"] != 200 or len(body) < 1000:
        raise RuntimeError(f"MoneyPuck team payload invalid for {team}: {meta['status']} bytes={len(body)}")
    path.write_bytes(body)
    fetched_at = iso()
    stored = {"source_url": url, "captured_at_utc": fetched_at, "last_modified": meta["headers"].get("Last-Modified"),
              "etag": meta["headers"].get("ETag"), "response_sha256": sha_bytes(body), "bytes": len(body),
              "xg_source_version": "MoneyPuck 2026-27 model; publisher states rebuilt for this season"}
    path.with_suffix(".json").write_bytes(json_bytes(stored))
    return parse_team_csv(path), stored


def parse_team_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {"team", "season", "gameId", "gameDate", "situation", "scoreVenueAdjustedxGoalsFor", "scoreVenueAdjustedxGoalsAgainst"}
        if not required.issubset(reader.fieldnames or []):
            raise RuntimeError(f"MoneyPuck CSV schema missing required columns: {sorted(required-set(reader.fieldnames or []))}")
        # Retain only the published game-level 5v5 fields needed for rolling features.
        rows = [{key: row[key] for key in ("team", "season", "gameId", "gameDate", "situation",
                                           "scoreVenueAdjustedxGoalsFor", "scoreVenueAdjustedxGoalsAgainst")}
                for row in reader if row.get("situation") == "5on5"]
    if not rows:
        raise RuntimeError(f"MoneyPuck team CSV has no 5on5 records: {path.name}")
    return rows


def roll_xg(team_rows: list[dict], before_date: str, completed_game_ids: set[int]) -> dict:
    eligible = []
    for row in team_rows:
        raw_date = row.get("gameDate", "")
        try:
            source_date = dt.datetime.strptime(raw_date, "%Y%m%d").date().isoformat()
        except ValueError:
            source_date = raw_date[:10]
        if row.get("situation") != "5on5" or source_date >= before_date:
            continue
        try:
            xgf = float(row["scoreVenueAdjustedxGoalsFor"])
            xga = float(row["scoreVenueAdjustedxGoalsAgainst"])
            gid = int(row["gameId"])
        except (ValueError, TypeError, KeyError):
            continue
        if gid in completed_game_ids and math.isfinite(xgf) and math.isfinite(xga):
            eligible.append((source_date, gid, xgf, xga))
    eligible.sort(key=lambda x: (x[0], x[1]))
    recent = eligible[-10:]
    if len(recent) < 5:
        raise RuntimeError(f"Only {len(recent)} valid prior 5v5 xG team games before {before_date}")
    return {"rolling10_5v5_score_venue_xgf": statistics.mean(x[2] for x in recent),
            "rolling10_5v5_score_venue_xga": statistics.mean(x[3] for x in recent),
            "prior_game_ids": [x[1] for x in recent], "max_source_date": recent[-1][0], "n": len(recent)}


def poisson_pmf(mu: float, cap: int = 20) -> np.ndarray:
    vals = np.arange(cap + 1)
    logp = vals * math.log(max(mu, 1e-12)) - mu - np.array([math.lgamma(int(x) + 1) for x in vals])
    p = np.exp(logp)
    return p / p.sum()


def score_markets(home_mu: float, away_mu: float, tie_home: float) -> dict:
    hp, ap = poisson_pmf(home_mu), poisson_pmf(away_mu)
    matrix = np.outer(hp, ap)
    p_tie = float(np.trace(matrix))
    home_win = float(sum(matrix[i, :i].sum() for i in range(len(hp))) + p_tie * tie_home)
    total = np.add.outer(np.arange(len(hp)), np.arange(len(ap)))
    diff = np.subtract.outer(np.arange(len(hp)), np.arange(len(ap)))
    result = {"p_home_win_from_score": home_win, "p_away_win_from_score": 1 - home_win,
              "p_tie_before_shootout_break": p_tie,
              "regulation_win_probability": None,
              "regulation_probability_status": "unavailable_v1_no_regulation_only_training_target",
              "settlement_target": "regulation_plus_overtime_goals_excluding_shootout_deciding_goal",
              "score_distribution_goal_support": list(range(len(hp))),
              "home_goal_marginal_probabilities": hp.tolist(),
              "away_goal_marginal_probabilities": ap.tolist(),
              "joint_score_probability_matrix_home_rows_away_columns": matrix.tolist()}
    for line in (4.5, 5.5, 6.5, 7.5):
        p_over = float(matrix[total > line].sum())
        result[f"p_over_{line}"] = p_over
        result[f"p_under_{line}"] = 1 - p_over
    result["p_home_minus_1_5"] = float(matrix[diff > 1.5].sum())
    result["p_away_plus_1_5"] = 1 - result["p_home_minus_1_5"]
    result["p_away_minus_1_5"] = float(matrix[diff < -1.5].sum())
    result["p_home_plus_1_5"] = 1 - result["p_away_minus_1_5"]
    return result


def forecast(horizon_hours: float) -> list[dict]:
    model = json.loads(MODEL_PATH.read_text())
    if model.get("model_version") != "nhl-prospective-2026-27-v1" or model.get("model_sha256") != sha_bytes(json_bytes({k: v for k, v in model.items() if k != "model_sha256"})):
        raise RuntimeError("Frozen model integrity check failed")
    session = get_session()
    if session["model_version"] != model["model_version"] or session["model_sha256"] != sha_file(MODEL_PATH):
        raise RuntimeError("Prospective session is pinned to a different model artifact")
    asof = utcnow()
    session_started = dt.datetime.fromisoformat(session["started_at_utc"].replace("Z", "+00:00"))
    if asof <= session_started:
        raise RuntimeError("Forecast timestamp must be later than prospective session start")
    games, schedule_meta = live_schedule(asof, horizon_hours)
    existing = read_jsonl(LEDGER)
    done = {(int(x["game_id"]), x["model_name"]) for x in existing}
    for game in games:
        present = {m for m in MODELS if (game["game_id"], m) in done}
        if present and present != set(MODELS):
            raise RuntimeError(f"Partial immutable forecast set for game {game['game_id']}: {sorted(present)}")
    games = [g for g in games if not all((g["game_id"], m) in done for m in MODELS)]
    if not games:
        print("No unforecast scheduled NHL games inside the requested horizon.")
        return []

    context = feature_context(asof, games, schedule_meta)
    forecast_time = utcnow()
    if forecast_time <= session_started:
        raise RuntimeError("Forecast timestamp must follow the frozen prospective session start")
    append_rows = build_forecasts(games, forecast_time, model, context, schedule_meta)
    append_forecasts(append_rows)
    return append_rows


def feature_context(asof: dt.datetime, games: list[dict], schedule_meta: dict) -> dict:
    """Everything the per-game forecast loop needs, as of `asof`.

    Shared by the scheduled ledger writer and the T-90 snapshot generator so the leak-safe
    feature assembly has one definition: the Elo state is reconstructed only from games
    already played, and each team's xG rows are read with `asof` as the cutoff.
    """
    # Use all canonical results to reconstruct the selected Elo state, including games without xG rows.
    canonical = load_csv(CANONICAL)
    season_start = schedule_meta.get("regular_season_start_date")
    if not season_start:
        raise RuntimeError("Official NHL schedule omitted regularSeasonStartDate")
    current, season_evidence = current_results(asof, season_start)
    _, live_ratings = live_elo(canonical, current)
    completed_game_ids = {int(r["game_id"]) for r in canonical} | {int(r["game_id"]) for r in current}
    teams = sorted({team_key(g[s]) for g in games for s in ("home_team", "away_team")})
    team_data, team_meta = {}, {}
    for team in teams:
        rows, meta = read_team_csv(team, asof)
        team_data[team], team_meta[team] = rows, meta
    return {"live_ratings": live_ratings, "completed_game_ids": completed_game_ids,
            "team_data": team_data, "team_meta": team_meta, "season_evidence": season_evidence}


def build_forecasts(games: list[dict], forecast_time: dt.datetime, model: dict,
                    context: dict, schedule_meta: dict) -> list[dict]:
    """One forecast row per game and model. Computes; writes nothing.

    The only definition of the model math, so the scheduled ledger writer and the T-90
    snapshot generator cannot drift apart.
    """
    live_ratings = context["live_ratings"]
    completed_game_ids = context["completed_game_ids"]
    team_data = context["team_data"]
    team_meta = context["team_meta"]
    season_evidence = context["season_evidence"]
    append_rows = []
    for game in games:
        gid, home, away = game["game_id"], team_key(game["home_team"]), team_key(game["away_team"])
        start = dt.datetime.fromisoformat(game["start_time_utc"].replace("Z", "+00:00"))
        if start <= forecast_time:
            raise RuntimeError(f"Refusing post-start forecast for NHL game {gid}")
        rh = live_ratings.get(home, 1500.0)
        ra = live_ratings.get(away, 1500.0)
        venue = 0.0 if game["neutral_site"] else 35.0
        elo_record = {"home_elo": rh, "away_elo": ra, "diff": (rh-ra)/400.0, "home_venue": float(venue > 0),
                      "prob": 1.0/(1.0+10.0**(-((rh-ra+venue)/400.0)))}
        hx = roll_xg(team_data[home], game["game_date"], completed_game_ids)
        ax = roll_xg(team_data[away], game["game_date"], completed_game_ids)
        er = elo_record
        xg_features = {
            "home_rolling10_5v5_score_venue_xgf": hx["rolling10_5v5_score_venue_xgf"],
            "away_rolling10_5v5_score_venue_xga": ax["rolling10_5v5_score_venue_xga"],
            "away_rolling10_5v5_score_venue_xgf": ax["rolling10_5v5_score_venue_xgf"],
            "home_rolling10_5v5_score_venue_xga": hx["rolling10_5v5_score_venue_xga"],
        }
        feature_hashes = {home: team_meta[home]["response_sha256"], away: team_meta[away]["response_sha256"]}
        snapshot = {"as_of_utc": iso(forecast_time), "game_id": gid, "home_team": home, "away_team": away,
                    "scheduled_start_utc": game["start_time_utc"], "feature_max_source_dates": {"home": hx["max_source_date"], "away": ax["max_source_date"]},
                    "rolling_window_game_ids": {"home": hx["prior_game_ids"], "away": ax["prior_game_ids"]},
                    "elo_pre_game": {"home": er["home_elo"], "away": er["away_elo"], "k": 10, "home_ice": 35},
                    "xg_features": xg_features, "xg_source_hashes": feature_hashes,
                    "xg_source_versions": {home: team_meta[home]["xg_source_version"], away: team_meta[away]["xg_source_version"]},
                    "xg_source_metadata": {home: team_meta[home], away: team_meta[away]},
                    "schedule_source": {"url": schedule_meta["url"], "sha256": schedule_meta["response_sha256"],
                                        "retrieved_at_utc": schedule_meta.get("retrieved_at_utc")},
                    "elo_recent_schedule_evidence": season_evidence,
                    "model_artifact_sha256": sha_file(MODEL_PATH)}
        snapshot_hash = sha_bytes(json_bytes(snapshot))
        per_model = {
            "B3_elo": [float(er["home_venue"]), float(er["diff"])],
            "B5_xg_poisson": [1.0, math.log(max(xg_features["home_rolling10_5v5_score_venue_xgf"], .05)), math.log(max(xg_features["away_rolling10_5v5_score_venue_xga"], .05)),
                              0.0, math.log(max(xg_features["away_rolling10_5v5_score_venue_xgf"], .05)), math.log(max(xg_features["home_rolling10_5v5_score_venue_xga"], .05))],
            "B7_elo_xg_poisson": [1.0, math.log(max(xg_features["home_rolling10_5v5_score_venue_xgf"], .05)), math.log(max(xg_features["away_rolling10_5v5_score_venue_xga"], .05)), er["diff"],
                                  0.0, math.log(max(xg_features["away_rolling10_5v5_score_venue_xgf"], .05)), math.log(max(xg_features["home_rolling10_5v5_score_venue_xga"], .05)), -er["diff"]],
        }
        # B3 uses two separate team-side records, unlike the xG models.
        for name in MODELS:
            if name == "B3_elo":
                matrix = [[er["home_venue"], er["diff"]], [0.0, -er["diff"]]]
            elif name == "B5_xg_poisson":
                matrix = [[1.0, per_model[name][1], per_model[name][2]], [0.0, per_model[name][4], per_model[name][5]]]
            else:
                matrix = [[1.0, per_model[name][1], per_model[name][2], per_model[name][3]],
                          [0.0, per_model[name][5], per_model[name][6], per_model[name][7]]]
            params = model["poisson_models"][{"B3_elo": "elo", "B5_xg_poisson": "xg", "B7_elo_xg_poisson": "elo_xg"}[name]]
            mus = [math.exp(float(params["intercept"]) + float(np.dot(params["coef"], row))) for row in matrix]
            if not all(math.isfinite(mu) and 0.01 <= mu <= 15.0 for mu in mus):
                raise RuntimeError(f"Implausible/non-finite goal mean for {gid} {name}: {mus}")
            markets = score_markets(mus[0], mus[1], model["historical_home_shootout_win_rate"])
            home_prob = float(er["prob"]) if name == "B3_elo" else markets["p_home_win_from_score"]
            forecast_id = sha_bytes(f"{gid}|{name}|{model['model_version']}|{snapshot_hash}".encode())
            append_rows.append({"forecast_id": forecast_id, "game_id": gid, "season": game["season"], "game_date": game["game_date"],
                                "scheduled_start_utc": game["start_time_utc"], "forecasted_at_utc": iso(forecast_time), "home_team": home, "away_team": away,
                                "model_name": name, "model_version": model["model_version"], "model_artifact_sha256": sha_file(MODEL_PATH),
                                "feature_snapshot": snapshot, "feature_snapshot_sha256": snapshot_hash,
                                "home_expected_goals": mus[0], "away_expected_goals": mus[1], "projected_total_goals": mus[0] + mus[1],
                                "projected_goal_differential_home": mus[0] - mus[1], "home_win_probability": home_prob,
                                "away_win_probability": 1.0 - home_prob, **markets})
    return append_rows


def kalshi_series_markets() -> tuple[list[dict], list[dict]]:
    params = {"series_ticker": "KXNHLGAME", "limit": 1000}
    all_markets, pages, seen = [], [], set()
    while True:
        url = KALSHI + "/markets?" + urllib.parse.urlencode(params)
        payload, meta, _ = fetch_json(url)
        items = payload.get("markets")
        if not isinstance(items, list):
            raise RuntimeError("Kalshi markets response missing `markets` list")
        all_markets.extend(items)
        cursor = payload.get("cursor") or ""
        pages.append({"url": url, "response_sha256": meta["response_sha256"], "count": len(items), "has_cursor": bool(cursor)})
        if not cursor:
            break
        if cursor in seen:
            raise RuntimeError("Kalshi markets cursor repeated; refusing incomplete quote capture")
        seen.add(cursor)
        params["cursor"] = cursor
        time.sleep(0.2)
    tickers = [m.get("ticker") for m in all_markets]
    if len(tickers) != len(set(tickers)):
        raise RuntimeError("Kalshi market pagination returned duplicate tickers")
    return all_markets, pages


def capture_markets() -> list[dict]:
    forecasts = read_jsonl(LEDGER)
    if not forecasts:
        raise RuntimeError("No archived forecasts to join to Kalshi markets")
    forecasts_by_game = defaultdict(list)
    for row in forecasts:
        forecasts_by_game[int(row["game_id"])].append(row)
    markets, pages = kalshi_series_markets()
    market_list_captured_at = utcnow()
    capture_batch_id = sha_bytes(f"{iso(market_list_captured_at)}|{json.dumps(pages, sort_keys=True)}".encode())
    by_event = defaultdict(list)
    for market in markets:
        event = market.get("event_ticker", "")
        if event.startswith("KXNHLGAME-"):
            by_event[event].append(market)
    now = utcnow()
    snapshots = []
    for gid, samples in forecasts_by_game.items():
        sample = samples[0]
        expected = {sample["home_team"], sample["away_team"]}
        candidates = []
        for event, rows in by_event.items():
            date_match = re.match(r"^KXNHLGAME-(\d{2}[A-Z]{3}\d{2})", event)
            if not date_match:
                continue
            try:
                event_date = dt.datetime.strptime(date_match.group(1), "%y%b%d").date().isoformat()
            except ValueError:
                continue
            if event_date != sample["game_date"]:
                continue
            event_teams = set()
            for row in rows:
                ticker = row.get("ticker", "")
                code = ticker[len(event)+1:] if ticker.startswith(event + "-") else ""
                norm = team_key(code)
                if norm in expected:
                    event_teams.add(norm)
            if event_teams == expected:
                candidates.append((event, rows))
        start = dt.datetime.fromisoformat(sample["scheduled_start_utc"].replace("Z", "+00:00"))
        if market_list_captured_at >= start:
            raise RuntimeError(f"Refusing post-start Kalshi quote capture for {gid}")
        if len(candidates) != 1:
            snapshots.append({"snapshot_id": sha_bytes(f"{gid}|{iso(now)}|no_unique_event".encode()), "game_id": gid,
                              "forecast_ids_by_model": {r["model_name"]: r["forecast_id"] for r in samples},
                              "captured_at_utc": iso(market_list_captured_at), "capture_batch_id": capture_batch_id,
                              "coverage_status": "missing_or_ambiguous_event",
                              "candidate_event_count": len(candidates), "kalshi_pages": pages, "source": "Kalshi public markets API"})
            continue
        event, rows = candidates[0]
        if len(rows) != 2:
            raise RuntimeError(f"Kalshi event {event} yielded {len(rows)} contracts, expected two sides")
        for market in rows:
            ticker = market["ticker"]
            url = f"{KALSHI}/markets/{urllib.parse.quote(ticker, safe='')}/orderbook"
            payload, meta, raw = fetch_json(url)
            captured_at = dt.datetime.fromisoformat(meta["retrieved_at_utc"].replace("Z", "+00:00"))
            if captured_at >= start:
                raise RuntimeError(f"Kalshi orderbook returned after puck drop for {gid}")
            book = payload.get("orderbook_fp") or payload.get("orderbook")
            if not isinstance(book, dict):
                raise RuntimeError(f"Orderbook response missing levels for {ticker}")
            yes_levels = book.get("yes_dollars", book.get("yes", [])) or []
            no_levels = book.get("no_dollars", book.get("no", [])) or []
            # Kalshi documents levels best-to-worst, so the first entry is the best price.
            yes_bid = float(yes_levels[0][0]) if yes_levels else None
            no_bid = float(no_levels[0][0]) if no_levels else None
            yes_ask = 1.0 - no_bid if no_bid is not None else None
            yes_bid_size = float(yes_levels[0][1]) if yes_levels else None
            yes_ask_size = float(no_levels[0][1]) if no_levels else None
            spread = yes_ask - yes_bid if yes_bid is not None and yes_ask is not None else None
            if spread is None or spread < 0 or yes_bid_size is None or yes_ask_size is None or min(yes_bid_size, yes_ask_size) <= 0:
                quote_quality = "incomplete_or_crossed_book"
            elif spread > 0.20:
                quote_quality = "wide_spread_over_20c"
            else:
                quote_quality = "two_sided_spread_at_most_20c"
            if not ticker.startswith(event + "-"):
                raise RuntimeError(f"Kalshi market ticker is not a contract under event {event}: {ticker}")
            side = team_key(ticker[len(event)+1:])
            snapshots.append({"snapshot_id": sha_bytes(f"{gid}|{ticker}|{iso(captured_at)}|{meta['response_sha256']}".encode()),
                              "game_id": gid, "forecast_ids_by_model": {r["model_name"]: r["forecast_id"] for r in samples}, "event_ticker": event,
                              "market_ticker": ticker, "market_side_team": side, "captured_at_utc": iso(captured_at),
                              "capture_batch_id": capture_batch_id, "market_list_captured_at_utc": iso(market_list_captured_at),
                              "seconds_before_start": (start-captured_at).total_seconds(),
                              "market_updated_at": market.get("updated_time"), "coverage_status": "captured",
                              "quote_quality": quote_quality, "yes_bid": yes_bid, "yes_ask": yes_ask,
                              "spread": spread, "yes_bid_size": yes_bid_size, "yes_ask_size": yes_ask_size,
                              "market_reported_yes_bid": market.get("yes_bid_dollars"), "market_reported_yes_ask": market.get("yes_ask_dollars"),
                              "last_trade_price": market.get("last_price_dollars"), "volume": market.get("volume_fp"),
                              "open_interest": market.get("open_interest_fp"), "orderbook": book,
                              "orderbook_response_sha256": sha_bytes(raw), "orderbook_source_url": meta["url"],
                              "market_metadata": {k: market.get(k) for k in ("yes_sub_title", "title", "status", "rules_primary", "rules_secondary")},
                              "market_pages": pages, "market_series_source": KALSHI + "/markets"})
    append_jsonl(MARKETS_LEDGER, snapshots)
    return snapshots


def official_period_goal_breakdown(payload: dict) -> dict:
    """Separate NHL-published regulation, overtime and shootout scoring records."""
    home_code = payload["homeTeam"]["abbrev"]
    away_code = payload["awayTeam"]["abbrev"]
    regulation = {home_code: 0, away_code: 0}
    overtime = {home_code: 0, away_code: 0}
    scoring = (payload.get("summary") or {}).get("scoring")
    if not isinstance(scoring, list):
        raise RuntimeError(f"Official NHL landing lacks period scoring for {payload.get('id')}")
    for period in scoring:
        ptype = (period.get("periodDescriptor") or {}).get("periodType")
        destination = regulation if ptype == "REG" else overtime if ptype == "OT" else None
        if destination is None:
            continue
        for goal in period.get("goals", []):
            team_code = (goal.get("teamAbbrev") or {}).get("default")
            if team_code not in destination:
                raise RuntimeError(f"Unknown official goal team in {payload.get('id')}: {team_code}")
            destination[team_code] += 1
    shootout_events = ((payload.get("summary") or {}).get("shootout") or {}).get("events") or []
    shootout_goals = {home_code: 0, away_code: 0}
    for event in shootout_events:
        team_code = (event.get("teamAbbrev") or {}).get("default")
        if event.get("result") == "goal":
            if team_code not in shootout_goals:
                raise RuntimeError(f"Unknown official shootout team in {payload.get('id')}: {team_code}")
            shootout_goals[team_code] += 1
    return {"home_team": home_code, "away_team": away_code, "regulation": regulation,
            "overtime": overtime, "shootout_goals": shootout_goals}


def collect_official_results() -> list[dict]:
    forecasts = read_jsonl(LEDGER)
    if not forecasts:
        raise RuntimeError("No forecasts to grade")
    already = {int(r["game_id"]) for r in read_jsonl(RESULTS_LEDGER)}
    games = {int(r["game_id"]): r for r in forecasts if int(r["game_id"]) not in already}
    rows = []
    for gid, forecast_row in games.items():
        url = f"{NHL}/gamecenter/{gid}/landing"
        payload, meta, _ = fetch_json(url)
        state = payload.get("gameState") or payload.get("gameScheduleState")
        if state not in {"OFF", "FINAL"}:
            continue
        home = payload.get("homeTeam", {})
        away = payload.get("awayTeam", {})
        if home.get("abbrev") != forecast_row["home_team"] or away.get("abbrev") != forecast_row["away_team"]:
            raise RuntimeError(f"NHL official identity mismatch for {gid}")
        official_h, official_a = int(home["score"]), int(away["score"])
        period_type = (payload.get("periodDescriptor") or {}).get("periodType")
        breakdown = official_period_goal_breakdown(payload)
        home_code, away_code = breakdown["home_team"], breakdown["away_team"]
        regulation, overtime, shootout_goals = breakdown["regulation"], breakdown["overtime"], breakdown["shootout_goals"]
        if period_type == "SO":
            model_h, model_a = official_h, official_a
            if official_h > official_a:
                model_h -= 1
            else:
                model_a -= 1
        else:
            model_h, model_a = official_h, official_a
        if regulation[home_code] + overtime[home_code] != model_h or regulation[away_code] + overtime[away_code] != model_a:
            raise RuntimeError(f"Official period goals do not reconcile to statistical goal target for {gid}")
        rows.append({"game_id": gid, "game_date": forecast_row["game_date"], "retrieved_at_utc": iso(), "source_url": meta["url"],
                     "source_response_sha256": meta["response_sha256"], "game_state": state, "last_period_type": period_type,
                     "home_team": home["abbrev"], "away_team": away["abbrev"], "official_home_score": official_h,
                     "official_away_score": official_a, "official_home_winner": int(official_h > official_a),
                     "official_home_regulation_goals": regulation[home_code], "official_away_regulation_goals": regulation[away_code],
                     "official_home_overtime_goals": overtime[home_code], "official_away_overtime_goals": overtime[away_code],
                     "official_home_shootout_goals": shootout_goals[home_code], "official_away_shootout_goals": shootout_goals[away_code],
                     "official_shootout_winner": (home_code if official_h > official_a else away_code) if period_type == "SO" else None,
                     "model_home_goals_target_reg_ot_excl_so": model_h, "model_away_goals_target_reg_ot_excl_so": model_a,
                     "settlement_rule_version": "nhl-official-result-v1",
                     "target_rule": "official final goals with shootout deciding goal removed; regulation and OT goals retained"})
    append_jsonl(RESULTS_LEDGER, rows)
    return rows


def append_missing_score_distributions() -> list[dict]:
    """Append PMFs for early v1 records that predate the inline distribution field."""
    model = json.loads(MODEL_PATH.read_text())
    forecasts = read_jsonl(LEDGER)
    existing = {r["forecast_id"] for r in read_jsonl(SCORE_DISTRIBUTIONS)}
    additions = []
    for row in forecasts:
        if "joint_score_probability_matrix_home_rows_away_columns" in row or row["forecast_id"] in existing:
            continue
        details = score_markets(float(row["home_expected_goals"]), float(row["away_expected_goals"]),
                                float(model["historical_home_shootout_win_rate"]))
        additions.append({"forecast_id": row["forecast_id"], "game_id": row["game_id"], "model_name": row["model_name"],
                          "model_version": row["model_version"], "forecasted_at_utc": row["forecasted_at_utc"],
                          "derived_at_utc": iso(), "derivation": "deterministic expansion of immutable expected goals and frozen Poisson/tie-break parameters; no outcome or market input",
                          "forecast_record_sha256": sha_bytes(json_bytes(row)), "model_artifact_sha256": sha_file(MODEL_PATH),
                          "score_probability_distribution": {k: details[k] for k in (
                              "score_distribution_goal_support", "home_goal_marginal_probabilities", "away_goal_marginal_probabilities",
                              "joint_score_probability_matrix_home_rows_away_columns")}})
    append_jsonl(SCORE_DISTRIBUTIONS, additions)
    return additions


def binary_metrics(rows: list[dict], probability_field: str, target_field: str) -> dict:
    if not rows:
        return {"n": 0, "brier": None, "log_loss": None, "calibration_bins": []}
    y = np.asarray([int(r[target_field]) for r in rows], dtype=float)
    p = np.clip(np.asarray([float(r[probability_field]) for r in rows]), 1e-8, 1 - 1e-8)
    bins = []
    for low in np.arange(0, 1, .1):
        mask = (p >= low) & (p < low + .1 if low < .9 else p <= 1)
        if mask.any():
            bins.append({"range": f"{low:.1f}-{low+.1:.1f}", "n": int(mask.sum()), "mean_probability": float(p[mask].mean()), "observed_rate": float(y[mask].mean())})
    return {"n": len(rows), "brier": float(np.mean((p-y)**2)),
            "log_loss": float(np.mean(-(y*np.log(p)+(1-y)*np.log(1-p)))), "calibration_bins": bins}


def paired_ci(a: list[float], b: list[float], seed: int = 20261014, iterations: int = 4000) -> dict:
    differences = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    if not len(differences):
        return {"n": 0, "mean_delta": None, "ci95": [None, None]}
    rng = np.random.default_rng(seed)
    means = np.empty(iterations)
    for i in range(iterations):
        means[i] = rng.choice(differences, size=len(differences), replace=True).mean()
    return {"n": len(differences), "mean_delta": float(differences.mean()),
            "ci95": [float(np.quantile(means, .025)), float(np.quantile(means, .975))]}


def cumulative_report() -> dict:
    forecasts = read_jsonl(LEDGER)
    results = {int(r["game_id"]): r for r in read_jsonl(RESULTS_LEDGER)}
    # The official result row is attached to each model forecast by canonical NHL game ID.
    rows = [{**f, **results[int(f["game_id"])]} for f in forecasts if int(f["game_id"]) in results]
    by_month = defaultdict(list)
    for row in rows:
        by_month[row["game_date"][:7]].append(row)
    reports = {}
    market_coverage_by_month = {}
    for month in sorted(by_month):
        observed_month = by_month[month]
        for model_name in MODELS:
            model_month = [r for r in observed_month if r["model_name"] == model_name]
            y = "official_home_winner"
            outcomes = [r for r in model_month if r.get(y) is not None]
            if not outcomes:
                continue
            goals = [(abs(int(r["home_expected_goals"])-int(r["model_home_goals_target_reg_ot_excl_so"]))+
                      abs(int(r["away_expected_goals"])-int(r["model_away_goals_target_reg_ot_excl_so"]))) / 2 for r in model_month]
            nll = []
            for r in model_month:
                hg, ag = int(r["model_home_goals_target_reg_ot_excl_so"]), int(r["model_away_goals_target_reg_ot_excl_so"])
                hm, am = float(r["home_expected_goals"]), float(r["away_expected_goals"])
                nll.append(-(hg*math.log(max(hm, 1e-12))-hm-math.lgamma(hg+1) + ag*math.log(max(am, 1e-12))-am-math.lgamma(ag+1)))
            cumulative = [r for r in rows if r["game_date"][:7] <= month and r["model_name"] == model_name]
            cumulative_outcomes = [r for r in cumulative if r.get(y) is not None]
            cumulative_nll = []
            for r in cumulative:
                hg, ag = int(r["model_home_goals_target_reg_ot_excl_so"]), int(r["model_away_goals_target_reg_ot_excl_so"])
                hm, am = float(r["home_expected_goals"]), float(r["away_expected_goals"])
                cumulative_nll.append(-(hg*math.log(max(hm, 1e-12))-hm-math.lgamma(hg+1) + ag*math.log(max(am, 1e-12))-am-math.lgamma(ag+1)))
            totals_and_puck = {}
            for line in (5.5, 6.5):
                field = f"p_over_{line}"
                total_y = [int(r["model_home_goals_target_reg_ot_excl_so"]) + int(r["model_away_goals_target_reg_ot_excl_so"]) > line for r in model_month]
                p_over = np.asarray([float(r[field]) for r in model_month])
                totals_and_puck[f"over_{line}"] = {"brier": float(np.mean((p_over-np.asarray(total_y, dtype=float))**2)),
                                                   "n": len(model_month)}
            puck_y = [int(r["model_home_goals_target_reg_ot_excl_so"]) - int(r["model_away_goals_target_reg_ot_excl_so"]) > 1.5 for r in model_month]
            puck_p = np.asarray([float(r["p_home_minus_1_5"]) for r in model_month])
            totals_and_puck["home_minus_1_5"] = {"brier": float(np.mean((puck_p-np.asarray(puck_y, dtype=float))**2)), "n": len(model_month)}
            cumulative_totals_and_puck = {}
            for line in (5.5, 6.5):
                field = f"p_over_{line}"
                total_y = [int(r["model_home_goals_target_reg_ot_excl_so"]) + int(r["model_away_goals_target_reg_ot_excl_so"]) > line for r in cumulative]
                p_over = np.asarray([float(r[field]) for r in cumulative])
                cumulative_totals_and_puck[f"over_{line}"] = {"brier": float(np.mean((p_over-np.asarray(total_y, dtype=float))**2)),
                                                                "n": len(cumulative)}
            cumulative_puck_y = [int(r["model_home_goals_target_reg_ot_excl_so"]) - int(r["model_away_goals_target_reg_ot_excl_so"]) > 1.5 for r in cumulative]
            cumulative_puck_p = np.asarray([float(r["p_home_minus_1_5"]) for r in cumulative])
            cumulative_totals_and_puck["home_minus_1_5"] = {"brier": float(np.mean((cumulative_puck_p-np.asarray(cumulative_puck_y, dtype=float))**2)),
                                                               "n": len(cumulative)}
            reports.setdefault(month, {})[model_name] = {
                "month": {"moneyline": binary_metrics(model_month, "home_win_probability", y),
                          "team_goal_mae": float(np.mean(goals)), "joint_goal_nll": float(np.mean(nll)),
                          "totals_puckline_brier": totals_and_puck, "n_scored": len(model_month)},
                "cumulative": {"moneyline": binary_metrics(cumulative_outcomes, "home_win_probability", y),
                               "joint_goal_nll": float(np.mean(cumulative_nll)),
                               "team_goal_mae": float(np.mean([(abs(int(r["home_expected_goals"])-int(r["model_home_goals_target_reg_ot_excl_so"]))+
                                   abs(int(r["away_expected_goals"])-int(r["model_away_goals_target_reg_ot_excl_so"]))) / 2 for r in cumulative])),
                               "totals_puckline_brier": cumulative_totals_and_puck,
                               "n_scored": len(cumulative)},
            }
        # Paired game-level Brier intervals; candidates must share identical IDs.
        cumulative_rows = [r for r in rows if r["game_date"][:7] <= month]
        month_by_model = {m: {int(r["game_id"]): r for r in cumulative_rows if r["model_name"] == m} for m in MODELS}
        common = set.intersection(*(set(v) for v in month_by_model.values())) if all(month_by_model.values()) else set()
        pairs = {}
        for a, b in (("B7_elo_xg_poisson", "B3_elo"), ("B7_elo_xg_poisson", "B5_xg_poisson")):
            ids = sorted(common)
            loss_a = [(float(month_by_model[a][gid]["home_win_probability"])-int(month_by_model[a][gid][y]))**2 for gid in ids]
            loss_b = [(float(month_by_model[b][gid]["home_win_probability"])-int(month_by_model[b][gid][y]))**2 for gid in ids]
            mae_a, mae_b, nll_a, nll_b = [], [], [], []
            for gid in ids:
                ra, rb = month_by_model[a][gid], month_by_model[b][gid]
                hg = int(ra["model_home_goals_target_reg_ot_excl_so"])
                ag = int(ra["model_away_goals_target_reg_ot_excl_so"])
                mae_a.append((abs(float(ra["home_expected_goals"])-hg)+abs(float(ra["away_expected_goals"])-ag))/2)
                mae_b.append((abs(float(rb["home_expected_goals"])-hg)+abs(float(rb["away_expected_goals"])-ag))/2)
                nll_a.append(-(hg*math.log(max(float(ra["home_expected_goals"]),1e-12))-float(ra["home_expected_goals"])-math.lgamma(hg+1)
                               +ag*math.log(max(float(ra["away_expected_goals"]),1e-12))-float(ra["away_expected_goals"])-math.lgamma(ag+1)))
                nll_b.append(-(hg*math.log(max(float(rb["home_expected_goals"]),1e-12))-float(rb["home_expected_goals"])-math.lgamma(hg+1)
                               +ag*math.log(max(float(rb["away_expected_goals"]),1e-12))-float(rb["away_expected_goals"])-math.lgamma(ag+1)))
            pairs[f"{a}_minus_{b}"] = {"moneyline_brier": paired_ci(loss_a, loss_b),
                                         "team_goal_mae": paired_ci(mae_a, mae_b), "joint_goal_nll": paired_ci(nll_a, nll_b)}
        reports[month]["paired_game_level_brier"] = pairs
    quote_rows = read_jsonl(MARKETS_LEDGER)
    latest_quote_by_game = {}
    for quote in quote_rows:
        latest_quote_by_game.setdefault(int(quote["game_id"]), []).append(quote)
    market_by_month = {}
    for month in sorted(by_month):
        cumulative_game_ids = {int(r["game_id"]) for r in rows if r["game_date"][:7] <= month}
        game_ids = {int(r["game_id"]) for r in by_month[month]}
        for period_name, period_game_ids in (("month", game_ids), ("cumulative", cumulative_game_ids)):
            observations = []
            period_latest_quotes = []
            for gid in period_game_ids:
                qrows = latest_quote_by_game.get(gid, [])
                latest_row = max(qrows, key=lambda q: q["captured_at_utc"], default=None)
                latest_batch = latest_row.get("capture_batch_id") if latest_row else None
                if latest_batch:
                    latest_snapshot = [q for q in qrows if q.get("capture_batch_id") == latest_batch]
                else:
                    latest_at = latest_row.get("captured_at_utc") if latest_row else None
                    latest_snapshot = [q for q in qrows if q["captured_at_utc"] == latest_at]
                period_latest_quotes.extend(latest_snapshot)
                captured = [q for q in latest_snapshot if q.get("coverage_status") == "captured" and q.get("yes_bid") is not None and q.get("yes_ask") is not None]
                sides = {q["market_side_team"]: q for q in captured}
                model_game = next((r for r in rows if int(r["game_id"]) == gid), None)
                if not model_game:
                    continue
                if set(sides) == {model_game["home_team"], model_game["away_team"]} and all(
                    q.get("quote_quality") == "two_sided_spread_at_most_20c" for q in sides.values()
                ):
                    qh, qa = sides[model_game["home_team"]], sides[model_game["away_team"]]
                    hm = (float(qh["yes_bid"])+float(qh["yes_ask"]))/2
                    am = (float(qa["yes_bid"])+float(qa["yes_ask"]))/2
                    if hm + am > 0:
                        observations.append({"game_id": gid, "p_home": hm/(hm+am), "home_spread": qh["yes_ask"]-qh["yes_bid"],
                                             "away_spread": qa["yes_ask"]-qa["yes_bid"],
                                             "seconds_before_start": float(np.mean([qh["seconds_before_start"], qa["seconds_before_start"]])),
                                             "home_win": int(model_game["official_home_winner"])})
            coverage = {"forecast_games": len(period_game_ids),
                        "latest_market_contract_snapshots": len(period_latest_quotes),
                        "captured_contracts": sum(q.get("coverage_status") == "captured" for q in period_latest_quotes),
                        "missing_or_ambiguous_events": sum(q.get("coverage_status") == "missing_or_ambiguous_event" for q in period_latest_quotes),
                        "wide_spread_contracts": sum(q.get("quote_quality") == "wide_spread_over_20c" for q in period_latest_quotes),
                        "incomplete_book_contracts": sum(q.get("quote_quality") == "incomplete_or_crossed_book" for q in period_latest_quotes),
                        "usable_two_sided_games": len(observations)}
            market_coverage_by_month.setdefault(month, {})[period_name] = coverage
            if not observations:
                market_by_month.setdefault(month, {})[period_name] = {"coverage": coverage, "normalized_midpoint_moneyline": None,
                                                                      "statistical_models_same_market_sample": {}}
                continue
            valid_ids = {x["game_id"] for x in observations}
            report = {"coverage": coverage,
                      "normalized_midpoint_moneyline": binary_metrics(observations, "p_home", "home_win"),
                      "mean_home_spread": float(np.mean([x["home_spread"] for x in observations])),
                      "mean_away_spread": float(np.mean([x["away_spread"] for x in observations])),
                      "mean_quote_seconds_before_start": float(np.mean([x["seconds_before_start"] for x in observations])),
                      "statistical_models_same_market_sample": {m: binary_metrics(
                          [r for r in rows if int(r["game_id"]) in valid_ids and r["model_name"] == m],
                          "home_win_probability", "official_home_winner") for m in MODELS}}
            market_probability = {int(x["game_id"]): float(x["p_home"]) for x in observations}
            market_result = {int(x["game_id"]): int(x["home_win"]) for x in observations}
            report["paired_model_minus_kalshi_brier"] = {}
            for model_name in MODELS:
                model_rows = {int(r["game_id"]): r for r in rows
                              if int(r["game_id"]) in valid_ids and r["model_name"] == model_name}
                common_ids = sorted(valid_ids & set(model_rows))
                model_losses = [(float(model_rows[gid]["home_win_probability"])-market_result[gid])**2 for gid in common_ids]
                market_losses = [(market_probability[gid]-market_result[gid])**2 for gid in common_ids]
                report["paired_model_minus_kalshi_brier"][model_name] = paired_ci(model_losses, market_losses)
            market_by_month.setdefault(month, {})[period_name] = report
            market_coverage_by_month.setdefault(month, {})[period_name] = report["coverage"]
    output = {"generated_at_utc": iso(), "session": json.loads(MANIFEST.read_text()) if MANIFEST.exists() else None,
              "forecast_count": len(forecasts), "graded_game_model_rows": len(rows), "monthly_cumulative": reports,
              "paired_interval_convention": "paired game-level loss difference, model A minus model B; positive values mean model A has greater loss",
              "market_data_separate_from_model_features": True, "market_comparison_by_month": market_by_month,
              "market_quote_coverage_by_month": market_coverage_by_month,
              "limitations": ["Regulation-only win probability is not modeled in v1.",
                              "Market settlement transformations are not applied to goal totals until a versioned contract rule is recorded."]}
    path = HERE / f"cumulative_results_2026-27_{utcnow().strftime('%Y%m%dT%H%M%S%fZ')}.json"
    path.write_bytes(json_bytes(output))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze", help="fit the frozen model specification on historical training data")
    sub.add_parser("init", help="start the prospective clock; write-once")
    p_forecast = sub.add_parser("forecast", help="archive pregame forecasts for upcoming NHL games")
    p_forecast.add_argument("--horizon-hours", type=float, default=24)
    sub.add_parser("capture-markets", help="capture separate Kalshi bid/ask and orderbook snapshots")
    sub.add_parser("collect-results", help="append official completed-game outcomes")
    sub.add_parser("complete-score-distributions", help="append full score matrices for early forecast rows missing inline distributions")
    sub.add_parser("report", help="write the first cumulative monthly scoring report")
    args = parser.parse_args()
    if args.command == "freeze":
        artifact = fit_frozen()
        if MODEL_PATH.exists():
            raise RuntimeError(f"Model artifact already exists: {MODEL_PATH}; frozen versions are write-once")
        MODEL_PATH.write_bytes(json_bytes(artifact))
        print(json.dumps({"model_version": artifact["model_version"], "sha256": sha_file(MODEL_PATH), "fit_rows": artifact["fit_rows"]}, indent=2))
    elif args.command == "init":
        print(json.dumps(init_session(), indent=2))
    elif args.command == "forecast":
        rows = forecast(args.horizon_hours)
        print(json.dumps({"forecast_rows_appended": len(rows), "games": sorted({r['game_id'] for r in rows})}, indent=2))
    elif args.command == "capture-markets":
        rows = capture_markets()
        print(json.dumps({"market_rows_appended": len(rows),
                          "captured_contracts": sum(r['coverage_status']=='captured' for r in rows),
                          "usable_spread_contracts": sum(r.get('quote_quality')=='two_sided_spread_at_most_20c' for r in rows),
                          "wide_spread_contracts": sum(r.get('quote_quality')=='wide_spread_over_20c' for r in rows)}, indent=2))
    elif args.command == "collect-results":
        rows = collect_official_results()
        print(json.dumps({"official_result_rows_appended": len(rows)}, indent=2))
    elif args.command == "complete-score-distributions":
        rows = append_missing_score_distributions()
        print(json.dumps({"supplemental_score_distributions_appended": len(rows)}, indent=2))
    elif args.command == "report":
        print(json.dumps(cumulative_report(), indent=2))


if __name__ == "__main__":
    main()
