"""Strict NHL PBP SOG parsing and team-total validation.

Team SOG includes goalie shots. Skater boxscore SOG is therefore a subset of
the team total; any remainder must be reconciled to numeric goalie IDs in PBP.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping


FINAL_STATES = {"OFF", "FINAL"}
SOG_EVENT_TYPES = {"shot-on-goal", "goal"}
SOG_PERIOD_TYPES = {"REG", "OT"}


@dataclass(frozen=True)
class ParsedPbpSog:
    game_id: str
    team_ids: dict[int, tuple[str, str]]
    roster_by_id: dict[str, dict[str, Any]]
    events_by_team_side: dict[tuple[str, str], tuple[dict[str, Any], ...]]
    no_shot_goals: tuple[dict[str, Any], ...]

    def player_counts(self, team: str, side: str) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for event in self.events_by_team_side.get((team, side), ()):
            counts[event["player_id"]] += 1
        return dict(counts)

    def position_by_player(self, team: str, side: str) -> dict[str, str]:
        team_id = next((ident for ident, value in self.team_ids.items() if value == (team, side)), None)
        if team_id is None:
            raise ValueError(f"PBP_TEAM_SIDE_MISSING {self.game_id}/{team}/{side}")
        return {
            player_id: str(row["positionCode"]).upper()
            for player_id, row in self.roster_by_id.items()
            if row["teamId"] == team_id
        }


@dataclass(frozen=True)
class TeamSogResult:
    game_id: str
    team: str
    side: str
    official_team_sog: int
    official_skater_sog: int
    goalie_pbp_sog: int
    reconstructed_team_sog: int
    difference: int
    status: str


def _positive_nhl_id(value: Any, label: str) -> str:
    if isinstance(value, bool):
        raise ValueError(f"INVALID_NUMERIC_NHL_PLAYER_ID {label}: {value!r}")
    result = str(value or "")
    if not result.isdigit() or int(result) <= 0:
        raise ValueError(f"INVALID_NUMERIC_NHL_PLAYER_ID {label}: {value!r}")
    return result


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"INVALID_NONNEGATIVE_INTEGER {label}: {value!r}")
    return value


def parse_pbp_sog_events(
    game_id: str,
    pbp: Mapping[str, Any],
    team_aliases: Mapping[str, str] | None = None,
) -> ParsedPbpSog:
    """Extract regulation/OT shots on goal using NHL numeric player IDs.

    ``shot-on-goal`` events use ``shootingPlayerId``. Goals count as shots on
    goal only when NHL PBP supplies ``shotType`` and use ``scoringPlayerId``.
    Unattributed goals without a shot type are retained separately and are not
    silently counted as SOG. Shootout events are excluded.
    """
    aliases = dict(team_aliases or {})
    if not isinstance(pbp, Mapping):
        raise ValueError(f"PBP_PAYLOAD_NOT_OBJECT {game_id}")
    if str(pbp.get("id", "")) != str(game_id):
        raise ValueError(f"PBP_GAME_IDENTITY_MISMATCH {game_id}/{pbp.get('id')}")
    if pbp.get("gameType") != 2 or pbp.get("gameState") not in FINAL_STATES:
        raise ValueError(f"PBP_NOT_FINAL_REGULAR_SEASON {game_id}")

    team_ids: dict[int, tuple[str, str]] = {}
    for side in ("home", "away"):
        team = pbp.get(f"{side}Team")
        if not isinstance(team, Mapping):
            raise ValueError(f"PBP_TEAM_MISSING {game_id}/{side}")
        team_id = team.get("id")
        if isinstance(team_id, bool) or not isinstance(team_id, int) or team_id <= 0 or team_id in team_ids:
            raise ValueError(f"PBP_INVALID_TEAM_ID {game_id}/{side}")
        abbrev = aliases.get(str(team.get("abbrev", "")), str(team.get("abbrev", "")))
        if not abbrev:
            raise ValueError(f"PBP_TEAM_ABBREVIATION_MISSING {game_id}/{side}")
        team_ids[team_id] = (abbrev, side)

    roster = pbp.get("rosterSpots")
    if not isinstance(roster, list):
        raise ValueError(f"PBP_ROSTER_MISSING {game_id}")
    roster_by_id: dict[str, dict[str, Any]] = {}
    for item in roster:
        if not isinstance(item, Mapping):
            raise ValueError(f"PBP_ROSTER_ROW_INVALID {game_id}")
        player_id = _positive_nhl_id(item.get("playerId"), f"PBP roster {game_id}")
        if player_id in roster_by_id:
            raise ValueError(f"PBP_DUPLICATE_ROSTER_ID {game_id}/{player_id}")
        player_team_id = item.get("teamId")
        if isinstance(player_team_id, bool) or not isinstance(player_team_id, int) or player_team_id not in team_ids:
            raise ValueError(f"PBP_ROSTER_TEAM_ID_INVALID {game_id}/{player_id}")
        if not isinstance(item.get("positionCode"), str) or not item["positionCode"].strip():
            raise ValueError(f"PBP_ROSTER_POSITION_MISSING {game_id}/{player_id}")
        roster_by_id[player_id] = dict(item)

    plays = pbp.get("plays")
    if not isinstance(plays, list):
        raise ValueError(f"PBP_PLAYS_MISSING {game_id}")
    by_team_side: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    no_shot_goals: list[dict[str, Any]] = []
    seen_event_ids: set[int] = set()
    for play in plays:
        if not isinstance(play, Mapping):
            raise ValueError(f"PBP_PLAY_ROW_INVALID {game_id}")
        period = play.get("periodDescriptor") or {}
        if not isinstance(period, Mapping):
            raise ValueError(f"PBP_PERIOD_DESCRIPTOR_INVALID {game_id}/{play.get('eventId')}")
        period_type = period.get("periodType")
        if period_type not in SOG_PERIOD_TYPES:
            continue
        event_type = play.get("typeDescKey")
        if event_type not in SOG_EVENT_TYPES:
            continue
        details = play.get("details") or {}
        if not isinstance(details, Mapping):
            raise ValueError(f"PBP_EVENT_DETAILS_INVALID {game_id}/{play.get('eventId')}")
        owner = details.get("eventOwnerTeamId")
        if isinstance(owner, bool) or not isinstance(owner, int) or owner not in team_ids:
            raise ValueError(f"PBP_SHOT_OWNER_MISSING {game_id}/{play.get('eventId')}")
        if event_type == "goal" and not details.get("shotType"):
            no_shot_goals.append({"play": dict(play), "owner": team_ids[owner]})
            continue

        player_value = details.get("shootingPlayerId") if event_type == "shot-on-goal" else details.get("scoringPlayerId")
        player_id = _positive_nhl_id(player_value, f"PBP event {game_id}/{play.get('eventId')}")
        player = roster_by_id.get(player_id)
        if not player:
            raise ValueError(f"PBP_SHOOTER_NOT_IN_ROSTER {game_id}/{player_id}")
        if player.get("teamId") != owner:
            raise ValueError(f"PBP_SHOOTER_TEAM_MISMATCH {game_id}/{player_id}")
        event_id = _nonnegative_int(play.get("eventId"), f"PBP event id {game_id}")
        if event_id in seen_event_ids:
            raise ValueError(f"PBP_DUPLICATE_EVENT_ID {game_id}/{event_id}")
        seen_event_ids.add(event_id)
        event = {
            "player_id": player_id,
            "event_id": event_id,
            "sort_order": _nonnegative_int(play.get("sortOrder"), f"PBP sort order {game_id}"),
            "event_type": event_type,
            "period": _nonnegative_int(period.get("number"), f"PBP period {game_id}"),
            "period_type": period_type,
            "time": str(play.get("timeInPeriod", "")),
            "details": dict(details),
        }
        by_team_side[team_ids[owner]].append(event)

    for key, events in by_team_side.items():
        events.sort(key=lambda item: (item["sort_order"], item["event_id"]))
        side = key[1]
        team_summary = pbp[f"{side}Team"]
        published_sog = _nonnegative_int(team_summary.get("sog"), f"PBP team SOG {game_id}/{side}")
        if len(events) != published_sog:
            raise ValueError(f"PBP_TEAM_SOG_EVENT_MISMATCH {game_id}/{side}: events={len(events)} summary={published_sog}")
    for side in ("home", "away"):
        team = pbp[f"{side}Team"]
        abbrev = aliases.get(str(team.get("abbrev", "")), str(team.get("abbrev", "")))
        published_sog = _nonnegative_int(team.get("sog"), f"PBP team SOG {game_id}/{side}")
        event_total = len(by_team_side.get((abbrev, side), ()))
        if event_total != published_sog:
            raise ValueError(f"PBP_TEAM_SOG_EVENT_MISMATCH {game_id}/{side}: events={event_total} summary={published_sog}")

    return ParsedPbpSog(
        game_id=str(game_id),
        team_ids=team_ids,
        roster_by_id=roster_by_id,
        events_by_team_side={key: tuple(value) for key, value in by_team_side.items()},
        no_shot_goals=tuple(no_shot_goals),
    )


def validate_team_sog(
    game_id: str,
    team: str,
    side: str,
    official_team_sog: int,
    official_skater_sog_by_player: Mapping[str, int],
    pbp_sog: ParsedPbpSog,
) -> TeamSogResult:
    """Compare team SOG with official skater SOG plus goalie PBP shots.

    A missing goalie-event source is not representable as zero: callers must
    supply a parsed final PBP payload. Every skater value is reconciled by ID
    to PBP, and any additional PBP shooter must be roster-classified as goalie.
    """
    if not isinstance(pbp_sog, ParsedPbpSog):
        raise ValueError(f"PBP_SOG_EVIDENCE_REQUIRED {game_id}/{team}/{side}")
    if pbp_sog.game_id != str(game_id):
        raise ValueError(f"PBP_GAME_IDENTITY_MISMATCH {game_id}/{pbp_sog.game_id}")
    if side not in {"home", "away"}:
        raise ValueError(f"INVALID_TEAM_SIDE {game_id}/{side}")
    official_total = _nonnegative_int(official_team_sog, f"official team SOG {game_id}/{side}")
    skaters: dict[str, int] = {}
    for player_id_raw, value in official_skater_sog_by_player.items():
        player_id = _positive_nhl_id(player_id_raw, f"official skater {game_id}/{team}")
        if player_id in skaters:
            raise ValueError(f"DUPLICATE_OFFICIAL_SKATER_ID {game_id}/{player_id}")
        skaters[player_id] = _nonnegative_int(value, f"official skater SOG {game_id}/{player_id}")

    positions = pbp_sog.position_by_player(team, side)
    pbp_counts = pbp_sog.player_counts(team, side)
    for player_id, official_sog in skaters.items():
        position = positions.get(player_id)
        if position is None:
            raise ValueError(f"OFFICIAL_SKATER_MISSING_FROM_PBP_ROSTER {game_id}/{player_id}")
        if position == "G":
            raise ValueError(f"GOALIE_IN_OFFICIAL_SKATER_ROWS {game_id}/{player_id}")
        event_count = pbp_counts.get(player_id, 0)
        if event_count != official_sog:
            raise ValueError(f"OFFICIAL_SKATER_SOG_PBP_MISMATCH {game_id}/{player_id}: official={official_sog} PBP={event_count}")

    goalie_counts: dict[str, int] = {}
    for player_id, event_count in pbp_counts.items():
        if player_id in skaters:
            continue
        position = positions.get(player_id)
        if position != "G":
            raise ValueError(f"UNMATCHED_NON_GOALIE_PBP_SHOOTER {game_id}/{team}/{player_id}/{position}")
        goalie_counts[player_id] = event_count

    skater_total = sum(skaters.values())
    goalie_total = sum(goalie_counts.values())
    reconstructed = skater_total + goalie_total
    return TeamSogResult(
        game_id=str(game_id),
        team=team,
        side=side,
        official_team_sog=official_total,
        official_skater_sog=skater_total,
        goalie_pbp_sog=goalie_total,
        reconstructed_team_sog=reconstructed,
        difference=reconstructed - official_total,
        status="PASS" if reconstructed == official_total else "TEAM_SOG_MISMATCH",
    )
