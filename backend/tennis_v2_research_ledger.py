#!/usr/bin/env python3
"""Freeze and grade a research-only prospective ledger for tennis simulator V2.

The ledger is a separate SQLite file. It records calibrated Elo, Elo plus direct
point-model features, Elo-informed V2, and direct/V2 total-games distributions.
Historical point features are frozen to verified Grand Slam Archive and Match
Charting Project sequences through 2024, matching the development experiment.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
import sys
from collections import defaultdict, Counter
from itertools import groupby
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research/tennis/point-events/2026-10-16"))
sys.path.insert(0, str(ROOT / "backend"))

import analyze_archives as archives  # noqa: E402
import tennis_match_sim as sim  # noqa: E402
import tennis_point_model as point_model  # noqa: E402
import tennis_total_games_backtest as total_games  # noqa: E402
from tennis_bovada_odds import bovada_odds  # noqa: E402

MODEL_VERSION = "tennis-elo-informed-simulator-v2-research-2026-10-16"
POINT_HISTORY_CUTOFF = 20241231
ELO_START = 1500.0
ELO_K = 32.0
ELO_GAMMA = 0.1
ELO_CALIBRATION_SLOPE = 0.7214679709875599
V2_CALIBRATION_SLOPE = 0.4273928354003909
ELO_POINT_ELO_COEF = 0.6954341956477393
ELO_POINT_FEATURE_COEF = 0.3996709769192981
STANDARD_RULES = total_games.STANDARD_RULES
SURFACE_BY_TOURNAMENT_ID = {"315": "Hard", "381": "Hard"}
DEFAULT_LEDGER = Path(os.environ.get("LP_TENNIS_V2_LEDGER_PATH") or
                      ROOT / "backend/data/tennis_v2_research.sqlite3")


def _logit(probability: float) -> float:
    p = min(1.0 - 1e-9, max(1e-9, probability))
    return math.log(p / (1.0 - p))


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, value))))


def _ordinal(day: int) -> int:
    return point_model._ordinal(day)


def _scoreboard_matches(con: sqlite3.Connection, now: dt.datetime,
                        days: int) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT league,game_id,start_time,payload FROM scoreboard_snapshots "
        "WHERE league IN ('atp','wta') AND LOWER(state)='pre' AND start_time IS NOT NULL "
        "ORDER BY start_time,game_id"
    ).fetchall()
    until = now + dt.timedelta(days=days)
    matches = []
    for league, game_id, start_time, payload in rows:
        try:
            start = dt.datetime.fromisoformat(str(start_time).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=dt.timezone.utc)
            start = start.astimezone(dt.timezone.utc)
            game = json.loads(payload)
        except (TypeError, ValueError):
            continue
        if not now < start <= until:
            continue
        game["_league"] = league
        game["_game_id"] = str(game_id)
        game["_start_time"] = start.isoformat()
        game["_start_date"] = int(start.strftime("%Y%m%d"))
        matches.append(game)
    return matches


def _sackmann_ids(con: sqlite3.Connection, game: dict[str, Any]) -> tuple[str | None, str | None]:
    result = []
    league = game["_league"]
    for side in ("home", "away"):
        athlete_id = str((game.get(side) or {}).get("athlete_id") or "")
        row = con.execute(
            "SELECT si.source_player_key FROM players p "
            "JOIN player_source_ids si ON si.player_id=p.id "
            "WHERE p.league=? AND p.espn_id=? AND si.source='sackmann' AND si.league=?",
            (league, athlete_id, league),
        ).fetchone() if athlete_id else None
        result.append(str(row[0]) if row else None)
    return result[0], result[1]


def _surface(game: dict[str, Any]) -> str | None:
    event_id = str(game.get("tournament_id") or "")
    if event_id in SURFACE_BY_TOURNAMENT_ID:
        return SURFACE_BY_TOURNAMENT_ID[event_id]
    event = str(game.get("event") or "").lower()
    if "shanghai" in event or "wuhan" in event:
        return "Hard"
    return None


def _simulator_distribution(point_home: float, point_away: float) -> tuple[float, dict[str, float], dict[str, float]]:
    result = sim.match_distribution(point_home, point_away, STANDARD_RULES, first_server=None)
    resolved = result["p_a"] + result["p_b"]
    if resolved <= 0 or result["unresolved"] > 1e-8:
        raise ValueError("V2 match simulation did not resolve all probability mass")
    pmf = {str(value): mass / resolved for value, mass in result["total_games"].items() if mass > 0}
    structure = {
        "deciding_set_probability": result["sets_played"].get(3, 0.0) / resolved,
        "any_tiebreak_probability": result["p_tiebreak_any"] / resolved,
    }
    return result["p_a"] / resolved, pmf, structure


def _player_counts(stats: Any, tour: str, surface: str, player_id: int,
                   day: int) -> dict[str, float]:
    serve_won, serve_n, return_won, return_n = stats.player_counts(
        tour, surface, player_id, day
    )
    return {"serve_points_won": serve_won, "serve_points": serve_n,
            "return_points_won": return_won, "return_points": return_n}


def _forecast_identity(game: dict[str, Any],
                       sackmann_ids: tuple[str | None, str | None]) -> dict[str, str]:
    home_sackmann, away_sackmann = sackmann_ids
    return {
        "home_sackmann_id": str(home_sackmann or ""),
        "away_sackmann_id": str(away_sackmann or ""),
        "home_espn_id": str((game.get("home") or {}).get("athlete_id") or ""),
        "away_espn_id": str((game.get("away") or {}).get("athlete_id") or ""),
    }


def _make_forecast(game: dict[str, Any], ids: tuple[str | None, str | None], surface: str,
                   stats: Any, elo: dict[tuple[str, int], float], direct: Any,
                   source_info: list[dict[str, str]]) -> dict[str, Any] | None:
    home_text, away_text = ids
    if not home_text or not away_text:
        return None
    try:
        home_id, away_id = int(home_text), int(away_text)
    except (TypeError, ValueError):
        return None
    tour, day = game["_league"], game["_start_date"]
    baseline = stats.baseline(tour, surface)
    home_elo = elo[(tour, home_id)]
    away_elo = elo[(tour, away_id)]
    elo_raw = _sigmoid(math.log(10.0) * (home_elo - away_elo) / 400.0)

    serve_h = stats.serve(tour, surface, home_id, day, baseline)
    serve_a = stats.serve(tour, surface, away_id, day, baseline)
    return_h = stats.returns(tour, surface, home_id, day, baseline)
    return_a = stats.returns(tour, surface, away_id, day, baseline)
    point_home = point_model.point_prob(serve_h, return_a, baseline)
    point_away = point_model.point_prob(serve_a, return_h, baseline)
    point_difference = _logit(point_home) - _logit(point_away)
    elo_calibrated = _sigmoid(ELO_CALIBRATION_SLOPE * _logit(elo_raw))
    elo_plus_point = _sigmoid(ELO_POINT_ELO_COEF * _logit(elo_raw)
                              + ELO_POINT_FEATURE_COEF * point_difference)

    strength_home = math.log(10.0) * (home_elo - ELO_START) / 400.0
    strength_away = math.log(10.0) * (away_elo - ELO_START) / 400.0
    adjusted_serve_h = _sigmoid(_logit(serve_h) + ELO_GAMMA * strength_home)
    adjusted_serve_a = _sigmoid(_logit(serve_a) + ELO_GAMMA * strength_away)
    adjusted_return_h = _sigmoid(_logit(return_h) + ELO_GAMMA * strength_home)
    adjusted_return_a = _sigmoid(_logit(return_a) + ELO_GAMMA * strength_away)
    v2_point_home = point_model.point_prob(adjusted_serve_h, adjusted_return_a, baseline)
    v2_point_away = point_model.point_prob(adjusted_serve_a, adjusted_return_h, baseline)
    v2_raw_winner, v2_pmf, v2_structure = _simulator_distribution(v2_point_home, v2_point_away)
    v2_calibrated = _sigmoid(V2_CALIBRATION_SLOPE * _logit(v2_raw_winner))

    format_key = "standard_tiebreak_7"
    support = total_games.support_for(format_key)
    competition = total_games.competition_bucket(abs(home_elo - away_elo))
    direct_pmf = direct.forecasts(format_key, surface, competition, _ordinal(day), support)[
        "direct_surface_competitive"
    ]
    direct_pmf = {str(value): probability for value, probability in zip(support, direct_pmf)}
    home_name = (game.get("home") or {}).get("name")
    away_name = (game.get("away") or {}).get("name")
    return {
        "schema_version": 1,
        "model_version": MODEL_VERSION,
        "tour": tour,
        "game_id": game["_game_id"],
        "start_time": game["_start_time"],
        "locked_at": None,
        "tournament": game.get("event"),
        "round": game.get("round"),
        "surface": surface,
        "home_player": home_name,
        "away_player": away_name,
        "identity": _forecast_identity(game, ids),
        "inputs": {
            "history_cutoff": dt.datetime.strptime(
                str(POINT_HISTORY_CUTOFF), "%Y%m%d"
            ).date().isoformat(),
            "point_sources": source_info,
            "surface_baseline": baseline,
            "elo_home": home_elo,
            "elo_away": away_elo,
            "point_home_raw": point_home,
            "point_away_raw": point_away,
            "point_home_elo_adjusted": v2_point_home,
            "point_away_elo_adjusted": v2_point_away,
            "home_point_history": _player_counts(stats, tour, surface, home_id, day),
            "away_point_history": _player_counts(stats, tour, surface, away_id, day),
            "sportsbook_odds_used": False,
        },
        "calibration": {
            "method": "symmetric logistic; trained on 2021 validation matches",
            "elo_logit_slope": ELO_CALIBRATION_SLOPE,
            "elo_plus_point_coefficients": {
                "elo_logit": ELO_POINT_ELO_COEF,
                "point_logit_difference": ELO_POINT_FEATURE_COEF,
            },
            "v2_logit_slope": V2_CALIBRATION_SLOPE,
            "elo_strength_gamma": ELO_GAMMA,
        },
        "match_winner_home_probability": {
            "calibrated_elo": elo_calibrated,
            "elo_plus_point_features": elo_plus_point,
            "elo_informed_v2": v2_calibrated,
        },
        "total_games_pmf": {
            "direct_format_surface_competitiveness": direct_pmf,
            "elo_informed_v2": v2_pmf,
        },
        "match_structure_probability": {"elo_informed_v2": v2_structure},
        "scoring_rules": STANDARD_RULES,
    }


def _load_research_context(db_path: str, forecast_days: list[int]) -> tuple[dict[int, list[dict[str, Any]]], Any, Any, Any, list[dict[str, str]]]:
    archives.MAIN_DB = Path(db_path)
    # Match the frozen V2 experiment: point features came from the two historical archives,
    # with no US Open or Kalshi observations in the 2021 validation / 2022-24 test window.
    archives.ARCHIVES = [row for row in archives.ARCHIVES
                         if row[0] in ("grand_slam_archive", "match_charting_project")]
    main_rows, main_index = archives.read_main(Path(db_path))
    raw_histories, _ = archives.archive_records(main_index)
    verified, _ = archives.deduplicate([
        row for row in raw_histories
        if row["full"] and 2000 <= row["year"] <= POINT_HISTORY_CUTOFF // 10000
    ])
    point_counts = archives.match_point_counts(verified)
    by_point_day: dict[int, list[tuple[dict[str, Any], Counter]]] = defaultdict(list)
    for match in verified:
        counts = point_counts.get(match["source"], {}).get(match["key"], Counter())
        by_point_day[int(match["tourney_date"])].append((match, counts))

    main_by_day: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in main_rows:
        main_by_day[int(row["tourney_date"])].append(row)
    tour_rows: dict[int, list[tuple]] = defaultdict(list)
    for tour in ("atp", "wta"):
        for row in total_games.load_matches(db_path, tour, max(forecast_days)):
            tour_rows[int(row[0])].append((tour, row))

    stats = archives.PointStats()
    elo: dict[tuple[str, int], float] = defaultdict(lambda: ELO_START)
    direct = total_games.DirectGames()
    days = sorted(set(main_by_day) | set(by_point_day) | set(forecast_days))
    contexts: dict[int, tuple[Any, Any, Any]] = {}
    for day in days:
        if day in forecast_days:
            contexts[day] = (copy.deepcopy(stats), elo.copy(), copy.deepcopy(direct))

        # Update point histories only after the whole date block has been forecast.
        for match, counts in by_point_day.get(day, []):
            stats.add(match, counts)

        rows = tour_rows.get(day, [])
        # The empirical games distribution uses pre-match Elo buckets and prior dates only.
        for tour, row in rows:
            date, event_id, event_name, level, surface, winner, loser, best_of, score = row[:9]
            if date < total_games.HISTORY_START or best_of != 3 or not total_games.is_complete(score):
                continue
            tagged = total_games.score_format(score, level, event_name, date)
            if tagged is None:
                continue
            format_key, _ = tagged
            observed = total_games.total_games_from_score(score, format_key)
            if observed is None:
                continue
            direct.add(format_key, surface, total_games.competition_bucket(
                abs(elo[(tour, winner)] - elo[(tour, loser)])), observed, _ordinal(date))

        # Elo updates are date-blocked and include complete main-tour match results.
        deltas = []
        for row in main_by_day.get(day, []):
            if not archives.is_complete(row.get("score")):
                continue
            tour = row["tour"]
            winner, loser = int(row["winner_id"]), int(row["loser_id"])
            expected = 1.0 / (1.0 + 10.0 ** ((elo[(tour, loser)] - elo[(tour, winner)]) / 400.0))
            deltas.append((tour, winner, loser, ELO_K * (1.0 - expected)))
        for tour, winner, loser, delta in deltas:
            elo[(tour, winner)] += delta
            elo[(tour, loser)] -= delta

    source_info = []
    for source, path, _ in archives.ARCHIVES:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as source_con:
            row = source_con.execute(
                "SELECT source,source_dataset,source_commit FROM tennis_point_sources LIMIT 1"
            ).fetchone()
        source_info.append({"source": row[0], "dataset": row[1], "commit": row[2] or ""})
    return contexts, stats, elo, direct, source_info


def _ensure_ledger(con: sqlite3.Connection) -> None:
    con.executescript("""
      CREATE TABLE IF NOT EXISTS tennis_v2_research_forecasts(
        tour TEXT NOT NULL,
        game_id TEXT NOT NULL,
        locked_at TEXT NOT NULL,
        start_time TEXT NOT NULL,
        model_version TEXT NOT NULL,
        payload TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        PRIMARY KEY(tour,game_id)
      );
      CREATE TABLE IF NOT EXISTS tennis_v2_research_grades(
        tour TEXT NOT NULL,
        game_id TEXT NOT NULL,
        graded_at TEXT NOT NULL,
        actual_winner TEXT,
        actual_total_games INTEGER,
        actual_deciding_set INTEGER,
        actual_any_tiebreak INTEGER,
        scores_json TEXT NOT NULL,
        PRIMARY KEY(tour,game_id)
      );
    """)


def _store_forecast(ledger: sqlite3.Connection, payload: dict[str, Any]) -> int:
    """Insert a forecast once; retries can never rewrite an existing lock."""
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(serialized.encode()).hexdigest()
    result = ledger.execute(
        "INSERT OR IGNORE INTO tennis_v2_research_forecasts "
        "(tour,game_id,locked_at,start_time,model_version,payload,payload_sha256) "
        "VALUES(?,?,?,?,?,?,?)",
        (payload["tour"], payload["game_id"], payload["locked_at"],
         payload["start_time"], payload["model_version"], serialized, digest),
    )
    return result.rowcount


def _identifier(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _espn_id_for_sackmann(source: sqlite3.Connection, tour: str,
                          sackmann_id: Any) -> str | None:
    key = _identifier(sackmann_id)
    if not key:
        return None
    rows = source.execute(
        "SELECT p.espn_id FROM players p "
        "JOIN player_source_ids si ON si.player_id=p.id "
        "WHERE p.league=? AND si.source='sackmann' AND si.league=? "
        "AND si.source_player_key=? AND p.espn_id IS NOT NULL",
        (tour, tour, key),
    ).fetchall()
    ids = {_identifier(row[0]) for row in rows} - {None}
    return next(iter(ids)) if len(ids) == 1 else None


def _locked_espn_ids(source: sqlite3.Connection,
                     forecast: dict[str, Any]) -> tuple[str | None, str | None]:
    identity = forecast.get("identity") or {}
    tour = str(forecast.get("tour") or "")
    home_id = _identifier(identity.get("home_espn_id"))
    away_id = _identifier(identity.get("away_espn_id"))
    if home_id is None:
        home_id = _espn_id_for_sackmann(source, tour, identity.get("home_sackmann_id"))
    if away_id is None:
        away_id = _espn_id_for_sackmann(source, tour, identity.get("away_sackmann_id"))
    return home_id, away_id


def _identity_matches(source: sqlite3.Connection, forecast: dict[str, Any],
                      game: dict[str, Any]) -> bool:
    expected_home, expected_away = _locked_espn_ids(source, forecast)
    actual_home = _identifier((game.get("home") or {}).get("athlete_id"))
    actual_away = _identifier((game.get("away") or {}).get("athlete_id"))
    return bool(
        expected_home and expected_away and expected_home != expected_away
        and actual_home == expected_home and actual_away == expected_away
    )


def _final_outcome(game: dict[str, Any], state: str) -> dict[str, Any] | None:
    status = str(game.get("status") or "").lower()
    if any(token in status for token in (
        "cancel", "postpon", "retir", "walkover", "abandon", "default"
    )):
        return None
    home, away = game.get("home") or {}, game.get("away") or {}
    try:
        home_score, away_score = float(home.get("score")), float(away.get("score"))
        hs, aws = [int(x) for x in home.get("sets") or []], [int(x) for x in away.get("sets") or []]
    except (TypeError, ValueError):
        return None
    if (state != "post" or game.get("completed") is not True or home_score == away_score
            or not hs or len(hs) != len(aws)):
        return None
    return {
        "winner": home.get("name") if home_score > away_score else away.get("name"),
        "home_won": int(home_score > away_score),
        "total_games": sum(hs) + sum(aws),
        "deciding_set": int(len(hs) == 3),
        "any_tiebreak": int(any((h, a) in ((7, 6), (6, 7)) for h, a in zip(hs, aws))),
    }


def grade_finals(ledger: sqlite3.Connection, source_db: str,
                 now: dt.datetime) -> dict[str, int]:
    source = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    count = 0
    identity_mismatch = 0
    try:
        for row in ledger.execute(
            "SELECT tour,game_id,payload FROM tennis_v2_research_forecasts "
            "WHERE NOT EXISTS (SELECT 1 FROM tennis_v2_research_grades g "
            "WHERE g.tour=tennis_v2_research_forecasts.tour "
            "AND g.game_id=tennis_v2_research_forecasts.game_id)"
        ):
            snapshots = source.execute(
                "SELECT payload,state FROM scoreboard_snapshots WHERE league=? AND game_id=? "
                "ORDER BY fetched_at DESC LIMIT 1", (row["tour"], row["game_id"])
            ).fetchone()
            if not snapshots:
                continue
            try:
                game = json.loads(snapshots["payload"])
                forecast = json.loads(row["payload"])
            except (TypeError, ValueError):
                continue
            outcome = _final_outcome(game, str(snapshots["state"] or "").lower())
            if outcome is None:
                continue
            if not _identity_matches(source, forecast, game):
                identity_mismatch += 1
                continue
            probs = forecast["match_winner_home_probability"]
            home_won = float(outcome["home_won"])
            scores = {
                name: {
                    "brier": (prob - home_won) ** 2,
                    "log_loss": -math.log(max(1e-12, prob if home_won else 1.0 - prob)),
                }
                for name, prob in probs.items()
            }
            structure = forecast["match_structure_probability"]["elo_informed_v2"]
            scores["elo_informed_v2_deciding_set"] = {
                "brier": (structure["deciding_set_probability"] - outcome["deciding_set"]) ** 2
            }
            scores["elo_informed_v2_any_tiebreak"] = {
                "brier": (structure["any_tiebreak_probability"] - outcome["any_tiebreak"]) ** 2
            }
            for model, distribution in forecast["total_games_pmf"].items():
                support = sorted((int(k), float(v)) for k, v in distribution.items())
                cdf_model = cdf_actual = 0.0
                crps = 0.0
                for games in range(min(support[0][0], outcome["total_games"]),
                                   max(support[-1][0], outcome["total_games"]) + 1):
                    cdf_model += sum(p for value, p in support if value == games)
                    cdf_actual = float(outcome["total_games"] <= games)
                    crps += (cdf_model - cdf_actual) ** 2
                model_scores = {"crps": crps}
                for line in (18.5, 20.5, 22.5, 24.5, 26.5):
                    p_over = sum(probability for games, probability in support if games > line)
                    observed_over = float(outcome["total_games"] > line)
                    model_scores[f"over_{line}_brier"] = (p_over - observed_over) ** 2
                scores[model] = model_scores
            ledger.execute(
                "INSERT OR IGNORE INTO tennis_v2_research_grades "
                "(tour,game_id,graded_at,actual_winner,actual_total_games,actual_deciding_set,"
                "actual_any_tiebreak,scores_json) VALUES(?,?,?,?,?,?,?,?)",
                (row["tour"], row["game_id"], now.isoformat(), outcome["winner"],
                 outcome["total_games"], outcome["deciding_set"], outcome["any_tiebreak"],
                 json.dumps(scores, sort_keys=True)),
            )
            count += 1
        ledger.commit()
    finally:
        source.close()
    return {"graded": count, "identity_mismatch": identity_mismatch}


def _frozen_bovada_quote(source: sqlite3.Connection, game: dict,
                         now: dt.datetime) -> dict | None:
    """Read the market at the V2 forecast instant without changing its model inputs."""
    ids = []
    for side in ("home", "away"):
        espn_id = str((game.get(side) or {}).get("athlete_id") or "")
        row = source.execute(
            "SELECT id FROM players WHERE league=? AND espn_id=?",
            (game["_league"], espn_id),
        ).fetchone() if espn_id else None
        ids.append(row[0] if row else None)
    return bovada_odds(source, game["_game_id"], game["_league"], ids[0], ids[1], now)


def run(db_path: str, ledger_path: str, days: int) -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    Path(ledger_path).parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    candidates = _scoreboard_matches(source, now, days)
    ledger = sqlite3.connect(ledger_path)
    ledger.row_factory = sqlite3.Row
    try:
        _ensure_ledger(ledger)
        already_locked = {
            (str(row[0]), str(row[1])) for row in ledger.execute(
                "SELECT tour,game_id FROM tennis_v2_research_forecasts"
            )
        }
        matches = [game for game in candidates
                   if (game["_league"], game["_game_id"]) not in already_locked]
        ids = {game["_game_id"]: _sackmann_ids(source, game) for game in matches}
        # These are provenance only, not forecast features. Capture before closing
        # the source DB and freeze alongside the V2 prediction, never afterward.
        book_quotes = {
            game["_game_id"]: _frozen_bovada_quote(source, game, now)
            for game in matches
        }
    except Exception:
        ledger.close()
        source.close()
        raise
    source.close()

    report = {"candidate_matches": len(candidates),
              "already_locked": len(candidates) - len(matches),
              "locked": 0, "unresolved_identity": 0, "graded": 0,
              "quotes_frozen": 0, "quotes_unavailable": 0,
              "ledger": str(ledger_path)}
    try:
        if matches:
            forecast_dates = sorted({game["_start_date"] for game in matches})
            contexts, _, _, _, source_info = _load_research_context(db_path, forecast_dates)
            for game in matches:
                surface = _surface(game)
                if not surface:
                    report["unresolved_identity"] += 1
                    continue
                point_stats, elo, direct = contexts[game["_start_date"]]
                payload = _make_forecast(game, ids[game["_game_id"]], surface,
                                         point_stats, elo, direct, source_info)
                if payload is None:
                    report["unresolved_identity"] += 1
                    continue
                payload["locked_at"] = now.isoformat()
                payload["frozen_bovada_odds"] = book_quotes[game["_game_id"]]
                inserted = _store_forecast(ledger, payload)
                report["locked"] += inserted
                if inserted:
                    key = "quotes_frozen" if payload["frozen_bovada_odds"] is not None else "quotes_unavailable"
                    report[key] += 1
            ledger.commit()
        grading = grade_finals(ledger, db_path, now)
        report["graded"] = grading["graded"]
        report["grade_identity_mismatch"] = grading["identity_mismatch"]
    finally:
        ledger.close()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("LP_DB_PATH") or str(ROOT / "backend/data/picks.dev.db"))
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args(argv)
    if args.days < 1 or args.days > 14:
        parser.error("--days must be between 1 and 14")
    print(json.dumps(run(args.db, args.ledger, args.days), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
