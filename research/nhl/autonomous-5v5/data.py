"""Build the pinned, identity-free 5v5 transition dataset from verified sources."""

from __future__ import annotations

import collections
import gzip
import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from kernel import Context, FAMILIES, OWNER_DOMAINS, Token, Transition


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BEHAVIOR_DIR = ROOT / "research/nhl/behavior-evidence"
DEFAULT_DATA_ROOT = Path("/root/lp-data/nhl-fullframe-event-audit-2026-10-21")
DEFAULT_BOXSCORE_ROOT = Path("/root/lp-data/nhl-official-outcome-backfill-2026-10-20")
DEFAULT_CACHE = Path("/root/lp-data/nhl-autonomous-5v5-2026-10-27/eligible-sequences-v1.json.gz")
TRAIN_SEASONS = (2019, 2020)
DEV_SEASONS = (2021,)
EXPECTED_PBP_MANIFEST_SHA256 = "d87e40a3387f014429377cc8dfb010cec8ca2d0e4d03d0b5bdbfacd8de9ca990"
EXPECTED_SHIFT_MANIFEST_SHA256 = "deba1a38d9f9c969139dc15ac57e7085988c05bcab36db43bd87fe5805f1c6f5"
EXPECTED_V01_SHA256 = "b6afea41c21660c564ea13ea75c5c17a6088e95cec1f590fb11426c95016e9fc"
EXPECTED_AUDIT_SHA256 = "5b03df12a6e1dfd2bf546192c59c35b26c6bf2b75b04b338b14b57f85cc145a9"
EXPECTED_EVIDENCE_CORE_SHA256 = "cdcccbb1b4f5185df96178fccad4450a1bb3d8c9e5c4124389439c2281fc3490"
EXPECTED_EVENT_STATE_JSON_SHA256 = "1029c286cc3e20907338fea3f5f5bc612c6bb0bec793661f558ab57edd934f75"
CACHE_SCHEMA = "nhl-autonomous-5v5-eligible-sequences-v2"
PERIOD_SECONDS = 1200
BOUNDARY_TYPES = {"period-start", "period-end", "game-end", "shootout-complete"}
PENALTY_TYPES = {"penalty"}
TEAM_FAMILIES = {"goal", "shot-on-goal", "missed-shot", "blocked-shot",
                 "faceoff", "hit", "giveaway", "takeaway"}


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def family_for(source_type: str) -> str:
    return source_type if source_type in FAMILIES[:-1] else "other"


def _load_behavior_module():
    behavior_dir = str(BEHAVIOR_DIR)
    if behavior_dir not in sys.path:
        sys.path.insert(0, behavior_dir)
    spec = importlib.util.spec_from_file_location(
        "nhl_autonomous_5v5_behavior_audit", BEHAVIOR_DIR / "audit_behavior.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the frozen Event-State v3 source reconciler")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class Bundle:
    game_id: str
    season: int
    period: int
    second: int
    mark: tuple[Token, ...]
    eligible: bool
    context_after: Context
    reason: str | None = None
    source_types: tuple[str, ...] = ()


@dataclass
class PeriodData:
    game_id: str
    season: int
    period: int
    transitions: list[Transition] = field(default_factory=list)
    shift_5v5_seconds: int = 0
    shift_non5v5_seconds: int = 0
    shift_ambiguous_seconds: int = 0
    ambiguous_seconds: int = 0
    eligible_bundle_count: int = 0
    eligible_event_family_counts: collections.Counter[str] = field(default_factory=collections.Counter)
    excluded_bundle_counts: collections.Counter[str] = field(default_factory=collections.Counter)
    gap_excluded_counts: collections.Counter[str] = field(default_factory=collections.Counter)
    other_source_types: collections.Counter[str] = field(default_factory=collections.Counter)
    shift_anomaly_counts: collections.Counter[str] = field(default_factory=collections.Counter)

    @property
    def gap_exposure_seconds(self) -> int:
        return sum(row.gap_seconds for row in self.transitions)


