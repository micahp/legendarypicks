"""Hash-pinned readers for the NHL V3 Phase 1 replay inputs."""
from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import io
import json
import re
import sys
from itertools import zip_longest
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Sequence
from urllib.parse import parse_qs, urlparse

from replay_model import (
    GameDefinition, GameProvenance, NormalizedEvent, NormalizedShiftInterval,
    Quality, SourceIdentity, TargetValue,
)


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
DEFAULT_ARTIFACT_DIR = Path("/root/lp-data/nhl-fullframe-event-audit-2026-10-21/derived/hardened-final")
DEFAULT_RAW_DIR = Path("/root/lp-data/nhl-fullframe-event-audit-2026-10-21/raw")
DEFAULT_OFFICIAL_DIR = REPO_ROOT / "research/nhl/official-outcome-backfill-2026-10-20"
DEFAULT_LABEL_DIR = Path("/root/lp-data/nhl-official-outcome-quality-adjudication-2026-10-20")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class InputIntegrityError(ValueError):
    """Raised when a source pin, identity join, or payload check fails."""


@dataclass
class InputBundle:
    artifact_dir: Path
    official_dir: Path
    label_path: Path
    label_summary_path: Path
    pins: dict
    games: dict[str, GameDefinition]
    provenance: dict[str, GameProvenance]
    targets_by_game: dict[str, list[TargetValue]]
    game_metrics: dict[str, dict[str, str]]
    official_sog_by_game_side: dict[tuple[str, str], int]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise InputIntegrityError(f"INPUT_MISSING {label}: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise InputIntegrityError(f"INPUT_HASH_MISMATCH {label}: {actual} != {expected}")


def _csv_rows(path: Path, *, compressed: bool = False) -> Iterator[dict[str, str]]:
    opener = gzip.open if compressed else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise InputIntegrityError(f"CSV_HEADER_MISSING {path}")
        yield from reader


def _int(value: str | None, label: str, *, optional: bool = False) -> int | None:
    if value is None or value == "":
        if optional:
            return None
        raise InputIntegrityError(f"INTEGER_REQUIRED {label}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise InputIntegrityError(f"INTEGER_INVALID {label}={value!r}") from exc


def _bool(value: str, label: str) -> bool:
    if value in {"true", "True", "1"}:
        return True
    if value in {"false", "False", "0"}:
        return False
    raise InputIntegrityError(f"BOOLEAN_INVALID {label}={value!r}")


def _source_identity(row: dict[str, str]) -> SourceIdentity:
    if row["source_kind"] not in {"pbp", "shifts"}:
        raise InputIntegrityError(f"SOURCE_KIND_INVALID {row['source_kind']}")
    for name in ("sha256_raw", "sha256_gz"):
        if not SHA_RE.fullmatch(row[name]):
            raise InputIntegrityError(f"SOURCE_HASH_INVALID {row['game_id']}/{row['source_kind']}/{name}")
    if row["content_type"] != "application/json":
        raise InputIntegrityError(f"SOURCE_CONTENT_TYPE_INVALID {row['game_id']}/{row['source_kind']}")
    if row["verification_disposition"] != "ACCEPT":
        raise InputIntegrityError(
            f"SOURCE_VERIFICATION_NOT_ACCEPTED {row['game_id']}/{row['source_kind']}/"
            f"{row['verification_disposition']}")
    if row["prior_manifest_disposition"] != "ACCEPT":
        raise InputIntegrityError(
            f"PRIOR_MANIFEST_NOT_ACCEPTED {row['game_id']}/{row['source_kind']}/"
            f"{row['prior_manifest_disposition']}")
    if _int(row["http_status"], "http_status") != 200:
        raise InputIntegrityError(f"SOURCE_HTTP_STATUS_NOT_200 {row['game_id']}/{row['source_kind']}")
    try:
        datetime.fromisoformat(row["retrieved_at_utc"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise InputIntegrityError(f"SOURCE_RETRIEVAL_TIMESTAMP_INVALID {row['game_id']}") from exc
    return SourceIdentity(
        source_kind=row["source_kind"], source_url=row["source_url"],
        http_status=int(row["http_status"]), content_type=row["content_type"],
        payload_rows=int(row["payload_rows"]), sha256_raw=row["sha256_raw"],
        sha256_gz=row["sha256_gz"], bytes_raw=int(row["bytes_raw"]),
        bytes_gz=int(row["bytes_gz"]), retrieved_at_utc=row["retrieved_at_utc"],
        evidence_origin=row["evidence_origin"],
        attempts=_int(row["attempts"], "source_attempts", optional=True),
        request_duration_seconds=row["request_duration_seconds"],
        request_elapsed_with_pacing_seconds=row["request_elapsed_with_pacing_seconds"],
        sample_event_manifest_sha256=row["sample_event_manifest_sha256"],
        sample_source_commit=row["sample_source_commit"],
        source_identity_basis=row["source_identity_basis"],
        prior_manifest_sha256=row["prior_manifest_sha256"],
        verification_disposition=row["verification_disposition"],
        prior_manifest_disposition=row["prior_manifest_disposition"],
        reason_codes=tuple(code for code in row["reason_codes"].split(";") if code),
        canonical_frame_sha256=row["canonical_frame_sha256"],
        audit_version=row["audit_version"],
    )


def _validate_source_url(game_id: str, source: SourceIdentity) -> None:
    parsed = urlparse(source.source_url)
    if source.source_kind == "pbp":
        expected = f"/v1/gamecenter/{game_id}/play-by-play"
        if parsed.scheme != "https" or parsed.hostname != "api-web.nhle.com" or parsed.path != expected:
            raise InputIntegrityError(f"PBP_SOURCE_URL_IDENTITY_MISMATCH {game_id}: {source.source_url}")
    else:
        query = parse_qs(parsed.query)
        query_text = "&".join(query.get("cayenneExp", [])) + "&" + parsed.query
        if (parsed.scheme != "https" or parsed.hostname != "api.nhle.com" or
                "shiftcharts" not in parsed.path.lower() or game_id not in query_text):
            raise InputIntegrityError(f"SHIFT_SOURCE_URL_IDENTITY_MISMATCH {game_id}: {source.source_url}")


def _approved_targets(pins: dict, label_path: Path, summary_path: Path,
                      target_path: Path) -> dict[str, list[TargetValue]]:
    reader_path = REPO_ROOT / pins["approved_label_artifact"]["reader"]
    spec = importlib.util.spec_from_file_location("nhl_v3_approved_label_reader", reader_path)
    if spec is None or spec.loader is None:
        raise InputIntegrityError(f"APPROVED_LABEL_READER_UNLOADABLE {reader_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    targets_by_game: dict[str, list[TargetValue]] = defaultdict(list)
    flat_targets: list[TargetValue] = []
    target_index: dict[str, TargetValue] = {}
    audit_reader = module.iter_nhl_research_labels(
        purpose="audit", path=label_path, summary_path=summary_path)
    target_reader = _csv_rows(target_path, compressed=True)
    sentinel = object()
    for row, label in zip_longest(target_reader, audit_reader, fillvalue=sentinel):
        if row is sentinel or label is sentinel:
            raise InputIntegrityError("TARGET_LABEL_POPULATION_LENGTH_MISMATCH")
        key = f"{label.game_id}:{label.player_id}:{label.statistic}"
        if (row["game_id"], row["player_id"], row["statistic"]) != (
                label.game_id, label.player_id, label.statistic):
            raise InputIntegrityError(f"TARGET_LABEL_ORDER_OR_ID_MISMATCH {key}")
        expected_copies = {
            "quality_status": label.quality_status,
            "reason_code": label.reason_code,
            "official_value": "" if label.official_value is None else str(label.official_value),
            "accepted_value": "" if label.accepted_value is None else str(label.accepted_value),
        }
        for field, expected in expected_copies.items():
            if row[field] != expected:
                raise InputIntegrityError(
                    f"TARGET_LABEL_COPY_MISMATCH {key}/{field}: {row[field]!r}!={expected!r}")
        approved_flags = {
            "training": label.eligible_training,
            "evaluation": label.eligible_evaluation,
            "grading": label.eligible_grading,
        }
        for purpose, approved in approved_flags.items():
            ledger_flag = row[f"eligible_{purpose}"] == "1"
            if row[f"eligible_{purpose}"] not in {"0", "1"}:
                raise InputIntegrityError(f"TARGET_LEDGER_FLAG_INVALID {key}/{purpose}")
            if ledger_flag and not approved:
                raise InputIntegrityError(f"TARGET_LEDGER_ESCALATES_QUARANTINED_LABEL {key}/{purpose}")
        if row["event_count_match"] not in {"0", "1"}:
            raise InputIntegrityError(f"TARGET_EVENT_MATCH_FLAG_INVALID {key}")
        if row["event_count_match"] != "1" or row["event_disposition"] != "ACCEPT":
            if any(row[f"eligible_{purpose}"] == "1" for purpose in approved_flags):
                raise InputIntegrityError(f"TARGET_LEDGER_ESCALATES_EVENT_MISMATCH {key}")
        count_value = _int(row["pbp_event_count"], f"target_event_count/{key}", optional=True)
        target = TargetValue(
            game_id=label.game_id, player_id=label.player_id, statistic=label.statistic,
            official_value=label.official_value, accepted_value=label.accepted_value,
            quality_status=label.quality_status, reason_code=label.reason_code,
            audit_reason_code=row["reason_code"], source_issue_id=row["source_issue_id"],
            eligible_training=label.eligible_training,
            eligible_evaluation=label.eligible_evaluation,
            eligible_grading=label.eligible_grading,
            audit_eligible_training=row["eligible_training"] == "1",
            audit_eligible_evaluation=row["eligible_evaluation"] == "1",
            audit_eligible_grading=row["eligible_grading"] == "1",
            audit_event_count=count_value,
            audit_event_count_match=row["event_count_match"] == "1",
            audit_event_disposition=row["event_disposition"],
            purpose_values={"training": None, "evaluation": None, "grading": None},
        )
        flat_targets.append(target)
        targets_by_game[label.game_id].append(target)
        target_index[key] = target

    for purpose in ("training", "evaluation", "grading"):
        purpose_reader = module.iter_nhl_research_labels(
            purpose=purpose, path=label_path, summary_path=summary_path)
        seen_purpose = 0
        for label in purpose_reader:
            key = f"{label.game_id}:{label.player_id}:{label.statistic}"
            target = target_index.get(key)
            if target is None:
                raise InputIntegrityError(f"TARGET_PURPOSE_ROW_NOT_IN_AUDIT {purpose}/{key}")
            eligible = getattr(target, f"eligible_{purpose}")
            if not eligible:
                raise InputIntegrityError(f"TARGET_PURPOSE_READER_ESCALATION {purpose}/{key}")
            if label.value != label.accepted_value:
                raise InputIntegrityError(f"APPROVED_LABEL_READER_VALUE_CONTRACT {purpose}/{key}")
            target.purpose_values[purpose] = label.value
            seen_purpose += 1
        expected_count = sum(bool(getattr(target, f"eligible_{purpose}")) for target in flat_targets)
        if seen_purpose != expected_count:
            raise InputIntegrityError(
                f"TARGET_PURPOSE_POPULATION_LENGTH_MISMATCH {purpose}/{seen_purpose}!={expected_count}")
    for target in flat_targets:
        for purpose in ("training", "evaluation", "grading"):
            eligible = getattr(target, f"eligible_{purpose}")
            if eligible != (target.purpose_values[purpose] is not None):
                raise InputIntegrityError(
                    f"TARGET_PURPOSE_ELIGIBILITY_MISMATCH {target.game_id}:{target.player_id}:"
                    f"{target.statistic}/{purpose}")
    return dict(targets_by_game)


def load_bundle(*, artifact_dir: Path = DEFAULT_ARTIFACT_DIR,
                official_dir: Path = DEFAULT_OFFICIAL_DIR,
                label_path: Path = DEFAULT_LABEL_DIR / "research_label_quality.csv",
                label_summary_path: Path | None = None,
                pins_path: Path = HERE / "SOURCE-PINS.json") -> InputBundle:
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    if pins["base_commit"] != "33c6b8fad5c36fd7749557c6b56bb21898e33135":
        raise InputIntegrityError("SOURCE_PINS_BASE_COMMIT_MISMATCH")
    if label_summary_path is None:
        label_summary_path = official_dir / "research_label_summary.json"

    for name, expected in pins["artifacts"].items():
        _verify_hash(artifact_dir / name, expected, name)
    for name, expected in pins["official_artifacts"].items():
        _verify_hash(official_dir / name, expected, name)
    label_pin = pins["approved_label_artifact"]
    if sha256_file(label_path) != label_pin["sha256"]:
        raise InputIntegrityError(f"APPROVED_LABEL_HASH_MISMATCH {label_path}")

    frame_rows = list(_csv_rows(official_dir / "canonical_frame.csv"))
    if len(frame_rows) != pins["expected_population"]["games"]:
        raise InputIntegrityError(f"CANONICAL_FRAME_COUNT_MISMATCH {len(frame_rows)}")
    frame_by_id = {row["game_id"]: row for row in frame_rows}
    if len(frame_by_id) != len(frame_rows):
        raise InputIntegrityError("CANONICAL_FRAME_DUPLICATE_GAME_ID")

    metrics = list(_csv_rows(artifact_dir / "game_metrics.csv"))
    metrics_by_id = {row["game_id"]: row for row in metrics}
    if len(metrics_by_id) != len(metrics) or metrics_by_id.keys() != frame_by_id.keys():
        raise InputIntegrityError("GAME_METRICS_FRAME_POPULATION_MISMATCH")

    sog_by_id_side: dict[tuple[str, str], int] = {}
    for row in _csv_rows(official_dir / "official_team_sog_validation.csv"):
        key = (row["game_id"], row["side"])
        if key in sog_by_id_side or row["side"] not in {"home", "away"}:
            raise InputIntegrityError(f"OFFICIAL_TEAM_SOG_DUPLICATE_OR_SIDE_INVALID {key}")
        sog_by_id_side[key] = _int(row["official_team_sog"], f"official_team_sog/{key}")
    if len(sog_by_id_side) != 2 * len(frame_by_id):
        raise InputIntegrityError(f"OFFICIAL_TEAM_SOG_COVERAGE_MISMATCH {len(sog_by_id_side)}")

    games: dict[str, GameDefinition] = {}
    season_counts: Counter[int] = Counter()
    for gid, frame in frame_by_id.items():
        metric = metrics_by_id[gid]
        if frame["home_team"] != metric["pbp_home_abbrev"] or frame["away_team"] != metric["pbp_away_abbrev"]:
            raise InputIntegrityError(f"PBP_FRAME_TEAM_IDENTITY_MISMATCH {gid}")
        if metric["pbp_team_identity_valid"] != "True":
            raise InputIntegrityError(f"PBP_TEAM_IDENTITY_NOT_ACCEPTED {gid}")
        home_id = _int(metric["pbp_home_team_id"], f"home_team_id/{gid}")
        away_id = _int(metric["pbp_away_team_id"], f"away_team_id/{gid}")
        if home_id == away_id:
            raise InputIntegrityError(f"PBP_TEAM_IDS_NOT_DISTINCT {gid}")
        official_home_score = _int(frame["canonical_home_score"], f"home_score/{gid}")
        official_away_score = _int(frame["canonical_away_score"], f"away_score/{gid}")
        official_home_sog = sog_by_id_side[(gid, "home")]
        official_away_sog = sog_by_id_side[(gid, "away")]
        if (_int(metric["official_home_score"], f"metric_home_score/{gid}") != official_home_score or
                _int(metric["official_away_score"], f"metric_away_score/{gid}") != official_away_score or
                _int(metric["official_home_sog"], f"metric_home_sog/{gid}") != official_home_sog or
                _int(metric["official_away_sog"], f"metric_away_sog/{gid}") != official_away_sog):
            raise InputIntegrityError(f"OFFICIAL_OUTCOME_LEDGER_CONFLICT {gid}")
        season = _int(frame["season"], f"season/{gid}")
        if season != _int(metric["season"], f"metric_season/{gid}"):
            raise InputIntegrityError(f"GAME_SEASON_CONFLICT {gid}")
        season_counts[season] += 1
        games[gid] = GameDefinition(
            game_id=gid, season=season, game_date=frame["game_date"],
            home_team=frame["home_team"], away_team=frame["away_team"],
            home_team_id=home_id, away_team_id=away_id,
            official_home_score=official_home_score, official_away_score=official_away_score,
            official_home_sog=official_home_sog, official_away_sog=official_away_sog,
            score_disposition=metric["team_score_target_disposition"],
            sog_disposition=metric["team_sog_target_disposition"],
        )

    expected_seasons = {int(k): v for k, v in pins["expected_population"]["seasons"].items()}
    if dict(season_counts) != expected_seasons:
        raise InputIntegrityError(f"SEASON_COVERAGE_MISMATCH {dict(season_counts)}")

    provenance_rows: dict[str, dict[str, SourceIdentity]] = defaultdict(dict)
    full_frame_hashes: dict[str, str] = {}
    for row in _csv_rows(artifact_dir / "game_source_provenance.csv.gz", compressed=True):
        gid, kind = row["game_id"], row["source_kind"]
        if gid not in games or kind in provenance_rows[gid]:
            raise InputIntegrityError(f"SOURCE_PROVENANCE_DUPLICATE_OR_EXTRA {gid}/{kind}")
        source = _source_identity(row)
        if source.canonical_frame_sha256 != pins["canonical_frame_sha256"]:
            raise InputIntegrityError(f"PROVENANCE_FRAME_HASH_MISMATCH {gid}/{kind}")
        if source.audit_version != "nhl-fullframe-event-audit-2026-10-21-v1":
            raise InputIntegrityError(f"AUDIT_VERSION_MISMATCH {gid}/{kind}/{source.audit_version}")
        _validate_source_url(gid, source)
        if source.payload_rows <= 0 or source.bytes_raw <= 0 or source.bytes_gz <= 0:
            raise InputIntegrityError(f"SOURCE_PAYLOAD_METADATA_INVALID {gid}/{kind}")
        provenance_rows[gid][kind] = source
        full_frame_hashes[gid] = row["full_frame_games_sha256"]
    if set(provenance_rows) != set(games) or any(set(pair) != {"pbp", "shifts"} for pair in provenance_rows.values()):
        raise InputIntegrityError("SOURCE_PROVENANCE_COVERAGE_MISMATCH")

    provenance: dict[str, GameProvenance] = {}
    for gid, pair in provenance_rows.items():
        expected_events = _int(metrics_by_id[gid]["event_rows"], f"metric_event_rows/{gid}")
        if pair["pbp"].payload_rows != expected_events:
            raise InputIntegrityError(f"PBP_SOURCE_ROW_COUNT_METRIC_MISMATCH {gid}")
        if pair["pbp"].sha256_raw == pair["shifts"].sha256_raw:
            raise InputIntegrityError(f"PBP_SHIFT_SOURCE_HASH_COLLISION {gid}")
        provenance[gid] = GameProvenance(
            game_id=gid, season=games[gid].season, pbp=pair["pbp"], shifts=pair["shifts"],
            frame_sha256=pins["canonical_frame_sha256"], full_frame_games_sha256=full_frame_hashes[gid],
        )

    targets_by_game = _approved_targets(
        pins, label_path, label_summary_path,
        artifact_dir / "target_reconciliation.csv.gz")

    return InputBundle(
        artifact_dir=artifact_dir, official_dir=official_dir, label_path=label_path,
        label_summary_path=label_summary_path, pins=pins, games=games,
        provenance=provenance, targets_by_game=dict(targets_by_game),
        game_metrics=metrics_by_id, official_sog_by_game_side=sog_by_id_side,
    )


def _optional_decimal(value: str | None, label: str):
    if value is None or value == "":
        return None
    from decimal import Decimal, InvalidOperation
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise InputIntegrityError(f"DECIMAL_INVALID {label}={value!r}") from exc
    if not number.is_finite():
        raise InputIntegrityError(f"DECIMAL_NOT_FINITE {label}={value!r}")
    return number


def _normalized_event(row: dict[str, str], bundle: InputBundle) -> NormalizedEvent:
    gid = row["game_id"]
    provenance = bundle.provenance.get(gid)
    if provenance is None:
        raise InputIntegrityError(f"EVENT_WITHOUT_SOURCE_PROVENANCE {gid}")
    season = _int(row["season"], f"event_season/{gid}")
    if season != bundle.games[gid].season:
        raise InputIntegrityError(f"EVENT_SEASON_MISMATCH {gid}/{row['source_event_id']}")
    source_event_id = row["source_event_id"]
    if not source_event_id:
        raise InputIntegrityError(f"SOURCE_EVENT_ID_MISSING {gid}")
    def maybe_text(key: str) -> str | None:
        value = row.get(key, "")
        return value if value != "" else None
    quality = Quality(
        source_order=row["source_order_disposition"], event=row["event_disposition"],
        team_count=row["team_count_disposition"], player_identity=row["player_identity_disposition"],
        shooter_identity=row["shooter_identity_status"],
        goalie_identity=row["goalie_identity_status"], goalie_event=row["goalie_event_disposition"],
        spatial=row["spatial_model_disposition"], shot_type=row["shot_type_disposition"],
        penalty_timing=row["penalty_timing_disposition"],
        penalty_duration=row["penalty_duration_disposition"],
        penalty_identity=row["penalty_identity_disposition"],
        period_number=row["period_number_disposition"],
        period_number_reason_code=row["period_number_reason_code"],
        situation_deployment=row["situation_deployment_disposition"],
        situation_shift_status=row["situation_shift_status"],
        shooter_shift_status=row["shooter_shift_status"],
        shooter_on_ice=row["shooter_on_ice_disposition"],
        goalie_shift_status=row["goalie_shift_status"],
        goalie_shift_comparison=row["goalie_shift_comparison_disposition"],
        reason_codes=tuple(code for code in row["reason_codes"].split(";") if code),
    )
    return NormalizedEvent(
        game_id=gid, season=season, source_event_id=source_event_id,
        source_play_index=_int(row["source_play_index"], f"source_play_index/{gid}/{source_event_id}"),
        publisher_sort_order=_int(row["publisher_sort_order"], f"publisher_sort_order/{gid}/{source_event_id}"),
        event_type=row["event_type"],
        period_number=_int(row["period_number"], f"period_number/{gid}/{source_event_id}"),
        period_type=row["period_type"], time_in_period=row["time_in_period"],
        event_owner_team_id=_int(row["event_owner_team_id"], f"event_owner/{gid}/{source_event_id}", optional=True),
        event_owner_side_source=maybe_text("event_owner_side"),
        credited_shooter_id=_int(row["credited_shooter_id"], f"shooter/{gid}/{source_event_id}", optional=True),
        shooter_id_source=maybe_text("shooter_id_source"),
        goalie_in_net_id=_int(row["goalie_in_net_id"], f"goalie/{gid}/{source_event_id}", optional=True),
        situation_code=maybe_text("situation_code"), source_strength_state=maybe_text("strength_state"),
        ordinary_shot_eligible=(None if row["ordinary_shot_eligible"] == "" else
                                _bool(row["ordinary_shot_eligible"], f"ordinary_shot_eligible/{gid}/{source_event_id}")),
        shot_x=_optional_decimal(row["shot_x"], f"shot_x/{gid}/{source_event_id}"),
        shot_y=_optional_decimal(row["shot_y"], f"shot_y/{gid}/{source_event_id}"),
        shot_type=maybe_text("shot_type"), zone_code=maybe_text("zone_code"),
        miss_reason=maybe_text("miss_reason"), penalty_type_code=maybe_text("penalty_type_code"),
        penalty_reason=maybe_text("penalty_reason"),
        penalty_duration_minutes=_optional_decimal(row["penalty_duration_minutes"], f"penalty_duration/{gid}/{source_event_id}"),
        penalty_committed_by_player_id=_int(row["penalty_committed_by_player_id"], f"penalty_committed/{gid}/{source_event_id}", optional=True),
        penalty_drawn_by_player_id=_int(row["penalty_drawn_by_player_id"], f"penalty_drawn/{gid}/{source_event_id}", optional=True),
        penalty_served_by_player_id=_int(row["penalty_served_by_player_id"], f"penalty_served/{gid}/{source_event_id}", optional=True),
        source_retrieved_at_utc=provenance.pbp.retrieved_at_utc,
        provenance=provenance, quality=quality,
    )


def iter_game_event_groups(bundle: InputBundle, *, game_ids: set[str] | None = None
                           ) -> Iterator[tuple[str, list[NormalizedEvent]]]:
    """Stream source-ordered rows, yielding one game at a time; never re-sort."""
    path = bundle.artifact_dir / "event_dispositions.csv.gz"
    previous_game: str | None = None
    seen_games: set[str] = set()
    yielded_games: set[str] = set()
    current: list[NormalizedEvent] = []
    total = 0
    per_game_count: Counter[str] = Counter()
    for row in _csv_rows(path, compressed=True):
        gid = row["game_id"]
        if gid not in bundle.games:
            raise InputIntegrityError(f"EVENT_GAME_OUTSIDE_PINNED_FRAME {gid}")
        if previous_game is not None and gid != previous_game:
            if gid in seen_games:
                raise InputIntegrityError(f"EVENT_GAME_ROWS_NOT_CONTIGUOUS {gid}")
            if game_ids is None or previous_game in game_ids:
                yielded_games.add(previous_game)
                yield previous_game, current
            seen_games.add(previous_game)
            current = []
        previous_game = gid
        if game_ids is None or gid in game_ids:
            current.append(_normalized_event(row, bundle))
        per_game_count[gid] += 1
        total += 1
    if previous_game is not None:
        if game_ids is None or previous_game in game_ids:
            yielded_games.add(previous_game)
            yield previous_game, current
        seen_games.add(previous_game)
    if total != bundle.pins["expected_population"]["pbp_events"]:
        raise InputIntegrityError(f"EVENT_LEDGER_POPULATION_MISMATCH {total}")
    if set(per_game_count) != set(bundle.games):
        raise InputIntegrityError("EVENT_LEDGER_GAME_COVERAGE_MISMATCH")
    for gid, count in per_game_count.items():
        if count != bundle.provenance[gid].pbp.payload_rows:
            raise InputIntegrityError(f"EVENT_LEDGER_SOURCE_ROW_COUNT_MISMATCH {gid}/{count}")
    if game_ids is not None and not game_ids.issubset(set(bundle.games)):
        raise InputIntegrityError(f"COHORT_GAME_OUTSIDE_FRAME {sorted(game_ids - set(bundle.games))}")
    if game_ids is not None and yielded_games != game_ids:
        raise InputIntegrityError(f"COHORT_EVENT_COVERAGE {sorted(game_ids - yielded_games)}")


def verify_source_body(raw_dir: Path, game_id: str, source: SourceIdentity) -> None:
    """Rehash one compressed/raw body and validate game ID plus payload shape."""
    path = raw_dir / source.source_kind / f"{game_id}.json.gz"
    if not path.is_file():
        raise InputIntegrityError(f"RAW_BODY_MISSING {game_id}/{source.source_kind}: {path}")
    compressed_hash = sha256_file(path)
    compressed_size = path.stat().st_size
    if compressed_hash != source.sha256_gz or compressed_size != source.bytes_gz:
        raise InputIntegrityError(f"RAW_COMPRESSED_BODY_MISMATCH {game_id}/{source.source_kind}")
    raw_hash = hashlib.sha256()
    raw_size = 0
    chunks: list[bytes] = []
    try:
        with gzip.open(path, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                raw_hash.update(chunk)
                raw_size += len(chunk)
                chunks.append(chunk)
    except (OSError, EOFError) as exc:
        raise InputIntegrityError(f"RAW_GZIP_INVALID {game_id}/{source.source_kind}: {exc}") from exc
    if raw_hash.hexdigest() != source.sha256_raw or raw_size != source.bytes_raw:
        raise InputIntegrityError(f"RAW_DECOMPRESSED_BODY_MISMATCH {game_id}/{source.source_kind}")
    try:
        payload = json.loads(b"".join(chunks))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputIntegrityError(f"RAW_JSON_INVALID {game_id}/{source.source_kind}") from exc

    sidecar_path = raw_dir / source.source_kind / f"{game_id}.meta.json"
    if not sidecar_path.is_file():
        raise InputIntegrityError(f"RAW_SIDECAR_MISSING {game_id}/{source.source_kind}")
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    if str(sidecar.get("game_id")) != game_id or sidecar.get("kind") != source.source_kind:
        raise InputIntegrityError(f"RAW_SIDECAR_IDENTITY_MISMATCH {game_id}/{source.source_kind}")
    if sidecar.get("bytes_raw") != source.bytes_raw or sidecar.get("bytes_gz") != source.bytes_gz:
        raise InputIntegrityError(f"RAW_SIDECAR_SIZE_MISMATCH {game_id}/{source.source_kind}")
    if sidecar.get("rows") != source.payload_rows:
        raise InputIntegrityError(f"RAW_SIDECAR_ROW_COUNT_MISMATCH {game_id}/{source.source_kind}")
    for sidecar_key, expected in (("sha256_raw", source.sha256_raw), ("sha256_gz", source.sha256_gz)):
        if sidecar.get(sidecar_key) != expected:
            raise InputIntegrityError(f"RAW_SIDECAR_HASH_MISMATCH {game_id}/{source.source_kind}/{sidecar_key}")
    if sidecar.get("http_status") != 200 or sidecar.get("content_type") != "application/json":
        raise InputIntegrityError(f"RAW_SIDECAR_RESPONSE_MISMATCH {game_id}/{source.source_kind}")

    if source.source_kind == "pbp":
        plays = payload.get("plays") if isinstance(payload, dict) else None
        if str(payload.get("id")) != game_id or not isinstance(plays, list) or len(plays) != source.payload_rows:
            raise InputIntegrityError(f"RAW_PBP_PAYLOAD_SHAPE_OR_GAME_ID {game_id}")
        last_sort: int | None = None
        seen_ids: set[str] = set()
        for index, play in enumerate(plays):
            if not isinstance(play, dict):
                raise InputIntegrityError(f"RAW_PBP_PLAY_NOT_OBJECT {game_id}/{index}")
            event_id, sort_order = play.get("eventId"), play.get("sortOrder")
            if event_id is None or sort_order is None or not isinstance(play.get("periodDescriptor"), dict):
                raise InputIntegrityError(f"RAW_PBP_PLAY_REQUIRED_FIELDS_MISSING {game_id}/{index}")
            event_key = str(event_id)
            current_sort = int(sort_order)
            if event_key in seen_ids or (last_sort is not None and current_sort <= last_sort):
                raise InputIntegrityError(f"RAW_PBP_ID_OR_ORDER_CONFLICT {game_id}/{index}")
            seen_ids.add(event_key)
            last_sort = current_sort
    else:
        shifts = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(shifts, list) or len(shifts) != source.payload_rows:
            raise InputIntegrityError(f"RAW_SHIFT_PAYLOAD_SHAPE_OR_COUNT {game_id}")
        if payload.get("total") != source.payload_rows:
            raise InputIntegrityError(f"RAW_SHIFT_TOTAL_MISMATCH {game_id}")
        for index, shift in enumerate(shifts):
            if not isinstance(shift, dict) or str(shift.get("gameId")) != game_id:
                raise InputIntegrityError(f"RAW_SHIFT_GAME_ID_MISMATCH {game_id}/{index}")


def verify_all_source_bodies(bundle: InputBundle, raw_dir: Path) -> dict[str, int]:
    counts = Counter()
    for gid in bundle.games:
        for kind in ("pbp", "shifts"):
            verify_source_body(raw_dir, gid, getattr(bundle.provenance[gid], "pbp" if kind == "pbp" else "shifts"))
            counts[kind] += 1
    return dict(counts)


def iter_shift_intervals(bundle: InputBundle) -> Iterator[NormalizedShiftInterval]:
    """Yield pinned shift dispositions with game provenance available by key."""
    for row in _csv_rows(bundle.artifact_dir / "player_shift_dispositions.csv.gz", compressed=True):
        gid = row["game_id"]
        if gid not in bundle.provenance:
            raise InputIntegrityError(f"SHIFT_LEDGER_GAME_OUTSIDE_FRAME {gid}")
        if row["disposition"] not in {"ACCEPT", "QUARANTINE", "REJECT"}:
            raise InputIntegrityError(f"SHIFT_DISPOSITION_UNKNOWN {gid}/{row['interval_id']}")
        yield NormalizedShiftInterval(
            game_id=gid, season=_int(row["season"], f"shift_season/{gid}"),
            source_shift_id=row["interval_id"], player_id=row["player_id"],
            player_type=row["player_type"], period_number=_int(row["period"], f"shift_period/{gid}"),
            start_seconds=_int(row["start_seconds"], f"shift_start/{gid}", optional=True),
            end_seconds=_int(row["end_seconds"], f"shift_end/{gid}", optional=True),
            duration_seconds=_int(row["duration_seconds"], f"shift_duration/{gid}", optional=True),
            official_toi_seconds=_int(row["official_toi_seconds"], f"shift_official_toi/{gid}", optional=True),
            player_game_shift_toi_seconds=_int(row["shift_toi_seconds_player_game"], f"shift_toi/{gid}", optional=True),
            toi_delta_seconds=_int(row["toi_delta_seconds"], f"shift_delta/{gid}", optional=True),
            disposition=row["disposition"],
            reason_codes=tuple(code for code in row["reason_codes"].split(";") if code),
            provenance=bundle.provenance[gid],
        )


def verify_issue_ledger(
    bundle: InputBundle,
) -> tuple[int, Counter[str], dict[tuple[str, str, str], dict[str, str]], list[dict[str, str]]]:
    count = 0
    reasons: Counter[str] = Counter()
    target_issues: dict[tuple[str, str, str], dict[str, str]] = {}
    team_sog_issues: list[dict[str, str]] = []
    for row in _csv_rows(bundle.artifact_dir / "unresolved_issues.csv.gz", compressed=True):
        if row["game_id"] not in bundle.games:
            raise InputIntegrityError(f"ISSUE_GAME_OUTSIDE_FRAME {row['game_id']}")
        count += 1
        reasons[row["reason_code"]] += 1
        if row["component"] == "target_reconciliation" and row["subject_type"] == "player_stat":
            try:
                player_id, statistic = row["subject_id"].split("/", 1)
            except ValueError as exc:
                raise InputIntegrityError(
                    f"ISSUE_PLAYER_STAT_SUBJECT_MALFORMED {row['game_id']}/{row['subject_id']}"
                ) from exc
            key = (row["game_id"], player_id, statistic)
            if key in target_issues:
                raise InputIntegrityError(f"DUPLICATE_TARGET_ISSUE {key}")
            target_issues[key] = row
        if row["reason_code"] == "PBP_SOG_VS_OFFICIAL":
            team_sog_issues.append(row)
    return count, reasons, target_issues, team_sog_issues
