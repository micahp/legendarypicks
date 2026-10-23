#!/usr/bin/env python3
"""Read-only verification of the committed NHL JC decision record."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RESULTS = Path(__file__).resolve().parent / "results"
MEMO = ROOT / "docs/research/NHL-JC-CHAIN-DECISION-2026-10-23.md"
OUTPUT = RESULTS / "jc-chain-verification-2026-10-23-v1.json"

PINS = {
    "jc-attribution-jcdiag-2026-10-23-v1.json": "f47910cde7e09865299667c1c2a6603d9c749e48fb1fed3e3eec0c7da5752e8c",
    "jc-diag2-pair-persistence-2026-10-23-v1.json": "54dbb4e6322dc240ac42910f3c69bab9dfcd781c89e234fa2161d8068b8ed3ed",
    "jc-diag3-pair-shrink-2026-10-23-v1.json": "e2003ce0f3702f0d94d2915c512b74320ff4f2aed04b3af5137a3d01286051fd",
    "jc-diag4-additive-offset-2026-10-23-v1.json": "cf9681fa36416ce56996b66c1179c7f17a30a4ed544a0b07b5cd59d896cdc947",
    "jc-diag5-delta-persistence-2026-10-23-v1.json": "9510d70d418c09da63a6218077b8c1e2b7cc9a11e3b7ed82e63a5457c1039099",
    "jc-diag6-distance-conditioned-2026-10-23-v1.json": "8dfe2f551727484e43c612c5e2ede85ce0d237f4f479edb89e7ad1e5e59c62ed",
    "jc-diag7-oos-pair-value-2026-10-23-v1.json": "fa0d853a39cc33591e1157896572c40a58e374270cf26603cd56850ae6311dce",
    "jc-diag8-identity-feasibility-2026-10-23-v1.json": "5a7342f6ef63169b42390bf08ae3c216298bf45c649b8e414fddd8c6a61a34a8",
}
EXPECTED_BYTES = {
    "jc-diag7-oos-pair-value-2026-10-23-v1.json": 76326,
    "jc-diag8-identity-feasibility-2026-10-23-v1.json": 1547298,
}

CITE_RE = re.compile(
    r"\[CITE `([^`]+)`; fields (.*?); SHA-256 `([0-9a-f]{64})`\]"
)

checks: list[dict[str, Any]] = []


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def short(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return rendered if len(rendered) <= 160 else rendered[:157] + "..."


def add_check(
    name: str,
    artifact: str,
    field_path: str,
    expected: Any,
    observed: Any,
    tolerance: float | None = None,
) -> bool:
    if tolerance is not None and isinstance(expected, (int, float)) and isinstance(
        observed, (int, float)
    ) and not isinstance(expected, bool) and not isinstance(observed, bool):
        passed = math.isclose(float(expected), float(observed), rel_tol=0.0, abs_tol=tolerance)
    else:
        passed = expected == observed
    checks.append(
        {
            "name": name,
            "artifact": artifact,
            "field_path": field_path,
            "expected": expected,
            "observed": observed,
            "passed": bool(passed),
            **({"tolerance": tolerance} if tolerance is not None else {}),
        }
    )
    return bool(passed)


def resolve_pointer(root: Any, pointer: str) -> Any:
    current = root
    if pointer in ("", "/"):
        return current
    for raw_part in pointer.lstrip("/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return current


def verify_citations(memo: str, roots: dict[str, Any], relative_paths: dict[str, str]) -> None:
    cited: dict[str, set[str]] = {}
    for index, match in enumerate(CITE_RE.finditer(memo), start=1):
        artifact_path, fields_blob, memo_sha = match.groups()
        artifact = Path(artifact_path).name
        actual_pin = PINS.get(artifact)
        add_check(
            f"memo_citation_{index:02d}_sha256",
            artifact,
            f"memo citation hash for {artifact_path}",
            actual_pin,
            memo_sha,
        )
        cited.setdefault(artifact, set())
        if artifact not in roots or artifact_path != relative_paths.get(artifact):
            add_check(
                f"memo_citation_{index:02d}_artifact_path",
                artifact,
                "repository-relative cited JSON path",
                relative_paths.get(artifact),
                artifact_path,
            )
            continue
        fields = re.findall(r"`([^`]+)`", fields_blob)
        add_check(
            f"memo_citation_{index:02d}_has_field",
            artifact,
            "citation field list",
            True,
            bool(fields),
        )
        for field_index, field in enumerate(fields, start=1):
            try:
                resolve_pointer(roots[artifact], field)
                present = True
            except (KeyError, IndexError, TypeError, ValueError):
                present = False
            add_check(
                f"memo_citation_{index:02d}_field_{field_index:02d}",
                artifact,
                field,
                "present",
                "present" if present else "missing",
            )
            cited[artifact].add(field)
    for artifact in PINS:
        add_check(
            f"memo_cites_{artifact}",
            artifact,
            "memo citation presence",
            True,
            artifact in cited,
        )


def main() -> int:
    relative_paths = {
        filename: f"research/nhl-multi-agent-movement-2026-10-23/results/{filename}"
        for filename in PINS
    }
    artifact_hashes: dict[str, dict[str, Any]] = {}
    artifact_bytes: dict[str, bytes] = {}
    roots: dict[str, Any] = {}
    pin_failures = False

    for filename, expected_hash in PINS.items():
        path = RESULTS / filename
        try:
            raw = path.read_bytes()
            observed_hash = sha256(raw)
            artifact_bytes[filename] = raw
        except OSError as exc:
            raw = b""
            observed_hash = f"READ_ERROR:{exc.__class__.__name__}"
        expected_size = EXPECTED_BYTES.get(filename)
        artifact_hashes[relative_paths[filename]] = {
            "sha256": observed_hash,
            "bytes": len(raw),
        }
        pin_ok = add_check(
            f"pinned_sha256_{filename}", filename, "SHA-256", expected_hash, observed_hash
        )
        pin_failures = pin_failures or not pin_ok
        if expected_size is not None:
            size_ok = add_check(
                f"pinned_bytes_{filename}",
                filename,
                "byte_count",
                expected_size,
                len(raw),
            )
            pin_failures = pin_failures or not size_ok

    if not pin_failures:
        for filename, raw in artifact_bytes.items():
            roots[filename] = json.loads(raw)

    try:
        memo_bytes = MEMO.read_bytes()
        memo = memo_bytes.decode("utf-8")
        memo_hash = sha256(memo_bytes)
    except OSError as exc:
        memo = ""
        memo_hash = f"READ_ERROR:{exc.__class__.__name__}"
    checker_hash = sha256(Path(__file__).read_bytes())

    if not pin_failures:
        verify_citations(memo, roots, relative_paths)
        d1 = roots["jc-attribution-jcdiag-2026-10-23-v1.json"]
        d2 = roots["jc-diag2-pair-persistence-2026-10-23-v1.json"]
        d3 = roots["jc-diag3-pair-shrink-2026-10-23-v1.json"]
        d4 = roots["jc-diag4-additive-offset-2026-10-23-v1.json"]
        d5 = roots["jc-diag5-delta-persistence-2026-10-23-v1.json"]
        d6 = roots["jc-diag6-distance-conditioned-2026-10-23-v1.json"]
        d7 = roots["jc-diag7-oos-pair-value-2026-10-23-v1.json"]
        d8 = roots["jc-diag8-identity-feasibility-2026-10-23-v1.json"]

        def exact(name: str, artifact: str, pointer: str, expected: Any) -> Any:
            try:
                observed = resolve_pointer(roots[artifact], pointer)
            except (KeyError, IndexError, TypeError, ValueError):
                observed = "MISSING"
            add_check(name, artifact, pointer, expected, observed)
            return observed

        # DIAG1 attribution and label availability.
        exact("D1_status", "jc-attribution-jcdiag-2026-10-23-v1.json", "/status",
              "descriptive attribution only; no candidate scoring, selection, policy change, or adoption")
        exact("D1_linkable_activity_labels", "jc-attribution-jcdiag-2026-10-23-v1.json",
              "/Q6_constraint_activity_mechanism_screen/linkable_activity_labels_found", False)
        exact("D1_role_label_status", "jc-attribution-jcdiag-2026-10-23-v1.json",
              "/Q1_pair_type_and_team_decomposition/role_labels/status", "not estimable")
        exact("D1_role_fields_empty", "jc-attribution-jcdiag-2026-10-23-v1.json",
              "/Q1_pair_type_and_team_decomposition/role_labels/fields_found", [])
        exact("D1_activity_label_paths_empty", "jc-attribution-jcdiag-2026-10-23-v1.json",
              "/Q6_constraint_activity_mechanism_screen/explicit_player_or_pair_activity_label_paths", [])
        add_check("D1_activity_label_path_count", "jc-attribution-jcdiag-2026-10-23-v1.json",
                  "/Q6_constraint_activity_mechanism_screen/explicit_player_or_pair_activity_label_paths",
                  0, len(d1["Q6_constraint_activity_mechanism_screen"][
                      "explicit_player_or_pair_activity_label_paths"]))

        # DIAG2 pair persistence relative to its permutation reference.
        exact("D2_M1_observed_share", "jc-diag2-pair-persistence-2026-10-23-v1.json",
              "/P1_plus15_to_plus45_pair_persistence/summary/models/EqualTeam/M1/observed_share/equal_game_mean_available_games",
              0.8305414523474803)
        exact("D2_M1_null_share", "jc-diag2-pair-persistence-2026-10-23-v1.json",
              "/P1_plus15_to_plus45_pair_persistence/summary/models/EqualTeam/M1/permutation_null_mean/equal_game_mean_available_games",
              0.6201172173403376)

        # DIAG3 shrinkage slope and residual structure.
        exact("D3_M1_kappa_plus45", "jc-diag3-pair-shrink-2026-10-23-v1.json",
              "/Q1_through_origin_slopes/by_horizon/45/EqualTeam/M1/equal_game_kappa/equal_game_mean",
              0.9187677553966251)
        exact("D3_M2_kappa_plus45", "jc-diag3-pair-shrink-2026-10-23-v1.json",
              "/Q1_through_origin_slopes/by_horizon/45/EqualTeam/M2/equal_game_kappa/equal_game_mean",
              0.917783443374861)
        exact("D3_M1_residual", "jc-diag3-pair-shrink-2026-10-23-v1.json",
              "/Q3_fixed_slope_residual_structure_plus45/by_candidate/M1/overall_common_three_horizon_support/metrics/residual_ft/equal_game_mean",
              -4.2508129518662505)
        exact("D3_M2_residual", "jc-diag3-pair-shrink-2026-10-23-v1.json",
              "/Q3_fixed_slope_residual_structure_plus45/by_candidate/M2/overall_common_three_horizon_support/metrics/residual_ft/equal_game_mean",
              -4.273154725868025)

        # DIAG4 raw persistence and frozen population.
        exact("D4_M0_raw_share", "jc-diag4-additive-offset-2026-10-23-v1.json",
              "/Q3/transitions/plus15_to_plus45/summaries/M0/raw/observed_share/equal_game_mean",
              0.7630291734469827)
        exact("D4_M0_null_share", "jc-diag4-additive-offset-2026-10-23-v1.json",
              "/Q3/transitions/plus15_to_plus45/summaries/M0/raw/permutation_null_mean/equal_game_mean",
              0.47819563088399875)
        for pointer, expected in [
            ("/population/game_count", 10),
            ("/population/rollout_starts", 200),
            ("/population/plus45_scored_starts", 172),
            ("/population/plus45_pair_counts/total", 2164),
            ("/population/plus45_pair_counts/Home", 1064),
            ("/population/plus45_pair_counts/Away", 1100),
            ("/population/equalteam_eligible_plus45_start_team_cells", 142),
            ("/population/timebase", "ordinal Image Id increments, not seconds"),
        ]:
            exact("D4_population" + pointer.replace("/", "_"),
                  "jc-diag4-additive-offset-2026-10-23-v1.json", pointer, expected)

        # DIAG5 corrected-delta gaps and monotonicity across the four distance bins.
        for model, expected in [("M1", 0.38596525340316096), ("M2", 0.35597797432366096)]:
            exact(f"D5_{model}_corrected_delta_gap", "jc-diag5-delta-persistence-2026-10-23-v1.json",
                  f"/Q2/transitions/plus15_to_plus45/models/{model}/summary/observed_minus_null/equal_game_mean",
                  expected)
        for model in ("M1", "M2"):
            rows = d5["Q4"]["distance_gradient"]["bins"][model]
            values = [row["metrics_ft"]["delta"]["equal_game_mean"] for row in rows]
            add_check(f"D5_{model}_distance_bin_count", "jc-diag5-delta-persistence-2026-10-23-v1.json",
                      f"/Q4/distance_gradient/bins/{model}", 4, len(rows))
            add_check(f"D5_{model}_bin_labels", "jc-diag5-delta-persistence-2026-10-23-v1.json",
                      f"/Q4/distance_gradient/bins/{model}/*/bin", [1, 2, 3, 4],
                      [row["bin"] for row in rows])
            for index in range(3):
                add_check(f"D5_{model}_strictly_more_negative_bin_{index + 1}_to_{index + 2}",
                          "jc-diag5-delta-persistence-2026-10-23-v1.json",
                          f"/Q4/distance_gradient/bins/{model}/{index + 1}:{index + 2}", True,
                          values[index + 1] < values[index])
            endpoints = {
                "M1": (-2.136556824375522, -6.456252087389958),
                "M2": (-2.1566900410137624, -6.527259047160311),
            }[model]
            for position, (label, expected) in enumerate(zip(("bin1", "bin4"), endpoints)):
                add_check(f"D5_{model}_{label}_delta", "jc-diag5-delta-persistence-2026-10-23-v1.json",
                          f"/Q4/distance_gradient/bins/{model}/{label}/metrics_ft/delta/equal_game_mean",
                          expected, values[0 if position == 0 else 3], 1e-10)
        exact("D5_M1_bin1_to_bin4_delta", "jc-diag5-delta-persistence-2026-10-23-v1.json",
              "/Q4/distance_gradient/gradient_comparison/M1/delta_bin4_minus_bin1_ft",
              -4.319695263014435)
        exact("D5_M2_bin1_to_bin4_delta", "jc-diag5-delta-persistence-2026-10-23-v1.json",
              "/Q4/distance_gradient/gradient_comparison/M2/delta_bin4_minus_bin1_ft",
              -4.370569006146549)
        for pointer, expected in [
            ("/population/game_count", 10),
            ("/population/scored_start_count", 172),
            ("/population/plus45_pair_count", 2164),
            ("/population/plus45_pair_counts_by_team/Home", 1064),
            ("/population/plus45_pair_counts_by_team/Away", 1100),
            ("/population/equalteam_plus45_cells", 142),
            ("/population/timebase", "ordinal Image Id increments, not seconds"),
        ]:
            exact("D5_population" + pointer.replace("/", "_"),
                  "jc-diag5-delta-persistence-2026-10-23-v1.json", pointer, expected)
        add_check("D5_population_statement_confirms_starts",
                  "jc-diag5-delta-persistence-2026-10-23-v1.json",
                  "/population/population_statement", True,
                  "200 rollout starts (172 group-scored at +45)" in d5["population"]["population_statement"])

        # DIAG6 registered mixed reading and scale-dependent retained/raw ratios.
        exact("D6_registered_reading", "jc-diag6-distance-conditioned-2026-10-23-v1.json",
              "/Q5/overall_reading", "mixed")
        exact("D6_M1_retained_raw_ratio", "jc-diag6-distance-conditioned-2026-10-23-v1.json",
              "/Q5/primary_retained_fractions/M1/equal_game_mean_ratio", 0.8933858227557131)
        exact("D6_M2_retained_raw_ratio", "jc-diag6-distance-conditioned-2026-10-23-v1.json",
              "/Q5/primary_retained_fractions/M2/equal_game_mean_ratio", 0.9442712649286923)
        for pointer, expected in [
            ("/population/game_count", 10),
            ("/population/rollout_start_count", 172),
            ("/population/plus45_scored_start_count", 172),
            ("/population/plus45_pair_count", 2164),
            ("/population/plus45_pair_counts_by_team/Home", 1064),
            ("/population/plus45_pair_counts_by_team/Away", 1100),
            ("/population/plus45_equalteam_cells", 142),
            ("/population/timebase", "ordinal Image Id increments, not seconds"),
        ]:
            exact("D6_population" + pointer.replace("/", "_"),
                  "jc-diag6-distance-conditioned-2026-10-23-v1.json", pointer, expected)
        add_check("D6_population_statement_confirms_starts",
                  "jc-diag6-distance-conditioned-2026-10-23-v1.json",
                  "/population/statement", True,
                  "200 rollout starts (172 group-scored at +45)" in d6["population"]["statement"])

        # DIAG7: verify each fold's support, then the requested M1-primary ICC.
        model_rows: dict[str, list[dict[str, Any]]] = {}
        for model in ("M1", "M2"):
            folds = d7["Q1"]["candidates"][model]["outer_fold_training_and_fallback_audit"]
            games = sorted(folds)
            add_check(f"D7_{model}_fold_count", "jc-diag7-oos-pair-value-2026-10-23-v1.json",
                      f"/Q1/candidates/{model}/outer_fold_training_and_fallback_audit", 10, len(games))
            model_rows[model] = [folds[game] for game in games]
            for game in games:
                row = folds[game]
                prefix = f"/Q1/candidates/{model}/outer_fold_training_and_fallback_audit/{game}"
                exact(f"D7_{model}_{game}_B_nonzero", "jc-diag7-oos-pair-value-2026-10-23-v1.json",
                      prefix + "/heldout_unseen_and_weight_counts/B_nonzero_weight", 0)
                exact(f"D7_{model}_{game}_B_unseen", "jc-diag7-oos-pair-value-2026-10-23-v1.json",
                      prefix + "/heldout_unseen_and_weight_counts/B_unseen_or_zero_weight",
                      row["heldout_pair_count"])
                exact(f"D7_{model}_{game}_C_training_mean", "jc-diag7-oos-pair-value-2026-10-23-v1.json",
                      prefix + "/heldout_unseen_and_weight_counts/C_training_mean_used", 0)
            add_check(f"D7_{model}_B_nonzero_total", "jc-diag7-oos-pair-value-2026-10-23-v1.json",
                      f"/Q1/candidates/{model}/outer_fold_training_and_fallback_audit/*/B_nonzero_weight",
                      0, sum(row["heldout_unseen_and_weight_counts"]["B_nonzero_weight"]
                             for row in model_rows[model]))
            add_check(f"D7_{model}_B_unseen_total", "jc-diag7-oos-pair-value-2026-10-23-v1.json",
                      f"/Q1/candidates/{model}/outer_fold_training_and_fallback_audit/*/B_unseen_or_zero_weight",
                      2164, sum(row["heldout_unseen_and_weight_counts"]["B_unseen_or_zero_weight"]
                               for row in model_rows[model]))
            add_check(f"D7_{model}_heldout_pair_total",
                      "jc-diag7-oos-pair-value-2026-10-23-v1.json",
                      f"/Q1/candidates/{model}/outer_fold_training_and_fallback_audit/*/heldout_pair_count",
                      2164, sum(row["heldout_pair_count"] for row in model_rows[model]))

        tau_by_model: dict[str, list[float]] = {}
        within_by_model: dict[str, list[float]] = {}
        for model in ("M1", "M2"):
            tau_by_model[model] = [row["variance_components"]["tau2"] for row in model_rows[model]]
            within_by_model[model] = [row["variance_components"]["within_variance"]
                                      for row in model_rows[model]]

        def mean(values: list[float]) -> float:
            return sum(values) / len(values)

        def add_derived(name: str, model: str, metric: str, expected: float, actual: float,
                        tolerance: float) -> None:
            add_check(name, "jc-diag7-oos-pair-value-2026-10-23-v1.json",
                      f"derived.{model}.{metric}; source=Q1/candidates/{model}/outer_fold_training_and_fallback_audit/*/variance_components",
                      expected, actual, tolerance)

        m1_tau = tau_by_model["M1"]
        m1_within = within_by_model["M1"]
        m1_mean_tau = mean(m1_tau)
        m1_mean_within = mean(m1_within)
        m1_icc = m1_mean_tau / (m1_mean_tau + m1_mean_within)
        add_derived("D7_M1_tau2_min", "M1", "tau2_min", 2.1137048754904875, min(m1_tau), 1e-10)
        add_derived("D7_M1_tau2_max", "M1", "tau2_max", 2.933435460884494, max(m1_tau), 1e-10)
        add_derived("D7_M1_within_min", "M1", "within_min", 3.7829577014139035, min(m1_within), 1e-10)
        add_derived("D7_M1_within_max", "M1", "within_max", 4.791856605302006, max(m1_within), 1e-10)
        add_derived("D7_M1_mean_tau2_primary_gate", "M1", "mean_tau2", 2.4444585166,
                    m1_mean_tau, 1e-3)
        add_derived("D7_M1_mean_within_primary_gate", "M1", "mean_within_variance",
                    4.2856119544, m1_mean_within, 1e-3)
        add_derived("D7_M1_ICC_primary_gate", "M1", "ICC_from_M1_means", 0.363214,
                    m1_icc, 5e-7)

        m2_mean_tau = mean(tau_by_model["M2"])
        m2_mean_within = mean(within_by_model["M2"])
        m2_icc = m2_mean_tau / (m2_mean_tau + m2_mean_within)
        add_derived("D7_M2_mean_tau2_informational", "M2", "mean_tau2", 2.4441426679,
                    m2_mean_tau, 1e-9)
        add_derived("D7_M2_mean_within_informational", "M2", "mean_within_variance",
                    4.4076516409, m2_mean_within, 1e-9)
        add_derived("D7_M2_ICC_informational", "M2", "ICC_from_M2_means", 0.356716,
                    m2_icc, 5e-7)

        pooled_tau = tau_by_model["M1"] + tau_by_model["M2"]
        pooled_within = within_by_model["M1"] + within_by_model["M2"]
        pooled_mean_tau = mean(pooled_tau)
        pooled_mean_within = mean(pooled_within)
        pooled_icc = pooled_mean_tau / (pooled_mean_tau + pooled_mean_within)
        add_derived("D7_pooled_mean_tau2_informational", "M1+M2", "mean_tau2", 2.4443005923,
                    pooled_mean_tau, 1e-9)
        add_derived("D7_pooled_mean_within_informational", "M1+M2", "mean_within_variance",
                    4.3466317976, pooled_mean_within, 1e-9)
        add_derived("D7_pooled_ICC_informational", "M1+M2", "ICC_from_pooled_means", 0.359936,
                    pooled_icc, 5e-7)
        add_check("D7_primary_gate_label_is_M1_only", "memo", "ICC gate label", True,
                  "primary M1-only, 10 folds" in memo and "pooled number is not the gate" in memo)

        # DIAG8 identity-source feasibility, overlap, unmatched pairs, and provenance gate.
        for pointer, expected in [
            ("/Q1/verified_cross_game_identity_source", "none"),
            ("/Q1/qualifying_identity_source_count", 0),
            ("/Q1/research_data_file_count", 69),
            ("/Q1/research_data_bytes_total", 1586547032),
            ("/Q1/tracking_id_overlap/pairwise_comparison_count", 45),
            ("/Q1/tracking_id_overlap/numeric_jersey_value_overlap_pairs", 45),
            ("/Q1/tracking_id_overlap/exact_numeric_raw_id_value_overlap_pairs", 45),
            ("/Q1/tracking_id_overlap/exact_raw_id_literal_overlap_pairs", 45),
            ("/Q1/tracking_id_overlap/composite_id_exact_overlap_pairs", 0),
            ("/Q2/unmatched_pair_count", 2164),
            ("/provenance_gate/passed_count", 114),
            ("/provenance_gate/check_count", 114),
        ]:
            exact("D8" + pointer.replace("/", "_"),
                  "jc-diag8-identity-feasibility-2026-10-23-v1.json", pointer, expected)
        add_check("D8_candidate_path_count", "jc-diag8-identity-feasibility-2026-10-23-v1.json",
                  "/Q1/candidate_source_paths", 57, len(d8["Q1"]["candidate_source_paths"]))
        add_check("D8_repository_identity_artifact_count",
                  "jc-diag8-identity-feasibility-2026-10-23-v1.json",
                  "/Q1/repository_identity_artifacts", 4, len(d8["Q1"]["repository_identity_artifacts"]))
        exact("D8_raw_events_file_count", "jc-diag8-identity-feasibility-2026-10-23-v1.json",
              "/Q1/raw_source_asset_counts/asset_files_by_type/events", 10)
        exact("D8_raw_shifts_file_count", "jc-diag8-identity-feasibility-2026-10-23-v1.json",
              "/Q1/raw_source_asset_counts/asset_files_by_type/shifts", 10)
        exact("D8_raw_tracking_file_count", "jc-diag8-identity-feasibility-2026-10-23-v1.json",
              "/Q1/raw_source_asset_counts/asset_files_by_type/tracking", 33)
        add_check("D8_raw_stathletes_file_count", "jc-diag8-identity-feasibility-2026-10-23-v1.json",
                  "/Q1/raw_source_asset_counts/asset_files_by_type/{events,shifts,tracking}", 53,
                  sum(d8["Q1"]["raw_source_asset_counts"]["asset_files_by_type"][kind]
                      for kind in ("events", "shifts", "tracking")))
        exact("D8_published_identity_entry_count", "jc-diag8-identity-feasibility-2026-10-23-v1.json",
              "/Q1/repository_identity_artifacts/0/row_count", 1038)
        exact("D8_published_identity_field", "jc-diag8-identity-feasibility-2026-10-23-v1.json",
              "/Q1/repository_identity_artifacts/0/persistent_athlete_id_field", "nhl_id")
        exact("D8_published_identity_no_game_id", "jc-diag8-identity-feasibility-2026-10-23-v1.json",
              "/Q1/repository_identity_artifacts/0/game_identifier_present", False)
        exact("D8_published_identity_no_track_crosswalk",
              "jc-diag8-identity-feasibility-2026-10-23-v1.json",
              "/Q1/repository_identity_artifacts/0/direct_tracking_identity_crosswalk", False)
        for bin_id in ("1", "2", "3", "4"):
            exact(f"D8_bin_{bin_id}_unmatched", "jc-diag8-identity-feasibility-2026-10-23-v1.json",
                  f"/Q2/unmatched_distance_bins/{bin_id}/unmatched", 541)
            exact(f"D8_bin_{bin_id}_total", "jc-diag8-identity-feasibility-2026-10-23-v1.json",
                  f"/Q2/unmatched_distance_bins/{bin_id}/total", 541)

        # The memo displays only values reasserted above; bind those displayed values to checks.
        required_tokens = [
            "0.8305414523", "0.6201172173", "0.9187677554", "−4.2508129519",
            "0.7630291734", "0.4781956309", "0.3859652534", "0.3559779743",
            "0.8933858228", "0.9442712649", "−2.1365568244", "−6.4562520874",
            "−2.1566900410", "−6.5272590472", "2.1137048755", "2.9334354609",
            "3.7829577014", "4.7918566053", "2.4444585166", "4.2856119544",
            "0.363214", "2.4441426679", "4.4076516409", "0.356716",
            "2.4443005923", "4.3466317976", "0.359936", "57 candidate sources",
            "53 raw Stathletes", "4 repository identity artifacts", "1,038", "45 pairwise",
            "2,164", "541/541", "142 EqualTeam", "200 starts", "172 group-scored",
        ]
        for token in required_tokens:
            add_check(f"memo_contains_{token}", "memo", "required cited value/text", token,
                      token if token in memo else "MISSING")

    # The memo's final line records this run's exact verification denominator.
    total_with_final_check = len(checks) + 1
    final_line = next((line.strip() for line in reversed(memo.splitlines()) if line.strip()), "")
    expected_final = f"verified {total_with_final_check}/{total_with_final_check}; exit code 0"
    add_check("memo_final_verification_line", "memo", "last non-empty line", expected_final, final_line)

    all_checked = bool(checks) and all(row["passed"] for row in checks)
    result = {
        "schema_version": 1,
        "all_checked": all_checked,
        "checks": checks,
        "artifact_hashes": artifact_hashes,
        "memo_sha256": memo_hash,
        "checker_sha256": checker_hash,
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")

    for row in checks:
        state = "PASS" if row["passed"] else "FAIL"
        print(
            f"{state} | {row['name']} | {row['artifact']} | {row['field_path']} | "
            f"expected={short(row['expected'])} | observed={short(row['observed'])}"
        )
    passed_count = sum(1 for row in checks if row["passed"])
    print(f"verified {passed_count}/{len(checks)}")
    return 0 if all_checked else 1


if __name__ == "__main__":
    raise SystemExit(main())
