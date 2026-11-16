"""Free, date-specific tennis projections built from pre-match Sackmann history.

This is a read-only walk-forward forecast. A match's date and later results are
excluded from its training data. Player inputs are Sackmann IDs resolved through
the tennis spine; unresolved IDs simply have no player-level projection.
"""
from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from itertools import groupby
from typing import Any

import tennis_match_sim as sim
import tennis_point_model as point_model
from espn_client.scoreboard import major_for_event

ELO_START = 1500.0
ELO_K = 32.0
P0_SHRINK_MATCHES = 10.0
# Every ESPN tournament id we have actually observed, kept as a fast path. This is NOT the
# coverage list: ids for most events are unknown until the event is first seen, so surfaces
# are keyed on the canonical major name from espn_client.scoreboard. Coverage and surfaces
# then come from one list and cannot drift apart.
SURFACE_BY_EVENT = {"189": "Hard", "315": "Hard", "381": "Hard", "959": "Hard"}
SURFACE_BY_MAJOR = {
    "Australian Open": "Hard",
    "French Open": "Clay",
    "Wimbledon": "Grass",
    "US Open": "Hard",
    "Indian Wells": "Hard",
    "Miami Open": "Hard",
    "Monte-Carlo Masters": "Clay",
    "Madrid Open": "Clay",
    "Italian Open": "Clay",
    "Canadian Open": "Hard",
    "Cincinnati Open": "Hard",
    "Shanghai Masters": "Hard",
    "Paris Masters": "Hard",
    "China Open": "Hard",
    "Qatar Open": "Hard",
    "Dubai": "Hard",
    "Wuhan Open": "Hard",
    "ATP Finals": "Hard",
    "WTA Finals": "Hard",
    # ATP 500s, 2026. Surfaces from the tour listings (toomanyrackets.com, tennis-db.com).
    "Dallas Open": "Hard",
    "Rotterdam Open": "Hard",
    "Qatar ExxonMobil Open": "Hard",
    "Rio Open": "Clay",
    "Acapulco Open": "Hard",
    "Barcelona Open": "Clay",
    "Munich Open": "Clay",
    "Hamburg Open": "Clay",
    "Halle Open": "Grass",
    "Queen's Club": "Grass",
    "Washington": "Hard",
    "Tokyo Open": "Hard",
    "Vienna Open": "Hard",
    "Basel": "Hard",
    # WTA 500s, 2026. Linz is Hard: the 2025 WTA data lists it as Hard, and tennis-db says Clay.
    "Brisbane International": "Hard",
    "Adelaide International": "Hard",
    "Abu Dhabi Open": "Hard",
    "Mérida Open": "Hard",
    "Charleston Open": "Clay",
    "Linz Open": "Hard",
    "Stuttgart Open": "Clay",
    "Strasbourg Open": "Clay",
    "Berlin Open": "Grass",
    "Bad Homburg Open": "Grass",
    "Monterrey Open": "Hard",
    "Guadalajara Open": "Hard",
    "Singapore Tennis Open": "Hard",
    "Ningbo Open": "Hard",
    "Pan Pacific Open": "Hard",
    # ATP 250s, 2026. Surfaces from the ATP's 2026 calendar. Brisbane and Adelaide are above, shared with the WTA 500s.
    "Hong Kong Tennis Open": "Hard",
    "ASB Classic": "Hard",
    "Open Occitanie": "Hard",
    "Argentina Open": "Clay",
    "Delray Beach Open": "Hard",
    "Chile Open": "Clay",
    "Tiriac Open": "Clay",
    "US Men's Clay Court Championship": "Clay",
    "Grand Prix Hassan II": "Clay",
    "Geneva Open": "Clay",
    "Boss Open": "Grass",
    "Libéma Open": "Grass",
    "Mallorca Championships": "Grass",
    "Eastbourne Open": "Grass",
    "Nordea Open": "Clay",
    "Gstaad Open": "Clay",
    "Umag Open": "Clay",
    "Generali Open": "Clay",
    "Estoril Open": "Clay",
    "Mifel Tennis Open": "Hard",
    "Winston-Salem Open": "Hard",
    "Chengdu Open": "Hard",
    "Hangzhou Open": "Hard",
    "Almaty Open": "Hard",
    "Brussels Open": "Hard",
    "Lyon Open": "Hard",
    "Stockholm Open": "Hard",
    # WTA 250s, 2026. Surfaces from tennis-db and the Wikipedia 2026 WTA calendar, which agree. ASB Classic,
    # Libéma and Eastbourne are shared with the ATP 250s above and below.
    "Hobart International": "Hard",
    "Ostrava Open": "Hard",
    "Transylvania Open": "Hard",
    "ATX Open": "Hard",
    "Bogotá Open": "Clay",
    "Rouen Open": "Clay",
    "Morocco Open": "Clay",
    "Nottingham Open": "Grass",
    "Iași Open": "Clay",
    "Athens Open": "Hard",
    "Hamburg Ladies Open": "Clay",
    "Prague Open": "Hard",
    "Memphis Classic": "Hard",
    "São Paulo Open": "Hard",
    "Korea Open": "Hard",
    "Japan Women's Open": "Hard",
    "Guangzhou Open": "Hard",
    "Hong Kong Open": "Hard",
    "Chennai Open": "Hard",
}
# Men's Grand Slams are best of five; every other tracked event on both tours is best of three.
FIVE_SET_MAJORS = {"Australian Open", "French Open", "Wimbledon", "US Open"}
HISTORY_START = 20200101
DOUBLE_FAULT_FIELDS = ("homeDoubleFaults", "awayDoubleFaults")


