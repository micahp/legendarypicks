"""Fail-closed inputs shared by the NBA forecast, lock, and grade jobs."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

import espn_client
from nba_game_model import MODEL_INFO, build_state, forecast_game
from nba_model_data import TeamGame
from nba_model_store import (DEFAULT_DB, MODEL_VERSION, canonical_json, iso_utc,
                             latest_live_games, open_db, parse_time, record_missed_windows,
                             record_schedule_missed_windows, store_live_observation,
                             upsert_previews)
from team_codes import normalize
from team_stats_contract import extract_espn_team_stats

UTC = dt.timezone.utc
CURRENT_NBA_SEASON = 2027
NBA_MODEL_DB = os.environ.get("NBA_MODEL_DB_PATH", DEFAULT_DB)


def require_dev_picks_db(path: str | None = None) -> str:
    """Open the shared picks DB only when LP_DB_PATH explicitly names the dev file."""
    value = path or os.environ.get("LP_DB_PATH")
    if not value:
        raise RuntimeError("LP_DB_PATH must explicitly point to picks.dev.db")
    resolved = Path(value).expanduser().resolve(strict=True)
    if resolved.name != "picks.dev.db":
        raise RuntimeError(f"NBA model jobs are dev-only; refusing LP_DB_PATH={resolved}")
    return str(resolved)


def open_dev_source(path: str | None = None) -> sqlite3.Connection:
    resolved = require_dev_picks_db(path)
    return sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)


def _as_score(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        score = float(value)
        return int(score) if score.is_integer() else None
    except (TypeError, ValueError):
        return None


def _pair_attempts(value: Any, label: str) -> int:
    if not isinstance(value, str):
        raise ValueError(f"ESPN summary misses {label} made-attempted value")
    match = re.fullmatch(r"\s*\d+\s*[-/]\s*(\d+)\s*", value)
    if not match:
        raise ValueError(f"invalid ESPN {label} made-attempted value: {value!r}")
    return int(match.group(1))


def _number(stats: dict[str, Any], key: str, side: str) -> float:
    value = stats.get(key)
    if value is None:
        raise ValueError(f"ESPN {side} summary misses {key}")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"ESPN {side} summary has invalid {key}: {value!r}") from exc
    if parsed < 0:
        raise ValueError(f"ESPN {side} summary has negative {key}")
    return parsed


def _team_side(value: str, side: str) -> str:
    try:
        return normalize("nba", str(value or ""))
    except Exception as exc:  # noqa: BLE001 - fail with source context
        raise ValueError(f"ESPN {side} team identity is not recognized: {value!r}") from exc


def _validated_summary(event: dict[str, Any], summary: dict[str, Any], schedule: sqlite3.Row,
                       observed_at: dt.datetime) -> dict[str, Any]:
    game_id = str(schedule["game_id"])
    event_id = str(event.get("game_id") or "")
    if not event_id or (schedule["espn"] and str(schedule["espn"]) != event_id):
        raise ValueError(f"{game_id}: ESPN event ID does not match the NBA schedule crosswalk")
    expected_home, expected_away = _team_side(schedule["home_team"], "scheduled home"), \
        _team_side(schedule["away_team"], "scheduled away")
    for side in ("home", "away"):
        team = event.get(side) or {}
        if _team_side(team.get("abbrev"), f"scoreboard {side}") != (expected_home if side == "home" else expected_away):
            raise ValueError(f"{game_id}: scoreboard {side} team differs from NBA schedule")
    if event.get("completed") is not True:
        raise ValueError(f"{game_id}: ESPN scoreboard does not mark the game completed")
    home_score, away_score = _as_score((event.get("home") or {}).get("score")), \
        _as_score((event.get("away") or {}).get("score"))
    if home_score is None or away_score is None:
        raise ValueError(f"{game_id}: ESPN scoreboard has no final scores")
    if schedule["status"] == 3:
        scheduled_home, scheduled_away = _as_score(schedule["home_score"]), _as_score(schedule["away_score"])
        if (scheduled_home, scheduled_away) != (home_score, away_score):
            raise ValueError(f"{game_id}: ESPN final conflicts with the NBA schedule final")

    competition = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    status_type = ((competition.get("status") or {}).get("type") or {})
    if status_type.get("completed") is not True:
        raise ValueError(f"{game_id}: ESPN summary is not marked completed")
    summary_sides = {}
    for competitor in competition.get("competitors") or []:
        side = competitor.get("homeAway")
        team = competitor.get("team") or {}
        if side not in ("home", "away") or side in summary_sides:
            raise ValueError(f"{game_id}: ESPN summary has ambiguous competitor sides")
        summary_sides[side] = (_team_side(team.get("abbreviation"), f"summary {side}"),
                               _as_score(competitor.get("score")))
    if summary_sides.get("home") != (expected_home, home_score) or \
            summary_sides.get("away") != (expected_away, away_score):
        raise ValueError(f"{game_id}: ESPN summary teams/scores differ from scoreboard and schedule")

    rows = extract_espn_team_stats("nba", summary)
    raw_team_stats = {}
    for item in ((summary.get("boxscore") or {}).get("teams") or []):
        side = item.get("homeAway") or item.get("_homeAway")
        stat_values = {stat.get("name"): stat.get("displayValue")
                       for stat in item.get("statistics") or []}
        raw_team_stats[side] = stat_values
    by_side = {}
    for row in rows:
        side = row.get("home_away")
        if side not in ("home", "away") or side in by_side:
            raise ValueError(f"{game_id}: ESPN summary boxscore team sides are ambiguous")
        expected = expected_home if side == "home" else expected_away
        if _team_side(row.get("team_abbrev"), f"boxscore {side}") != expected:
            raise ValueError(f"{game_id}: ESPN boxscore {side} team differs from schedule")
        values = row["stats"]
        turnover_stats = raw_team_stats.get(side, {})
        turnovers = (turnover_stats["totalTurnovers"]
                     if "totalTurnovers" in turnover_stats
                     else turnover_stats.get("turnovers", values.get("turnovers")))
        by_side[side] = {
            "field_goals_attempted": _pair_attempts(values.get("fgm_fga"), "field goals"),
            "free_throws_attempted": _pair_attempts(values.get("ftm_fta"), "free throws"),
            "offensive_rebounds": _number(values, "off_rebounds", side),
            "turnovers": _number({"turnovers": turnovers}, "turnovers", side),
        }
    if set(by_side) != {"home", "away"}:
        raise ValueError(f"{game_id}: ESPN summary does not contain paired team boxscores")
    source_payload = {"scoreboard": event, "summary": summary,
                      "schedule": {key: schedule[key] for key in
                                   ("game_id", "season", "game_date", "start_utc", "home_team", "away_team", "espn")}}
    source_hash = hashlib.sha256(canonical_json(source_payload).encode()).hexdigest()
    return {
        "nba_game_id": game_id, "season": int(schedule["season"]),
        "game_date": schedule["game_date"], "scheduled_start_utc": schedule["start_utc"],
        "source_event_id": event_id, "home_team": expected_home, "away_team": expected_away,
        "home_score": home_score, "away_score": away_score,
        "home_stats": by_side["home"], "away_stats": by_side["away"],
        "source_hash": source_hash, "source": "ESPN scoreboard+summary",
        "final_confirmed": True, "observed_at_utc": iso_utc(observed_at),
    }


def _scoreboard_window(games_by_day, start: dt.date, end: dt.date):
    """Split ESPN range responses before its approximately 100-event response cap."""
    grouped, count = games_by_day("nba", start.isoformat(), end.isoformat())
    if count < 100:
        return grouped, count
    span = (end - start).days
    if span < 1:
        raise RuntimeError(f"ESPN NBA scoreboard range reached the event cap on {start}")
    midpoint = start + dt.timedelta(days=span // 2)
    left, left_count = _scoreboard_window(games_by_day, start, midpoint)
    right, right_count = _scoreboard_window(games_by_day, midpoint + dt.timedelta(days=1), end)
    merged = {day: list(rows) for day, rows in left.items()}
    for day, rows in right.items():
        merged.setdefault(day, []).extend(rows)
    return merged, left_count + right_count


def refresh_completed_games(lp_db_path: str | None = None, model_db_path: str = NBA_MODEL_DB,
                            now: dt.datetime | None = None, *,
                            games_by_day=espn_client.games_by_day,
                            summary_fetch=espn_client.summary) -> dict[str, Any]:
    """Append completed games after matching the dev NBA schedule and ESPN summary."""
    now = now or dt.datetime.now(UTC)
    source = open_dev_source(lp_db_path)
    try:
        source.row_factory = sqlite3.Row
        today = espn_client._ny_date(now)
        start = (today - dt.timedelta(days=5)).isoformat()
        end = today.isoformat()
        schedules = source.execute(
            "SELECT * FROM nba_schedule WHERE season=? AND season_type IN ('REG','CUP') "
            "AND game_date BETWEEN ? AND ? ORDER BY game_date,game_id",
            (CURRENT_NBA_SEASON, start, end),
        ).fetchall()
        schedule_by_id = {str(row["espn"]): row for row in schedules if row["espn"]}
        schedule_by_teams = {}
        for row in schedules:
            key = (row["game_date"], _team_side(row["home_team"], "scheduled home"),
                   _team_side(row["away_team"], "scheduled away"))
            schedule_by_teams.setdefault(key, []).append(row)
        with espn_client.batch_pacing():
            by_day, raw_events = _scoreboard_window(
                games_by_day, today - dt.timedelta(days=6), today + dt.timedelta(days=1)
            )
    finally:
        source.close()

    events = {str(event.get("game_id")): event
              for day_events in by_day.values() for event in day_events if event.get("game_id")}
    model = open_db(model_db_path)
    report = {"season": CURRENT_NBA_SEASON, "scoreboard_events": len(events),
              "scheduled_candidates": 0, "stored": 0, "already_present": 0,
              "rejected": []}
    try:
        with espn_client.batch_pacing():
            for event_id, event in events.items():
                if event.get("completed") is not True:
                    continue
                schedule = schedule_by_id.get(event_id)
                if schedule is None:
                    try:
                        event_day = parse_time(event["date"]).date()
                        home = _team_side((event.get("home") or {}).get("abbrev"), "scoreboard home")
                        away = _team_side((event.get("away") or {}).get("abbrev"), "scoreboard away")
                        candidates = [row for (day, h, a), rows in schedule_by_teams.items()
                                      if h == home and a == away
                                      and abs((dt.date.fromisoformat(day) - event_day).days) <= 1
                                      for row in rows]
                        if len(candidates) == 1 and not candidates[0]["espn"]:
                            schedule = candidates[0]
                        elif len(candidates) > 1:
                            raise ValueError(f"ambiguous NBA schedule identity for ESPN event {event_id}")
                    except (KeyError, TypeError, ValueError) as exc:
                        report["rejected"].append({"event_id": event_id, "reason": str(exc)})
                        continue
                if schedule is None:
                    continue
                report["scheduled_candidates"] += 1
                try:
                    raw = summary_fetch("nba", event_id)
                    observation = _validated_summary(event, raw, schedule, now)
                    inserted = store_live_observation(model, observation)
                    report["stored" if inserted else "already_present"] += 1
                except (KeyError, TypeError, ValueError) as exc:
                    report["rejected"].append({"event_id": event_id, "game_id": schedule["game_id"],
                                               "reason": str(exc)})
        report["raw_scoreboard_events"] = raw_events
    finally:
        model.close()
    return report


def _team_game(row: dict[str, Any]) -> TeamGame:
    fields = {key: row[key] for key in TeamGame.__dataclass_fields__}
    return TeamGame(**fields)


def build_preview_rows(lp_db_path: str | None = None, model_db_path: str = NBA_MODEL_DB,
                       now: dt.datetime | None = None, horizon_days: int = 3) -> list[dict[str, Any]]:
    now = now or dt.datetime.now(UTC)
    source = open_dev_source(lp_db_path)
    source.row_factory = sqlite3.Row
    try:
        schedule = source.execute(
            "SELECT game_id,season,game_date,start_utc,away_team,home_team FROM nba_schedule "
            "WHERE season=? AND season_type IN ('REG','CUP') AND start_utc>? AND start_utc<=? "
            "ORDER BY start_utc,game_id",
            (CURRENT_NBA_SEASON, iso_utc(now), iso_utc(now + dt.timedelta(days=horizon_days))),
        ).fetchall()
    finally:
        source.close()
    model = open_db(model_db_path, readonly=True)
    try:
        meta = {row["key"]: json.loads(row["value"])
                for row in model.execute("SELECT key,value FROM nba_model_meta")}
        historical = [_team_game(dict(row)) for row in model.execute(
            "SELECT source_game_id AS game_id,season,game_date,home_team,away_team,home_score,away_score,"
            "home_fga,home_fta,home_orb,home_tov,away_fga,away_fta,away_orb,away_tov,schedule_game_id "
            "FROM nba_model_history ORDER BY game_date,source_game_id")]
        live_rows = latest_live_games(model, before_utc=now)
        live = [_team_game(row) for row in live_rows]
        source_hash = meta.get("history_source_hash")
        if not historical or not source_hash:
            raise RuntimeError("NBA model history has not been imported")
    finally:
        model.close()

    combined = {game.schedule_game_id: game for game in historical}
    combined.update({game.schedule_game_id: game for game in live})
    all_games = list(combined.values())
    live_hashes = {row["schedule_game_id"]: (row["source_hash"], row["game_date"])
                   for row in live_rows}

    rows = []
    states: dict[str, dict[str, Any]] = {}
    for game in schedule:
        game_date = game["game_date"]
        if game_date not in states:
            pregame = [row for row in all_games if row.game_date < game_date
                       and row.season <= CURRENT_NBA_SEASON]
            states[game_date] = build_state(pregame, through_season=CURRENT_NBA_SEASON)
        home, away = _team_side(game["home_team"], "scheduled home"), \
            _team_side(game["away_team"], "scheduled away")
        forecasts = forecast_game(states[game_date], str(game["game_id"]), home, away,
                                  int(game["season"]))
        prior_live_hashes = sorted(
            digest for digest, live_date in live_hashes.values() if live_date < game_date
        )
        snapshot = {
            "cutoff_utc": iso_utc(now), "available_at_utc": iso_utc(now),
            "history_date_exclusive": game_date,
            "scheduled_game": {
                "nba_game_id": str(game["game_id"]), "season": int(game["season"]),
                "game_date": game_date, "scheduled_start_utc": game["start_utc"],
                "home_team": home, "away_team": away,
            },
            "history_games": states[game_date]["history_games"],
            "fitted_through": states[game_date]["fitted_through"],
            "history_source_hash": source_hash,
            "live_source_hashes": prior_live_hashes,
            "schedule_source": "dev nba_schedule official NBA game_id",
        }
        feature_hash = hashlib.sha256(canonical_json(snapshot).encode()).hexdigest()
        for model_info in MODEL_INFO:
            model_id = model_info["id"]
            rows.append({
                "game_id": str(game["game_id"]), "model": model_id,
                "season": int(game["season"]), "scheduled_start_utc": game["start_utc"],
                "home_team": home, "away_team": away,
                "model_version": MODEL_VERSION[model_id], "forecast": forecasts[model_id],
                "feature_snapshot": snapshot, "source_hash": feature_hash,
            })
    return rows


def refresh_previews(lp_db_path: str | None = None, model_db_path: str = NBA_MODEL_DB,
                     now: dt.datetime | None = None) -> dict[str, int]:
    now = now or dt.datetime.now(UTC)
    rows = build_preview_rows(lp_db_path, model_db_path, now)
    model = open_db(model_db_path)
    try:
        written = upsert_previews(model, rows, now)
        games = len({row["game_id"] for row in rows})
    finally:
        model.close()
    return {"preview_games": games, "preview_rows": written}


def lock_due_forecasts(model_db_path: str = NBA_MODEL_DB,
                       now: dt.datetime | None = None, *,
                       lp_db_path: str | None = None) -> dict[str, Any]:
    now = now or dt.datetime.now(UTC)
    model = open_db(model_db_path)
    try:
        rows = model.execute(
            "SELECT * FROM nba_model_previews WHERE scheduled_start_utc>? "
            "AND scheduled_start_utc<=? ORDER BY scheduled_start_utc,game_id,model",
            (iso_utc(now), iso_utc(now + dt.timedelta(minutes=92))),
        ).fetchall()
        items = [{
            "game_id": row["game_id"], "model": row["model"], "season": row["season"],
            "scheduled_start_utc": row["scheduled_start_utc"],
            "home_team": row["home_team"], "away_team": row["away_team"],
            "model_version": row["model_version"], "forecast": json.loads(row["forecast_json"]),
            "feature_snapshot": json.loads(row["feature_snapshot_json"]),
            "source_hash": row["source_hash"], "previewed_at_utc": row["previewed_at_utc"],
        } for row in rows]
        report = upsert_lock_calls(model, items, now)
        picks_path = lp_db_path or os.environ.get("LP_DB_PATH")
        if not picks_path:
            missed = record_missed_windows(model, now)
        else:
            picks_path = require_dev_picks_db(picks_path)
            picks_uri = f"{Path(picks_path).as_uri()}?mode=ro"
            try:
                model.execute("ATTACH DATABASE ? AS nba_picks", (picks_uri,))
            except sqlite3.Error:
                missed = record_missed_windows(model, now)
            else:
                try:
                    missed = record_schedule_missed_windows(model, now)
                finally:
                    model.execute("DETACH DATABASE nba_picks")
        report["missed_events_recorded"] = missed
        report["missed_window_games"] += missed
        return report
    finally:
        model.close()


def upsert_lock_calls(model: sqlite3.Connection, rows: list[dict[str, Any]],
                      now: dt.datetime) -> dict[str, int]:
    from nba_model_store import lock_forecasts
    return lock_forecasts(model, rows, now)


def grade_due_forecasts(lp_db_path: str | None = None, model_db_path: str = NBA_MODEL_DB,
                        now: dt.datetime | None = None) -> dict[str, int]:
    from nba_model_store import grade_forecasts, latest_verified_results
    require_dev_picks_db(lp_db_path)
    model = open_db(model_db_path)
    try:
        return grade_forecasts(model, latest_verified_results(model), now)
    finally:
        model.close()
