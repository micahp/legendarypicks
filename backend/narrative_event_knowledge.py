"""Research-only, deterministic narrative facts with explicit evidence and as-of rules.

This module does not write to the application database and does not retain publisher
play descriptions or article text. Callers pass allowlisted structured play data.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math
import re
from statistics import mean, pstdev
from typing import Any, Iterable

import team_codes


SCHEMA_VERSION = 1
_STAT_KEYS = {
    "nba": ("PTS", "REB", "AST", "PRA"),
    "nfl": ("targets", "carries"),
}
_SCORE_THRESHOLD = {"nba": 10, "nfl": 7}


class NarrativeDataError(ValueError):
    """Raised when event order, identity, time, or score evidence is not trustworthy."""


def _canonical_team(league: str, value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    try:
        return team_codes.normalize(league, str(value))
    except team_codes.UnknownTeamCode:
        return None


def parse_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise NarrativeDataError("timestamps must include a timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _nonempty(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise NarrativeDataError(f"missing {label}")
    return result


def normalize_espn_plays(
    raw_plays: Iterable[dict[str, Any]],
    *,
    league: str,
    game_id: str,
    captured_at: str,
) -> list[dict[str, Any]]:
    """Reduce ESPN Core play objects to structured fields; never copy the `text` field.

    `captured_at` is the first time this research run observed the payload. It is
    deliberately conservative: these records cannot be used in historical as-of
    replay before that timestamp.
    """
    league = league.lower()
    if league not in {"nba", "nfl"}:
        raise NarrativeDataError(f"unsupported league: {league}")
    captured = parse_utc(captured_at)
    if captured is None:
        raise NarrativeDataError("captured_at must be a timezone-aware timestamp")

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ordinal, raw in enumerate(raw_plays):
        event_id = _nonempty(raw.get("id"), "play id")
        if event_id in seen:
            raise NarrativeDataError(f"duplicate play id {event_id}")
        seen.add(event_id)
        period_obj = raw.get("period") or {}
        period = period_obj.get("number") if isinstance(period_obj, dict) else period_obj
        try:
            period = int(period)
            home_score = int(raw["homeScore"])
            away_score = int(raw["awayScore"])
        except (KeyError, TypeError, ValueError):
            raise NarrativeDataError(f"play {event_id} lacks period or score snapshots")
        if period < 1 or min(home_score, away_score) < 0:
            raise NarrativeDataError(f"play {event_id} has invalid period or score")

        clock_obj = raw.get("clock")
        clock = clock_obj.get("displayValue") if isinstance(clock_obj, dict) else clock_obj
        clock_seconds = _clock_seconds(clock)
        wallclock = raw.get("wallclock")
        occurred = parse_utc(wallclock)
        if clock_seconds is None or occurred is None:
            # A record without both clocks cannot support event-time retrieval.
            continue

        team = raw.get("team") or {}
        if isinstance(team, dict):
            team_code = team.get("abbreviation") or team.get("displayName")
        else:
            team_code = team
        type_obj = raw.get("type") or {}
        type_label = type_obj.get("text") if isinstance(type_obj, dict) else type_obj
        drive_obj = raw.get("drive") or {}
        drive_id = (drive_obj.get("id") or drive_obj.get("number")
                    if isinstance(drive_obj, dict) else drive_obj)
        participants = []
        for participant in raw.get("participants") or []:
            athlete = participant.get("athlete") or {}
            athlete_id = athlete.get("id") if isinstance(athlete, dict) else None
            if athlete_id:
                participants.append(str(athlete_id))
        try:
            score_value = int(raw.get("scoreValue") or 0)
        except (TypeError, ValueError):
            raise NarrativeDataError(f"play {event_id} has invalid scoreValue")

        out.append({
            "game_id": str(game_id),
            "event_id": event_id,
            "ordinal": ordinal,
            "period": period,
            "clock_seconds_remaining": clock_seconds,
            "occurred_at": iso_utc(occurred),
            "available_at": iso_utc(captured),
            "home_score": home_score,
            "away_score": away_score,
            "team": str(team_code or "").strip().upper() or None,
            "scoring_play": bool(raw.get("scoringPlay")),
            "score_value": score_value,
            "play_type": str(type_label or "").strip() or None,
            "drive_id": str(drive_id) if drive_id is not None else None,
            "down": _optional_int(raw.get("start"), "down"),
            "turnover": bool(raw.get("isTurnover")),
            "participant_ids": sorted(set(participants)),
        })

    # Remaining clock is authoritative within a period. The publisher's
    # sequenceNumber is not a monotonic play order on both sports endpoints.
    out.sort(key=lambda p: (p["period"], -p["clock_seconds_remaining"],
                            p["occurred_at"], p["ordinal"], p["event_id"]))
    for seq, play in enumerate(out):
        play["sequence"] = seq
    return out


def _optional_int(value: Any, key: str) -> int | None:
    if isinstance(value, dict):
        value = value.get(key) if value.get(key) is not None else value.get("value")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _clock_seconds(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    match = re.fullmatch(r"(?:(\d+):)?(\d{1,2})(?:\.(\d+))?", text)
    if not match:
        return None
    minutes = int(match.group(1) or 0)
    seconds = int(match.group(2))
    if seconds > 59:
        return None
    return minutes * 60 + seconds


def _fact(
    *, league: str, game_id: str, event_id: str, category: str,
    occurred_at: str, available_at: str, evidence_ids: list[str],
    calculation: dict[str, Any], team: str | None = None,
    supporting_games: Iterable[str] | None = None,
    source: str = "espn_core_pbp",
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "league": league,
        "game_id": str(game_id),
        "event_id": str(event_id),
        "category": category,
        "source": source,
        "team": team,
        "occurred_at": occurred_at,
        "available_at": available_at,
        "supporting_game_ids": sorted(set(map(str, supporting_games or [game_id]))),
        "supporting_event_ids": sorted(set(map(str, evidence_ids))),
        "calculation": calculation,
        "verified": True,
    }


def derive_game_events(
    *, league: str, game_id: str, home_team: str, away_team: str,
    final_home_score: int, final_away_score: int,
    plays: Iterable[dict[str, Any]],
    source: str = "espn_core_pbp",
    source_game_date: str | None = None,
) -> list[dict[str, Any]]:
    """Derive score-trajectory, run, late-play and drive candidate facts.

    Refuses a game when IDs repeat, event times are invalid, score snapshots regress,
    the timeline is out of sequence, or its terminal score disagrees with the schedule.
    """
    league = league.lower()
    if league not in {"nba", "nfl"}:
        raise NarrativeDataError(f"unsupported league: {league}")
    home_team, away_team = home_team.upper(), away_team.upper()
    game_id = str(game_id)
    ordered = sorted(plays, key=lambda p: int(p.get("sequence", p.get("ordinal", 0))))
    if not ordered:
        raise NarrativeDataError(f"game {game_id} has no timestamped plays")
    seen: set[str] = set()
    prior_h = prior_a = 0
    prior_leader: str | None = None
    lead_changes: list[dict[str, Any]] = []
    scoring_events: list[dict[str, Any]] = []
    late_events: list[dict[str, Any]] = []
    turnover_events: list[dict[str, Any]] = []
    drives: dict[str, list[dict[str, Any]]] = {}
    previous_time: datetime | None = None

    for play in ordered:
        eid = _nonempty(play.get("event_id"), "event id")
        if eid in seen:
            raise NarrativeDataError(f"duplicate play id {eid}")
        seen.add(eid)
        occurred = parse_utc(play.get("occurred_at"))
        available = parse_utc(play.get("available_at"))
        if occurred is None or available is None:
            raise NarrativeDataError(f"play {eid} has an invalid evidence timestamp")
        if previous_time and occurred < previous_time:
            raise NarrativeDataError(f"play {eid} is out of chronological order")
        previous_time = occurred
        try:
            home_score, away_score = int(play["home_score"]), int(play["away_score"])
            period = int(play.get("period") or 1)
            clock = int(play.get("clock_seconds_remaining") or 0)
        except (KeyError, TypeError, ValueError):
            raise NarrativeDataError(f"play {eid} lacks score or clock evidence")
        if home_score < prior_h or away_score < prior_a:
            raise NarrativeDataError(f"score regressed at play {eid}")
        delta_h, delta_a = home_score - prior_h, away_score - prior_a
        if delta_h and delta_a:
            raise NarrativeDataError(f"play {eid} changes both teams' score")
        leader = home_team if home_score > away_score else (
            away_team if away_score > home_score else None)
        if leader and prior_leader and leader != prior_leader:
            lead_changes.append(play)
        if leader:
            prior_leader = leader
        if delta_h or delta_a or play.get("scoring_play"):
            scoring_team = home_team if delta_h else away_team if delta_a else play.get("team")
            points = delta_h or delta_a or int(play.get("score_value") or 0)
            scoring_events.append({**play, "scoring_team": scoring_team, "points": points})
        if play.get("turnover"):
            turnover_events.append(play)
        if period >= 4 and (period > 4 or clock <= 300) and (
                delta_h or delta_a or play.get("turnover") or play.get("down") == 4):
            late_events.append(play)
        if play.get("drive_id"):
            drives.setdefault(str(play["drive_id"]), []).append(play)
        prior_h, prior_a = home_score, away_score

    if (prior_h, prior_a) != (int(final_home_score), int(final_away_score)):
        raise NarrativeDataError(
            f"game {game_id} PBP ends home-away {prior_h}-{prior_a}, schedule says "
            f"{int(final_home_score)}-{int(final_away_score)}")
    if not scoring_events:
        raise NarrativeDataError(f"game {game_id} has no structured scoring events")

    winner = home_team if final_home_score > final_away_score else (
        away_team if final_away_score > final_home_score else None)
    facts: list[dict[str, Any]] = []
    max_deficit = 0
    deficit_play = None
    for play in ordered:
        if winner == home_team:
            deficit = int(play["away_score"]) - int(play["home_score"])
        elif winner == away_team:
            deficit = int(play["home_score"]) - int(play["away_score"])
        else:
            deficit = 0
        if deficit > max_deficit:
            max_deficit, deficit_play = deficit, play
    if max_deficit > 0 and deficit_play:
        facts.append(_fact(
            league=league, game_id=game_id,
            event_id=f"{game_id}:comeback:{winner}", category="comeback",
            team=winner, occurred_at=ordered[-1]["occurred_at"],
            available_at=max(p["available_at"] for p in ordered),
            evidence_ids=[p["event_id"] for p in ordered],
            calculation={"largest_deficit_overcome": max_deficit,
                         "final_margin": abs(int(final_home_score)-int(final_away_score)),
                         "final_home_score": int(final_home_score),
                         "final_away_score": int(final_away_score)}, source=source))

    if lead_changes:
        facts.append(_fact(
            league=league, game_id=game_id,
            event_id=f"{game_id}:lead-changes", category="lead_changes",
            team=None, occurred_at=ordered[-1]["occurred_at"],
            available_at=max(p["available_at"] for p in ordered),
            evidence_ids=[p["event_id"] for p in lead_changes],
            calculation={"count": len(lead_changes), "method": "non_tied_leader_switches"}, source=source))

    if turnover_events:
        facts.append(_fact(
            league=league, game_id=game_id,
            event_id=f"{game_id}:turnovers", category="turnover_events",
            team=None, occurred_at=ordered[-1]["occurred_at"],
            available_at=max(p["available_at"] for p in ordered),
            evidence_ids=[p["event_id"] for p in turnover_events],
            calculation={"count": len(turnover_events),
                         "teams_with_events": sorted({str(p.get("team")) for p in turnover_events
                                                       if p.get("team")})}, source=source))

    run_team: str | None = None
    run_points = 0
    run_ids: list[str] = []
    runs: list[tuple[int, str, list[str]]] = []
    for score_event in scoring_events:
        team = score_event.get("scoring_team")
        points = int(score_event.get("points") or 0)
        if not team or points <= 0:
            continue
        if team != run_team:
            if run_team and run_points:
                runs.append((run_points, run_team, run_ids))
            run_team, run_points, run_ids = team, 0, []
        run_points += points
        run_ids.append(score_event["event_id"])
    if run_team and run_points:
        runs.append((run_points, run_team, run_ids))
    if runs:
        points, team, ids = max(runs, key=lambda row: (row[0], row[1], row[2]))
        facts.append(_fact(
            league=league, game_id=game_id,
            event_id=f"{game_id}:scoring-run:{team}", category="scoring_run",
            team=team, occurred_at=next(p["occurred_at"] for p in ordered
                                       if p["event_id"] == ids[-1]),
            available_at=max(p["available_at"] for p in ordered),
            evidence_ids=ids,
            calculation={"points": points, "scoring_plays": len(ids),
                         "highlight_threshold": _SCORE_THRESHOLD[league],
                         "meets_highlight_threshold": points >= _SCORE_THRESHOLD[league]}, source=source))

    if winner:
        # A decisive scoring play is the final lead change to the winner, when
        # present; this avoids claiming an extra point or meaningless late score
        # decided the game. If the winner never trailed, keep no decisive label.
        decisive = next((p for p in reversed(lead_changes)
                         if ((int(p["home_score"]) > int(p["away_score"])) == (winner == home_team))), None)
        if decisive:
            drive_events = drives.get(str(decisive.get("drive_id")), []) if decisive.get("drive_id") else []
            evidence = [p["event_id"] for p in (drive_events or [decisive])]
            facts.append(_fact(
                league=league, game_id=game_id,
                event_id=f"{game_id}:final-lead-change:{decisive['event_id']}",
                category="final_lead_change", team=winner,
                occurred_at=decisive["occurred_at"],
                available_at=max(p["available_at"] for p in ordered),
                evidence_ids=evidence,
                calculation={"final_home_score": int(final_home_score),
                             "final_away_score": int(final_away_score),
                             "play_type": decisive.get("play_type"),
                             "drive_id": decisive.get("drive_id"),
                             "method": "last_lead_change_to_final_winner"}, source=source))

    if late_events:
        facts.append(_fact(
            league=league, game_id=game_id,
            event_id=f"{game_id}:late-game-events", category="clutch_events",
            team=None, occurred_at=late_events[-1]["occurred_at"],
            available_at=max(p["available_at"] for p in ordered),
            evidence_ids=[p["event_id"] for p in late_events],
            calculation={"fourth_quarter_final_five_minutes_or_overtime": len(late_events),
                         "event_types": sorted({str(p.get("play_type") or "unknown")
                                                for p in late_events})}, source=source))

    # The latest completed team drive associated with a late score is a candidate,
    # not a verified game-winning drive unless the score-change rule above confirms it.
    for score_event in reversed(scoring_events):
        did = score_event.get("drive_id")
        drive_events = drives.get(str(did), []) if did else []
        if did and drive_events and int(score_event.get("period") or 0) >= 4:
            facts.append(_fact(
                league=league, game_id=game_id,
                event_id=f"{game_id}:late-drive:{did}", category="late_scoring_drive",
                team=score_event.get("scoring_team"),
                occurred_at=score_event["occurred_at"],
                available_at=max(p["available_at"] for p in ordered),
                evidence_ids=[p["event_id"] for p in drive_events],
                calculation={"drive_id": str(did), "plays": len(drive_events),
                             "verified_as_game_winning": bool(winner == score_event.get("scoring_team")
                                                               and score_event is scoring_events[-1])}, source=source))
            break

    participants = sorted({home_team, away_team})
    opponent_by_team = {home_team: away_team, away_team: home_team}
    for fact in facts:
        if source_game_date:
            fact["source_game_date"] = str(source_game_date)[:10]
        if fact.get("team"):
            fact["source_game_opponent"] = opponent_by_team.get(str(fact["team"]).upper())
        else:
            # Game-level events are relevant to either participant, and to neither
            # team's unrelated opponents.
            fact["relevant_teams"] = participants
    return facts


def derive_player_outliers(
    *, league: str, target_game_id: str, target_start: str, target_end: str,
    target_available_at: str,
    logs: Iterable[dict[str, Any]], fact_game_id: str | None = None,
    min_prior_games: int = 5, z_threshold: float = 2.0, lookback_games: int = 10,
) -> list[dict[str, Any]]:
    """Find simple per-player, per-stat outliers using only logs available before play.

    This first prototype is explicitly not role-adjusted. It compares a player
    with their latest prior games of the same game type and requires a canonical
    player ID plus log IDs.
    """
    league = league.lower()
    if league not in _STAT_KEYS:
        raise NarrativeDataError(f"unsupported league: {league}")
    kickoff = parse_utc(target_start)
    game_end = parse_utc(target_end)
    target_available = parse_utc(target_available_at)
    if kickoff is None or game_end is None or target_available is None or game_end < kickoff:
        raise NarrativeDataError("target start, end, and availability must be valid ordered timestamps")
    rows = list(logs)
    fact_game_id = str(fact_game_id or target_game_id)
    targets = [r for r in rows if str(r.get("game_id")) == str(target_game_id)]
    history_by_player_type: dict[tuple[str, str], list[tuple[dict[str, Any], datetime | None, datetime | None]]] = defaultdict(list)
    for row in rows:
        pid = row.get("player_id")
        game_type = row.get("game_type")
        if not pid or not game_type:
            continue
        history_by_player_type[(str(pid), str(game_type))].append((
            row, parse_utc(row.get("game_start") or row.get("game_date")),
            parse_utc(row.get("available_at"))))
    facts: list[dict[str, Any]] = []
    for target in targets:
        pid = target.get("player_id")
        target_log_id = target.get("log_id")
        target_at = parse_utc(target.get("game_start") or target.get("game_date"))
        target_seen = parse_utc(target.get("available_at"))
        if not pid or target_log_id is None or target_at is None or target_seen is None:
            continue
        if target_at < kickoff or target_seen > target_available:
            continue
        if target_seen < game_end:
            continue
        game_type = str(target.get("game_type") or "")
        for stat in _STAT_KEYS[league]:
            try:
                value = float((target.get("stats") or {}).get(stat))
            except (TypeError, ValueError):
                continue
            prior_rows = []
            for row, row_at, row_seen in history_by_player_type.get((str(pid), game_type), []):
                if row is target:
                    continue
                if str(row.get("game_id")) == str(target_game_id):
                    continue
                if row_at is None or row_seen is None or row_at >= kickoff or row_seen > kickoff:
                    continue
                try:
                    prior = float((row.get("stats") or {}).get(stat))
                except (TypeError, ValueError):
                    continue
                if row.get("log_id") is not None:
                    prior_rows.append((row_at, prior, row))
            prior_rows.sort(key=lambda item: item[0], reverse=True)
            prior_rows = prior_rows[:max(0, int(lookback_games))]
            prior_values = [item[1] for item in prior_rows]
            prior_ids = [str(item[2]["log_id"]) for item in prior_rows]
            prior_games = [str(item[2].get("canonical_game_id") or item[2].get("game_id"))
                           for item in prior_rows]
            if len(prior_values) < min_prior_games or len(prior_ids) < min_prior_games:
                continue
            sigma = pstdev(prior_values)
            z_score = ((value - mean(prior_values)) / sigma if sigma
                       else (999.0 if value > mean(prior_values) else 0.0))
            if z_score < z_threshold:
                continue
            facts.append(_fact(
                league=league, game_id=fact_game_id,
                event_id=f"{fact_game_id}:player:{pid}:{target_log_id}:{stat}",
                category="player_outlier", team=target.get("team"),
                occurred_at=iso_utc(game_end), available_at=iso_utc(target_seen),
                evidence_ids=[str(target_log_id), *prior_ids],
                supporting_games=[fact_game_id,
                                  str(target.get("canonical_game_id") or target_game_id), *prior_games],
                calculation={"player_id": str(pid), "stat": stat, "value": value,
                             "prior_games": len(prior_values), "prior_mean": round(mean(prior_values), 3),
                             "prior_population_sd": round(sigma, 3), "z_score": round(z_score, 3),
                             "baseline": f"latest_{len(prior_values)}_same_player_same_game_type_games_unadjusted",
                             "source_game_id": str(target_game_id),
                             "min_prior_games": min_prior_games}, source="player_game_logs"))
    return sorted(facts, key=lambda f: (-f["calculation"]["z_score"], f["event_id"]))


def retrieve_pregame_context(
    facts: Iterable[dict[str, Any]], *, league: str, target_game_id: str,
    target_start: str, as_of: str, teams: Iterable[str],
    player_ids: Iterable[str] = (), limit: int = 5,
) -> list[dict[str, Any]]:
    """Return verified, team/player-relevant facts strictly available before cutoff."""
    kickoff, cutoff = parse_utc(target_start), parse_utc(as_of)
    if kickoff is None or cutoff is None:
        raise NarrativeDataError("target_start and as_of must be timezone-aware")
    if cutoff > kickoff:
        raise NarrativeDataError("as_of must not be after target kickoff")
    team_set = {canonical for t in teams if (canonical := _canonical_team(league, t))}
    player_set = {str(p) for p in player_ids}
    eligible = []
    for fact in facts:
        if fact.get("league") != league or not fact.get("verified"):
            continue
        if str(fact.get("game_id")) == str(target_game_id):
            continue
        occurred, available = parse_utc(fact.get("occurred_at")), parse_utc(fact.get("available_at"))
        if occurred is None or available is None or occurred >= kickoff or available > cutoff:
            continue
        if not fact.get("supporting_game_ids") or not fact.get("supporting_event_ids"):
            continue
        calculation = fact.get("calculation", {})
        fact_team = _canonical_team(league, fact.get("team"))
        relevant_teams = {canonical for team in fact.get("relevant_teams", [])
                          if (canonical := _canonical_team(league, team))}
        event_teams = {canonical for team in calculation.get("teams_with_events") or []
                       if (canonical := _canonical_team(league, team))}
        relevant = (
            fact_team in team_set
            or bool(team_set.intersection(relevant_teams))
            or bool(team_set.intersection(event_teams))
            or str(calculation.get("player_id", "")) in player_set
        )
        if not relevant:
            continue
        eligible.append(fact)
    category_order = {"final_lead_change": 0, "comeback": 1, "player_outlier": 2,
                      "snap_workload": 3, "fourth_down_attempts": 4, "turnover_events": 5,
                      "scoring_summary": 6, "drive_summary": 7, "team_box_summary": 8,
                      "scoring_run": 9, "late_scoring_drive": 10, "clutch_events": 11,
                      "standings_record": 12, "lead_changes": 13}
    eligible.sort(key=lambda f: (
        category_order.get(f.get("category"), 99),
        -int((parse_utc(f["occurred_at"]) - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds()),
        str(f.get("game_id")), str(f.get("event_id"))))
    return eligible[:max(0, int(limit))]