def _ensure_store(con: sqlite3.Connection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS tennis_projection_days ("
                "league TEXT NOT NULL, model_day TEXT NOT NULL, computed_at TEXT NOT NULL, "
                "PRIMARY KEY (league, model_day))")
    con.execute("CREATE TABLE IF NOT EXISTS tennis_projection_candidates ("
                "league TEXT NOT NULL, model_day TEXT NOT NULL, game_id TEXT NOT NULL, projection TEXT NOT NULL, "
                "PRIMARY KEY (league, model_day, game_id))")


def stored_candidates(con: sqlite3.Connection, league: str, model_day: str) -> dict[str, Any] | None:
    """Projections precomputed for one league and UTC model day, or None if that day was never computed."""
    _ensure_store(con)
    if con.execute("SELECT 1 FROM tennis_projection_days WHERE league=? AND model_day=?",
                   (league, model_day)).fetchone() is None:
        return None
    rows = con.execute("SELECT game_id, projection FROM tennis_projection_candidates WHERE league=? AND model_day=?",
                       (league, model_day)).fetchall()
    return {game_id: json.loads(projection) for game_id, projection in rows}


def store_candidates(con: sqlite3.Connection, league: str, model_day: str,
                     candidates: dict[str, Any], computed_at: str) -> None:
    """Replace the stored projections for one league and UTC model day."""
    _ensure_store(con)
    con.execute("DELETE FROM tennis_projection_candidates WHERE league=? AND model_day=?", (league, model_day))
    con.executemany("INSERT INTO tennis_projection_candidates (league, model_day, game_id, projection) VALUES (?,?,?,?)",
                    [(league, model_day, game_id, json.dumps(projection)) for game_id, projection in candidates.items()])
    con.execute("INSERT OR REPLACE INTO tennis_projection_days (league, model_day, computed_at) VALUES (?,?,?)",
                (league, model_day, computed_at))


def forget_days(con: sqlite3.Connection, league: str, model_days: list[str]) -> None:
    """Drop stored projections for these days so the next read recomputes them."""
    _ensure_store(con)
    for model_day in model_days:
        con.execute("DELETE FROM tennis_projection_candidates WHERE league=? AND model_day=?", (league, model_day))
        con.execute("DELETE FROM tennis_projection_days WHERE league=? AND model_day=?", (league, model_day))


def _sackmann_player_ids(match: dict[str, Any]) -> dict[str, str | None]:
    identity = match.get("identity") or {}
    result = {}
    for side in ("home", "away"):
        player_id = (identity.get(side) or {}).get("sackmann_player_id")
        result[side] = str(player_id) if player_id else None
    return result


def needs_projection_refresh(stored: dict[str, Any] | None,
                             matches: list[dict[str, Any]]) -> bool:
    """Refresh missing fields and caches whose tennis-spine mapping has changed."""
    if stored is None:
        return True
    for match in matches:
        projection = stored.get(str(match.get("gameId")))
        if projection is None:
            return True
        if any(field not in projection for field in DOUBLE_FAULT_FIELDS):
            return True
        if projection.get("_sackmannPlayerIds") != _sackmann_player_ids(match):
            return True
    return False


def _logistic(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def _logit(value: float) -> float:
    value = min(max(value, 1e-9), 1.0 - 1e-9)
    return math.log(value / (1.0 - value))


def _complete(score: str | None) -> bool:
    return score is not None and not any(token in score for token in ("RET", "W/O", "DEF", "ABD"))


def _games_interval(distribution: dict[int, float]) -> list[int] | None:
    if not distribution:
        return None
    lo = hi = None
    cumulative = 0.0
    for games, probability in sorted(distribution.items()):
        cumulative += probability
        if lo is None and cumulative >= 0.10:
            lo = games
        if cumulative >= 0.90:
            hi = games
            break
    return [int(lo), int(hi)] if lo is not None and hi is not None else None


def project_day(con: sqlite3.Connection, tour: str, day: str, matches: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return forecasts keyed by ESPN game ID, using data dated before `day`."""
    cutoff = int(day.replace("-", ""))
    table = f"tennis_{tour}_matches"
    sql = (
        f"SELECT tourney_date,surface,winner_id,loser_id,best_of,score,"
        f"w_svpt,w_1stWon,w_2ndWon,l_svpt,l_1stWon,l_2ndWon,w_ace,l_ace,w_df,l_df "
        f"FROM {table} WHERE {point_model.TOUR_FILTER[tour]} AND tourney_date BETWEEN ? AND ? "
        "AND winner_id IS NOT NULL AND loser_id IS NOT NULL ORDER BY tourney_date,match_num"
    )

    global_elo: dict[str, float] = defaultdict(lambda: ELO_START)
    surface_elo: dict[tuple[str, str], float] = defaultdict(lambda: ELO_START)
    state = point_model.OnlineStats(baseline_years=0, half_life_years=None, player_half_life=2.0)
    format_count: dict[int, int] = defaultdict(int)
    format_aces: dict[int, float] = defaultdict(float)
    player_count: dict[tuple[str, int], int] = defaultdict(int)
    player_aces: dict[tuple[str, int], float] = defaultdict(float)
    overall_count = overall_aces = 0.0
    format_df_count: dict[int, int] = defaultdict(int)
    format_double_faults: dict[int, float] = defaultdict(float)
    player_df_count: dict[tuple[str, int], int] = defaultdict(int)
    player_double_faults: dict[tuple[str, int], float] = defaultdict(float)
    overall_df_count = overall_double_faults = 0.0

    history_rows = con.execute(sql, (HISTORY_START, cutoff - 1))
    for _, rows_for_day in groupby(history_rows, key=lambda item: item[0]):
        day_rows = list(rows_for_day)
        global_updates = []
        surface_updates = []
        for row in day_rows:
            winner, loser, surface = str(row[2]), str(row[3]), str(row[1] or "")
            expected = _logistic((global_elo[winner] - global_elo[loser]) * math.log(10.0) / 400.0)
            global_updates.append((winner, loser, ELO_K * (1.0 - expected)))
            if surface:
                expected_surface = _logistic(
                    (surface_elo[(winner, surface)] - surface_elo[(loser, surface)]) * math.log(10.0) / 400.0
                )
                surface_updates.append((winner, loser, surface, ELO_K * (1.0 - expected_surface)))
        # No match on a date informs another match from that same date.
        for winner, loser, delta in global_updates:
            global_elo[winner] += delta
            global_elo[loser] -= delta
        for winner, loser, surface, delta in surface_updates:
            surface_elo[(winner, surface)] += delta
            surface_elo[(loser, surface)] -= delta

        for row in day_rows:
            date, surface, winner, loser, best_of, score = row[:6]
            winner, loser = str(winner), str(loser)
            best_of = int(best_of or 3)
            surface = str(surface or "")
            wace, lace = row[12], row[13]
            if _complete(score) and wace is not None and lace is not None:
                format_count[best_of] += 2
                format_aces[best_of] += float(wace) + float(lace)
                player_count[(winner, best_of)] += 1
                player_count[(loser, best_of)] += 1
                player_aces[(winner, best_of)] += float(wace)
                player_aces[(loser, best_of)] += float(lace)
                overall_count += 2
                overall_aces += float(wace) + float(lace)

            wdf, ldf = row[14], row[15]
            if _complete(score):
                for player_id, double_faults in ((winner, wdf), (loser, ldf)):
                    if double_faults is None or float(double_faults) < 0:
                        continue
                    key = (player_id, best_of)
                    format_df_count[best_of] += 1
                    format_double_faults[best_of] += float(double_faults)
                    player_df_count[key] += 1
                    player_double_faults[key] += float(double_faults)
                    overall_df_count += 1
                    overall_double_faults += float(double_faults)

            wsv, w1, w2, lsv, l1, l2 = row[6:12]
            if (surface and _complete(score) and None not in (wsv, w1, w2, lsv, l1, l2)
                    and wsv > 0 and lsv > 0):
                state.add((int(date), surface, winner, loser, wsv, w1, w2, lsv, l1, l2))

    state.expire(cutoff)
    source_ids: dict[str, str] = {}
    for match in matches:
        for side in ("home", "away"):
            identity = (match.get("identity") or {}).get(side) or {}
            if identity.get("espn_id") and identity.get("sackmann_player_id"):
                source_ids[str(identity["espn_id"])] = str(identity["sackmann_player_id"])

    out: dict[str, dict[str, Any]] = {}
    for match in matches:
        event_id = str(match.get("tournamentId") or "")
        major = major_for_event(tour, match.get("event"))
        surface = SURFACE_BY_EVENT.get(event_id) or SURFACE_BY_MAJOR.get(major or "")
        best_of = 5 if tour == "atp" and major in FIVE_SET_MAJORS else 3
        sides = {}
        for side in ("home", "away"):
            athlete_id = str(match.get(f"{side}AthleteId") or "")
            sides[side] = source_ids.get(athlete_id)
        home_id, away_id = sides["home"], sides["away"]

        projection: dict[str, Any] = {
            "probability": None,
            "projectedWinner": None,
            "homeAces": None,
            "awayAces": None,
            "totalGames": None,
            "totalGamesInterval": None,
            "totalGamesLabel": None,
            "unavailableReason": None,
            "homeDoubleFaults": None,
            "awayDoubleFaults": None,
            "modelVersion": "tennis-global-surface-elo-blend-v2",
            "_sackmannPlayerIds": {"home": home_id, "away": away_id},
        }
        if home_id and away_id:
            p_global = _logistic((global_elo[home_id] - global_elo[away_id]) * math.log(10.0) / 400.0)
            p_surface = (
                _logistic((surface_elo[(home_id, surface)] - surface_elo[(away_id, surface)]) * math.log(10.0) / 400.0)
                if surface else p_global
            )
            p_home = _logistic(0.5 * (_logit(p_global) + _logit(p_surface)))
            projection["probability"] = p_home if p_home >= 0.5 else 1.0 - p_home
            projection["projectedWinner"] = match["home"] if p_home >= 0.5 else match["away"]

            tour_mean = format_aces[best_of] / format_count[best_of] if format_count[best_of] else (
                overall_aces / overall_count if overall_count else None
            )
            if tour_mean is not None:
                for side, pid, field in (("home", home_id, "homeAces"), ("away", away_id, "awayAces")):
                    n = player_count[(pid, best_of)]
                    projection[field] = (player_aces[(pid, best_of)] + P0_SHRINK_MATCHES * tour_mean) / (n + P0_SHRINK_MATCHES)

            tour_df_mean = format_double_faults[best_of] / format_df_count[best_of] if format_df_count[best_of] else (
                overall_double_faults / overall_df_count if overall_df_count else None
            )
            if tour_df_mean is not None:
                for side, pid, field in (
                    ("home", home_id, "homeDoubleFaults"),
                    ("away", away_id, "awayDoubleFaults"),
                ):
                    key = (pid, best_of)
                    n = player_df_count[key]
                    projection[field] = (
                        player_double_faults[key] + P0_SHRINK_MATCHES * tour_df_mean
                    ) / (n + P0_SHRINK_MATCHES)

            if surface and state.baseline(surface) > 0:
                serve_home = point_model.point_prob(
                    state.serve(home_id, surface, 250.0), state.returns(away_id, surface, 250.0), state.baseline(surface)
                )
                serve_away = point_model.point_prob(
                    state.serve(away_id, surface, 250.0), state.returns(home_id, surface, 250.0), state.baseline(surface)
                )
                simulated = sim.match_distribution(
                    serve_home, serve_away,
                    {"bestOf": best_of, "finalSet": "tiebreak", "finalSetTiebreakAt": 6},
                )
                if not simulated["unresolved"]:
                    projection["totalGames"] = simulated["expected_games"]
                    projection["totalGamesInterval"] = _games_interval(simulated["total_games"])
            elif not surface:
                projection["totalGamesLabel"] = "Event surface is not mapped yet."
        else:
            projection["unavailableReason"] = "One or both player IDs are not mapped through the tennis spine."

        out[str(match["gameId"])] = projection
    return out
