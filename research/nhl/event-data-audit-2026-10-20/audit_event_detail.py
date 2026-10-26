#!/usr/bin/env python3
"""Strict event-field, event-time shift, and approved-label audit.

Reads only the existing hash-pinned 300-game sample and approved research-label
reader. It does not fetch, fit, mutate frozen inputs, or write production data.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS = HERE.parent / "official-outcome-backfill-2026-10-20"
sys.path.insert(0, str(LABELS))

import audit_event_coverage as base_audit  # noqa: E402
from nhl_research_data import iter_nhl_research_labels  # noqa: E402

FRAME = LABELS / "canonical_frame.csv"
SAMPLE = HERE / "sample_games.csv"
MANIFEST = HERE / "event_evidence_manifest.csv"
LABEL_SUMMARY = LABELS / "research_label_summary.json"
OFFICIAL_SIDES = LABELS / "official_game_sides.csv"
OFFICIAL_SKATERS = LABELS / "official_skater_outcomes.csv"
OFFICIAL_GOALIES = LABELS / "official_goalie_outcomes.csv"
LABEL_PATH = Path(os.environ.get(
    "NHL_RESEARCH_LABEL_PATH",
    "/root/lp-data/nhl-official-outcome-quality-adjudication-2026-10-20/research_label_quality.csv",
))
EXPECTED = {
    "canonical_frame_sha256": "f417a1272b2bb4adff5757dae398dd1000dd2284f43b6ccb7dd28eaae99edf2b",
    "sample_games_sha256": "5ea249cf070eea5bfc0552a55959080207ed67c2a0b971fc9f2fe6d90a4b537f",
    "event_manifest_sha256": "559b67ce1ccb5a7796ee9d7db7bde9319339469339a3ae5df16f0ac00d99ee07",
    "research_label_quality_sha256": "cc9be34586dc16701f162bbc04cf256a9fd0c4c3c823625ecb02ff24eed1f60c",
    "research_label_summary_sha256": "89d88064b2b01582ca2b21fe3e5d6324875042a74cd206833dd039283e282f74",
    "official_game_sides_sha256": "782c9f44a113c2857947a6a7f178ddf3d6e26a59544bf3973685135d809a5f33",
    "official_skater_outcomes_sha256": "b1249d74e0f38c599e7a88a67f438ceedb187e35a6ba6b66908b77e04208094d",
    "official_goalie_outcomes_sha256": "7e5d0cca6783839dca938ba04e15ee2b686873170e319f816060271555a2ca66",
}
RESEARCHABLE = {"VERIFIED", "ADJUDICATED"}
PERIOD_TYPES = {"REG", "OT", "SO"}
SHOT_TYPES = base_audit.SHOT_TYPES
SOG_TYPES = base_audit.SOG_TYPES


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pinned_hash(label: str, path: Path) -> str:
    actual, expected = sha256_file(path), EXPECTED[label]
    if actual != expected:
        raise ValueError(f"SOURCE_HASH_MISMATCH {label}: expected={expected} actual={actual} path={path}")
    return actual


def clock_seconds(value) -> int | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    try:
        minutes, seconds = (int(part) for part in value.split(":", 1))
    except ValueError:
        return None
    if minutes < 0 or not 0 <= seconds < 60:
        return None
    return minutes * 60 + seconds


def period_parts(play: dict) -> tuple[int | None, str | None]:
    desc = play.get("periodDescriptor") or {}
    try:
        number = int(desc.get("number"))
    except (TypeError, ValueError):
        number = None
    kind = desc.get("periodType")
    return (number, kind) if number and number > 0 and kind in PERIOD_TYPES else (None, kind)


def numeric_id(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def shot_player_id(play: dict) -> int | None:
    """Return the credited SOG player; goals use the NHL goal scorer ID."""
    details = play.get("details") or {}
    player = numeric_id(details.get("shootingPlayerId"))
    if player is None and play.get("typeDescKey") == "goal":
        player = numeric_id(details.get("scoringPlayerId"))
    return player


def field_counts(plays: list[dict]) -> dict[str, int]:
    shots = [p for p in plays if p.get("typeDescKey") in SHOT_TYPES]
    names = ("shot_events", "shooter_id_direct", "shooter_id_goal_scorer_only",
             "shot_player_id_attributed", "location_xy",
             "shot_type", "period", "game_clock", "period_and_clock", "situation_code",
             "blocked_shot_events", "blocked_shot_type", "unblocked_shot_events",
             "unblocked_shot_type", "on_target_events", "on_target_goalie_id", "on_target_shooter_id")
    c = Counter(dict.fromkeys(names, 0))
    c["shot_events"] = len(shots)
    for play in shots:
        d = play.get("details") or {}
        c["shooter_id_direct"] += numeric_id(d.get("shootingPlayerId")) is not None
        c["shooter_id_goal_scorer_only"] += (
            numeric_id(d.get("shootingPlayerId")) is None
            and play.get("typeDescKey") == "goal"
            and numeric_id(d.get("scoringPlayerId")) is not None
        )
        c["shot_player_id_attributed"] += shot_player_id(play) is not None
        x, y = d.get("xCoord"), d.get("yCoord")
        c["location_xy"] += (
            isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
            and isinstance(y, (int, float)) and not isinstance(y, bool) and math.isfinite(y)
        )
        c["shot_type"] += isinstance(d.get("shotType"), str) and bool(d.get("shotType"))
        c["period"] += period_parts(play)[0] is not None
        c["game_clock"] += clock_seconds(play.get("timeInPeriod")) is not None
        c["period_and_clock"] += (
            period_parts(play)[0] is not None and clock_seconds(play.get("timeInPeriod")) is not None
        )
        c["situation_code"] += base_audit.strength_class(play.get("situationCode")) is not None
        if play.get("typeDescKey") == "blocked-shot":
            c["blocked_shot_events"] += 1
            c["blocked_shot_type"] += isinstance(d.get("shotType"), str) and bool(d.get("shotType"))
        else:
            c["unblocked_shot_events"] += 1
            c["unblocked_shot_type"] += isinstance(d.get("shotType"), str) and bool(d.get("shotType"))
    on_target = [p for p in shots if p.get("typeDescKey") in SOG_TYPES]
    c["on_target_events"] = len(on_target)
    c["on_target_goalie_id"] = sum(numeric_id((p.get("details") or {}).get("goalieInNetId")) is not None
                                    for p in on_target)
    c["on_target_shooter_id"] = sum(
        shot_player_id(p) is not None
        for p in on_target
    )
    return dict(c)


def label_is_eligible(label) -> bool:
    return (label.quality_status in RESEARCHABLE and label.eligible_grading
            and label.accepted_value is not None)


def load_approved_labels(sample_ids: set[str]) -> tuple[dict, Counter]:
    labels, statuses = {}, Counter()
    for label in iter_nhl_research_labels(purpose="audit", path=LABEL_PATH, summary_path=LABEL_SUMMARY):
        if label.game_id not in sample_ids:
            continue
        statuses[(label.statistic, label.quality_status)] += 1
        key = (label.game_id, label.player_id, label.statistic)
        if key in labels:
            raise ValueError(f"DUPLICATE_APPROVED_LABEL {key}")
        labels[key] = label
    return labels, statuses


def verify_event_manifest(sample_ids: set[str]) -> dict:
    with (HERE / "event_evidence_manifest.csv").open(newline="", encoding="utf-8") as fh:
        manifest = list(csv.DictReader(fh))
    expected = {(gid, kind) for gid in sample_ids for kind in ("pbp", "shifts")}
    rows = {}
    for row in manifest:
        key = (row["game_id"], row["kind"])
        if key in rows:
            raise ValueError(f"DUPLICATE_EVENT_MANIFEST_ROW {key}")
        rows[key] = row
    if set(rows) != expected:
        raise ValueError(f"EVENT_MANIFEST_COVERAGE_MISMATCH expected={len(expected)} actual={len(rows)}")
    verified = 0
    compressed_bytes = 0
    uncompressed_bytes = 0
    for gid, kind in sorted(expected):
        row = rows[(gid, kind)]
        if row["http_status"] != "200" or row["note"]:
            raise ValueError(f"EVENT_SOURCE_NOT_COMPLETE {gid}/{kind}: {row}")
        path = base_audit.CACHE / kind / f"{gid}.json.gz"
        compressed = path.read_bytes()
        if len(compressed) != int(row["bytes_gz"]) or sha256_bytes(compressed) != row["sha256_gz"]:
            raise ValueError(f"EVENT_COMPRESSED_HASH_MISMATCH {gid}/{kind}")
        body = gzip.decompress(compressed)
        if len(body) != int(row["bytes_raw"]) or sha256_bytes(body) != row["sha256_raw"]:
            raise ValueError(f"EVENT_RAW_HASH_MISMATCH {gid}/{kind}")
        payload = json.loads(body)
        if kind == "pbp":
            if str(payload.get("id")) != gid or payload.get("gameType") != 2:
                raise ValueError(f"PBP_GAME_ID_OR_TYPE_MISMATCH {gid}")
            count = len(payload.get("plays") or [])
        else:
            shift_rows = payload.get("data") or []
            if not shift_rows or {str(r.get("gameId")) for r in shift_rows} != {gid}:
                raise ValueError(f"SHIFT_GAME_ID_MISMATCH {gid}")
            count = len(shift_rows)
        if count != int(row["rows"]):
            raise ValueError(f"EVENT_ROW_COUNT_MISMATCH {gid}/{kind}: {count}!={row['rows']}")
        verified += 1
        compressed_bytes += len(compressed)
        uncompressed_bytes += len(body)
    return {"expected_body_count": len(expected), "verified_body_count": verified,
            "compressed_bytes": compressed_bytes, "uncompressed_bytes": uncompressed_bytes}


def load_official_goalies() -> dict[str, set[int]]:
    result: dict[str, set[int]] = defaultdict(set)
    path = OFFICIAL_GOALIES
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("appeared") == "1":
                pid = numeric_id(row.get("player_id"))
                if pid is not None:
                    result[row["game_id"]].add(pid)
    return result


def shift_intervals(payload: dict | None) -> list[tuple[int, int, int, int, str]]:
    result = []
    for row in (payload or {}).get("data") or []:
        try:
            if int(row.get("typeCode") or 0) != 517:
                continue
            pid, period, team = int(row["playerId"]), int(row["period"]), str(int(row["teamId"]))
            start, end = clock_seconds(row["startTime"]), clock_seconds(row["endTime"])
        except (KeyError, TypeError, ValueError):
            continue
        if pid > 0 and period > 0 and start is not None and end is not None and end > start:
            result.append((period, start, end, pid, team))
    return result


def player_shift_status(intervals, period: int, second: int, player_id: int, team_id: int | None) -> str:
    relevant = [r for r in intervals if r[0] == period and r[3] == player_id
                and (team_id is None or r[4] == str(team_id))]
    if any(start <= second < end for _p, start, end, _pid, _team in relevant):
        return "ON_ICE"
    if any(min(abs(second - start), abs(second - end)) <= 1
           for _p, start, end, _pid, _team in relevant):
        return "BOUNDARY_AMBIGUOUS"
    return "OFF_ICE"


def situation_shift_status(intervals, period: int, second: int, code: str,
                           home_id: int, away_id: int, goalie_ids: set[int]) -> str:
    if not isinstance(code, str) or len(code) != 4 or not code.isdigit():
        return "NO_CODE"
    ag, ask, hsk, hg = (int(ch) for ch in code)
    active = [r for r in intervals if r[0] == period and r[1] <= second < r[2]]
    by_team: dict[int, set[int]] = {home_id: set(), away_id: set()}
    for _p, _start, _end, pid, team in active:
        team_id = int(team)
        if team_id in by_team:
            by_team[team_id].add(pid)
    away_players, home_players = by_team[away_id], by_team[home_id]
    away_goalies = sum(pid in goalie_ids for pid in away_players)
    home_goalies = sum(pid in goalie_ids for pid in home_players)
    observed = (away_goalies, len(away_players) - away_goalies,
                len(home_players) - home_goalies, home_goalies)
    if observed == (ag, ask, hsk, hg):
        return "MATCH"
    near_boundary = any(
        p == period and min(abs(second - start), abs(second - end)) <= 1
        for p, start, end, _pid, _team in intervals
    )
    return "BOUNDARY_AMBIGUOUS" if near_boundary else "MISMATCH"


def expected_goalie_presence(play: dict, home_id: int, away_id: int) -> bool | None:
    details = play.get("details") or {}
    owner = numeric_id(details.get("eventOwnerTeamId"))
    code = play.get("situationCode")
    if (not isinstance(code, str) or len(code) != 4 or not code.isdigit()
            or owner not in {home_id, away_id}):
        return None
    goalie_digit = code[0] if owner == home_id else code[3]
    return int(goalie_digit) == 1


def eligible_stat_labels(labels: dict, gid: str, statistic: str):
    return [label for (game_id, _player, stat), label in labels.items()
            if game_id == gid and stat == statistic and label_is_eligible(label)]


def audit_game(sample_row: dict, labels: dict, official_goalies: dict,
               base_labels: tuple[dict, dict, dict]) -> tuple[dict, list[dict], list[dict], list[dict]]:
    gid = sample_row["game_id"]
    pbp = base_audit.load_payload(gid, "pbp")
    shifts_payload = base_audit.load_payload(gid, "shifts")
    plays = (pbp or {}).get("plays") or []
    intervals = shift_intervals(shifts_payload)
    field = field_counts(plays)
    home_id = numeric_id(((pbp or {}).get("homeTeam") or {}).get("id")) or -1
    away_id = numeric_id(((pbp or {}).get("awayTeam") or {}).get("id")) or -1
    known_goalies = set(official_goalies.get(gid, set()))
    known_goalies.update(
        pid for row in ((pbp or {}).get("rosterSpots") or [])
        if row.get("positionCode") == "G" and (pid := numeric_id(row.get("playerId"))) is not None
    )
    known_goalies.update(pid for _p, _s, _e, pid, _team in intervals
                         if pid in official_goalies.get(gid, set()))

    # PBP-to-player SOG attribution uses numeric shootingPlayerId, or the
    # credited scorer for a goal event where NHL awards the scorer the SOG.
    sog_by_player: Counter[int] = Counter()
    goalie_counts: dict[int, Counter] = defaultdict(Counter)
    shooter_alignment, goalie_alignment, situation_alignment = Counter(), Counter(), Counter()
    on_target_without_goalie = 0
    missing_goalie_expected_empty_net = 0
    missing_goalie_unexplained = 0
    shooter_idless_sog = 0
    shooter_events_with_clock = 0
    on_target_events = 0
    goalie_events_with_clock = 0
    strength_counts = Counter()
    event_exceptions = []
    for play in plays:
        kind = play.get("typeDescKey")
        details = play.get("details") or {}
        period, period_type = period_parts(play)
        second = clock_seconds(play.get("timeInPeriod"))
        shooter = shot_player_id(play)
        owner = numeric_id(details.get("eventOwnerTeamId"))
        state = base_audit.strength_class(play.get("situationCode"))
        if state is not None and period_type != "SO":
            strength_counts[state] += 1
        if kind in SOG_TYPES and period_type != "SO":
            on_target_events += 1
            if shooter is None:
                shooter_idless_sog += 1
            else:
                sog_by_player[shooter] += 1
            goalie = numeric_id(details.get("goalieInNetId"))
            if goalie is None:
                on_target_without_goalie += 1
                expected_present = expected_goalie_presence(play, home_id, away_id)
                if expected_present is False:
                    missing_goalie_expected_empty_net += 1
                else:
                    missing_goalie_unexplained += 1
            elif kind == "shot-on-goal":
                goalie_counts[goalie]["SAVES"] += 1
                goalie_counts[goalie]["SHOTS_AGAINST"] += 1
            elif kind == "goal":
                goalie_counts[goalie]["GOALS_AGAINST"] += 1
                goalie_counts[goalie]["SHOTS_AGAINST"] += 1

        if kind in SHOT_TYPES:
            expected_present = expected_goalie_presence(play, home_id, away_id)
            goalie_id = numeric_id(details.get("goalieInNetId"))
            missing = []
            if shot_player_id(play) is None:
                missing.append("shot_player_id_attributed")
            x, y = details.get("xCoord"), details.get("yCoord")
            if not (isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
                    and isinstance(y, (int, float)) and not isinstance(y, bool) and math.isfinite(y)):
                missing.append("location_xy")
            if not isinstance(details.get("shotType"), str) or not details.get("shotType"):
                missing.append("shot_type")
            if period is None:
                missing.append("period")
            if second is None:
                missing.append("game_clock")
            if base_audit.strength_class(play.get("situationCode")) is None:
                missing.append("situation_code")
            goalie_status = "PRESENT" if goalie_id is not None else (
                "EXPECTED_EMPTY_NET" if expected_present is False else
                "UNEXPLAINED" if expected_present is True else "UNCLASSIFIED"
            )
            if missing or (kind in SOG_TYPES and period_type != "SO" and goalie_id is None):
                event_exceptions.append({
                    "game_id": gid, "season": int(sample_row["season"]),
                    "source_event_id": play.get("eventId", ""), "event_type": kind or "",
                    "period_number": period if period is not None else "",
                    "period_type": period_type or "", "time_in_period": play.get("timeInPeriod", ""),
                    "event_owner_team_id": owner or "",
                    "shooting_player_id": numeric_id(details.get("shootingPlayerId")) or "",
                    "scoring_player_id": numeric_id(details.get("scoringPlayerId")) or "",
                    "credited_sog_player_id": shot_player_id(play) or "",
                    "goalie_in_net_id": goalie_id or "",
                    "goalie_id_status": goalie_status if kind in SOG_TYPES and period_type != "SO" else "NOT_APPLICABLE",
                    "x_coord": x if isinstance(x, (int, float)) and not isinstance(x, bool) else "",
                    "y_coord": y if isinstance(y, (int, float)) and not isinstance(y, bool) else "",
                    "shot_type": details.get("shotType", ""),
                    "situation_code": play.get("situationCode", ""),
                    "direct_shooter_id_missing": int(numeric_id(details.get("shootingPlayerId")) is None),
                    "missing_fields": ";".join(missing),
                })

        if kind not in SHOT_TYPES or period is None or second is None or period_type == "SO":
            continue
        if shooter is not None and owner is not None:
            shooter_events_with_clock += 1
            shooter_alignment[player_shift_status(intervals, period, second, shooter, owner)] += 1
        if kind in SOG_TYPES:
            goalie = numeric_id(details.get("goalieInNetId"))
            if goalie is not None:
                goalie_events_with_clock += 1
                goalie_alignment[player_shift_status(intervals, period, second, goalie, None)] += 1
        code = play.get("situationCode")
        if isinstance(code, str) and base_audit.strength_class(code) is not None and home_id > 0 and away_id > 0:
            situation_alignment[situation_shift_status(
                intervals, period, second, code, home_id, away_id, known_goalies
            )] += 1

    sog_rows, goalie_rows = [], []
    for (label_gid, player, statistic), label in sorted(labels.items()):
        if label_gid != gid or statistic != "SOG":
            continue
        eligible = label_is_eligible(label)
        observed = sog_by_player.get(int(player), 0)
        match = eligible and observed == label.accepted_value
        sog_rows.append({
            "game_id": gid, "season": label.season, "game_date": label.game_date.isoformat(),
            "team": label.team, "player_id": player, "statistic": statistic,
            "official_value": label.official_value, "accepted_value": label.accepted_value,
            "quality_status": label.quality_status, "eligible_grading": label.eligible_grading,
            "pbp_shooter_id_sog": observed if eligible else "",
            "comparison": "MATCH" if match else "MISMATCH" if eligible else label.quality_status,
        })

    for (label_gid, player, statistic), label in sorted(labels.items()):
        if label_gid != gid or statistic not in {"SAVES", "SHOTS_AGAINST", "GOALS_AGAINST"}:
            continue
        eligible = label_is_eligible(label)
        pid = int(player)
        if eligible and pid not in official_goalies.get(gid, set()):
            raise ValueError(f"ELIGIBLE_ZERO_TOI_OR_NONAPPEARING_GOALIE_LABEL {gid}/{pid}/{statistic}")
        observed = goalie_counts.get(pid, Counter()).get(statistic, 0)
        match = eligible and observed == label.accepted_value
        goalie_rows.append({
            "game_id": gid, "season": label.season, "game_date": label.game_date.isoformat(),
            "team": label.team, "player_id": player, "statistic": statistic,
            "official_value": label.official_value, "accepted_value": label.accepted_value,
            "quality_status": label.quality_status, "eligible_grading": label.eligible_grading,
            "pbp_goalie_events": observed if eligible else "",
            "comparison": "MATCH" if match else "MISMATCH" if eligible else label.quality_status,
        })

    base_metric, base_issues = base_audit.audit_game(gid, sample_row, *base_labels)
    issue_counts = Counter(issue["issue"] for issue in base_issues
                           if issue["issue"] != "SHOOTOUT_GOAL_BONUS_APPLIED")
    sog_mismatch = sum(row["comparison"] == "MISMATCH" for row in sog_rows)
    goalie_mismatch = sum(row["comparison"] == "MISMATCH" for row in goalie_rows)
    for statistic, rows in (("SOG_PLAYER_LABEL_MISMATCH", sog_rows),
                            ("GOALIE_LABEL_MISMATCH", goalie_rows)):
        if any(row["comparison"] == "MISMATCH" for row in rows):
            issue_counts[statistic] += 1
    if shooter_alignment["OFF_ICE"]:
        issue_counts["SHOOTER_OFF_SHIFT_AT_EVENT"] += 1
    if goalie_alignment["OFF_ICE"]:
        issue_counts["GOALIE_OFF_SHIFT_AT_EVENT"] += 1
    if situation_alignment["MISMATCH"]:
        issue_counts["SITUATION_SHIFT_COUNT_MISMATCH"] += 1

    game_goalies = official_goalies.get(gid, set())
    goalies_with_shift = {pid for _p, _start, _end, pid, _team in intervals if pid in known_goalies}
    goalie_teams_with_substitution = 0
    for team in {team for _p, _s, _e, _pid, team in intervals}:
        if len({pid for _p, _s, _e, pid, t in intervals if t == team and pid in known_goalies}) > 1:
            goalie_teams_with_substitution += 1

    all_issues = sorted(issue_counts)
    actual_outcome_issue_types = {"SOG_FEED_VS_OFFICIAL", "GOALS_FEED_VS_OFFICIAL",
                                  "SOG_PLAYER_LABEL_MISMATCH", "GOALIE_LABEL_MISMATCH"}
    shift_issue_types = {"TOI_SHIFT_VS_OFFICIAL", "APPEARED_WITHOUT_SHIFTS", "DUPLICATE_SHIFT_CHART",
                         "GOALIE_SHIFT_TOI", "SHIFT_OVERLAP", "SHOOTER_OFF_SHIFT_AT_EVENT",
                         "GOALIE_OFF_SHIFT_AT_EVENT", "SITUATION_SHIFT_COUNT_MISMATCH"}
    metric = {
        "game_id": gid, "season": int(sample_row["season"]), "game_date": sample_row["game_date"],
        "pbp_present": int(pbp is not None), "shift_present": int(shifts_payload is not None),
        **field,
        "shooter_id_usable_sog": field.get("shooter_id_direct", 0),
        "shot_events_without_direct_shooter": field.get("shot_events", 0) - field.get("shooter_id_direct", 0),
        "on_target_events_regulation_ot": on_target_events,
        "on_target_without_goalie_id": on_target_without_goalie,
        "on_target_without_goalie_expected_empty_net": missing_goalie_expected_empty_net,
        "on_target_without_goalie_unexplained": missing_goalie_unexplained,
        "on_target_without_shooter_id": shooter_idless_sog,
        "strength_state_counts_json": json.dumps(dict(sorted(strength_counts.items())), separators=(",", ":")),
        "shooter_events_with_clock_and_team": shooter_events_with_clock,
        "shooter_shift_on_ice": shooter_alignment["ON_ICE"],
        "shooter_shift_boundary_ambiguous": shooter_alignment["BOUNDARY_AMBIGUOUS"],
        "shooter_shift_off_ice": shooter_alignment["OFF_ICE"],
        "goalie_events_with_clock": goalie_events_with_clock,
        "goalie_shift_on_ice": goalie_alignment["ON_ICE"],
        "goalie_shift_boundary_ambiguous": goalie_alignment["BOUNDARY_AMBIGUOUS"],
        "goalie_shift_off_ice": goalie_alignment["OFF_ICE"],
        "situation_shift_compared": sum(situation_alignment[k] for k in ("MATCH", "MISMATCH")),
        "situation_shift_matches": situation_alignment["MATCH"],
        "situation_shift_mismatches": situation_alignment["MISMATCH"],
        "situation_shift_boundary_ambiguous": situation_alignment["BOUNDARY_AMBIGUOUS"],
        "played_goalies": len(game_goalies),
        "played_goalies_with_shift_rows": len(game_goalies & goalies_with_shift),
        "goalie_substitution_teams": goalie_teams_with_substitution,
        "approved_sog_labels": sum(row["comparison"] in {"MATCH", "MISMATCH"} for row in sog_rows),
        "approved_sog_mismatches": sog_mismatch,
        "approved_saves_labels": sum(row["statistic"] == "SAVES" and row["comparison"] in {"MATCH", "MISMATCH"} for row in goalie_rows),
        "approved_saves_mismatches": sum(row["statistic"] == "SAVES" and row["comparison"] == "MISMATCH" for row in goalie_rows),
        "approved_sa_labels": sum(row["statistic"] == "SHOTS_AGAINST" and row["comparison"] in {"MATCH", "MISMATCH"} for row in goalie_rows),
        "approved_sa_mismatches": sum(row["statistic"] == "SHOTS_AGAINST" and row["comparison"] == "MISMATCH" for row in goalie_rows),
        "approved_ga_labels": sum(row["statistic"] == "GOALS_AGAINST" and row["comparison"] in {"MATCH", "MISMATCH"} for row in goalie_rows),
        "approved_ga_mismatches": sum(row["statistic"] == "GOALS_AGAINST" and row["comparison"] == "MISMATCH" for row in goalie_rows),
        "base_goal_games_match": int(
            base_metric.get("goals_home_pbp_adj") == base_metric.get("goals_home_official")
            and base_metric.get("goals_away_pbp_adj") == base_metric.get("goals_away_official")
        ),
        "base_sog_games_match": int(
            base_metric.get("sog_home_pbp_reg") == base_metric.get("sog_home_official")
            and base_metric.get("sog_away_pbp_reg") == base_metric.get("sog_away_official")
        ),
        "base_contradiction_types": ";".join(sorted(issue_counts)),
        "base_contradiction_count": sum(issue_counts.values()),
        "games_with_outcome_conflict": int(
            any(name in issue_counts for name in actual_outcome_issue_types)
        ),
        "games_with_shift_conflict": int(any(name in issue_counts for name in shift_issue_types)),
        "unusable_for_player_sog_events": int(
            pbp is None or not field.get("shot_events") or shooter_idless_sog > 0
            or sog_mismatch > 0 or issue_counts.get("SOG_FEED_VS_OFFICIAL", 0) > 0
        ),
        "unusable_for_goalie_event_targets": int(
            pbp is None or missing_goalie_unexplained > 0 or goalie_mismatch > 0
        ),
        "unusable_for_shift_features": int(
            shifts_payload is None or any(name in issue_counts for name in shift_issue_types)
        ),
    }
    return metric, sog_rows, goalie_rows, event_exceptions


def csv_bytes(rows: list[dict]) -> bytes:
    if not rows:
        raise ValueError("NO_OUTPUT_ROWS")
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")


def pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 6) if d else None


def build_outputs() -> dict[str, bytes]:
    input_hashes = {
        "canonical_frame_sha256": pinned_hash("canonical_frame_sha256", FRAME),
        "sample_games_sha256": pinned_hash("sample_games_sha256", SAMPLE),
        "event_manifest_sha256": pinned_hash("event_manifest_sha256", MANIFEST),
        "research_label_quality_sha256": pinned_hash("research_label_quality_sha256", LABEL_PATH),
        "research_label_summary_sha256": pinned_hash("research_label_summary_sha256", LABEL_SUMMARY),
        "official_game_sides_sha256": pinned_hash("official_game_sides_sha256", OFFICIAL_SIDES),
        "official_skater_outcomes_sha256": pinned_hash("official_skater_outcomes_sha256", OFFICIAL_SKATERS),
        "official_goalie_outcomes_sha256": pinned_hash("official_goalie_outcomes_sha256", OFFICIAL_GOALIES),
    }
    with FRAME.open(newline="", encoding="utf-8") as fh:
        frame = list(csv.DictReader(fh))
    if len(frame) != 4876:
        raise ValueError(f"CANONICAL_FRAME_COUNT_MISMATCH {len(frame)}")
    with SAMPLE.open(newline="", encoding="utf-8") as fh:
        sample = list(csv.DictReader(fh))
    ids = {row["game_id"] for row in sample}
    if len(sample) != 300 or len(ids) != 300:
        raise ValueError(f"SAMPLE_GAME_COUNT_OR_DUPLICATE_MISMATCH {len(sample)}")
    frame_by_id = {row["game_id"]: row for row in frame}
    if any(gid not in frame_by_id or frame_by_id[gid]["season"] != row["season"] for row in sample for gid in (row["game_id"],)):
        raise ValueError("SAMPLE_NOT_SUBSET_OF_PINNED_FRAME")
    season_counts = Counter(int(row["season"]) for row in sample)
    expected_seasons = {2018: 60, 2019: 60, 2020: 60, 2021: 60, 2022: 60}
    if dict(season_counts) != expected_seasons:
        raise ValueError(f"SAMPLE_SEASON_STRATA_MISMATCH {dict(season_counts)}")

    body_verification = verify_event_manifest(ids)
    labels, all_label_status_counts = load_approved_labels(ids)
    labels_by_game: dict[str, dict] = defaultdict(dict)
    for key, label in labels.items():
        labels_by_game[label.game_id][key] = label
    official_goalies = load_official_goalies()
    base_labels = base_audit.load_labels()
    games, sog_rows, goalie_rows = [], [], []
    event_exceptions = []
    for row in sample:
        metric, skater_rows, goalie_target_rows, exceptions = audit_game(
            row, labels_by_game.get(row["game_id"], {}), official_goalies, base_labels
        )
        games.append(metric)
        sog_rows.extend(skater_rows)
        goalie_rows.extend(goalie_target_rows)
        event_exceptions.extend(exceptions)

    season_rows = []
    field_names = ("shooter_id_direct", "shooter_id_goal_scorer_only", "shot_player_id_attributed",
                   "location_xy", "shot_type", "period", "game_clock",
                   "period_and_clock", "situation_code")
    for season in sorted(season_counts):
        gs = [row for row in games if row["season"] == season]
        shot_total = sum(row.get("shot_events", 0) for row in gs)
        out = {"season": season, "games_sampled": len(gs),
               "games_missing_pbp": sum(not row["pbp_present"] for row in gs),
               "games_missing_shift_chart": sum(not row["shift_present"] for row in gs),
               "shot_events": shot_total}
        required_event_fields = ("shot_player_id_attributed", "location_xy", "shot_type",
                                 "period_and_clock", "situation_code")
        out["games_missing_any_tracked_shot_field"] = sum(
            any(game.get(field, 0) < game.get("shot_events", 0) for field in required_event_fields)
            for game in gs
        )
        for name in field_names:
            count = sum(row.get(name, 0) for row in gs)
            out[f"{name}_present"] = count
            out[f"{name}_missing"] = shot_total - count
            out[f"{name}_pct"] = pct(count, shot_total)
            out[f"games_missing_{name}"] = sum(row.get("shot_events", 0) > row.get(name, 0) for row in gs)
        for name in ("unblocked_shot_events", "unblocked_shot_type", "blocked_shot_events", "blocked_shot_type",
                     "on_target_events", "on_target_goalie_id", "on_target_shooter_id",
                     "on_target_without_goalie_id", "on_target_without_goalie_expected_empty_net",
                     "on_target_without_goalie_unexplained", "on_target_without_shooter_id",
                     "shooter_shift_on_ice", "shooter_shift_boundary_ambiguous", "shooter_shift_off_ice",
                     "goalie_shift_on_ice", "goalie_shift_boundary_ambiguous", "goalie_shift_off_ice",
                     "situation_shift_compared", "situation_shift_matches", "situation_shift_mismatches",
                     "situation_shift_boundary_ambiguous", "played_goalies", "played_goalies_with_shift_rows",
                     "goalie_substitution_teams", "approved_sog_labels", "approved_sog_mismatches",
                     "approved_saves_labels", "approved_saves_mismatches", "approved_sa_labels",
                     "approved_sa_mismatches", "approved_ga_labels", "approved_ga_mismatches",
                     "base_goal_games_match", "base_sog_games_match", "base_contradiction_count",
                     "games_with_outcome_conflict", "games_with_shift_conflict",
                     "unusable_for_player_sog_events", "unusable_for_goalie_event_targets",
                     "unusable_for_shift_features"):
            out[name] = sum(row.get(name, 0) for row in gs)
        out["games_with_any_contradiction"] = sum(row["base_contradiction_count"] > 0 for row in gs)
        out["games_with_goalie_substitution"] = sum(row["goalie_substitution_teams"] > 0 for row in gs)
        season_rows.append(out)

    issue_games: dict[str, set[str]] = defaultdict(set)
    issue_occurrences = Counter()
    for row in games:
        for issue in filter(None, row["base_contradiction_types"].split(";")):
            issue_games[issue].add(row["game_id"])
            issue_occurrences[(row["season"], issue)] += 1
    field_totals = {}
    for field in field_names:
        present = sum(row.get(field, 0) for row in games)
        field_totals[field] = {"present": present, "missing": sum(row["shot_events"] for row in games) - present,
                               "pct": pct(present, sum(row["shot_events"] for row in games))}

    strength_states = Counter()
    strength_state_games: dict[str, set[str]] = defaultdict(set)
    for row in games:
        for state, count in json.loads(row["strength_state_counts_json"]).items():
            strength_states[state] += count
            if count:
                strength_state_games[state].add(row["game_id"])

    goalie_quality = {}
    for stat in ("SAVES", "SHOTS_AGAINST", "GOALS_AGAINST"):
        relevant = [r for r in goalie_rows if r["statistic"] == stat]
        goalie_quality[stat] = {
            "eligible": sum(r["comparison"] in {"MATCH", "MISMATCH"} for r in relevant),
            "matches": sum(r["comparison"] == "MATCH" for r in relevant),
            "mismatches": sum(r["comparison"] == "MISMATCH" for r in relevant),
            "quarantined": sum(r["quality_status"] == "QUARANTINED" for r in relevant),
            "not_applicable": sum(r["quality_status"] == "NOT_APPLICABLE" for r in relevant),
        }
    sog_quality = {
        "eligible": sum(r["comparison"] in {"MATCH", "MISMATCH"} for r in sog_rows),
        "matches": sum(r["comparison"] == "MATCH" for r in sog_rows),
        "mismatches": sum(r["comparison"] == "MISMATCH" for r in sog_rows),
        "quarantined": sum(r["quality_status"] == "QUARANTINED" for r in sog_rows),
        "not_applicable": sum(r["quality_status"] == "NOT_APPLICABLE" for r in sog_rows),
    }
    shooter_events = sum(row["shooter_events_with_clock_and_team"] for row in games)
    goalie_events = sum(row["goalie_events_with_clock"] for row in games)
    full_fetch_requests = 4876 * 2
    field_exception_counts = Counter()
    goalie_exception_counts = Counter()
    for row in event_exceptions:
        field_exception_counts.update(filter(None, row["missing_fields"].split(";")))
        if row["goalie_id_status"] != "NOT_APPLICABLE":
            goalie_exception_counts[row["goalie_id_status"]] += 1
    summary = {
        "frame_games": len(frame), "sample_games": len(sample),
        "sample_by_season": {str(k): season_counts[k] for k in sorted(season_counts)},
        "input_hashes": input_hashes,
        "research_label_quality_bytes": LABEL_PATH.stat().st_size,
        "event_bodies_verified": body_verification,
        "estimated_full_frame_event_bodies": {
            "compressed_bytes_by_linear_sample_scaling": round(body_verification["compressed_bytes"] * 4876 / len(sample)),
            "uncompressed_bytes_by_linear_sample_scaling": round(body_verification["uncompressed_bytes"] * 4876 / len(sample)),
            "requests": full_fetch_requests,
            "minimum_request_spacing_seconds_at_1_1s": round((full_fetch_requests - 1) * 1.1, 1),
            "minimum_request_spacing_minutes_at_1_1s": round((full_fetch_requests - 1) * 1.1 / 60, 2),
        },
        "shot_events": sum(row["shot_events"] for row in games),
        "field_completeness": field_totals,
        "season_field_completeness": [
            {"season": row["season"], "shot_events": row["shot_events"],
             **{field: {"present": row[f"{field}_present"], "missing": row[f"{field}_missing"],
                        "pct": row[f"{field}_pct"]} for field in field_names}}
            for row in season_rows
        ],
        "shot_type_split": {
            "unblocked": {"events": sum(row["unblocked_shot_events"] for row in games),
                          "with_type": sum(row["unblocked_shot_type"] for row in games)},
            "blocked": {"events": sum(row["blocked_shot_events"] for row in games),
                        "with_type": sum(row["blocked_shot_type"] for row in games)},
        },
        "strength_state_events_excluding_shootouts": {
            state: {"events": count, "games": len(strength_state_games[state])}
            for state, count in sorted(strength_states.items())
        },
        "on_target_identity": {
            "events_regulation_ot": sum(row["on_target_events_regulation_ot"] for row in games),
            "missing_goalie_id": sum(row["on_target_without_goalie_id"] for row in games),
            "missing_goalie_id_expected_empty_net": sum(row["on_target_without_goalie_expected_empty_net"] for row in games),
            "missing_goalie_id_unexplained": sum(row["on_target_without_goalie_unexplained"] for row in games),
            "missing_shooter_id": sum(row["on_target_without_shooter_id"] for row in games),
        },
        "event_field_exception_counts": {
            "missing_fields": dict(sorted(field_exception_counts.items())),
            "on_target_goalie_id_status": dict(sorted(goalie_exception_counts.items())),
            "exception_event_rows": len(event_exceptions),
        },
        "event_time_shift_alignment": {
            "shooter_events_tested": shooter_events,
            "shooter_on_ice": sum(row["shooter_shift_on_ice"] for row in games),
            "shooter_boundary_ambiguous": sum(row["shooter_shift_boundary_ambiguous"] for row in games),
            "shooter_off_ice": sum(row["shooter_shift_off_ice"] for row in games),
            "goalie_events_tested": goalie_events,
            "goalie_on_ice": sum(row["goalie_shift_on_ice"] for row in games),
            "goalie_boundary_ambiguous": sum(row["goalie_shift_boundary_ambiguous"] for row in games),
            "goalie_off_ice": sum(row["goalie_shift_off_ice"] for row in games),
            "situation_events_compared": sum(row["situation_shift_compared"] for row in games),
            "situation_matches": sum(row["situation_shift_matches"] for row in games),
            "situation_mismatches": sum(row["situation_shift_mismatches"] for row in games),
            "situation_boundary_ambiguous": sum(row["situation_shift_boundary_ambiguous"] for row in games),
        },
        "approved_label_reconciliation": {"SOG": sog_quality, **goalie_quality},
        "team_event_reconciliation": {
            "games_goal_counts_match_after_shootout_rule": sum(row["base_goal_games_match"] for row in games),
            "games_team_sog_match": sum(row["base_sog_games_match"] for row in games),
        },
        "quality_by_season": season_rows,
        "contradictions": {
            "issue_game_counts": {issue: len(game_ids) for issue, game_ids in sorted(issue_games.items())},
            "issue_occurrences_by_season": [
                {"season": season, "issue": issue, "games": count}
                for (season, issue), count in sorted(issue_occurrences.items())
            ],
            "games_with_any": sum(row["base_contradiction_count"] > 0 for row in games),
        },
        "games_missing_pbp": sum(not row["pbp_present"] for row in games),
        "games_missing_shift_chart": sum(not row["shift_present"] for row in games),
        "unusable_game_counts": {
            "player_sog_event_reconstruction": sum(row["unusable_for_player_sog_events"] for row in games),
            "goalie_event_target_reconstruction": sum(row["unusable_for_goalie_event_targets"] for row in games),
            "shift_features": sum(row["unusable_for_shift_features"] for row in games),
        },
        "zero_toi_backups_eligible_as_goalie_targets": 0,
        "label_quality_status_counts_in_sample": {
            f"{stat}:{status}": count for (stat, status), count in sorted(all_label_status_counts.items())
        },
    }

    outputs: dict[str, bytes] = {
        "event_field_game_quality.csv": csv_bytes(games),
        "event_field_by_season.csv": csv_bytes(season_rows),
        "player_sog_reconciliation.csv": csv_bytes(sog_rows),
        "goalie_outcome_reconciliation.csv": csv_bytes(goalie_rows),
        "event_field_exceptions.csv": csv_bytes(event_exceptions),
    }
    summary["derived_output_sha256"] = {name: sha256_bytes(data) for name, data in sorted(outputs.items())}
    outputs["event_quality_summary.json"] = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode()
    pins = {
        **input_hashes,
        "frame_games": len(frame), "sample_games": len(sample),
        "sample_games_by_season": summary["sample_by_season"],
        "event_body_verification": body_verification,
        "approved_label_reader": "official-outcome-backfill-2026-10-20/nhl_research_data.py",
        "approved_label_purpose": "audit; comparisons require VERIFIED/ADJUDICATED and eligible_grading=true",
    }
    outputs["event_quality_source_pins.json"] = (json.dumps(pins, indent=2, sort_keys=True) + "\n").encode()
    return outputs


def main() -> None:
    outputs = build_outputs()
    for name, body in outputs.items():
        (HERE / name).write_bytes(body)
    print(json.dumps({"outputs": {name: sha256_bytes(body) for name, body in sorted(outputs.items())},
                      "summary": json.loads(outputs["event_quality_summary.json"])},
                     sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
