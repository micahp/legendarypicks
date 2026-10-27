"""Independent structural-rule audit for NHL full-game simulation records.

This module intentionally imports no simulator or game-state code.  It audits
the emitted record against a small, explicit subset of NHL rulebook
requirements; missing evidence is reported as NOT_ASSESSED or QUARANTINED.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from typing import Any


REG_SECONDS = 1_200
OT_SECONDS = 300
SIDES = ("home", "away")
VALIDATOR_VERSION = "nhl-independent-gate1-v0.4"
RULEBOOKS = {
    "2021-22": {
        "source": "https://media.nhl.com/site/asset/public/ext/2021-22/2021-22Rules.pdf",
        "sha256": "17ef416dcb556f510df51efd45451e8d37da80da9e69488f78e3d8771228caa7",
    },
    "2026-27": {
        "source": "https://media.d3.nhle.com/image/private/t_document/prd/i9yumvyaojps5kixzaxz.pdf",
        "sha256": "3c7a8cc932144565a798b57926e11f61d2686d8c9538d2a3f06c51c8380003f0",
    },
}

SUPPORTED_EVENT_TYPES = {
    "period-start", "period-end", "game-end", "faceoff", "goal",
    "shot-on-goal", "missed-shot", "blocked-shot", "failed-shot-attempt",
    "giveaway", "takeaway", "hit", "stoppage", "penalty",
    "penalty-expiration", "penalty-service-start", "penalty-release", "penalty-segment-end",
    "goalie-substitution", "line-change", "shootout-attempt",
    "shootout-decision",
}
KNOWN_UNSUPPORTED_EVENTS = {
    "delayed-penalty": "delayed-penalty state and whistle resolution are not implemented in this Gate 1 slice",
    "shootout-complete": "source-feed terminal marker is not part of the simulation event schema",
}

STRUCTURAL_CHECKS = {
    "event_schema", "event_order_and_clock", "score_and_terminal_state",
    "roster_membership", "on_ice_personnel", "penalty_and_manpower",
    "restart_sequence", "overtime_and_shootout",
}


def _canonical_hash(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _check(code: str, rules: tuple[str, ...] | str,
           findings: list[dict[str, Any]] | None = None, *,
           status: str | None = None, evidence: str | None = None) -> dict[str, Any]:
    rows = findings or []
    if status is None:
        finding_statuses = {row.get("status", "FAIL") for row in rows}
        if "FAIL" in finding_statuses:
            status = "FAIL"
        elif "QUARANTINED" in finding_statuses:
            status = "QUARANTINED"
        elif "NOT_ASSESSED" in finding_statuses:
            status = "NOT_ASSESSED"
        else:
            status = "PASS"
    rule_rows = [rules] if isinstance(rules, str) else list(rules)
    return {"code": code, "status": status, "rules": rule_rows,
            "evidence": evidence, "findings": rows}


def _issue(sequence: int | None, message: str, *, status: str = "FAIL",
           detail: Any = None) -> dict[str, Any]:
    result: dict[str, Any] = {"status": status, "event_sequence": sequence,
                              "message": message}
    if detail is not None:
        result["detail"] = detail
    return result


def _event_time(event: dict[str, Any]) -> tuple[int, int, int]:
    period = int(event["period_number"])
    elapsed = int(event["clock_elapsed_seconds"])
    period_type = str(event["period_type"])
    if period_type == "REG" and 1 <= period <= 3 and 0 <= elapsed <= REG_SECONDS:
        return ((period - 1) * REG_SECONDS + elapsed, REG_SECONDS, elapsed)
    if period_type == "OT" and period == 4 and 0 <= elapsed <= OT_SECONDS:
        return (3 * REG_SECONDS + elapsed, OT_SECONDS, elapsed)
    if period_type == "SO" and period == 5 and elapsed == 0:
        return (3 * REG_SECONDS + OT_SECONDS, 0, 0)
    raise ValueError(f"unsupported or out-of-range period/clock {period_type} P{period} t={elapsed}")


def _player_map(game: dict[str, Any]) -> dict[str, dict[str, Any]]:
    players = game.get("summary", {}).get("player_totals")
    if not isinstance(players, dict):
        raise ValueError("summary.player_totals must be an object")
    return {str(pid): row for pid, row in players.items() if isinstance(row, dict)}


def _next_non_admin(events: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    administrative = {"goalie-substitution", "penalty-release", "penalty-segment-end",
                      "penalty-expiration", "penalty-service-start", "stoppage", "line-change"}
    for event in events[index + 1:]:
        if event.get("event_type") in administrative:
            continue
        return event
    return None


def _next_restart_candidate(events: list[dict[str, Any]], index: int,
                            *, allow_penalties: bool = False) -> dict[str, Any] | None:
    """Skip annotations/admin records that can occur during one whistle sequence."""
    administrative = {"goalie-substitution", "penalty-release", "penalty-segment-end",
                       "penalty-expiration", "penalty-service-start", "stoppage", "line-change"}
    if allow_penalties:
        administrative.add("penalty")
    for event in events[index + 1:]:
        if event.get("event_type") in administrative:
            continue
        return event
    return None


def _period_boundary_restart_follows(events: list[dict[str, Any]], event: dict[str, Any]) -> bool:
    """A whistle at the horn may restart at the next period's center faceoff."""
    index = next((i for i, row in enumerate(events) if row is event), None)
    if index is None:
        return False
    for following in events[index + 1:]:
        if following.get("event_type") in {"penalty", "stoppage", "penalty-release",
                "penalty-segment-end", "penalty-expiration", "penalty-service-start",
                "goalie-substitution", "line-change"}:
            continue
        if (following.get("event_type") == "period-start"
                and following.get("period_type") == "SO"):
            return True
        if following.get("event_type") == "period-start":
            restart = _next_restart_candidate(events, events.index(following))
            return restart is not None and restart.get("event_type") == "faceoff"
        if (following.get("event_type") == "game-end"
                and event.get("period_type") == "REG"
                and int(event.get("period_number", -1)) == 3):
            return True
        return False
    return False


def _absolute_seconds(event: dict[str, Any]) -> int:
    absolute, _, _ = _event_time(event)
    if event.get("period_type") == "SO":
        raise ValueError("shootout events do not advance the game penalty clock")
    return absolute


def _expected_manpower(active: list[dict[str, Any]], period_type: str,
                       pulled: dict[str, bool]) -> tuple[dict[str, int] | None, str | None]:
    """Resolve only common penalty combinations; refuse unsupported tables."""
    base = 3 if period_type == "OT" else 5
    manpower_penalties = [p for p in active if p["kind"] in {"MIN", "MAJ"}]
    if any(p["coincidental"] is None for p in manpower_penalties):
        return None, "active penalty has no explicit coincidental classification"
    coincidental = [p for p in manpower_penalties if p["coincidental"]]
    if coincidental:
        signatures = Counter((p["side"], p["kind"], p["duration"], p["start"]) for p in coincidental)
        for (side, kind, duration, start), count in list(signatures.items()):
            other = "away" if side == "home" else "home"
            if signatures[(other, kind, duration, start)] != count:
                return None, "unpaired or mismatched coincidental penalty table state"
            if kind != "MIN" or duration != 120 or period_type == "OT":
                return None, "coincidental combination requires the pinned NHL reference table"

    units = {side: sum(p["side"] == side and p["kind"] in {"MIN", "MAJ"}
                       and not p["coincidental"] for p in active) for side in SIDES}
    difference = units["home"] - units["away"]
    if abs(difference) > 2:
        return None, "more than two concurrent manpower units requires queued-penalty table state"
    if period_type == "OT":
        counts = {side: base for side in SIDES}
        if difference:
            short = "home" if difference > 0 else "away"
            advantage = min(2, abs(difference))
            other = "away" if short == "home" else "home"
            counts[short] = max(3, counts[short] - advantage)
            counts[other] = min(5, counts[other] + advantage)
    else:
        # Coincidental penalties do not change manpower; each unmatched
        # non-coincidental penalty removes a skater from its assessed team.
        counts = {side: max(3, base - units[side]) for side in SIDES}
    for side in SIDES:
        if pulled.get(side, False):
            counts[side] = min(6, counts[side] + 1)
    return counts, None


