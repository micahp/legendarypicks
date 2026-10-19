"""Schema validation for immutable NFL prop capture records."""

from __future__ import annotations

import math
import re
from typing import Any


SCHEMA_VERSION = "nfl-prop-capture.v1"
OUTCOME_STATES = {"true_zero", "resolved", "dnp", "missing", "unresolved", "void"}
SETTLEMENT_STATES = {"win", "loss", "push", "void", "dnp", "missing", "unresolved"}
NO_CARRIES_MARKETS = {"carries", "rush_attempts", "rushing_attempts", "total_rush_attempts"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _utc(value: Any) -> bool:
    return isinstance(value, str) and value.endswith("Z")


def validate_row(row: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(row, dict):
        return ["row is not an object"]
    required = (
        "schema_version", "observation_id", "capture_run_id", "capture_mode", "cp4_evidence_eligible",
        "league", "season", "competition", "event", "player", "market", "line", "side", "book",
        "forecast_created_at", "information_cutoff", "lock_time", "pre_kickoff_assertion", "pmf",
        "outcome_state", "settlement_state", "source_commit", "input_snapshot_sha256",
        "parameter_file_sha256", "capture_harness_sha256",
    )
    for key in required:
        if key not in row or row[key] is None:
            errors.append(f"missing {key}")
    if errors:
        return errors

    if row["schema_version"] != SCHEMA_VERSION:
        errors.append("unsupported schema_version")
    if row["capture_mode"] not in {"live", "backfill"}:
        errors.append("capture_mode must be live or backfill")
    if row["league"] != "nfl" or row["competition"] != "REG":
        errors.append("league/competition must be nfl/REG")
    if row["market"].get("stat") in {"car", "carries"} or row["market"].get("provider_market") in NO_CARRIES_MARKETS:
        errors.append("carries markets are excluded from this capture")
    if row["side"] not in {"over", "under"}:
        errors.append("side must be over or under")
    for key in ("source_commit",):
        if not isinstance(row[key], str) or not re.fullmatch(r"[0-9a-f]{7,40}", row[key]):
            errors.append(f"{key} is not a git SHA")
    for key in ("input_snapshot_sha256", "parameter_file_sha256", "capture_harness_sha256"):
        if not isinstance(row[key], str) or not SHA256_RE.fullmatch(row[key]):
            errors.append(f"{key} is not a SHA-256")

    if not _utc(row["forecast_created_at"]):
        errors.append("forecast_created_at must be UTC ISO-8601 ending in Z")
    if not _utc(row["information_cutoff"]):
        errors.append("information_cutoff must be UTC ISO-8601 ending in Z")
    if not _utc(row["lock_time"]):
        errors.append("lock_time must be UTC ISO-8601 ending in Z")
    event = row["event"]
    if not isinstance(event, dict) or not event.get("id") or not _utc(event.get("scheduled_start_utc")):
        errors.append("event id and scheduled_start_utc are required")
    player = row["player"]
    if (not isinstance(player, dict) or player.get("id") is None or not player.get("team_id")
            or not player.get("opponent_id") or player.get("identity_state") != "resolved"):
        errors.append("canonical player, team, and opponent ids are required")
    market = row["market"]
    if not isinstance(market, dict) or not market.get("provider_market") or not market.get("stat") or not market.get("units"):
        errors.append("market/stat/units are required")
    if not isinstance(row["line"], (int, float)) or not math.isfinite(row["line"]):
        errors.append("line must be finite numeric")
    if not isinstance(row["book"], str) or not row["book"]:
        errors.append("book is required")

    proof = row["pre_kickoff_assertion"]
    if not isinstance(proof, dict) or proof.get("available_before_cutoff") not in {True, False} or not proof.get("basis"):
        errors.append("pre-kickoff proof object is missing required assertion fields")
    elif row["capture_mode"] == "backfill":
        if proof.get("available_before_cutoff") is not False or proof.get("status") != "not_prospective":
            errors.append("backfill must carry an explicit negative pre-kickoff assertion")
        if row["cp4_evidence_eligible"] is not False:
            errors.append("backfill cannot be CP4 evidence")
    else:
        if proof.get("available_before_cutoff") is not True or proof.get("status") != "verified":
            errors.append("live row lacks verified pre-kickoff proof")
        if row["cp4_evidence_eligible"] is not True:
            errors.append("live row must state CP4 eligibility explicitly")
        if row["forecast_created_at"] > row["lock_time"] or row["information_cutoff"] > row["lock_time"]:
            errors.append("live forecast or information cutoff is after lock")

    pmf = row["pmf"]
    if not isinstance(pmf, dict):
        errors.append("pmf must be an object")
    else:
        support = pmf.get("support")
        probabilities = pmf.get("probabilities")
        if not isinstance(support, dict) or not isinstance(support.get("min"), int) or not isinstance(support.get("max"), int):
            errors.append("pmf support bounds are missing")
        elif not isinstance(probabilities, list) or len(probabilities) != support["max"] - support["min"] + 1:
            errors.append("pmf probabilities do not span declared support")
        else:
            try:
                vals = [float(p) for p in probabilities]
                total = math.fsum(vals)
                tolerance = float(pmf.get("mass_tolerance"))
                if any(not math.isfinite(p) or p < 0 for p in vals):
                    errors.append("pmf has non-finite or negative mass")
                if not math.isfinite(tolerance) or tolerance <= 0 or abs(total - 1.0) > tolerance:
                    errors.append("pmf mass does not sum to one within its stated tolerance")
                if not isinstance(pmf.get("endpoint_mass"), dict):
                    errors.append("pmf endpoint masses are missing")
                if not isinstance(pmf.get("tail_mass"), dict) or pmf["tail_mass"].get("below_support") != 0.0 or pmf["tail_mass"].get("above_support") != 0.0:
                    errors.append("pmf empirical tail masses are missing or nonzero")
                if not isinstance(pmf.get("truncation"), dict) or pmf["truncation"].get("draws_outside_support") != 0:
                    errors.append("pmf truncation accounting is missing")
                renorm = pmf.get("renormalization")
                if not isinstance(renorm, dict) or renorm.get("factor") != 1.0:
                    errors.append("pmf renormalization record is missing or unexpected")
            except (TypeError, ValueError):
                errors.append("pmf mass fields are malformed")
        if not isinstance(pmf.get("sample_count"), int) or pmf.get("sample_count", 0) <= 0:
            errors.append("pmf sample_count must be positive")

    if row["outcome_state"] not in OUTCOME_STATES:
        errors.append("outcome_state is missing or unknown")
    if row["settlement_state"] not in SETTLEMENT_STATES:
        errors.append("settlement_state is missing or unknown")
    if row["outcome_state"] == "true_zero" and row.get("actual_value") != 0:
        errors.append("true_zero requires actual_value=0")
    if row["outcome_state"] in {"dnp", "missing", "unresolved", "void"} and row.get("actual_value") is not None:
        errors.append(f"{row['outcome_state']} outcome must not carry actual_value")
    return errors