def _state_by_second(shifts_doc: dict[str, Any], game_id: str, period: int,
                     team_sides: dict[str, str], roster: dict[str, tuple[str, str]]) -> tuple[list[str], list[int], dict[str, int]]:
    rows = shifts_doc.get("data")
    if not isinstance(rows, list) or shifts_doc.get("total") != len(rows):
        raise ValueError(f"{game_id}: shift total does not equal source row count")
    starts: list[list[tuple[int, str, str | None, str]]] = [[] for _ in range(PERIOD_SECONDS + 1)]
    ends: list[list[tuple[int, str, str | None, str]]] = [[] for _ in range(PERIOD_SECONDS + 1)]
    invalid_period = False
    anomalies: collections.Counter[str] = collections.Counter()
    for index, source in enumerate(rows):
        if str(source.get("gameId")) != game_id:
            raise ValueError(f"{game_id}: shift row game ID mismatch")
        try:
            row_period = int(source["period"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"{game_id}: shift row has no parseable period")
        if row_period != period:
            continue
        start_raw = source.get("startTime")
        end_raw = source.get("endTime")
        duration_raw = source.get("duration")
        try:
            declared = _parse_clock(duration_raw)
        except (KeyError, TypeError, ValueError):
            declared = None
        try:
            start = _parse_clock(start_raw)
            end = _parse_clock(end_raw)
        except (KeyError, TypeError, ValueError):
            # NHL shift feeds include zero-duration event annotations with a
            # start but no end (for example, eventDescription=GOAL and
            # duration=00:00). They carry no on-ice interval and must not make
            # the whole period ambiguous.
            if declared == 0 and (not start_raw or not end_raw):
                anomalies["zero_duration_annotation"] += 1
                continue
            anomalies["unparseable_time"] += 1
            invalid_period = True
            continue
        if start == end:
            anomalies["zero_duration_annotation"] += 1
            continue
        if end < start or not 0 <= start < end <= PERIOD_SECONDS:
            anomalies["invalid_interval"] += 1
            invalid_period = True
            continue
        if declared is None:
            anomalies["unparseable_duration"] += 1
            invalid_period = True
            continue
        if declared != end - start:
            anomalies["declared_duration_mismatch"] += 1
        player_id = str(source.get("playerId") or "")
        team_id = str(source.get("teamId") or "")
        side = team_sides.get(team_id)
        roster_row = roster.get(player_id)
        position = roster_row[1] if roster_row and roster_row[0] == team_id else "?"
        if not player_id:
            position = "?"
        row = (index, player_id, side, position)
        starts[start].append(row)
        ends[end].append(row)

    active: dict[int, tuple[int, str, str | None, str]] = {}
    player_active: collections.Counter[str] = collections.Counter()
    side_players: collections.Counter[str] = collections.Counter()
    skaters: collections.Counter[str] = collections.Counter()
    goalies: collections.Counter[str] = collections.Counter()
    unknown_rows = 0
    duplicates = 0
    states: list[str] = []
    ambiguous_seconds: list[int] = []

    def add(row: tuple[int, str, str | None, str]) -> None:
        nonlocal unknown_rows, duplicates
        index, player_id, side, position = row
        active[index] = row
        if player_id:
            if player_active[player_id] == 1:
                duplicates += 1
            player_active[player_id] += 1
        if side not in {"home", "away"} or position not in {"C", "L", "R", "D", "F", "G"}:
            unknown_rows += 1
            return
        side_players[side] += 1
        if position == "G":
            goalies[side] += 1
        else:
            skaters[side] += 1

    def remove(row: tuple[int, str, str | None, str]) -> None:
        nonlocal unknown_rows, duplicates
        index, player_id, side, position = row
        active.pop(index, None)
        if player_id:
            count = player_active[player_id]
            if count == 2:
                duplicates -= 1
            if count <= 1:
                player_active.pop(player_id, None)
            else:
                player_active[player_id] -= 1
        if side not in {"home", "away"} or position not in {"C", "L", "R", "D", "F", "G"}:
            unknown_rows -= 1
            return
        side_players[side] -= 1
        if position == "G":
            goalies[side] -= 1
        else:
            skaters[side] -= 1

    for second in range(PERIOD_SECONDS):
        for row in ends[second]:
            remove(row)
        for row in starts[second]:
            add(row)
        if invalid_period or unknown_rows or duplicates or not side_players["home"] or not side_players["away"]:
            states.append("ambiguous")
            ambiguous_seconds.append(second)
        elif (skaters["home"] == 5 and skaters["away"] == 5
              and goalies["home"] == 1 and goalies["away"] == 1):
            states.append("5v5")
        else:
            states.append("non5v5")
    return states, ambiguous_seconds, dict(anomalies)


def _parse_clock(value: Any) -> int:
    if not isinstance(value, str):
        raise ValueError(f"clock must be text, got {value!r}")
    match = value.split(":")
    if len(match) != 2:
        raise ValueError(f"unsupported clock {value!r}")
    minutes, seconds = int(match[0]), int(match[1])
    if not 0 <= seconds < 60:
        raise ValueError(f"unsupported clock {value!r}")
    return minutes * 60 + seconds


def _token_for(record: dict[str, Any], roster_sides: dict[str, str]) -> tuple[Token | None, str | None]:
    source_type = str(record.get("type") or "<missing>")
    family = family_for(source_type)
    details = record.get("details") or {}
    owner = record.get("side")
    if family == "faceoff":
        winner = str(details.get("winningPlayerId") or "")
        owner = roster_sides.get(winner) or owner
    if owner not in {"home", "away"}:
        owner = "unknown"
    if family in TEAM_FAMILIES and owner == "unknown":
        return None, "missing_team_owner"
    if owner not in OWNER_DOMAINS[family]:
        return None, "unsupported_owner"
    return Token(family, owner), None


def _bundle_state_is_5v5(records: list[dict[str, Any]]) -> tuple[bool, str | None]:
    if any(record.get("type") in PENALTY_TYPES for record in records):
        return False, "penalty_bundle"
    for record in records:
        attribution = record.get("event_state_attribution") or {}
        if not attribution.get("eligible_for_conditional_fit"):
            return False, "ambiguous_event_state"
        state = attribution.get("state")
        if not isinstance(state, dict):
            return False, "ambiguous_event_state"
        if not (state.get("home_skaters") == 5 and state.get("away_skaters") == 5
                and state.get("home_goalie") == 1 and state.get("away_goalie") == 1):
            return False, "non5v5_event_state"
    return True, None


def _process_bundle_state(previous_score_diff: int, possession_known: bool,
                          records: list[dict[str, Any]], tokens: tuple[Token, ...],
                          second: int) -> Context:
    score_diff = previous_score_diff
    token_index = 0
    last_family = "faceoff"
    for record in records:
        source_type = str(record.get("type") or "<missing>")
        if source_type in BOUNDARY_TYPES:
            continue
        if source_type in PENALTY_TYPES:
            last_family = "other"
            continue
        family = family_for(source_type)
        details = record.get("details") or {}
        token = tokens[token_index] if token_index < len(tokens) else None
        if token and token.family == family:
            owner = token.owner
            token_index += 1
        else:
            owner = record.get("side") if record.get("side") in {"home", "away"} else "unknown"
            if family == "faceoff":
                winner = str(details.get("winningPlayerId") or "")
                owner = record.get("roster_sides", {}).get(winner, owner)
        last_family = family
        if family == "goal" and owner in {"home", "away"}:
            score_diff += 1 if owner == "home" else -1
            possession_known = False
        elif family == "faceoff":
            possession_known = owner in {"home", "away"}
        elif family in {"giveaway", "takeaway"}:
            possession_known = owner in {"home", "away"}
        elif family in {"shot-on-goal", "missed-shot", "blocked-shot", "stoppage"}:
            possession_known = False
    return Context(last_family, possession_known, score_diff, min(3, second // 300))


def _make_bundles(local: dict[str, Any], pbp: dict[str, Any], game_id: str,
                  season: int, period: int,
                  event_ambiguous_seconds: set[int]) -> tuple[list[Bundle], collections.Counter[str]]:
    home_id = str((pbp.get("homeTeam") or {}).get("id") or "")
    away_id = str((pbp.get("awayTeam") or {}).get("id") or "")
    team_sides = {home_id: "home", away_id: "away"}
    roster_sides = {
        str(row.get("playerId")): team_sides.get(str(row.get("teamId")), "")
        for row in pbp.get("rosterSpots") or [] if row.get("playerId") is not None
    }
    groups: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
    for record in local["event_records"]:
        if record.get("period_type") == "REG" and int(record.get("period") or 0) == period:
            groups[int(record["time"])].append(record)

    bundles: list[Bundle] = []
    excluded: collections.Counter[str] = collections.Counter()
    possession_known = False
    previous_score_diff = 0
    for second, all_records in sorted(groups.items()):
        records = [row for row in all_records if row.get("type") not in BOUNDARY_TYPES]
        if not records:
            continue
        records = [dict(row, roster_sides=roster_sides) for row in records]
        pre_score = records[0].get("score_before") or {"home": 0, "away": 0}
        try:
            previous_score_diff = int(pre_score.get("home", 0)) - int(pre_score.get("away", 0))
        except (TypeError, ValueError):
            raise ValueError(f"{game_id} P{period} {second}: invalid score snapshot")
        tokens: list[Token] = []
        token_error = None
        other_types: list[str] = []
        for record in records:
            source_type = str(record.get("type") or "<missing>")
            if source_type in PENALTY_TYPES:
                token_error = token_error or "penalty_bundle"
                continue
            if family_for(source_type) == "other":
                other_types.append(source_type)
            token, reason = _token_for(record, roster_sides)
            if token is not None:
                tokens.append(token)
            elif source_type not in PENALTY_TYPES:
                token_error = token_error or reason
        if not tokens and all(row.get("type") in PENALTY_TYPES for row in records):
            token_error = "penalty_bundle"
        eligible_state, state_reason = _bundle_state_is_5v5(records)
        reason = state_reason or token_error
        if not eligible_state and state_reason == "penalty_bundle":
            reason = "penalty_bundle"
        eligible = eligible_state and token_error is None and bool(tokens)
        if second in event_ambiguous_seconds:
            eligible = False
            reason = "ambiguous_event_state"
        if reason and not eligible:
            excluded[reason] += 1
        mark = tuple(tokens)
        context_after = _process_bundle_state(previous_score_diff, possession_known,
            records, mark, second)
        possession_known = context_after.possession_known
        bundles.append(Bundle(game_id, season, period, second, mark, eligible,
            context_after, reason, tuple(other_types)))
    return bundles, excluded


def _period_data(game_id: str, season: int, period: int, pbp: dict[str, Any],
                 shifts_doc: dict[str, Any], local: dict[str, Any]) -> PeriodData:
    home_id = str((pbp.get("homeTeam") or {}).get("id") or "")
    away_id = str((pbp.get("awayTeam") or {}).get("id") or "")
    team_sides = {home_id: "home", away_id: "away"}
    roster: dict[str, tuple[str, str]] = {}
    for row in pbp.get("rosterSpots") or []:
        player_id = str(row.get("playerId") or "")
        if player_id:
            roster[player_id] = (str(row.get("teamId") or ""),
                                 str(row.get("positionCode") or "?"))
    states, shift_ambiguous_seconds, shift_anomalies = _state_by_second(
        shifts_doc, game_id, period, team_sides, roster)
    event_ambiguous_seconds = {
        int(row["time"]) for row in local["event_records"]
        if row.get("period_type") == "REG" and int(row.get("period") or 0) == period
        and row.get("type") not in BOUNDARY_TYPES
        and not (row.get("event_state_attribution") or {}).get("eligible_for_conditional_fit")
    }
    ambiguous = set(shift_ambiguous_seconds) | event_ambiguous_seconds
    bundles, excluded = _make_bundles(local, pbp, game_id, season, period,
                                       event_ambiguous_seconds)
    result = PeriodData(game_id, season, period)
    result.shift_5v5_seconds = states.count("5v5")
    result.shift_non5v5_seconds = states.count("non5v5")
    result.shift_ambiguous_seconds = states.count("ambiguous")
    result.shift_anomaly_counts.update(shift_anomalies)
    result.ambiguous_seconds = len(ambiguous)
    result.eligible_bundle_count = sum(row.eligible for row in bundles)
    result.excluded_bundle_counts.update(excluded)
    for bundle in bundles:
        result.other_source_types.update(bundle.source_types)
        if bundle.eligible:
            result.eligible_event_family_counts.update(token.family for token in bundle.mark)
    for previous, current in zip(bundles, bundles[1:]):
        if not previous.eligible or not current.eligible:
            result.gap_excluded_counts["adjacent_bundle_not_eligible"] += 1
            continue
        gap = current.second - previous.second
        if gap <= 0:
            raise ValueError(f"{game_id} P{period}: bundles are not strictly ordered")
        between = states[previous.second:current.second]
        if any(state == "ambiguous" for state in between):
            result.gap_excluded_counts["shift_state_ambiguous"] += 1
            continue
        if any(state != "5v5" for state in between):
            result.gap_excluded_counts["interval_not_5v5"] += 1
            continue
        if len(current.mark) == 0:
            result.gap_excluded_counts["empty_event_mark"] += 1
            continue
        result.transitions.append(Transition(game_id, period, gap,
            previous.context_after, current.mark))
    return result


def _load_v01(data_root: Path, boxscore_root: Path):
    path = ROOT / "research/nhl/statistical-full-game-v0.1/nhl_statistical_game.py"
    spec = importlib.util.spec_from_file_location("nhl_autonomous_5v5_v01", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load pinned v0.1 corpus eligibility validator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.DEFAULT_BOXSCORE_ROOT = boxscore_root
    return module, module.load_corpus(data_root, (*TRAIN_SEASONS, *DEV_SEASONS))


def _verified_manifests(data_root: Path, behavior: Any) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    pbp_rows = behavior._read_manifest(
        data_root / "manifests/hardened-v1/pbp_verified_manifest.csv",
        EXPECTED_PBP_MANIFEST_SHA256)
    shift_rows = behavior._read_manifest(
        data_root / "manifests/hardened-v1/shifts_verified_manifest.csv",
        EXPECTED_SHIFT_MANIFEST_SHA256)
    pbp = {str(row["game_id"]): row for row in pbp_rows
           if row.get("kind") == "pbp" and row.get("http_status") == "200"}
    shifts = {str(row["game_id"]): row for row in shift_rows
              if row.get("kind") == "shifts" and row.get("http_status") == "200"}
    if len(pbp) != 4876 or len(shifts) != 4876:
        raise ValueError(f"verified archive population changed: PBP={len(pbp)}, shifts={len(shifts)}")
    return pbp, shifts


def _extract_event_records(pbp: dict[str, Any], shifts_doc: dict[str, Any],
                           game_id: str, behavior: Any) -> list[dict[str, Any]]:
    """Apply the pinned Event-State v3 left/right shift reconciliation."""
    home_id = str((pbp.get("homeTeam") or {}).get("id") or "")
    away_id = str((pbp.get("awayTeam") or {}).get("id") or "")
    team_sides = {home_id: "home", away_id: "away"}
    roster: dict[str, tuple[str, str]] = {}
    for item in pbp.get("rosterSpots") or []:
        player_id = str(item.get("playerId") or "")
        if player_id:
            roster[player_id] = (str(item.get("teamId") or ""),
                                 str(item.get("positionCode") or "?"))
    season_stats = behavior._new_season_stats(int(game_id[:4]))
    shift_by_period = behavior._normalize_shift_rows(
        shifts_doc, game_id, team_sides, roster, season_stats)
    period_events: dict[tuple[str, int], list[dict[str, Any]]] = collections.defaultdict(list)
    plays = sorted(enumerate(pbp.get("plays") or []),
                   key=lambda pair: (int(pair[1].get("sortOrder", pair[0])), pair[0]))
    for _, event in plays:
        descriptor = event.get("periodDescriptor") or {}
        period_type = str(descriptor.get("periodType") or "")
        try:
            number = int(descriptor.get("number") or 0)
        except (TypeError, ValueError):
            continue
        if period_type == "REG" and number in (1, 2, 3):
            period_events[(period_type, number)].append(event)

    scores = {"home": 0, "away": 0}
    records: list[dict[str, Any]] = []
    for period_type, period_number in sorted(period_events, key=lambda key: (key[1], key[0])):
        events = period_events[(period_type, period_number)]
        period_end = behavior._period_terminal_time(period_type, events)
        by_time: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
        for event in events:
            by_time[behavior.parse_clock(str(event.get("timeInPeriod")))].append(event)
        shifts = shift_by_period.get(period_number, [])
        starts: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
        ends: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
        for shift in shifts:
            if shift["start"] < shift["end"] and shift["end"] <= period_end:
                starts[shift["start"]].append(shift)
                ends[shift["end"]].append(shift)
        times = sorted({0, period_end, *by_time.keys(), *starts.keys(), *ends.keys()})
        active_rows: dict[int, dict[str, Any]] = {}
        for now in times:
            pre_boundary_rows = dict(active_rows)
            for shift in starts.get(now, []):
                pre_boundary_rows.pop(shift["row_index"], None)
            for shift in ends.get(now, []):
                pre_boundary_rows[shift["row_index"]] = shift
            for shift in ends.get(now, []):
                active_rows.pop(shift["row_index"], None)
            for shift in starts.get(now, []):
                active_rows[shift["row_index"]] = shift
            lineup, duplicate_players = behavior._lineup_from_active_rows(active_rows)
            pre_lineup, pre_duplicate_players = behavior._lineup_from_active_rows(pre_boundary_rows)
            at_boundary = bool(starts.get(now) or ends.get(now))
            pre_state = behavior._situation_from_lineup(pre_lineup, pre_duplicate_players)
            post_state = behavior._situation_from_lineup(lineup, duplicate_players)
            clock_events = by_time.get(now, [])
            for event in clock_events:
                event_type = str(event.get("typeDescKey") or "<missing>")
                details = event.get("details") or {}
                code = behavior.decode_situation_code(event.get("situationCode"))
                attribution = behavior.reconcile_event_state(
                    code, pre_state, post_state, at_shift_boundary=at_boundary)
                owner_side = behavior._event_owner_side(event, team_sides)
                before = dict(scores)
                record = {
                    "event_id": event.get("eventId"),
                    "sort_order": event.get("sortOrder"),
                    "type": event_type,
                    "period_type": period_type,
                    "period": period_number,
                    "time": now,
                    "side": owner_side,
                    "details": details,
                    "code": code,
                    "score_before": before,
                    "event_state_attribution": {
                        **attribution,
                        "source_situation_state": code,
                    },
                }
                if event_type == "goal" and owner_side in scores:
                    scores[owner_side] += 1
                record["score_after"] = dict(scores)
                records.append(record)
    return records


def build_cache(data_root: Path = DEFAULT_DATA_ROOT,
                boxscore_root: Path = DEFAULT_BOXSCORE_ROOT) -> dict[str, Any]:
    actual_hashes = {
        "v01_loader_sha256": sha256_file(ROOT / "research/nhl/statistical-full-game-v0.1/nhl_statistical_game.py"),
        "event_state_audit_sha256": sha256_file(BEHAVIOR_DIR / "audit_behavior.py"),
        "event_state_core_sha256": sha256_file(BEHAVIOR_DIR / "evidence_core.py"),
        "event_state_result_sha256": sha256_file(BEHAVIOR_DIR / "results/nhl-behavior-evidence-event-state-v3-2026-10-27.json"),
        "pbp_manifest_sha256": sha256_file(data_root / "manifests/hardened-v1/pbp_verified_manifest.csv"),
        "shift_manifest_sha256": sha256_file(data_root / "manifests/hardened-v1/shifts_verified_manifest.csv"),
    }
    expected = {
        "v01_loader_sha256": EXPECTED_V01_SHA256,
        "event_state_audit_sha256": EXPECTED_AUDIT_SHA256,
        "event_state_core_sha256": EXPECTED_EVIDENCE_CORE_SHA256,
        "event_state_result_sha256": EXPECTED_EVENT_STATE_JSON_SHA256,
        "pbp_manifest_sha256": EXPECTED_PBP_MANIFEST_SHA256,
        "shift_manifest_sha256": EXPECTED_SHIFT_MANIFEST_SHA256,
    }
    if actual_hashes != expected:
        frozen_actual = {key: actual_hashes[key] for key in expected}
        if frozen_actual != expected:
            raise ValueError(f"pinned source hashes changed: {frozen_actual}")
    actual_hashes["sequence_extractor_code_sha256"] = sha256_file(HERE / "data.py")
    actual_hashes["arrival_kernel_code_sha256"] = sha256_file(HERE / "kernel.py")

    behavior = _load_behavior_module()
    v01, corpus = _load_v01(data_root, boxscore_root)
    expected_population = {2019: 1064, 2020: 857, 2021: 1292}
    for season, count in expected_population.items():
        if corpus.eligible_by_season.get(season) != count:
            raise ValueError(f"{season} eligible population changed: {corpus.eligible_by_season.get(season)}")
    pbp_rows, shift_rows = _verified_manifests(data_root, behavior)

    all_periods: list[PeriodData] = []
    extraction_exclusions: collections.Counter[str] = collections.Counter()
    games_processed = collections.Counter()
    for game_id, summary in sorted(corpus.games.items()):
        if not summary.eligible:
            continue
        season = int(summary.start_season)
        pbp, shifts_doc = behavior._load_game_source(data_root, pbp_rows, shift_rows, game_id)
        if str(pbp.get("id")) != game_id:
            raise ValueError(f"{game_id}: verified PBP body has a different game ID")
        local = {"event_records": _extract_event_records(pbp, shifts_doc, game_id, behavior)}
        for period in (1, 2, 3):
            period_data = _period_data(game_id, season, period, pbp, shifts_doc, local)
            all_periods.append(period_data)
            extraction_exclusions.update(period_data.excluded_bundle_counts)
        games_processed[season] += 1

    expected_games = {2019: 1064, 2020: 857, 2021: 1292}
    if dict(games_processed) != expected_games:
        raise ValueError(f"processed eligible games do not reconcile: {dict(games_processed)}")
    if len(all_periods) != sum(expected_games.values()) * 3:
        raise ValueError("processed period count does not reconcile to eligible games")
    transitions = [row for period in all_periods for row in period.transitions]
    training = [row for row in transitions if row.game_id[:4] in {"2019", "2020"}]
    development = [row for row in transitions if row.game_id[:4] == "2021"]
    if not training or not development:
        raise ValueError("no train or development transitions after state eligibility")
    return {
        "schema": CACHE_SCHEMA,
        "source_hashes": actual_hashes,
        "source_roots_outside_repository": {
            "pbp_and_shifts": str(data_root), "independent_boxscores": str(boxscore_root),
        },
        "population": {
            "eligible_games_by_start_season": {str(k): int(v) for k, v in sorted(games_processed.items())},
            "periods": len(all_periods),
            "training_transition_gaps": len(training),
            "development_transition_gaps": len(development),
        },
        "extraction_exclusions": dict(sorted(extraction_exclusions.items())),
        "periods": [_period_to_dict(row) for row in all_periods],
    }


def _period_to_dict(period: PeriodData) -> dict[str, Any]:
    return {
        "game_id": period.game_id,
        "season": period.season,
        "period": period.period,
        "shift_5v5_seconds": period.shift_5v5_seconds,
        "shift_non5v5_seconds": period.shift_non5v5_seconds,
        "shift_ambiguous_seconds": period.shift_ambiguous_seconds,
        "ambiguous_seconds": period.ambiguous_seconds,
        "eligible_bundle_count": period.eligible_bundle_count,
        "eligible_event_family_counts": dict(sorted(period.eligible_event_family_counts.items())),
        "excluded_bundle_counts": dict(sorted(period.excluded_bundle_counts.items())),
        "gap_excluded_counts": dict(sorted(period.gap_excluded_counts.items())),
        "other_source_types": dict(sorted(period.other_source_types.items())),
        "shift_anomaly_counts": dict(sorted(period.shift_anomaly_counts.items())),
        "transitions": [{
            "game_id": row.game_id,
            "period": row.period,
            "gap_seconds": row.gap_seconds,
            "context": {
                "previous_family": row.context.previous_family,
                "possession_known": row.context.possession_known,
                "score_diff": row.context.score_diff,
                "clock_bucket": row.context.clock_bucket,
            },
            "mark": [[token.family, token.owner] for token in row.mark],
        } for row in period.transitions],
    }


def _period_from_dict(row: dict[str, Any]) -> PeriodData:
    result = PeriodData(str(row["game_id"]), int(row["season"]), int(row["period"]))
    for key in ("shift_5v5_seconds", "shift_non5v5_seconds", "shift_ambiguous_seconds",
                "ambiguous_seconds", "eligible_bundle_count"):
        setattr(result, key, int(row[key]))
    result.excluded_bundle_counts.update(row.get("excluded_bundle_counts", {}))
    result.eligible_event_family_counts.update(row.get("eligible_event_family_counts", {}))
    result.gap_excluded_counts.update(row.get("gap_excluded_counts", {}))
    result.other_source_types.update(row.get("other_source_types", {}))
    result.shift_anomaly_counts.update(row.get("shift_anomaly_counts", {}))
    for item in row.get("transitions", []):
        context = item["context"]
        result.transitions.append(Transition(
            str(item["game_id"]), int(item["period"]), int(item["gap_seconds"]),
            Context(str(context["previous_family"]), bool(context["possession_known"]),
                    int(context["score_diff"]), int(context["clock_bucket"])),
            tuple(Token(str(family), str(owner)) for family, owner in item["mark"]),
        ))
    return result


def write_cache(cache: dict[str, Any], path: Path = DEFAULT_CACHE) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (json.dumps(cache, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    with path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            compressed.write(body)
    return sha256_file(path)


def load_cache(path: Path = DEFAULT_CACHE) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("schema") != CACHE_SCHEMA:
        raise ValueError(f"unsupported sequence cache schema: {payload.get('schema')}")
    expected_hashes = {
        "v01_loader_sha256": EXPECTED_V01_SHA256,
        "event_state_audit_sha256": EXPECTED_AUDIT_SHA256,
        "event_state_core_sha256": EXPECTED_EVIDENCE_CORE_SHA256,
        "event_state_result_sha256": EXPECTED_EVENT_STATE_JSON_SHA256,
        "pbp_manifest_sha256": EXPECTED_PBP_MANIFEST_SHA256,
        "shift_manifest_sha256": EXPECTED_SHIFT_MANIFEST_SHA256,
        "sequence_extractor_code_sha256": sha256_file(HERE / "data.py"),
        "arrival_kernel_code_sha256": sha256_file(HERE / "kernel.py"),
    }
    actual_source_hashes = payload.get("source_hashes") or {}
    if any(actual_source_hashes.get(key) != value for key, value in expected_hashes.items()):
        raise ValueError("sequence cache source hashes do not match frozen inputs")
    return payload


def period_records(payload: dict[str, Any]) -> list[PeriodData]:
    return [_period_from_dict(row) for row in payload["periods"]]