def _check_event_schema(game: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    events = game.get("events")
    if not isinstance(events, list) or not events:
        return _check("event_schema", ("Rules 4, 77, 78, 84, 86"),
                      [_issue(None, "events must be a non-empty ordered list")])
    unsupported: list[dict[str, Any]] = []
    for index, event in enumerate(events, 1):
        if not isinstance(event, dict):
            findings.append(_issue(index, "event row is not an object"))
            continue
        event_type = event.get("event_type")
        if event_type in KNOWN_UNSUPPORTED_EVENTS:
            unsupported.append(_issue(event.get("sequence", index),
                KNOWN_UNSUPPORTED_EVENTS[str(event_type)], status="QUARANTINED",
                detail={"event_type": event_type}))
        elif event_type not in SUPPORTED_EVENT_TYPES:
            unsupported.append(_issue(event.get("sequence", index),
                "event type is outside the explicitly supported Gate 1 schema",
                status="QUARANTINED", detail={"event_type": event_type}))
        required = ("sequence", "period_number", "period_type", "clock_elapsed_seconds",
                    "event_type", "team_side", "participants", "details", "on_ice")
        missing = [key for key in required if key not in event]
        if missing:
            findings.append(_issue(event.get("sequence", index),
                "event omits required state fields", detail={"missing": missing}))
    if findings:
        return _check("event_schema", ("Rules 4, 77, 78, 84, 86"), findings)
    if unsupported:
        return _check("event_schema", ("Rules 4, 77, 78, 84, 86"), unsupported,
                      status="QUARANTINED")
    return _check("event_schema", ("Rules 4, 77, 78, 84, 86"))


def _check_order_and_clock(game: dict[str, Any]) -> dict[str, Any]:
    events = game.get("events") if isinstance(game.get("events"), list) else []
    findings: list[dict[str, Any]] = []
    prior_key: tuple[int, int] | None = None
    for index, event in enumerate(events, 1):
        if not isinstance(event, dict):
            continue
        sequence = event.get("sequence", index)
        if sequence != index:
            findings.append(_issue(sequence if isinstance(sequence, int) else index,
                "event sequence must be contiguous and equal to list order"))
        try:
            _, period_length, elapsed = _event_time(event)
            remaining = int(event["clock_remaining_seconds"])
            expected_remaining = 0 if period_length == 0 else period_length - elapsed
            if remaining != expected_remaining:
                findings.append(_issue(sequence, "clock remaining does not match period length and elapsed time",
                    detail={"actual": remaining, "expected": expected_remaining}))
            key = (int(event["period_number"]), elapsed)
            if prior_key is not None and key < prior_key:
                findings.append(_issue(sequence, "period/clock moved backwards in the event stream",
                    detail={"previous": prior_key, "actual": key}))
            prior_key = key
            time_text = str(event.get("time_in_period", ""))
            if time_text:
                expected_text = f"{elapsed // 60:02d}:{elapsed % 60:02d}"
                if time_text != expected_text:
                    findings.append(_issue(sequence, "formatted event clock conflicts with integer clock",
                        detail={"actual": time_text, "expected": expected_text}))
        except (KeyError, TypeError, ValueError) as exc:
            findings.append(_issue(sequence, "event has missing or invalid clock fields", detail=str(exc)))
    return _check("event_order_and_clock", ("Rules 4, 77, 84, 86"), findings)


def _check_score_and_terminal(game: dict[str, Any]) -> dict[str, Any]:
    events = game.get("events") if isinstance(game.get("events"), list) else []
    score = {side: 0 for side in SIDES}
    sog = {side: 0 for side in SIDES}
    findings: list[dict[str, Any]] = []
    game_ends: list[dict[str, Any]] = []
    starts: Counter[tuple[str, int]] = Counter()
    ends: Counter[tuple[str, int]] = Counter()
    terminal_seen = False
    for index, event in enumerate(events, 1):
        if not isinstance(event, dict):
            continue
        seq = event.get("sequence", index)
        if terminal_seen:
            findings.append(_issue(seq, "event follows a terminal game-end event"))
            continue
        event_type = event.get("event_type")
        ptype = event.get("period_type")
        pn = event.get("period_number")
        if event_type == "period-start":
            starts[(str(ptype), int(pn))] += 1
        elif event_type == "period-end":
            ends[(str(ptype), int(pn))] += 1
        before = event.get("state_before")
        expected_before = {"score": dict(score), "sog_event_count": dict(sog)}
        if before != expected_before:
            findings.append(_issue(seq, "state_before disagrees with independently accumulated score/SOG",
                detail={"actual": before, "expected": expected_before}))
        side = event.get("team_side")
        if event_type == "goal" and ptype != "SO":
            if side not in SIDES:
                findings.append(_issue(seq, "ordinary goal has no valid scoring side"))
            else:
                score[side] += 1
                sog[side] += 1
        elif event_type == "shot-on-goal" and ptype != "SO":
            if side not in SIDES:
                findings.append(_issue(seq, "shot-on-goal has no valid shooting side"))
            else:
                sog[side] += 1
        elif event_type == "shootout-decision":
            if side not in SIDES:
                findings.append(_issue(seq, "shootout decision has no winning side"))
            else:
                score[side] += 1
        elif event_type == "game-end":
            game_ends.append(event)
            terminal_seen = True
        after = event.get("state_after")
        expected_after = {"score": dict(score), "sog_event_count": dict(sog)}
        if after != expected_after:
            findings.append(_issue(seq, "state_after disagrees with independently accumulated score/SOG",
                detail={"actual": after, "expected": expected_after}))

    summary = game.get("summary", {})
    if len(game_ends) != 1:
        findings.append(_issue(None, "completed game must have exactly one game-end event",
            detail={"game_end_count": len(game_ends)}))
    for number in (1, 2, 3):
        if starts[("REG", number)] != 1 or ends[("REG", number)] != 1:
            findings.append(_issue(None, "each regulation period needs exactly one start and end",
                detail={"period": number, "starts": starts[("REG", number)],
                        "ends": ends[("REG", number)]}))
    if score != summary.get("official_final_score"):
        findings.append(_issue(None, "event score does not reconcile with official final score",
            detail={"events": score, "summary": summary.get("official_final_score")}))
    if sog != summary.get("sog_event_counts"):
        findings.append(_issue(None, "event SOG count does not reconcile with summary",
            detail={"events": sog, "summary": summary.get("sog_event_counts")}))
    team_totals = summary.get("team_totals") or {}
    for side in SIDES:
        event_goals = sum(e.get("event_type") == "goal" and e.get("period_type") != "SO"
                          and e.get("team_side") == side for e in events if isinstance(e, dict))
        event_attempts = sum(e.get("event_type") in {"goal", "shot-on-goal", "missed-shot", "blocked-shot"}
                             and e.get("team_side") == side and e.get("period_type") != "SO"
                             for e in events if isinstance(e, dict))
        event_sog = sum(e.get("event_type") in {"goal", "shot-on-goal"}
                        and e.get("team_side") == side and e.get("period_type") != "SO"
                        for e in events if isinstance(e, dict))
        row = team_totals.get(side)
        if not isinstance(row, dict):
            findings.append(_issue(None, "team totals are missing", detail={"side": side}))
        else:
            for field, expected in (("goals", event_goals), ("shot_attempts", event_attempts),
                                    ("shots_on_goal", event_sog)):
                if row.get(field) != expected:
                    findings.append(_issue(None, "team total does not reconcile with event ledger",
                        detail={"side": side, "field": field, "actual": row.get(field),
                                "expected": expected}))
    try:
        player_totals = summary.get("player_totals") or {}
        reg_ot = {side: sum(e.get("event_type") == "goal" and e.get("period_type") in {"REG", "OT"}
                            and e.get("team_side") == side for e in events if isinstance(e, dict))
                  for side in SIDES}
        for side in SIDES:
            player_goals = sum(int(p.get("goals", 0)) for p in player_totals.values()
                               if p.get("team_side") == side)
            if player_goals != reg_ot[side]:
                findings.append(_issue(None, "player goal totals do not reconcile to regulation/OT goals",
                    detail={"side": side, "players": player_goals, "events": reg_ot[side]}))
    except (AttributeError, TypeError, ValueError) as exc:
        findings.append(_issue(None, "player goal accounting cannot be read", detail=str(exc)))
    if score["home"] == score["away"]:
        findings.append(_issue(None, "regular-season full game has no official winner"))
    return _check("score_and_terminal_state", ("Rules 77, 78, 84"), findings)


def _check_roster_membership(game: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    try:
        players = _player_map(game)
    except (TypeError, ValueError) as exc:
        return _check("roster_membership", ("Rules 5, 7, 24, 84"),
                      [_issue(None, "cannot establish the recorded pregame player pool", detail=str(exc))])
    for index, event in enumerate(game.get("events", []), 1):
        if not isinstance(event, dict):
            continue
        seq = event.get("sequence", index)
        on_ice = event.get("on_ice")
        if not isinstance(on_ice, dict):
            findings.append(_issue(seq, "on_ice state must be an object"))
            continue
        for side in SIDES:
            ids = on_ice.get(side)
            if not isinstance(ids, list):
                findings.append(_issue(seq, "on_ice team list is missing", detail={"side": side}))
                continue
            if len(ids) != len(set(str(pid) for pid in ids)):
                findings.append(_issue(seq, "on-ice player is duplicated", detail={"side": side}))
            for pid in ids:
                player = players.get(str(pid))
                if player is None:
                    findings.append(_issue(seq, "on-ice player is outside the supplied roster snapshot",
                        detail={"side": side, "player_id": pid}))
                elif player.get("team_side") != side:
                    findings.append(_issue(seq, "on-ice player belongs to the opposing supplied roster",
                        detail={"side": side, "player_id": pid,
                                "recorded_team": player.get("team_side")}))
        for key, value in (event.get("participants") or {}).items():
            if key.endswith("_id") and value is not None and str(value) not in players:
                findings.append(_issue(seq, "participant ID is outside the supplied roster snapshot",
                    detail={"field": key, "player_id": value}))
            elif key.endswith("_ids") and isinstance(value, list):
                for pid in value:
                    if str(pid) not in players:
                        findings.append(_issue(seq, "participant ID is outside the supplied roster snapshot",
                            detail={"field": key, "player_id": pid}))
    if findings:
        return _check("roster_membership", ("Rules 5, 7, 24, 84"), findings)
    return _check("roster_membership", ("Rules 5, 7, 24, 84"), evidence=
                  "IDs reconcile to the supplied pregame roster snapshot; this does not prove the official dressed lineup.")


def _projected_game_roster(game: dict[str, Any]) -> dict[str, dict[str, str]] | None:
    snapshot = game.get("pregame_snapshot")
    projection = snapshot.get("projected_game_roster") if isinstance(snapshot, dict) else None
    players_by_side = projection.get("players_by_side") if isinstance(projection, dict) else None
    if not isinstance(players_by_side, dict):
        return None
    result: dict[str, dict[str, str]] = {}
    for side in SIDES:
        rows = players_by_side.get(side)
        if not isinstance(rows, list):
            return None
        player_map: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, dict) or row.get("player_id") is None or row.get("position") is None:
                return None
            player_id = str(row["player_id"])
            if player_id in player_map:
                return None
            player_map[player_id] = str(row["position"])
        result[side] = player_map
    return result


def _check_simulation_roster_consistency(game: dict[str, Any]) -> dict[str, Any]:
    snapshot = game.get("pregame_snapshot")
    projection = snapshot.get("projected_game_roster") if isinstance(snapshot, dict) else None
    projected = _projected_game_roster(game)
    if not isinstance(projection, dict):
        return _check("simulation_roster_consistency", ("Rules 5, 7, 24, 84"),
            [_issue(None, "pregame projected game roster is absent",
                    status="NOT_ASSESSED")], status="NOT_ASSESSED")
    if projected is None:
        return _check("simulation_roster_consistency", ("Rules 5, 7, 24, 84"),
            [_issue(None, "pregame projected game roster is malformed")])
    findings: list[dict[str, Any]] = []
    if projection.get("status") != "pregame_projection_only":
        findings.append(_issue(None, "roster status must identify a pregame projection"))
    if projection.get("actual_target_game_lineup_used") is not False:
        findings.append(_issue(None, "projected roster must attest that target-game lineup was not used"))
    if snapshot.get("actual_target_game_stats_or_lineups_used") is not False:
        findings.append(_issue(None, "pregame snapshot must attest that target-game lineups and stats were not used"))
    if not isinstance(projection.get("selection_policy"), str) or not projection["selection_policy"]:
        findings.append(_issue(None, "projected roster selection policy is missing"))
    sources = projection.get("source_by_side")
    if not isinstance(sources, dict) or any(not isinstance(sources.get(side), str) or not sources[side]
                                            for side in SIDES):
        findings.append(_issue(None, "projected roster source provenance is missing by team"))
    try:
        players = _player_map(game)
    except (TypeError, ValueError) as exc:
        return _check("simulation_roster_consistency", ("Rules 5, 7, 24, 84"),
                      [_issue(None, "simulated player totals cannot be read", detail=str(exc))])
    all_projected: set[str] = set()
    forward_positions = {"F", "C", "L", "R", "LW", "RW"}
    for side in SIDES:
        side_roster = projected[side]
        overlap = all_projected.intersection(side_roster)
        if overlap:
            findings.append(_issue(None, "projected player ID appears on both teams",
                                   detail={"player_ids": sorted(overlap)}))
        all_projected.update(side_roster)
        groups = {player_id: "F" if position in forward_positions else position
                  for player_id, position in side_roster.items()}
        counts = Counter(groups.values())
        if counts["F"] != 12 or counts["D"] != 6 or counts["G"] not in {1, 2}:
            findings.append(_issue(None, "projected roster must contain 12 forwards, 6 defensemen, and 1 or 2 goalies",
                detail={"side": side, "position_counts": dict(sorted(counts.items()))}))
        if len(side_roster) not in {19, 20} or any(position not in forward_positions | {"D", "G"}
                                                   for position in side_roster.values()):
            findings.append(_issue(None, "projected roster contains an unsupported size or position",
                detail={"side": side, "size": len(side_roster), "position_counts": dict(sorted(counts.items()))}))
        for player_id, position in side_roster.items():
            player = players.get(player_id)
            if player is None:
                findings.append(_issue(None, "projected player is absent from simulated player totals",
                    detail={"side": side, "player_id": player_id}))
            elif player.get("team_side") != side or player.get("position") != position:
                findings.append(_issue(None, "projected player identity disagrees with simulated totals",
                    detail={"side": side, "player_id": player_id,
                            "roster_position": position, "totals": player}))
    if set(players) != all_projected:
        findings.append(_issue(None, "simulated player totals do not equal the projected game roster",
            detail={"projected_only": sorted(all_projected - set(players)),
                    "totals_only": sorted(set(players) - all_projected)}))
    for event in game.get("events", []):
        if not isinstance(event, dict):
            continue
        seq = event.get("sequence")
        for side in SIDES:
            for player_id in event.get("on_ice", {}).get(side, []) if isinstance(event.get("on_ice"), dict) else []:
                if str(player_id) not in projected[side]:
                    findings.append(_issue(seq, "on-ice player is outside the projected game roster",
                        detail={"side": side, "player_id": player_id}))
        participants = event.get("participants") or {}
        for key, value in participants.items():
            if key.endswith("_id") and value is not None and str(value) not in all_projected:
                findings.append(_issue(seq, "event participant is outside the projected game roster",
                    detail={"field": key, "player_id": value}))
            elif key.endswith("_ids") and isinstance(value, list):
                for player_id in value:
                    if str(player_id) not in all_projected:
                        findings.append(_issue(seq, "event participant is outside the projected game roster",
                            detail={"field": key, "player_id": player_id}))
    if findings:
        return _check("simulation_roster_consistency", ("Rules 5, 7, 24, 84"), findings)
    return _check("simulation_roster_consistency", ("Rules 5, 7, 24, 84"), evidence=
                  "Simulated events and totals reconcile to a cutoff-safe projected roster; official dressed-lineup eligibility remains unassessed.")


def _check_personnel(game: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    unassessed: list[dict[str, Any]] = []
    try:
        players = _player_map(game)
    except (TypeError, ValueError) as exc:
        return _check("on_ice_personnel", ("Rules 5, 7, 68, 71, 74, 82, 84"),
                      [_issue(None, "cannot audit personnel without player positions", detail=str(exc))])
    ignored = {"period-start", "period-end", "game-end", "shootout-attempt", "shootout-decision"}
    for index, event in enumerate(game.get("events", []), 1):
        if not isinstance(event, dict) or event.get("event_type") in ignored:
            continue
        seq = event.get("sequence", index)
        on_ice = event.get("on_ice") or {}
        pulled = (event.get("details") or {}).get("goalie_pulled")
        actual_counts: dict[str, int] = {}
        for side in SIDES:
            ids = on_ice.get(side, [])
            if not isinstance(ids, list):
                findings.append(_issue(seq, "on-ice team state is not a list", detail={"side": side}))
                continue
            goalies = sum(players.get(str(pid), {}).get("position") == "G" for pid in ids)
            skaters = len(ids) - goalies
            actual_counts[side] = skaters
            if goalies > 1 or skaters < 3 or skaters > 6:
                findings.append(_issue(seq, "on-ice count exceeds supported player-strength bounds",
                    detail={"side": side, "skaters": skaters, "goalies": goalies}))
            if isinstance(pulled, dict):
                expected_goalies = 0 if pulled.get(side) is True else 1
                if goalies != expected_goalies:
                    findings.append(_issue(seq, "goalkeeper presence conflicts with explicit pulled state",
                        detail={"side": side, "goalies": goalies, "pulled": pulled.get(side)}))
        if event.get("strength") is not None and len(actual_counts) == 2:
            expected_label = f"{actual_counts['home']}v{actual_counts['away']}"
            if event["strength"] != expected_label:
                findings.append(_issue(seq, "strength label conflicts with on-ice player counts",
                    detail={"actual": event["strength"], "expected": expected_label}))
        elif event.get("period_type") in {"REG", "OT"}:
            unassessed.append(_issue(seq, "strength label is absent", status="NOT_ASSESSED"))
        if not isinstance(pulled, dict) and event.get("period_type") in {"REG", "OT"}:
            unassessed.append(_issue(seq, "event omits goalie-pulled state", status="NOT_ASSESSED"))
        if event.get("event_type") in {"goal", "shot-on-goal", "missed-shot", "blocked-shot"}:
            participants = event.get("participants") or {}
            shooter = participants.get("shooter_id")
            if shooter is not None:
                shooter_row = players.get(str(shooter), {})
                if shooter_row.get("team_side") != event.get("team_side"):
                    findings.append(_issue(seq, "shot participant is not on the shooting team"))
            goalie = participants.get("goalie_id")
            defending = "away" if event.get("team_side") == "home" else "home"
            goalie_present = any(players.get(str(pid), {}).get("position") == "G"
                                 for pid in on_ice.get(defending, []))
            if goalie is None:
                if participants.get("empty_net") is not True or goalie_present:
                    findings.append(_issue(seq, "missing goalie is not represented as a valid empty-net shot"))
            elif (players.get(str(goalie), {}).get("position") != "G"
                  or players.get(str(goalie), {}).get("team_side") != defending
                  or str(goalie) not in {str(pid) for pid in on_ice.get(defending, [])}):
                findings.append(_issue(seq, "shot goalie does not match the defending on-ice state"))
    if findings:
        return _check("on_ice_personnel", ("Rules 5, 7, 68, 71, 74, 82, 84"), findings)
    if unassessed:
        return _check("on_ice_personnel", ("Rules 5, 7, 68, 71, 74, 82, 84"), unassessed,
                      status="NOT_ASSESSED")
    return _check("on_ice_personnel", ("Rules 5, 7, 68, 71, 74, 82, 84"))


def _check_restarts(game: dict[str, Any]) -> dict[str, Any]:
    """Audit restart event order independently of whether restart coordinates exist."""
    events = game.get("events", [])
    findings: list[dict[str, Any]] = []
    try:
        players = _player_map(game)
    except (TypeError, ValueError):
        players = {}
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        event_type = event.get("event_type")
        if event_type == "faceoff":
            side = event.get("team_side")
            participants = event.get("participants") or {}
            winner = str(participants.get("faceoff_winner_id") or "")
            loser = str(participants.get("faceoff_loser_id") or "")
            other = "away" if side == "home" else "home"
            if side not in SIDES or not winner or not loser:
                findings.append(_issue(event.get("sequence"),
                    "faceoff must record a winner and loser and identify the winning team"))
            elif (winner not in players or loser not in players
                  or players[winner].get("team_side") != side
                  or players[loser].get("team_side") != other):
                findings.append(_issue(event.get("sequence"),
                    "faceoff winner/loser IDs do not match opposing team ownership"))
            elif (winner not in {str(pid) for pid in (event.get("on_ice") or {}).get(side, [])}
                  or loser not in {str(pid) for pid in (event.get("on_ice") or {}).get(other, [])}):
                findings.append(_issue(event.get("sequence"),
                    "faceoff winner and loser must be among the on-ice personnel"))
        elif event_type == "period-start" and event.get("period_type") in {"REG", "OT"}:
            next_event = _next_non_admin(events, index)
            if next_event is None or next_event.get("event_type") != "faceoff":
                findings.append(_issue(event.get("sequence"),
                    "period start is not followed by a faceoff restart"))
        elif event_type == "goal" and event.get("period_type") != "SO":
            elapsed = int(event.get("clock_elapsed_seconds", -1))
            _, period_limit, _ = _event_time(event)
            next_event = _next_non_admin(events, index)
            if next_event is None:
                if elapsed != period_limit:
                    findings.append(_issue(event.get("sequence"),
                        "non-terminal goal has no subsequent restart"))
                continue
            if next_event.get("event_type") == "game-end" and event.get("period_type") == "OT":
                continue
            if elapsed == period_limit and next_event.get("event_type") in {"period-end", "game-end"}:
                continue
            if next_event.get("event_type") != "faceoff":
                findings.append(_issue(event.get("sequence"),
                    "goal is not followed by a faceoff before live play",
                    detail={"next_event_sequence": next_event.get("sequence"),
                            "next_event_type": next_event.get("event_type")}))
        elif event_type in {"stoppage", "penalty"}:
            next_event = _next_restart_candidate(events, index, allow_penalties=True)
            if next_event is None or next_event.get("event_type") != "faceoff":
                terminal_boundary = (next_event is not None
                    and next_event.get("event_type") == "period-end"
                    and int(next_event.get("clock_elapsed_seconds", -1)) == _event_time(next_event)[1]
                    and _period_boundary_restart_follows(events, next_event))
                if not terminal_boundary:
                    findings.append(_issue(event.get("sequence"),
                        f"{event_type} that resumes play is not followed by a faceoff"))
    return _check("restart_sequence", ("Rules 15, 24, 25, 76, 78, 86"), findings)


def _check_restart_locations(game: dict[str, Any]) -> dict[str, Any]:
    """Check center restarts where location is recorded; never infer missing spots."""
    events = game.get("events", [])
    findings: list[dict[str, Any]] = []
    unassessed: list[dict[str, Any]] = []
    targets: list[tuple[int, str]] = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        event_type = event.get("event_type")
        if event_type == "goal" and event.get("period_type") != "SO":
            elapsed = int(event.get("clock_elapsed_seconds", -1))
            _, period_limit, _ = _event_time(event)
            if elapsed != period_limit:
                targets.append((index, "post-goal"))
        elif event_type == "period-start" and event.get("period_type") in {"REG", "OT"}:
            targets.append((index, "period-start"))
    for index, kind in targets:
        faceoff = _next_non_admin(events, index)
        if faceoff is None or faceoff.get("event_type") != "faceoff":
            continue  # Missing faceoffs are reported by _check_restarts.
        details = faceoff.get("details") or {}
        location = details.get("faceoff_location") or details.get("location")
        coords = (details.get("xCoord"), details.get("yCoord"))
        zone = details.get("zoneCode")
        center = (location in {"center", "CENTER", "center-ice"}
                  or coords == (0, 0) or (zone == "N" and coords == (0, 0)))
        if center:
            continue
        if location is None and coords == (None, None) and zone is None:
            unassessed.append(_issue(faceoff.get("sequence"),
                f"{kind} faceoff location is absent; center placement cannot be assessed",
                status="NOT_ASSESSED"))
        else:
            findings.append(_issue(faceoff.get("sequence"),
                f"{kind} faceoff is not identified at center ice",
                detail={"location": location, "coordinates": list(coords), "zone_code": zone}))
    if findings:
        return _check("restart_location", ("Rules 76, 78"), findings)
    if unassessed:
        return _check("restart_location", ("Rules 76, 78"), unassessed)
    return _check("restart_location", ("Rules 76, 78"))


def _check_penalties(game: dict[str, Any]) -> dict[str, Any]:
    events = game.get("events", [])
    try:
        players = _player_map(game)
    except (TypeError, ValueError) as exc:
        return _check("penalty_and_manpower", ("Rules 15-27, 84"),
                      [_issue(None, "cannot audit penalties without a player ledger", detail=str(exc))])
    active: list[dict[str, Any]] = []
    queued: list[dict[str, Any]] = []
    waiting_release: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    unassessed: list[dict[str, Any]] = []
    expected_goal_action: tuple[int, str, str] | None = None
    pending_expiries: set[tuple[str, str]] = set()
    expiry_second: int | None = None
    pending_service_starts: dict[tuple[str, str], dict[str, Any]] = {}
    last_stoppage_second: int | None = None
    supported_kind_durations = {"MIN": {120, 240}, "MAJ": {300}, "MIS": {600}}
    skip_personnel = {"period-start", "period-end", "game-end", "shootout-attempt", "shootout-decision"}

    for index, event in enumerate(events, 1):
        if not isinstance(event, dict) or event.get("period_type") == "SO":
            continue
        seq = event.get("sequence", index)
        event_type = event.get("event_type")
        side = event.get("team_side")
        details = event.get("details") or {}
        participants = event.get("participants") or {}
        try:
            now = _absolute_seconds(event)
        except (TypeError, ValueError, KeyError) as exc:
            findings.append(_issue(seq, "penalty clock cannot be resolved", detail=str(exc)))
            continue

        if pending_expiries:
            if event_type != "penalty-expiration" or now != expiry_second:
                findings.append(_issue(seq, "simultaneous penalty expiration sequence is incomplete"))
                pending_expiries.clear()
            else:
                key = (str(side), str(participants.get("player_id") or ""))
                if key not in pending_expiries:
                    findings.append(_issue(seq, "expiration event does not match a due player"))
                pending_expiries.discard(key)
        elif event_type == "penalty-expiration":
            due = [p for p in active if p["end"] <= now]
            key = (str(side), str(participants.get("player_id") or ""))
            due_keys = {(p["side"], p["player_id"]) for p in due}
            if not due or key not in due_keys or any(p["end"] < now for p in due):
                findings.append(_issue(seq, "penalty expiration is missing, early, late, or unmatched"))
            else:
                pending_expiries = due_keys - {key}
                expiry_second = now if pending_expiries else None
                due_by_side = {candidate_side: [p for p in due if p["side"] == candidate_side]
                               for candidate_side in SIDES}
                deferred_keys: set[tuple[str, str]] = set()
                starts_to_validate: list[dict[str, Any]] = []
                for candidate_side in SIDES:
                    side_queue = [p for p in queued if p["side"] == candidate_side]
                    manpower_due = [p for p in due_by_side[candidate_side]
                                    if p["kind"] in {"MIN", "MAJ"} and not p["coincidental"]]
                    if not side_queue or not manpower_due:
                        continue
                    if len(side_queue) != 1 or len(manpower_due) != 1:
                        quarantine.append(_issue(seq,
                            "queued service cannot resolve simultaneous or multiple penalty ordering",
                            status="QUARANTINED"))
                        continue
                    old = manpower_due[0]
                    waiting_release.append(old)
                    deferred_keys.add((old["side"], old["player_id"]))
                    queued_penalty = side_queue[0]
                    queued.remove(queued_penalty)
                    starts_to_validate.append({**queued_penalty,
                        "assessed_at": queued_penalty["start"],
                        "triggered_by_player_id": old["player_id"],"start": now})
                active = [p for p in active if (p["side"], p["player_id"]) not in due_keys]
                # Queue service is live at the expiration second and therefore
                # participates in the same event's manpower check.
                for start in starts_to_validate:
                    active.append({"side": start["side"],"player_id": start["player_id"],
                                   "kind": start["kind"],"duration": start["duration"],
                                   "start": now,"end": now + start["duration"],
                                   "coincidental": False})
                    service_key = (start["side"], start["player_id"])
                    pending_service_starts[service_key] = start
                reported_deferred = bool(details.get("return_deferred_under_rule_26_2", False))
                if (key in deferred_keys) != reported_deferred:
                    findings.append(_issue(seq,
                        "penalty expiration does not match Rule 26.2 deferred-return state"))
        elif any(p["end"] <= now for p in active):
            due = [p for p in active if p["end"] <= now]
            findings.append(_issue(seq, "active penalty reached expiry without an explicit exact-time expiration",
                detail={"due": [{"side": p["side"], "player_id": p["player_id"],
                                  "expiry": p["end"]} for p in due], "event_time": now}))

        if pending_service_starts and event_type not in {"penalty-expiration", "penalty-service-start"}:
            findings.append(_issue(seq, "queued penalty service start event is missing or out of order",
                detail={"pending": sorted(pending_service_starts)}))
            pending_service_starts.clear()

        active_for_event = [dict(p) for p in active]
        barred_for_event = (active_for_event + [dict(p) for p in queued]
                            + [dict(p) for p in waiting_release])

        on_ice = event.get("on_ice") or {}
        for ice_side in SIDES:
            ids = {str(pid) for pid in on_ice.get(ice_side, [])}
            serving = {p["player_id"] for p in barred_for_event if p["side"] == ice_side}
            if ids & serving:
                findings.append(_issue(seq, "player serving or awaiting release from a penalty remains on ice",
                    detail={"side": ice_side, "players": sorted(ids & serving)}))

        if expected_goal_action is not None:
            expected_time, expected_side, expected_type = expected_goal_action
            if (event_type == "penalty-service-start" and now == expected_time
                    and side == expected_side):
                pass
            elif now != expected_time or event_type != expected_type or side != expected_side:
                findings.append(_issue(seq,
                    "qualifying power-play goal lacks its required immediate minor release/segment transition",
                    detail={"expected": {"time": expected_time, "side": expected_side,
                                           "event_type": expected_type},
                            "actual": {"time": now, "side": side, "event_type": event_type}}))
                expected_goal_action = None
            else:
                expected_goal_action = None

        if event_type == "penalty":
            kind = str(details.get("penalty_kind") or "")
            duration = details.get("penalty_duration_seconds")
            actor = str(participants.get("penalized_player_id") or "")
            server = str(participants.get("serving_player_id") or "")
            if kind not in supported_kind_durations or duration not in supported_kind_durations.get(kind, set()):
                quarantine.append(_issue(seq, "penalty kind/duration is outside this validator's supported transition table",
                    status="QUARANTINED", detail={"kind": kind, "duration": duration}))
                continue
            if side not in SIDES or not actor or not server:
                findings.append(_issue(seq, "penalty lacks team, penalized player, or serving player"))
                continue
            if actor != server:
                findings.append(_issue(seq, "player penalty actor and server differ without a bench-minor rule record"))
            player = players.get(actor)
            if player is None or player.get("team_side") != side or player.get("position") == "G":
                findings.append(_issue(seq, "penalty server is not an eligible skater on the assessed team"))
            if actor not in {str(pid) for pid in (event.get("on_ice") or {}).get(side, [])}:
                findings.append(_issue(seq, "penalized skater was not on ice when assessed"))
            if any(p["side"] == side and p["player_id"] == actor
                   for p in active + queued + waiting_release):
                findings.append(_issue(seq, "player receives a second overlapping penalty in this supported model"))
            coincidental_raw = details.get("coincidental")
            if kind in {"MIN", "MAJ"} and not isinstance(coincidental_raw, bool):
                coincidental = None
                unassessed.append(_issue(seq,
                    "penalty omits the explicit coincidental classification required to derive manpower",
                    status="NOT_ASSESSED"))
            else:
                coincidental = coincidental_raw if isinstance(coincidental_raw, bool) else False
            side_penalties = [p for p in active if p["side"] == side
                              and p["kind"] in {"MIN", "MAJ"}]
            count_is_assessable = all(p["coincidental"] is not None for p in side_penalties)
            count = sum(not p["coincidental"] for p in side_penalties
                        if p["coincidental"] is not None)
            should_queue = (kind in {"MIN", "MAJ"} and coincidental is False
                            and count_is_assessable and count >= 2)
            reported_service_state = details.get("penalty_service_state")
            expected_service_state = "queued" if should_queue else "active"
            if reported_service_state is not None and reported_service_state != expected_service_state:
                findings.append(_issue(seq, "penalty service state disagrees with prior manpower state",
                    detail={"reported": reported_service_state,"expected": expected_service_state}))
            record = {"side": side,"player_id": actor,"kind": kind,
                      "duration": int(duration),"start": now,"end": now + int(duration),
                      "coincidental": coincidental}
            if should_queue:
                if queued or waiting_release:
                    quarantine.append(_issue(seq,
                        "additional queued manpower penalty is outside the supported subset",
                        status="QUARANTINED"))
                else:
                    record["assessment_event_sequence"] = seq
                    queued.append(record)
            else:
                active.append(record)

        elif event_type == "penalty-service-start":
            pid = str(participants.get("player_id") or "")
            service_key = (str(side), pid)
            expected = pending_service_starts.pop(service_key, None)
            if expected is None:
                findings.append(_issue(seq, "penalty-service-start has no exact prior queued trigger"))
            else:
                expected_fields = {
                    "penalty_kind": expected["kind"],
                    "penalty_duration_seconds": expected["duration"],
                    "penalty_assessment_event_sequence": expected["assessment_event_sequence"],
                    "assessed_at_absolute_second": expected["assessed_at"],
                    "service_started_at_absolute_second": now,
                    "triggered_by_expired_player_id": expected["triggered_by_player_id"],
                }
                actual_fields = {key: details.get(key) for key in expected_fields}
                if now != expected["start"] or actual_fields != expected_fields:
                    findings.append(_issue(seq, "penalty-service-start does not match queued assessment/trigger",
                        detail={"expected": expected_fields,"actual": actual_fields,"time": now}))

        elif event_type in {"penalty-release", "penalty-segment-end"}:
            pid = str(participants.get("player_id") or "")
            release_reason = details.get("release_reason")
            waiting_matches = [p for p in waiting_release
                               if p["side"] == side and p["player_id"] == pid]
            matches = [p for p in active if p["side"] == side and p["player_id"] == pid]
            if release_reason in {"penalty_expiration_stoppage",
                                  "penalty_expiration_entitled_during_play"}:
                if len(waiting_matches) != 1 or event_type != "penalty-release":
                    findings.append(_issue(seq, "Rule 26.2 release has no expired waiting player"))
                elif release_reason == "penalty_expiration_stoppage" and last_stoppage_second != now:
                    findings.append(_issue(seq, "deferred penalty return was not recorded at a stoppage"))
                elif release_reason == "penalty_expiration_entitled_during_play":
                    counts, unsupported = _expected_manpower(active_for_event,
                        str(event.get("period_type")),
                        {s: not any(players.get(str(x), {}).get("position") == "G"
                                    for x in on_ice.get(s, [])) for s in SIDES})
                    if unsupported or counts is None or counts.get(str(side), 0) <= 4:
                        findings.append(_issue(seq,
                            "during-play Rule 26.2 release occurred while team was not entitled to more than four players"))
                    waiting_release.remove(waiting_matches[0])
                else:
                    waiting_release.remove(waiting_matches[0])
            elif release_reason == "power_play_goal" and waiting_matches and event_type == "penalty-release":
                waiting_release.remove(waiting_matches[0])
            elif not matches:
                findings.append(_issue(seq, "penalty resolution has no active matching penalty"))
            else:
                penalty = matches[0]
                if event_type == "penalty-release":
                    if penalty["kind"] != "MIN" or details.get("release_reason") != "power_play_goal":
                        findings.append(_issue(seq, "early release is not a supported minor-penalty goal consequence"))
                    active.remove(penalty)
                else:
                    if penalty["kind"] != "MIN" or penalty["duration"] != 240:
                        findings.append(_issue(seq, "only the first segment of a double minor can end early"))
                    elif details.get("release_reason") != "power_play_goal":
                        findings.append(_issue(seq, "double-minor segment ended without a qualifying goal"))
                    else:
                        penalty["end"] = now + 120

        if event_type == "goal" and side in SIDES:
            opposing = "away" if side == "home" else "home"
            opposing_classification_unknown = any(p["side"] == opposing
                and p["kind"] in {"MIN", "MAJ"} and p["coincidental"] is None for p in active)
            units_assessable = all(p["coincidental"] is not None
                for p in active if p["kind"] in {"MIN", "MAJ"})
            units = {s: sum(p["side"] == s and p["kind"] in {"MIN", "MAJ"}
                           and p["coincidental"] is False for p in active) for s in SIDES}
            if opposing_classification_unknown:
                unassessed.append(_issue(seq,
                    "goal-scoring penalty release cannot be derived from an unclassified active penalty",
                    status="NOT_ASSESSED"))
            elif units_assessable and units[opposing] > units[side]:
                candidates = [p for p in active if p["side"] == opposing and p["kind"] == "MIN"
                              and p["coincidental"] is False]
                if candidates:
                    penalty = min(candidates, key=lambda p: (p["end"], p["start"], p["player_id"]))
                    action = "penalty-segment-end" if penalty["duration"] == 240 and penalty["end"] - now > 120 else "penalty-release"
                    expected_goal_action = (now, opposing, action)
                    if action == "penalty-release":
                        queued_matches = [p for p in queued if p["side"] == opposing]
                        if queued_matches:
                            if len(queued_matches) != 1:
                                quarantine.append(_issue(seq,
                                    "power-play goal cannot order multiple queued penalties",
                                    status="QUARANTINED"))
                            else:
                                active.remove(penalty)
                                waiting_release.append(penalty)
                                queued_penalty = queued_matches[0]
                                queued.remove(queued_penalty)
                                service = {"side": opposing,"player_id": queued_penalty["player_id"],
                                    "kind": queued_penalty["kind"],"duration": queued_penalty["duration"],
                                    "assessment_event_sequence": queued_penalty["assessment_event_sequence"],
                                    "assessed_at": queued_penalty["start"],
                                    "triggered_by_player_id": penalty["player_id"],"start": now}
                                active.append({"side": opposing,"player_id": service["player_id"],
                                    "kind": service["kind"],"duration": service["duration"],
                                    "start": now,"end": now + service["duration"],
                                    "coincidental": False})
                                pending_service_starts[(opposing, service["player_id"])] = service
                else:
                    # A major cannot be washed out by a goal; no release is expected.
                    expected_goal_action = None

        if event_type in {"goal", "penalty", "stoppage"}:
            last_stoppage_second = now

        if event_type in {"delayed-penalty"} or details.get("unsupported_penalty_omitted"):
            quarantine.append(_issue(seq, "penalty transition is explicitly outside the supported rules subset",
                status="QUARANTINED"))

        if event_type not in skip_personnel and event.get("period_type") in {"REG", "OT"}:
            actual = {s: sum(players.get(str(pid), {}).get("position") != "G"
                             for pid in on_ice.get(s, [])) for s in SIDES}
            pulled_raw = (event.get("details") or {}).get("goalie_pulled")
            pulled = {s: bool(pulled_raw.get(s)) if isinstance(pulled_raw, dict)
                      else not any(players.get(str(pid), {}).get("position") == "G"
                                   for pid in on_ice.get(s, [])) for s in SIDES}
            expected, unsupported = _expected_manpower(active_for_event, str(event["period_type"]), pulled)
            if unsupported:
                if "no explicit coincidental classification" not in unsupported:
                    quarantine.append(_issue(seq, unsupported, status="QUARANTINED"))
            elif expected != actual:
                findings.append(_issue(seq, "derived penalty/goalie state disagrees with on-ice manpower",
                    detail={"actual": actual, "expected": expected, "pulled": pulled}))
            label = event.get("strength")
            expected_label = f"{actual['home']}v{actual['away']}"
            if label is not None and label != expected_label:
                findings.append(_issue(seq, "strength label conflicts with independently counted skaters",
                    detail={"actual": label, "expected": expected_label}))

    if expected_goal_action is not None:
        findings.append(_issue(None, "game ended before a required power-play goal penalty transition"))
    if pending_expiries:
        findings.append(_issue(None, "game ended before all simultaneous penalty expirations were recorded",
            detail={"pending": sorted(pending_expiries)}))
    if pending_service_starts:
        findings.append(_issue(None, "game ended before queued penalty service-start events were recorded",
            detail={"pending": sorted(pending_service_starts)}))
    if findings:
        return _check("penalty_and_manpower", ("Rules 15-27, 84"), findings)
    if quarantine:
        return _check("penalty_and_manpower", ("Rules 15-27, 84"), quarantine,
                      status="QUARANTINED")
    if unassessed:
        return _check("penalty_and_manpower", ("Rules 15-27, 84"), unassessed,
                      status="NOT_ASSESSED")
    return _check("penalty_and_manpower", ("Rules 15-27, 84"))


def _check_shift_ledger(game: dict[str, Any]) -> dict[str, Any]:
    shifts = game.get("shift_ledger")
    if not isinstance(shifts, list):
        return _check("shift_interval_integrity", ("Rules 68, 71, 74, 82"),
                      [_issue(None, "shift_ledger is missing or not a list")])
    try:
        players = _player_map(game)
    except (TypeError, ValueError) as exc:
        return _check("shift_interval_integrity", ("Rules 68, 71, 74, 82"),
                      [_issue(None, "cannot reconcile shift IDs", detail=str(exc))])
    findings: list[dict[str, Any]] = []
    intervals: dict[tuple[int, str, str], list[tuple[int, int, int]]] = defaultdict(list)
    totals: Counter[str] = Counter()
    for index, row in enumerate(shifts, 1):
        if not isinstance(row, dict):
            findings.append(_issue(index, "shift interval is not an object"))
            continue
        try:
            period = int(row["period_number"])
            side = str(row["team_side"])
            pid = str(row["player_id"])
            start, end, duration = (int(row[k]) for k in ("start_seconds", "end_seconds", "duration_seconds"))
            limit = REG_SECONDS if period in (1, 2, 3) else OT_SECONDS if period == 4 else None
            if side not in SIDES or limit is None or start < 0 or end <= start or end > limit:
                raise ValueError("invalid side, period, or shift interval bounds")
            if end - start != duration:
                raise ValueError("recorded shift duration differs from endpoints")
            player = players.get(pid)
            if player is None or player.get("team_side") != side:
                raise ValueError("shift player is absent from the matching team roster")
            key = (period, side, pid)
            for old_start, old_end, old_row in intervals[key]:
                if max(start, old_start) < min(end, old_end):
                    findings.append(_issue(old_row,
                        "same player has overlapping shifts within a period",
                        detail={"player_id": pid, "overlap": [max(start, old_start), min(end, old_end)],
                                "other_row": index}))
            intervals[key].append((start, end, index))
            totals[pid] += duration
        except (KeyError, TypeError, ValueError) as exc:
            findings.append(_issue(index, "shift interval is incomplete or invalid", detail=str(exc)))
    for pid, player in players.items():
        try:
            declared = int(player.get("time_on_ice_seconds", 0))
        except (TypeError, ValueError):
            findings.append(_issue(None, "player TOI is not an integer", detail={"player_id": pid}))
            continue
        if totals[pid] != declared:
            findings.append(_issue(None, "player TOI does not reconcile to the shift ledger",
                detail={"player_id": pid, "ledger": totals[pid], "summary": declared}))
    return _check("shift_interval_integrity", ("Rules 68, 71, 74, 82"), findings)


def _check_line_changes(game: dict[str, Any]) -> dict[str, Any]:
    events = game.get("events", [])
    changes = [(i, e) for i, e in enumerate(events) if isinstance(e, dict)
               and e.get("event_type") == "line-change"]
    if not changes:
        return _check("line_change_legality", ("Rules 68, 71, 74, 82"),
                      [_issue(None, "simulator emits no explicit incoming/outgoing line-change event",
                              status="NOT_ASSESSED")], status="NOT_ASSESSED")
    findings: list[dict[str, Any]] = []
    unassessed: list[dict[str, Any]] = []
    players = _player_map(game)
    shifts = game.get("shift_ledger") if isinstance(game.get("shift_ledger"), list) else []
    for index, event in changes:
        seq = event.get("sequence", index + 1)
        side = event.get("team_side")
        if side not in SIDES or index == 0:
            findings.append(_issue(seq, "line-change lacks a team or prior lineup"))
            continue
        previous = events[index - 1]
        before = {str(pid) for pid in (previous.get("on_ice") or {}).get(side, [])}
        after = {str(pid) for pid in (event.get("on_ice") or {}).get(side, [])}
        participants = event.get("participants") or {}
        off = {str(pid) for pid in participants.get("players_off", [])}
        on = {str(pid) for pid in participants.get("players_on", [])}
        if not off or not on or off & on or off - before or on & before:
            findings.append(_issue(seq, "line-change participants do not describe valid outgoing/incoming players"))
            continue
        if (before - off) | on != after:
            findings.append(_issue(seq, "line-change on-ice state does not equal outgoing/incoming delta"))
        for pid in off | on:
            row = players.get(pid)
            if row is None or row.get("team_side") != side or row.get("position") == "G":
                findings.append(_issue(seq, "line change includes a missing, opposing, or goalkeeper ID",
                    detail={"player_id": pid}))
        period = int(event["period_number"])
        elapsed = int(event["clock_elapsed_seconds"])
        try:
            ends = {str(r.get("player_id")) for r in shifts if r.get("period_number") == period
                    and r.get("team_side") == side and int(r.get("end_seconds", -1)) == elapsed}
            starts = {str(r.get("player_id")) for r in shifts if r.get("period_number") == period
                      and r.get("team_side") == side and int(r.get("start_seconds", -1)) == elapsed}
        except (TypeError, ValueError):
            findings.append(_issue(seq, "line-change shift boundary is malformed"))
            continue
        if off - ends or on - starts:
            findings.append(_issue(seq, "line-change event does not match shift-ledger boundaries",
                detail={"missing_shift_end": sorted(off - ends),
                        "missing_shift_start": sorted(on - starts)}))
        details = event.get("details") or {}
        window = details.get("change_window")
        if window == "stoppage":
            stop_seq = details.get("stoppage_event_sequence")
            stop = next((candidate for candidate in events
                         if isinstance(candidate, dict) and candidate.get("sequence") == stop_seq), None)
            if (stop is None or stop.get("event_type") != "stoppage"
                    or stop.get("period_number") != period
                    or stop.get("clock_elapsed_seconds") != elapsed
                    or int(stop.get("sequence", 0)) >= int(seq)):
                unassessed.append(_issue(seq,
                    "stoppage-window claim is not tied to a preceding same-clock stoppage event",
                    status="NOT_ASSESSED"))
        elif window == "on_the_fly" and details.get("bench_exchange_evidence") not in {"tracking", "official_ruling"}:
            unassessed.append(_issue(seq,
                "on-the-fly change has no bench-exchange evidence",
                status="NOT_ASSESSED"))
    if findings:
        return _check("line_change_legality", ("Rules 68, 71, 74, 82"), findings)
    if unassessed:
        return _check("line_change_legality", ("Rules 68, 71, 74, 82"), unassessed,
                      status="NOT_ASSESSED")
    return _check("line_change_legality", ("Rules 68, 71, 74, 82"))


def _check_goalie_transitions(game: dict[str, Any]) -> dict[str, Any]:
    events = game.get("events", [])
    players = _player_map(game)
    findings: list[dict[str, Any]] = []
    unassessed: list[dict[str, Any]] = []
    last_goalie: dict[str, str | None] = {side: None for side in SIDES}
    transition_count = 0
    for index, event in enumerate(events, 1):
        if not isinstance(event, dict) or event.get("period_type") == "SO":
            continue
        seq = event.get("sequence", index)
        on_ice = event.get("on_ice") or {}
        transition = event.get("event_type") == "goalie-substitution"
        transition_side = event.get("team_side") if transition else None
        for side in SIDES:
            if transition and side == transition_side:
                continue
            ids = [str(pid) for pid in on_ice.get(side, [])]
            goalies = [pid for pid in ids if players.get(pid, {}).get("position") == "G"]
            if len(goalies) > 1:
                findings.append(_issue(seq, "team has more than one goalkeeper on ice", detail={"side": side}))
            if goalies:
                last_goalie[side] = goalies[0]
        if not transition:
            continue
        transition_count += 1
        side = event.get("team_side")
        participants = event.get("participants") or {}
        leaving = participants.get("goalie_leaving_id")
        entering = participants.get("goalie_entering_id")
        if side not in SIDES:
            findings.append(_issue(seq, "goalkeeper substitution has no team side"))
            continue
        leaving = str(leaving) if leaving is not None else None
        entering = str(entering) if entering is not None else None
        event_goalies = [str(pid) for pid in (on_ice.get(side) or [])
                         if players.get(str(pid), {}).get("position") == "G"]
        if leaving is not None and last_goalie[side] not in {None, leaving}:
            findings.append(_issue(seq, "goalkeeper leaving ID differs from the preceding on-ice goalkeeper",
                detail={"declared": leaving, "previous": last_goalie[side]}))
        if entering is None:
            if event_goalies:
                findings.append(_issue(seq, "goalie-pull event still has a goalkeeper on ice"))
            if leaving is None:
                findings.append(_issue(seq, "goalie pull omits the goalkeeper leaving"))
        else:
            row = players.get(entering)
            if row is None or row.get("team_side") != side or row.get("position") != "G":
                findings.append(_issue(seq, "goalie entering is not a rostered goalkeeper for that team"))
            if event_goalies != [entering]:
                findings.append(_issue(seq, "goalie entering ID does not match the on-ice state"))
        if leaving == entering:
            findings.append(_issue(seq, "goalkeeper substitution does not change the active goalkeeper"))
        last_goalie[side] = entering
        unassessed.append(_issue(seq,
            "legal stoppage/bench window for goalie pull or return is not represented",
            status="NOT_ASSESSED"))
    if not transition_count:
        unassessed.append(_issue(None, "no explicit goalie pull/return records are present",
                                 status="NOT_ASSESSED"))
    if findings:
        return _check("goalie_transition_state", ("Rules 68, 71, 74, 82, 84"), findings)
    return _check("goalie_transition_state", ("Rules 68, 71, 74, 82, 84"), unassessed,
                  status="NOT_ASSESSED")


def _shootout_winner(events: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    attempts = {side: 0 for side in SIDES}
    goals = {side: 0 for side in SIDES}
    winner: str | None = None
    findings: list[dict[str, Any]] = []
    shooters = {side: set() for side in SIDES}
    start = next((event for event in events if event.get("event_type") == "period-start"
                  and event.get("period_type") == "SO"), None)
    first_side = ((start.get("details") or {}).get("first_shooting_side")
                  if start is not None else None)
    decision_seen = False
    attempt_index = 0
    for event in events:
        if event.get("event_type") == "shootout-decision":
            decision_seen = True
            continue
        if event.get("event_type") != "shootout-attempt":
            continue
        seq = event.get("sequence")
        if winner is not None or decision_seen:
            findings.append(_issue(seq, "shootout continued after a mathematically decisive attempt"))
        side = event.get("team_side")
        result = (event.get("details") or {}).get("attempt_result")
        if side not in SIDES or result not in {"goal", "saved", "missed"}:
            findings.append(_issue(seq, "shootout attempt has an invalid team or result"))
            continue
        if event.get("period_type") != "SO" or int(event.get("period_number", -1)) != 5:
            findings.append(_issue(seq, "shootout attempt is outside the shootout period"))
        if first_side in SIDES:
            expected_side = first_side if attempt_index % 2 == 0 else (
                "away" if first_side == "home" else "home")
            if side != expected_side:
                findings.append(_issue(seq, "shootout attempts do not alternate by team",
                    detail={"expected_side": expected_side, "actual_side": side}))
        attempt_index += 1
        shooter = (event.get("participants") or {}).get("shooter_id")
        if shooter is not None:
            if str(shooter) in shooters[side]:
                # Repeats are legal only after every game-eligible player has shot.
                findings.append(_issue(seq, "repeated shooter cannot be checked without the submitted game lineup",
                                       status="NOT_ASSESSED"))
            shooters[side].add(str(shooter))
        attempts[side] += 1
        goals[side] += int(result == "goal")
        if attempts["home"] <= 3 and attempts["away"] <= 3:
            remaining = {team: max(0, 3 - attempts[team]) for team in SIDES}
            if goals["home"] > goals["away"] + remaining["away"]:
                winner = "home"
            elif goals["away"] > goals["home"] + remaining["home"]:
                winner = "away"
        elif attempts["home"] == attempts["away"] and attempts["home"] > 3:
            if goals["home"] != goals["away"]:
                winner = "home" if goals["home"] > goals["away"] else "away"
    return winner, findings


def _shootout_roster_findings(game: dict[str, Any], events: list[dict[str, Any]],
                              shootout_start_index: int) -> list[dict[str, Any]]:
    snapshot = game.get("pregame_snapshot")
    projection = snapshot.get("projected_game_roster") if isinstance(snapshot, dict) else None
    if not isinstance(projection, dict):
        return [_issue(None, "projected game roster is absent; shooter eligibility cannot be checked",
                       status="NOT_ASSESSED")]
    projected = _projected_game_roster(game)
    if projected is None:
        return [_issue(None, "projected game roster is malformed; shooter eligibility cannot be checked")]
    start = events[shootout_start_index]
    sequence = start.get("sequence")
    eligible = {side: set(projected[side]) for side in SIDES}
    active_misconduct = {side: set() for side in SIDES}
    for event in events[:shootout_start_index]:
        if not isinstance(event, dict):
            continue
        event_type = event.get("event_type")
        side = event.get("team_side")
        details = event.get("details") or {}
        participants = event.get("participants") or {}
        kind = str(details.get("penalty_kind") or "").upper()
        if event_type == "penalty" and kind == "MIS" and side in SIDES:
            for field in ("penalized_player_id", "serving_player_id"):
                player_id = participants.get(field)
                if player_id is not None:
                    active_misconduct[side].add(str(player_id))
        elif event_type in {"penalty-expiration", "penalty-release", "penalty-segment-end"} and kind == "MIS":
            player_id = participants.get("player_id") or details.get("player_returned_id")
            if player_id is not None and side in SIDES:
                active_misconduct[side].discard(str(player_id))
    findings: list[dict[str, Any]] = []
    for side in SIDES:
        eligible[side].difference_update(active_misconduct[side])
        if not eligible[side]:
            findings.append(_issue(sequence, "team has no eligible projected-roster shootout participant",
                                   detail={"side": side}))
    attempts_seen = {side: set() for side in SIDES}
    for event in events[shootout_start_index + 1:]:
        if not isinstance(event, dict) or event.get("event_type") != "shootout-attempt":
            continue
        side = event.get("team_side")
        seq = event.get("sequence")
        shooter = str((event.get("participants") or {}).get("shooter_id") or "")
        if side not in SIDES:
            findings.append(_issue(seq, "shootout attempt lacks a valid shooting side"))
            continue
        if shooter not in eligible[side]:
            findings.append(_issue(seq, "shootout shooter is not eligible from the projected roster",
                detail={"side": side, "shooter_id": shooter,
                        "active_misconduct_exclusions": sorted(active_misconduct[side])}))
            continue
        if shooter in attempts_seen[side]:
            if len(attempts_seen[side]) < len(eligible[side]):
                findings.append(_issue(seq, "player repeated before every eligible projected-roster player had shot",
                    detail={"side": side, "shooter_id": shooter,
                            "unique_shooters": len(attempts_seen[side]),
                            "eligible_shooters": len(eligible[side])}))
            else:
                attempts_seen[side].clear()
        attempts_seen[side].add(shooter)
    return findings


def _check_overtime_shootout(game: dict[str, Any]) -> dict[str, Any]:
    events = game.get("events", [])
    findings: list[dict[str, Any]] = []
    summary = game.get("summary", {})
    period_events = [(i, e) for i, e in enumerate(events) if isinstance(e, dict)]
    periods = {(str(e.get("period_type")), int(e.get("period_number", -1)))
               for _, e in period_events}
    ot_goals = [e for _, e in period_events if e.get("period_type") == "OT" and e.get("event_type") == "goal"]
    so_events = [e for _, e in period_events if e.get("period_type") == "SO"]
    reg_score = {side: 0 for side in SIDES}
    for _, event in period_events:
        if event.get("period_type") in {"REG", "OT"} and event.get("event_type") == "goal" \
                and event.get("team_side") in SIDES:
            reg_score[event["team_side"]] += 1
    score_at_reg_end = {side: 0 for side in SIDES}
    for _, event in period_events:
        if event.get("period_type") == "REG" and event.get("event_type") == "goal" \
                and event.get("team_side") in SIDES:
            score_at_reg_end[event["team_side"]] += 1
    overtime_start = next((e for _, e in period_events if e.get("period_type") == "OT"
                           and e.get("event_type") == "period-start"), None)
    shootout_start = next((e for _, e in period_events if e.get("period_type") == "SO"
                           and e.get("event_type") == "period-start"), None)
    overtime_starts = [e for _, e in period_events if e.get("period_type") == "OT"
                       and e.get("event_type") == "period-start"]
    overtime_ends = [e for _, e in period_events if e.get("period_type") == "OT"
                     and e.get("event_type") == "period-end"]
    if score_at_reg_end["home"] == score_at_reg_end["away"]:
        if overtime_start is None:
            findings.append(_issue(None, "regulation tie does not enter overtime"))
        elif len(overtime_starts) != 1 or int(overtime_start.get("clock_elapsed_seconds", -1)) != 0:
            findings.append(_issue(overtime_start.get("sequence"),
                "regular-season overtime must have one start at 00:00"))
        if not ot_goals and not so_events:
            findings.append(_issue(None, "tied overtime does not proceed to shootout"))
    elif overtime_start is not None or so_events:
        findings.append(_issue(None, "non-tied regulation game enters overtime or shootout"))
    if ot_goals:
        goal = min(ot_goals, key=lambda e: int(e.get("clock_elapsed_seconds", 0)))
        goal_index = next(i for i, e in enumerate(events) if e is goal)
        after_goal = _next_non_admin(events, goal_index)
        if after_goal is None or after_goal.get("event_type") != "game-end" \
                or int(after_goal.get("clock_elapsed_seconds", -1)) != int(goal.get("clock_elapsed_seconds", -2)):
            findings.append(_issue(goal.get("sequence"), "overtime goal does not end the game immediately"))
        terminal_index = next((i for i in range(goal_index + 1, len(events))
                               if isinstance(events[i], dict)
                               and events[i].get("event_type") == "game-end"), None)
        if terminal_index is not None:
            intervening = [event.get("event_type") for event in events[goal_index + 1:terminal_index]
                           if isinstance(event, dict)]
            if any(kind not in {"penalty-release", "penalty-segment-end", "penalty-expiration"}
                   for kind in intervening):
                findings.append(_issue(goal.get("sequence"),
                    "live event intervenes between overtime goal and terminal game-end",
                    detail={"intervening_event_types": intervening}))
        if so_events:
            findings.append(_issue(goal.get("sequence"), "shootout exists after an overtime sudden-death goal"))
        if overtime_ends:
            findings.append(_issue(goal.get("sequence"),
                "overtime sudden-death goal is followed by an overtime period-end"))
    elif overtime_start is not None:
        if so_events:
            if len(overtime_ends) != 1 or int(overtime_ends[0].get("clock_elapsed_seconds", -1)) != OT_SECONDS:
                findings.append(_issue(shootout_start.get("sequence") if shootout_start else None,
                    "scoreless overtime must end at five minutes exactly once before the shootout"))
            elif shootout_start is not None:
                ot_end_index = next(i for i, event in enumerate(events) if event is overtime_ends[0])
                so_start_index = next(i for i, event in enumerate(events) if event is shootout_start)
                if ot_end_index > so_start_index:
                    findings.append(_issue(shootout_start.get("sequence"),
                        "shootout starts before overtime has ended"))
        elif len(overtime_ends) != 1 or int(overtime_ends[0].get("clock_elapsed_seconds", -1)) != OT_SECONDS:
            findings.append(_issue(None,
                "scoreless overtime must end at five minutes when no sudden-death goal occurs"))
    if shootout_start is not None:
        if score_at_reg_end["home"] != score_at_reg_end["away"] or ot_goals:
            findings.append(_issue(shootout_start.get("sequence"), "shootout occurs without a tied score after overtime"))
        winner, shootout_findings = _shootout_winner(events)
        findings.extend(shootout_findings)
        shootout_start_index = next(i for i, event in enumerate(events) if event is shootout_start)
        eligibility_findings = _shootout_roster_findings(game, events, shootout_start_index)
        findings.extend(row for row in eligibility_findings if row.get("status") != "NOT_ASSESSED")
        unassessed_eligibility = next((row for row in eligibility_findings
                                       if row.get("status") == "NOT_ASSESSED"), None)
        declared = summary.get("shootout_winner")
        decisions = [e.get("team_side") for e in events if isinstance(e, dict)
                     and e.get("event_type") == "shootout-decision"]
        if winner is None or declared != winner or decisions != [winner]:
            findings.append(_issue(shootout_start.get("sequence"),
                "shootout attempts, earliest decision, and declared winner do not reconcile",
                detail={"calculated": winner, "summary": declared, "decision_events": decisions}))
        decision_indices = [i for i, event in enumerate(events) if isinstance(event, dict)
                            and event.get("event_type") == "shootout-decision"]
        attempt_indices = [i for i, event in enumerate(events) if isinstance(event, dict)
                           and event.get("event_type") == "shootout-attempt"]
        if len(decision_indices) == 1 and attempt_indices and decision_indices[0] <= max(attempt_indices):
            findings.append(_issue(events[decision_indices[0]].get("sequence"),
                "shootout decision must follow the final attempt"))
        if len(decision_indices) == 1:
            end_index = next((i for i, event in enumerate(events) if isinstance(event, dict)
                              and event.get("event_type") == "game-end"), None)
            if end_index is None or end_index <= decision_indices[0]:
                findings.append(_issue(events[decision_indices[0]].get("sequence"),
                    "shootout decision is not followed by terminal game-end"))
        official = summary.get("official_final_score") or {}
        reg_ot_score = {side: 0 for side in SIDES}
        for _, event in period_events:
            if event.get("period_type") in {"REG", "OT"} and event.get("event_type") == "goal" \
                    and event.get("team_side") in SIDES:
                reg_ot_score[event["team_side"]] += 1
        if reg_ot_score != summary.get("regulation_overtime_score"):
            findings.append(_issue(shootout_start.get("sequence"),
                "event regulation/OT score does not reconcile with summary",
                detail={"events": reg_ot_score, "summary": summary.get("regulation_overtime_score")}))
        for side in SIDES:
            expected = reg_ot_score[side] + int(side == winner)
            if int(official.get(side, -1)) != expected:
                findings.append(_issue(shootout_start.get("sequence"),
                    "official shootout final score must add one team goal only to the winner",
                    detail={"side": side, "actual": official.get(side), "expected": expected}))
        if unassessed_eligibility is not None:
            unassessed_eligibility["message"] = (
                "official dressed lineup is unavailable; shooter checks use the modeled projected roster only")
    else:
        unassessed_eligibility = None
        if so_events:
            findings.append(_issue(None, "shootout events occur without a shootout period start"))
        if summary.get("shootout_winner") is not None:
            findings.append(_issue(None, "summary declares a shootout winner without a shootout period"))
    if findings:
        return _check("overtime_and_shootout", ("Rules 77, 84"), findings)
    if unassessed_eligibility is not None:
        return _check("overtime_and_shootout", ("Rules 77, 84"), [unassessed_eligibility],
                      status="NOT_ASSESSED")
    return _check("overtime_and_shootout", ("Rules 77, 84"))


def audit_game(game: dict[str, Any], *, ruleset: str | None = None) -> dict[str, Any]:
    """Return check-level statuses; never repairs or normalizes the source game."""
    if not isinstance(game, dict):
        return {"validator": VALIDATOR_VERSION, "simulation_id": None,
                "seed": None, "input_sha256": None, "ruleset": ruleset,
                "structural_valid": False, "full_rule_assessed": False,
                "status_counts": {"FAIL": 1}, "checks": [_check("event_schema",
                    ("Rules 4, 77, 78, 84, 86"),
                    [_issue(None, "game record must be a JSON object")])]}
    checks = [
        _check_event_schema(game),
        _check_order_and_clock(game),
        _check_score_and_terminal(game),
        _check_roster_membership(game),
        _check_simulation_roster_consistency(game),
        _check_personnel(game),
        _check_penalties(game),
        _check_restarts(game),
        _check_restart_locations(game),
        _check_shift_ledger(game),
        _check_line_changes(game),
        _check_goalie_transitions(game),
        _check_overtime_shootout(game),
    ]
    if ruleset not in RULEBOOKS:
        checks.append(_check("ruleset_binding", ("All applicable rules"),
            [_issue(None, "rulebook edition is not explicitly pinned for this audit",
                    status="NOT_ASSESSED", detail={"ruleset": ruleset})],
            status="NOT_ASSESSED"))
    else:
        checks.append(_check("ruleset_binding", ("All applicable rules"),
                             evidence=f"NHL Official Rules {ruleset}; sha256 {RULEBOOKS[ruleset]['sha256']}"))
    checks.append(_check("geometry_and_officiating", ("Rules 2, 15, 31-39, 41-65, 67, 69, 76, 78-83, 85"),
        [_issue(None, "puck/player trajectories and declared official decisions are not present",
                status="NOT_ASSESSED")], status="NOT_ASSESSED"))
    checks.append(_check("game_lineup_eligibility", ("Rules 5, 7, 24, 84"),
        [_issue(None, "record contains a pregame projected roster, not the submitted dressed lineup",
                status="NOT_ASSESSED")], status="NOT_ASSESSED"))

    required = [row for row in checks if row["code"] in STRUCTURAL_CHECKS]
    structural_valid = all(row["status"] in {"PASS", "NOT_APPLICABLE"} for row in required)
    full_rule_assessed = all(row["status"] in {"PASS", "NOT_APPLICABLE"} for row in checks)
    counts = Counter(row["status"] for row in checks)
    return {
        "validator": VALIDATOR_VERSION,
        "simulation_id": game.get("simulation_id"),
        "seed": game.get("seed"),
        "input_sha256": _canonical_hash(game),
        "ruleset": ruleset,
        "structural_valid": structural_valid,
        "full_rule_assessed": full_rule_assessed,
        "status_counts": dict(sorted(counts.items())),
        "checks": checks,
    }


def summarize_audits(audits: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the explicit audit outputs without hiding failed or unassessed rows."""
    check_counts: dict[str, Counter[str]] = defaultdict(Counter)
    failures: list[dict[str, Any]] = []
    for audit in audits:
        for check in audit["checks"]:
            check_counts[check["code"]][check["status"]] += 1
            if check["status"] in {"FAIL", "QUARANTINED"}:
                failures.append({"simulation_id": audit.get("simulation_id"),
                    "seed": audit.get("seed"), "input_sha256": audit.get("input_sha256"),
                    "code": check["code"], "status": check["status"],
                    "findings": check["findings"]})
    return {
        "validator": VALIDATOR_VERSION,
        "games_audited": len(audits),
        "structural_valid_games": sum(bool(row["structural_valid"]) for row in audits),
        "full_rule_assessed_games": sum(bool(row["full_rule_assessed"]) for row in audits),
        "check_counts": {code: dict(sorted(counts.items()))
                         for code, counts in sorted(check_counts.items())},
        "rejected_seeds": failures,
    }
