"""Hash-verified, eligibility-aware reader for NHL official research labels.

Model targets and historical features must use ``value`` from this reader.
The original official value and quality status remain available for audits.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator, Literal


HERE = Path(__file__).resolve().parent
ARTIFACT_FILENAME = "research_label_quality.csv"
DEFAULT_LABEL_PATH = Path(
    os.environ.get(
        "NHL_RESEARCH_LABEL_PATH",
        "/root/lp-data/nhl-official-outcome-quality-adjudication-2026-10-20/research_label_quality.csv",
    )
)
DEFAULT_SUMMARY_PATH = HERE / "research_label_summary.json"
QUALITY_STATUSES = {"VERIFIED", "ADJUDICATED", "QUARANTINED", "NOT_APPLICABLE"}
RESEARCHABLE_STATUSES = {"VERIFIED", "ADJUDICATED"}
STATISTICS = {"SOG", "SAVES", "SHOTS_AGAINST", "GOALS_AGAINST"}
PURPOSES = {"training", "evaluation", "grading", "feature", "audit"}
_VERIFIED_ARTIFACTS: dict[tuple[str, str, int], tuple[int, int, int, int]] = {}
REQUIRED_COLUMNS = {
    "label_id", "record_key", "game_id", "season", "game_date", "team", "opponent", "home_away",
    "player_id", "statistic", "official_value", "accepted_value", "corrected_value", "quality_status",
    "reason_code", "reason", "adjudication_id", "source_issue_id", "original_gamecenter_raw_sha256",
    "independent_evidence_url", "independent_evidence_sha256", "eligible_training",
    "eligible_evaluation", "eligible_grading",
}


@dataclass(frozen=True)
class NHLResearchLabel:
    label_id: str
    record_key: str
    game_id: str
    season: int
    game_date: date
    team: str
    opponent: str
    home_away: str
    player_id: str
    statistic: str
    value: int | None
    official_value: int | None
    accepted_value: int | None
    corrected_value: int | None
    quality_status: str
    reason_code: str
    reason: str
    adjudication_id: str
    source_issue_id: str
    eligible_training: bool
    eligible_evaluation: bool
    eligible_grading: bool


def _sha256_file(handle: io.BufferedReader) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def _file_token(stat_result: os.stat_result) -> tuple[int, int, int, int]:
    return (stat_result.st_dev, stat_result.st_ino, stat_result.st_size, stat_result.st_mtime_ns)


def _optional_nonnegative_integer(value: str, label: str) -> int | None:
    if value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"INVALID_INTEGER_LABEL_VALUE {label}: {value!r}") from exc
    if parsed < 0:
        raise ValueError(f"NEGATIVE_LABEL_VALUE {label}: {value!r}")
    return parsed


def _boolean(value: str, label: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"INVALID_LABEL_ELIGIBILITY {label}: {value!r}")


def _expected_artifact(summary_path: Path) -> tuple[str, int]:
    if not summary_path.is_file():
        raise FileNotFoundError(f"LABEL_SUMMARY_MISSING {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    expected = summary.get("derived_output_sha256", {}).get(ARTIFACT_FILENAME)
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError(f"LABEL_SUMMARY_HASH_MISSING {summary_path}/{ARTIFACT_FILENAME}")
    artifact = summary.get("label_artifact", {})
    if artifact.get("filename") != ARTIFACT_FILENAME or artifact.get("sha256") != expected:
        raise ValueError(f"LABEL_ARTIFACT_MANIFEST_MISMATCH {summary_path}")
    if artifact.get("git_tracked") is not False or not artifact.get("storage_path"):
        raise ValueError(f"LABEL_ARTIFACT_STORAGE_UNDECLARED {summary_path}")
    size = artifact.get("bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ValueError(f"LABEL_ARTIFACT_SIZE_MISSING {summary_path}")
    return expected, size


def _parse_row(raw: dict[str, str], row_number: int, purpose: str) -> NHLResearchLabel:
    label = raw.get("label_id", f"row-{row_number}")
    required = REQUIRED_COLUMNS - raw.keys()
    if required:
        raise ValueError(f"LABEL_COLUMNS_MISSING row={row_number}: {sorted(required)}")
    game_id, player_id = raw["game_id"], raw["player_id"]
    if not game_id.isdigit() or not player_id.isdigit() or int(player_id) <= 0:
        raise ValueError(f"INVALID_NUMERIC_LABEL_ID {label}: game={game_id!r} player={player_id!r}")
    if raw["statistic"] not in STATISTICS:
        raise ValueError(f"UNKNOWN_LABEL_STATISTIC {label}: {raw['statistic']!r}")
    status = raw["quality_status"]
    if status not in QUALITY_STATUSES:
        raise ValueError(f"UNKNOWN_QUALITY_STATUS {label}: {status!r}")
    try:
        game_date = date.fromisoformat(raw["game_date"])
        season = int(raw["season"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"INVALID_LABEL_GAME_DATE_OR_SEASON {label}") from exc

    official_value = _optional_nonnegative_integer(raw["official_value"], f"{label}/official")
    accepted_value = _optional_nonnegative_integer(raw["accepted_value"], f"{label}/accepted")
    corrected_value = _optional_nonnegative_integer(raw["corrected_value"], f"{label}/corrected")
    eligibility = {
        name: _boolean(raw[f"eligible_{name}"], f"{label}/{name}")
        for name in ("training", "evaluation", "grading")
    }
    trusted = status in RESEARCHABLE_STATUSES
    if trusted and accepted_value is None:
        raise ValueError(f"TRUSTED_LABEL_HAS_NO_ACCEPTED_VALUE {label}")
    if not trusted and (accepted_value is not None or any(eligibility.values())):
        raise ValueError(f"UNTRUSTED_LABEL_MARKED_USABLE {label}/{status}")
    if corrected_value is not None and accepted_value != corrected_value:
        raise ValueError(f"CORRECTED_VALUE_NOT_ACCEPTED {label}")
    if trusted and corrected_value is None and accepted_value != official_value:
        raise ValueError(f"UNEXPLAINED_ACCEPTED_VALUE_CHANGE {label}")
    for name, eligible in eligibility.items():
        if eligible and (not trusted or accepted_value is None):
            raise ValueError(f"INELIGIBLE_LABEL_MARKED_ELIGIBLE {label}/{name}")

    if purpose in {"training", "evaluation", "grading", "feature"}:
        value = accepted_value
    else:
        value = None
    return NHLResearchLabel(
        label_id=label,
        record_key=raw["record_key"],
        game_id=game_id,
        season=season,
        game_date=game_date,
        team=raw["team"],
        opponent=raw["opponent"],
        home_away=raw["home_away"],
        player_id=player_id,
        statistic=raw["statistic"],
        value=value,
        official_value=official_value,
        accepted_value=accepted_value,
        corrected_value=corrected_value,
        quality_status=status,
        reason_code=raw["reason_code"],
        reason=raw["reason"],
        adjudication_id=raw["adjudication_id"],
        source_issue_id=raw["source_issue_id"],
        eligible_training=eligibility["training"],
        eligible_evaluation=eligibility["evaluation"],
        eligible_grading=eligibility["grading"],
    )


def iter_nhl_research_labels(
    *,
    purpose: Literal["training", "evaluation", "grading", "feature", "audit"],
    statistic: str | None = None,
    before_game_date: str | date | None = None,
    path: Path = DEFAULT_LABEL_PATH,
    summary_path: Path = DEFAULT_SUMMARY_PATH,
) -> Iterator[NHLResearchLabel]:
    """Stream quality-controlled labels for an explicit research purpose.

    Training, evaluation, and grading obey their committed row eligibility
    flags. Feature reads require a strict earlier-game date and only expose
    VERIFIED/ADJUDICATED accepted values. Audit reads expose source fields and
    statuses but always set ``value`` to ``None``. A missing feature row remains
    unknown; callers must not turn it into a zero.
    """
    if purpose not in PURPOSES:
        raise ValueError(f"INVALID_RESEARCH_PURPOSE {purpose!r}")
    if statistic is not None and statistic not in STATISTICS:
        raise ValueError(f"INVALID_LABEL_STATISTIC_FILTER {statistic!r}")
    cutoff: date | None = None
    if purpose == "feature":
        if before_game_date is None:
            raise ValueError("FEATURE_CUTOFF_REQUIRED")
        try:
            cutoff = before_game_date if isinstance(before_game_date, date) else date.fromisoformat(before_game_date)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"INVALID_FEATURE_CUTOFF {before_game_date!r}") from exc
    elif before_game_date is not None:
        raise ValueError("CUTOFF_ONLY_VALID_FOR_FEATURE_PURPOSE")

    if not path.is_file():
        raise FileNotFoundError(f"LABEL_ARTIFACT_MISSING {path}")
    expected_hash, expected_bytes = _expected_artifact(summary_path)
    with path.open("rb") as binary:
        initial_token = _file_token(os.fstat(binary.fileno()))
        cache_key = (str(path.resolve()), expected_hash, expected_bytes)
        if _VERIFIED_ARTIFACTS.get(cache_key) != initial_token:
            actual_hash = _sha256_file(binary)
            actual_bytes = binary.tell()
            if actual_hash != expected_hash or actual_bytes != expected_bytes:
                raise ValueError(
                    f"LABEL_ARTIFACT_HASH_MISMATCH expected={expected_hash}/{expected_bytes} "
                    f"actual={actual_hash}/{actual_bytes} path={path}"
                )
            if _file_token(os.fstat(binary.fileno())) != initial_token:
                raise ValueError(f"LABEL_ARTIFACT_CHANGED_DURING_VERIFICATION {path}")
            _VERIFIED_ARTIFACTS[cache_key] = initial_token
        binary.seek(0)
        text = io.TextIOWrapper(binary, encoding="utf-8", newline="")
        try:
            reader = csv.DictReader(text)
            if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise ValueError(f"LABEL_HEADER_INVALID {path}")
            missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames)
            if missing_columns:
                raise ValueError(f"LABEL_COLUMNS_MISSING {path}: {sorted(missing_columns)}")
            seen_ids: set[str] = set()
            for row_number, raw in enumerate(reader, start=2):
                label = _parse_row(raw, row_number, purpose)
                if label.label_id in seen_ids:
                    raise ValueError(f"DUPLICATE_LABEL_ID {label.label_id}")
                seen_ids.add(label.label_id)
                if statistic is not None and label.statistic != statistic:
                    continue
                if purpose == "audit":
                    yield label
                    continue
                if purpose == "feature":
                    if label.quality_status not in RESEARCHABLE_STATUSES or label.accepted_value is None:
                        continue
                    if label.game_date >= cutoff:
                        continue
                    yield label
                    continue
                eligibility = {
                    "training": label.eligible_training,
                    "evaluation": label.eligible_evaluation,
                    "grading": label.eligible_grading,
                }[purpose]
                if eligibility:
                    if label.quality_status not in RESEARCHABLE_STATUSES or label.accepted_value is None:
                        raise ValueError(f"ELIGIBILITY_STATUS_CONFLICT {label.label_id}/{purpose}")
                    yield label
        finally:
            text.detach()
        if _file_token(os.fstat(binary.fileno())) != initial_token:
            _VERIFIED_ARTIFACTS.pop(cache_key, None)
            raise ValueError(f"LABEL_ARTIFACT_CHANGED_DURING_READ {path}")
