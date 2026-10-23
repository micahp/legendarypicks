#!/usr/bin/env python3
"""Fail-closed, local-only inventory of DIAG7 cross-game identity feasibility."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import subprocess
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_name] = "1"

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research/nhl-multi-agent-movement-2026-10-23"
RESULTS = RESEARCH / "results"
DIAG7_JSON = RESULTS / "jc-diag7-oos-pair-value-2026-10-23-v1.json"
DIAG7_EVALUATOR = RESEARCH / "diagnose_jc_diag7_oos_pair_value.py"
DIAG7_REPORT = ROOT / "docs/research/NHL-JC-DIAG7-REPORT-2026-10-23.md"
DIAG7_PREREG = ROOT / "docs/research/NHL-JC-DIAG7-PREREG-2026-10-23.md"
PREREG = ROOT / "docs/research/NHL-JC-DIAG8-PREREG-2026-10-23.md"
REPORT = ROOT / "docs/research/NHL-JC-DIAG8-REPORT-2026-10-23.md"
DEFAULT_OUTPUT = RESULTS / "jc-diag8-identity-feasibility-2026-10-23-v1.json"
RESEARCH_DATA = Path("/root/lp-research-data")
MOVEMENT_DATA = RESEARCH_DATA / "nhl-multi-agent-movement-2026-10-23"
RELEASE_DATA = RESEARCH_DATA / "stathletes-big-data-cup-2026"
SOURCE_MANIFEST = RELEASE_DATA / "download-manifest.json"
EXTRACTION_MANIFEST = MOVEMENT_DATA / "extraction_manifest.json"

SOURCE_BASE = "e67c23f2ab65c4ae58498c58f4e6ef148c2dcef7"
STEP0_COMMIT = "e9806e61d2e252a4d55eb7da85fe74c7993b4795"
PREREG_COMMITS = ("b9c2b18a2ac66eea5ad0e4a3638381eb0c6fbd9a",
                  "a834d153bf42f794079f9fb08c0b82fc4e6a44cd")
PREREG_SHA256 = "1a7f6ec69b3d2feaf5bc44ac3189159c70371af524efd58cfffef182627b108a"
DIAG7_JSON_SHA256 = "fa0d853a39cc33591e1157896572c40a58e374270cf26603cd56850ae6311dce"
DIAG7_EVALUATOR_SHA256 = "199d0f759fbc0642f027f89b6167cb23abe951ce69690c2db15fc7e6b5e85dd2"
DIAG7_REPORT_BASE_SHA256 = "f0bad14ac437df5465ab6689d8971eb686f7841da2aee14e6b6bbad290345bd6"
DIAG7_REPORT_STEP0_SHA256 = "28fa57506071a490f5a92c2426e14e9713aa9c7e95101a3703d989a14ded21b3"
DIAG7_PREREG_SHA256 = "e5644b1a65098ffa070cf81bbdd8e46978558358ca74696276936124823aab99"
SOURCE_MANIFEST_SHA256 = "6ca13bfa3503d9a86b7dde9589aba4988fd5e9599318e0b97f2f84e94cfcb437"
EXTRACTION_MANIFEST_SHA256 = "03ded9f5df01f4932405eee3c420e8f932da2d7b1a77a1ab6bb4bdd0d2bc0746"
EXTRACTION_ARTIFACTS = {
    "normalized_observations.jsonl.gz": ("c92789cf3a35b9ba81e2d414e491c385f76cac97f27c720e4cf42af7f75f3227", 734_478_925),
    "rollout_starts.json.gz": ("07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de", 1_025_769),
    "training_windows.npz": ("694eb82615d6cd7ab442da23da9d7016aa9e47b6692e5469856a06de2991abd6", 132_355_130),
}
EXPECTED_GAMES = [
    "2025-10-11.Team.A.@.Team.D", "2025-10-17.Team.F.@.Team.L",
    "2025-10-24.Team.B.@.Team.A", "2025-10-24.Team.E.@.Team.D",
    "2025-10-28.Team.C.@.Team.A", "2025-10-29.Team.G.@.Team.L",
    "2025-11-02.Team.D.@.Team.A", "2025-11-16.Team.H.@.Team.K",
    "2025-11-19.Team.I.@.Team.K", "2025-11-28.Team.J.@.Team.K",
]
PLAYER_FIELDS_DIAG7 = ["history", "id", "jersey", "raw_id", "team", "x", "y"]
DATA_DIRS_TO_PRUNE = {".git", "node_modules", ".venv", "venv", ".next", "dist", "build", "__pycache__", ".pytest_cache"}
DB_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".duckdb"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def output_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def git_ancestor(commit: str) -> bool:
    p = subprocess.run(["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return p.returncode == 0


def frozen_blob_sha(commit: str, relpath: str) -> str | None:
    p = subprocess.run(["git", "show", f"{commit}:{relpath}"], cwd=ROOT,
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    return sha256_bytes(p.stdout) if p.returncode == 0 else None


def add_check(checks: list[dict], name: str, expected, actual) -> None:
    checks.append({"name": name, "expected": expected, "actual": actual,
                   "passed": expected == actual})


def verify_gate() -> tuple[dict, dict | None, dict | None, dict | None]:
    checks: list[dict] = []
    d7_path_sha = sha256_file(DIAG7_JSON)
    add_check(checks, "DIAG7_result_sha256", DIAG7_JSON_SHA256, d7_path_sha)
    add_check(checks, "DIAG7_result_bytes", 76_326, DIAG7_JSON.stat().st_size if DIAG7_JSON.is_file() else None)
    add_check(checks, "DIAG7_evaluator_sha256", DIAG7_EVALUATOR_SHA256, sha256_file(DIAG7_EVALUATOR))
    add_check(checks, "DIAG7_prereg_sha256", DIAG7_PREREG_SHA256, sha256_file(DIAG7_PREREG))
    add_check(checks, "DIAG7_report_at_source_base_sha256", DIAG7_REPORT_BASE_SHA256,
              frozen_blob_sha(SOURCE_BASE, "docs/research/NHL-JC-DIAG7-REPORT-2026-10-23.md"))
    add_check(checks, "DIAG7_report_after_Step0_sha256", DIAG7_REPORT_STEP0_SHA256,
              sha256_file(DIAG7_REPORT))
    add_check(checks, "DIAG8_prereg_sha256", PREREG_SHA256, sha256_file(PREREG))
    ancestry = {"source_base": git_ancestor(SOURCE_BASE), "step0_correction": git_ancestor(STEP0_COMMIT)}
    for i, commit in enumerate(PREREG_COMMITS, 1):
        ancestry[f"prereg_commit_{i}"] = git_ancestor(commit)
    for name, passed in ancestry.items():
        add_check(checks, f"ancestry_{name}", True, passed)

    d7 = json.loads(DIAG7_JSON.read_text(encoding="utf-8")) if DIAG7_JSON.is_file() else None
    if d7 is not None:
        gate = d7["provenance_gate"]
        inherited = [row for row in gate["artifact_hashes"] if row["name"].startswith("DIAG6_source:")]
        add_check(checks, "DIAG7_inherited_source_hash_count", 17, len(inherited))
        for row in inherited:
            raw_path = Path(row["path"])
            path = raw_path if raw_path.is_absolute() else ROOT / raw_path
            actual = sha256_file(path)
            checks.append({"name": row["name"], "path": row["path"],
                           "expected": row["expected_sha256"], "actual": actual,
                           "passed": actual == row["expected_sha256"]})
        add_check(checks, "DIAG7_embedded_hash_gate_count", "22/22", gate.get("pass_counts", {}).get("pinned_artifact_hashes"))
        add_check(checks, "DIAG7_DIAG6_value_assertions", "16/16", gate.get("pass_counts", {}).get("DIAG6_value_assertions"))
        add_check(checks, "DIAG7_inherited_source_gate_count", "17/17", gate.get("pass_counts", {}).get("DIAG6_source_hashes"))
        add_check(checks, "DIAG7_inherited_reassertions", "41/41", gate.get("pass_counts", {}).get("DIAG6_reassertions"))
        add_check(checks, "DIAG7_gate_passed", True, gate.get("all_assertions_passed"))
        pop = d7["population"]
        expected_pop = {"game_count": 10, "raw_rollout_start_count": 200,
                        "scored_start_count": 172, "pair_row_count": 2164,
                        "pair_rows_by_distance_bin": {str(i): 541 for i in range(1, 5)}}
        actual_pop = {"game_count": pop["game_count"], "raw_rollout_start_count": pop["raw_rollout_start_count"],
                      "scored_start_count": pop["scored_start_count"], "pair_row_count": pop["pair_row_count"],
                      "pair_rows_by_distance_bin": pop["pair_rows_by_distance_bin"]}
        add_check(checks, "DIAG7_population", expected_pop, actual_pop)
        add_check(checks, "DIAG7_game_ids", EXPECTED_GAMES, pop["games"])
        add_check(checks, "DIAG7_Q2_verified_pair_count", 0, d7["Q2"]["eligible_verified_pair_key_count"])
        add_check(checks, "DIAG7_Q3_registered_reading", "pair_identity_line_closes",
                  d7["Q3"]["overall_registered_reading"])
        # The preregistered 2.1137–2.9334 range is the ten M1 outer folds;
        # pooling M2 changes the extrema and would test a different quantity.
        variance_values = [fold["variance_components"]["tau2"]
                           for fold in d7["Q1"]["candidates"]["M1"]["outer_fold_training_and_fallback_audit"].values()]
        add_check(checks, "DIAG7_M1_tau2_fold_count", 10, len(variance_values))
        add_check(checks, "DIAG7_M1_tau2_range",
                  [2.1137048754904875, 2.933435460884494], [min(variance_values), max(variance_values)])
        for model in ("M1", "M2"):
            folds = d7["Q1"]["candidates"][model]["outer_fold_training_and_fallback_audit"]
            add_check(checks, f"DIAG7_{model}_fold_count", 10, len(folds))
            add_check(checks, f"DIAG7_{model}_B_nonzero_total", 0,
                      sum(f["heldout_unseen_and_weight_counts"]["B_nonzero_weight"] for f in folds.values()))
            add_check(checks, f"DIAG7_{model}_B_unseen_total", 2164,
                      sum(f["heldout_unseen_and_weight_counts"]["B_unseen_or_zero_weight"] for f in folds.values()))
            add_check(checks, f"DIAG7_{model}_C_applied_total", 0,
                      sum(f["heldout_unseen_and_weight_counts"]["C_training_mean_used"] for f in folds.values()))

    source_manifest_sha = sha256_file(SOURCE_MANIFEST)
    add_check(checks, "Stathletes_download_manifest_sha256", "6ca13bfa3503d9a86b7dde9589aba4988fd5e9599318e0b97f2f84e94cfcb437", source_manifest_sha)
    download_manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8")) if SOURCE_MANIFEST.is_file() else None
    asset_hashes = []
    if download_manifest is not None:
        add_check(checks, "Stathletes_manifest_asset_count", 54, download_manifest.get("asset_count"))
        add_check(checks, "Stathletes_manifest_list_count", 54, len(download_manifest.get("files", [])))
        add_check(checks, "Stathletes_manifest_total_bytes", 674_203_388, download_manifest.get("total_bytes"))
        names = set()
        for item in download_manifest["files"]:
            name = item["name"]
            if Path(name).name != name or name in {".", ".."}:
                raise RuntimeError(f"unsafe asset path in pinned source manifest: {name!r}")
            if name in names:
                raise RuntimeError(f"duplicate asset name in source manifest: {name}")
            names.add(name)
            path = RELEASE_DATA / name
            actual_hash = sha256_file(path)
            actual_bytes = path.stat().st_size if path.is_file() else None
            row = {"name": name, "path": str(path), "expected_sha256": item["sha256"],
                   "actual_sha256": actual_hash, "expected_bytes": item["bytes"],
                   "actual_bytes": actual_bytes,
                   "passed": actual_hash == item["sha256"] and actual_bytes == item["bytes"]}
            asset_hashes.append(row)
            checks.append({"name": f"Stathletes_asset:{name}", "path": str(path),
                           "expected": {"sha256": item["sha256"], "bytes": item["bytes"]},
                           "actual": {"sha256": actual_hash, "bytes": actual_bytes},
                           "passed": row["passed"]})

    extraction_sha = sha256_file(EXTRACTION_MANIFEST)
    add_check(checks, "movement_extraction_manifest_sha256", EXTRACTION_MANIFEST_SHA256, extraction_sha)
    extraction = json.loads(EXTRACTION_MANIFEST.read_text(encoding="utf-8")) if EXTRACTION_MANIFEST.is_file() else None
    if extraction is not None:
        add_check(checks, "extraction_source_manifest_sha256", SOURCE_MANIFEST_SHA256,
                  extraction["source_release"]["manifest_sha256"])
        for name, (expected_sha, expected_bytes) in EXTRACTION_ARTIFACTS.items():
            artifact = extraction["artifacts"].get(name)
            add_check(checks, f"extraction_manifest_entry:{name}",
                      {"sha256": expected_sha, "bytes": expected_bytes},
                      None if artifact is None else {"sha256": artifact["sha256"], "bytes": artifact["bytes"]})
            path = Path(artifact["path"]) if artifact else MOVEMENT_DATA / name
            actual_sha = sha256_file(path)
            actual_bytes = path.stat().st_size if path.is_file() else None
            checks.append({"name": f"movement_artifact:{name}", "path": str(path),
                           "expected": {"sha256": expected_sha, "bytes": expected_bytes},
                           "actual": {"sha256": actual_sha, "bytes": actual_bytes},
                           "passed": actual_sha == expected_sha and actual_bytes == expected_bytes})

    all_pass = all(row["passed"] for row in checks)
    summary = {
        "source_base": SOURCE_BASE, "step0_commit": STEP0_COMMIT,
        "preregistration_commits": list(PREREG_COMMITS), "preregistration_sha256": PREREG_SHA256,
        "checks": checks, "source_asset_hashes": asset_hashes,
        "check_count": len(checks), "passed_count": sum(row["passed"] for row in checks),
        "all_assertions_passed": all_pass, "Q1_Q2_calculated": False,
    }
    return summary, d7, download_manifest, extraction


def csv_game_key(name: str) -> str | None:
    for marker in (".Events.csv", ".Shifts.csv", ".Tracking_"):
        if marker in name:
            return name.split(marker, 1)[0]
    return None


def identity_like_fields(fields: list[str]) -> list[str]:
    identity_pattern = re.compile(r"player|athlete|person|jersey|name", re.I)
    explicit_game_context = {"date", "team", "home_team", "away_team", "game", "game_id", "gameid"}
    explicit_track_keys = {"id", "raw_id", "track_id"}
    selected = []
    for field in fields:
        normalized = re.sub(r"[^a-z0-9]+", "_", field.lower()).strip("_")
        if identity_pattern.search(normalized) or normalized in explicit_game_context | explicit_track_keys:
            selected.append(field)
    return selected


def count_csv_asset(path: Path, manifest_item: dict, id_sets: dict, jersey_sets: dict,
                    numeric_jersey_sets: dict, composite_id_sets: dict,
                    raw_value_sets: dict, raw_counts: dict) -> dict:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        if not fields:
            raise RuntimeError(f"CSV missing header: {path}")
        count = 0
        game = csv_game_key(path.name)
        group_count = 0
        last_image = None
        for row in reader:
            count += 1
            if "Image Id" in row:
                image = (row.get("Image Id") or "").strip()
                if image and image != last_image:
                    group_count += 1
                    last_image = image
            kind = (row.get("Player or Puck") or "").strip()
            if game and path.name.endswith(tuple(f".Tracking_{period}.csv" for period in ("P1", "P2", "P3", "POT"))) and kind == "Player":
                raw = (row.get("Player Id") or "").strip()
                jersey = (row.get("Player Jersey Number") or "").strip()
                raw_counts[game]["player_rows"] += 1
                if raw:
                    raw_counts[game]["player_id_rows"] += 1
                    raw_value_sets[game].add(raw)
                    team = (row.get("Team") or "").strip()
                    period = (row.get("Period") or "").strip()
                    composite_id_sets[game].add(f"{game}|{period}|{team}|{raw}")
                    try:
                        id_sets[game].add(int(raw))
                    except ValueError:
                        raw_counts[game]["non_numeric_player_id_rows"] += 1
                if jersey:
                    jersey_sets[game].add(jersey)
                    if jersey.isdigit():
                        numeric_jersey_sets[game].add(jersey)
        classification = ("tracking" if ".Tracking_" in path.name else
                          "events" if path.name.endswith(".Events.csv") else
                          "shifts" if path.name.endswith(".Shifts.csv") else "other_release_asset")
        candidate = classification in {"tracking", "events", "shifts"}
        return {
            "path": str(path), "name": path.name, "sha256": manifest_item["sha256"],
            "bytes": manifest_item["bytes"], "row_count": count, "row_count_unit": "CSV data records excluding header",
            "class": classification, "game_key_from_filename": game,
            "field_names": fields, "identity_bearing_fields": identity_like_fields(fields),
            "observation_group_count": group_count if "Image Id" in fields else None,
            "candidate_source": candidate,
            "game_coverage": [game] if game else [],
            "persistent_athlete_id_field": None,
            "source_game_id_field": None,
            "documented_persistent_athlete_id": False,
            "documented_game_identifier": False,
            "direct_tracking_to_athlete_link": False,
            "direct_frozen_game_to_source_game_link": False,
            "has_documented_persistent_athlete_id": False,
            "has_documented_game_id_for_cross_source_join": False,
            "direct_tracking_to_external_athlete_link": False,
            "qualifies_as_verified_identity_source": False,
            "identity_joinability_finding": "No persistent athlete ID, canonical game ID, or direct documented tracking-to-athlete crosswalk.",
        }


def flatten_key_paths(value, prefix: str = "", output: set[str] | None = None) -> set[str]:
    if output is None:
        output = set()
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            output.add(path)
            flatten_key_paths(child, path, output)
    elif isinstance(value, list) and value:
        flatten_key_paths(value[0], f"{prefix}[]", output)
    return output


def scan_normalized_jsonl(path: Path, expected_games: list[str]) -> dict:
    row_count = player_count = entity_count = puck_entity_count = unknown_entity_count = 0
    per_game = Counter()
    top_keys = set()
    player_keys = set()
    puck_keys = set()
    puck_entity_keys = set()
    first_game = None
    last_game = None
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            row_count += 1
            game = row.get("game")
            if game not in expected_games:
                raise RuntimeError(f"normalized row {line_number} has unexpected game {game!r}")
            per_game[game] += 1
            first_game = first_game or game
            last_game = game
            top_keys.update(row.keys())
            players = row.get("players", [])
            if not isinstance(players, list):
                raise RuntimeError(f"normalized row {line_number} players field is not a list")
            for player in players:
                if isinstance(player, dict):
                    entity_count += 1
                    kind = player.get("kind")
                    if kind == "Player":
                        player_count += 1
                        player_keys.update(player.keys())
                    elif kind == "Puck":
                        puck_entity_count += 1
                        puck_entity_keys.update(player.keys())
                    else:
                        unknown_entity_count += 1
                else:
                    raise RuntimeError(f"normalized row {line_number} has a non-object entity")
            puck = row.get("puck")
            if isinstance(puck, dict):
                puck_keys.update(puck.keys())
            elif isinstance(puck, list):
                for item in puck:
                    if isinstance(item, dict):
                        puck_keys.update(item.keys())
    if row_count != 959_754 or player_count == 0 or unknown_entity_count:
        raise RuntimeError(f"normalized JSONL count mismatch: observations={row_count}, players={player_count}, unknown_entities={unknown_entity_count}")
    return {"path": str(path), "sha256": EXTRACTION_ARTIFACTS["normalized_observations.jsonl.gz"][0],
            "bytes": path.stat().st_size, "row_count": row_count,
            "row_count_unit": "nonblank JSONL observation records", "player_object_count": player_count,
            "puck_entity_count": puck_entity_count, "entity_object_count": entity_count,
            "game_observation_rows": {g: int(per_game[g]) for g in expected_games},
            "top_level_fields_observed": sorted(top_keys), "player_fields_observed": sorted(player_keys),
            "puck_fields_observed": sorted(puck_entity_keys | puck_keys),
            "puck_entity_fields_observed": sorted(puck_entity_keys),
            "top_level_puck_fields_observed": sorted(puck_keys), "first_game": first_game, "last_game": last_game}


def scan_rollout_starts(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        data = json.load(stream)
    starts = data.get("starts")
    if not isinstance(starts, list) or len(starts) != 200:
        raise RuntimeError("rollout start inventory did not match the frozen 200 starts")
    player_fields, state_fields, game_counts = set(), set(), Counter()
    for start in starts:
        game_counts[start["game"]] += 1
        for player in start.get("players", []):
            player_fields.update(player.keys())
    first = starts[0]
    state_fields.update(first.keys())
    return {"path": str(path), "sha256": EXTRACTION_ARTIFACTS["rollout_starts.json.gz"][0],
            "bytes": path.stat().st_size, "row_count": len(starts), "row_count_unit": "rollout starts",
            "game_start_counts": {g: game_counts[g] for g in EXPECTED_GAMES},
            "start_fields": sorted(state_fields), "player_fields": sorted(player_fields),
            "identity_source_status": "derived local track identities only; no persistent athlete ID or external game crosswalk"}


def scan_npz_members(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        members = []
        for item in archive.infolist():
            members.append({"member": item.filename, "uncompressed_bytes": item.file_size,
                            "compressed_bytes": item.compress_size})
    return {"path": str(path), "sha256": EXTRACTION_ARTIFACTS["training_windows.npz"][0],
            "bytes": path.stat().st_size, "row_count": None,
            "row_count_unit": "numeric feature arrays; no athlete-level row identity",
            "members": members, "persistent_identity_fields": []}


def scan_scenario_archive(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        data = json.load(stream)
    scenarios = data.get("scenarios", {})
    player_fields, state_fields = set(), set()
    for scenario in scenarios.values():
        state = scenario.get("initial_state", {})
        state_fields.update(state.keys())
        for player in state.get("players", []):
            player_fields.update(player.keys())
    return {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size,
            "row_count": len(scenarios), "row_count_unit": "derived scenario records",
            "state_fields": sorted(state_fields), "player_fields": sorted(player_fields),
            "external_identity_source": False}


def read_repo_identity_artifacts() -> list[dict]:
    output = []
    published_path = ROOT / "backend/data/published-identity-names.json"
    if published_path.is_file():
        data = json.loads(published_path.read_text(encoding="utf-8"))
        nhl = data.get("leagues", {}).get("nhl", {})
        names = nhl.get("names", {})
        output.append({
            "path": str(published_path), "sha256": sha256_file(published_path),
            "bytes": published_path.stat().st_size, "row_count": len(names),
            "row_count_unit": "NHL publisher ID-to-name entries",
            "identity_fields": [nhl.get("id_column"), "names"],
            "persistent_athlete_id_documented": bool(nhl.get("id_column") == "nhl_id" and data.get("_provenance", {}).get("sources", {}).get("nhl")),
            "game_identifier_present": False, "direct_tracking_identity_crosswalk": False,
            "qualifies_as_verified_identity_source": False,
            "reason": "Publisher NHL ID/name snapshot; has no game key or documented mapping from anonymized tracking IDs to nhl_id.",
        })
    aliases_path = ROOT / "backend/data/name-aliases.json"
    if aliases_path.is_file():
        data = json.loads(aliases_path.read_text(encoding="utf-8"))
        nhl = data.get("nhl", {})
        count = len(nhl) if isinstance(nhl, (dict, list)) else 0
        output.append({"path": str(aliases_path), "sha256": sha256_file(aliases_path),
                       "bytes": aliases_path.stat().st_size, "row_count": count,
                       "row_count_unit": "NHL alias mapping entries", "identity_fields": sorted(nhl) if isinstance(nhl, dict) else [],
                       "persistent_athlete_id_documented": False, "game_identifier_present": False,
                       "direct_tracking_identity_crosswalk": False,
                       "qualifies_as_verified_identity_source": False,
                       "reason": "Name-alias maintenance data; not a game roster or tracking-ID crosswalk."})
    consolidations_path = ROOT / "backend/data/identity-consolidations.jsonl"
    if consolidations_path.is_file():
        rows = [json.loads(line) for line in consolidations_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        nhl_rows = [row for row in rows if "nhl" in json.dumps(row).lower() or "hockey" in json.dumps(row).lower()]
        output.append({"path": str(consolidations_path), "sha256": sha256_file(consolidations_path),
                       "bytes": consolidations_path.stat().st_size, "row_count": len(rows),
                       "row_count_unit": "JSONL consolidation records", "NHL_related_records": len(nhl_rows),
                       "persistent_athlete_id_documented": False, "game_identifier_present": False,
                       "direct_tracking_identity_crosswalk": False,
                       "qualifies_as_verified_identity_source": False,
                       "reason": "Repository identity consolidation log has no NHL game-level tracking crosswalk."})
    sample_path = ROOT / "backend/data/sample_data.json"
    if sample_path.is_file():
        data = json.loads(sample_path.read_text(encoding="utf-8"))
        nhl_sample = data.get("nhl", {})
        games = nhl_sample.get("games", []) if isinstance(nhl_sample, dict) else []
        output.append({"path": str(sample_path), "sha256": sha256_file(sample_path),
                       "bytes": sample_path.stat().st_size, "row_count": len(games),
                       "row_count_unit": "NHL sample fixture games", "identity_fields": [],
                       "persistent_athlete_id_documented": False, "game_identifier_present": bool(games),
                       "direct_tracking_identity_crosswalk": False,
                       "qualifies_as_verified_identity_source": False,
                       "reason": "Synthetic/sample game fixture, not an external roster or tracking identity source."})
    return output


def find_repository_databases() -> list[str]:
    found = []
    for current, dirs, files in os.walk(ROOT, followlinks=False):
        dirs[:] = [d for d in dirs if d not in DATA_DIRS_TO_PRUNE]
        for name in files:
            path = Path(current) / name
            if path.suffix.lower() in DB_SUFFIXES:
                if path.name == "picks.db":
                    found.append(f"excluded production DB without opening: {path}")
                else:
                    found.append(f"local DB candidate not opened by this inventory: {path}")
    return found


def inventory_research_data_files(gate: dict) -> list[dict]:
    expected_hashes = {str((RELEASE_DATA / row["name"]).resolve()): row["actual_sha256"]
                       for row in gate["source_asset_hashes"]}
    for name, (digest, _) in EXTRACTION_ARTIFACTS.items():
        expected_hashes[str((MOVEMENT_DATA / name).resolve())] = digest
    data_files = []
    for current, dirs, files in os.walk(RESEARCH_DATA, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in DATA_DIRS_TO_PRUNE)
        for name in sorted(files):
            path = Path(current) / name
            rel = str(path.relative_to(RESEARCH_DATA))
            if path.is_symlink():
                resolved = path.resolve()
                if RESEARCH_DATA.resolve() not in resolved.parents:
                    raise RuntimeError(f"research data symlink escapes declared root: {path} -> {resolved}")
                continue
            known = expected_hashes.get(str(path.resolve()))
            digest = known if known else sha256_file(path)
            data_files.append({"path": str(path), "relative_path": rel, "sha256": digest,
                               "bytes": path.stat().st_size,
                               "directory_class": ("stathletes_release" if "stathletes-big-data-cup-2026" in str(path) else
                                                   "movement_data" if "nhl-multi-agent-movement-2026-10-23" in str(path) else
                                                   "movement_smoke_or_other_nhl_data")})
    return sorted(data_files, key=lambda row: row["relative_path"])


def identity_overlap_summary(id_sets: dict, jersey_sets: dict, composite_id_sets: dict,
                             raw_value_sets: dict, raw_counts: dict,
                             numeric_jersey_sets: dict) -> dict:
    ranges = {}
    for game in EXPECTED_GAMES:
        values = id_sets[game]
        counts = raw_counts[game]
        ranges[game] = {"numeric_raw_id_min": min(values) if values else None,
                        "numeric_raw_id_max": max(values) if values else None,
                        "distinct_numeric_raw_ids": len(values),
                        "distinct_literal_raw_ids": len(raw_value_sets[game]),
                        "player_tracking_records": counts["player_rows"],
                        "records_with_raw_id": counts["player_id_rows"],
                        "records_missing_raw_id": counts["player_rows"] - counts["player_id_rows"],
                        "records_with_non_numeric_raw_id": counts["non_numeric_player_id_rows"],
                        "distinct_composite_ids": len(composite_id_sets[game]),
                        "distinct_jerseys": len(jersey_sets[game]),
                        "distinct_numeric_jersey_values": len(numeric_jersey_sets[game]),
                        "nonnumeric_jersey_field_values": sorted(v for v in jersey_sets[game] if not v.isdigit()),
                        "jersey_values": sorted(jersey_sets[game], key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else x))}
    interval_pairs = exact_pairs = exact_literal_pairs = jersey_pairs = numeric_jersey_pairs = 0
    composite_exact_pairs = 0
    pair_rows = []
    for i, game_a in enumerate(EXPECTED_GAMES):
        for game_b in EXPECTED_GAMES[i + 1:]:
            a, b = ranges[game_a], ranges[game_b]
            interval = bool(a["numeric_raw_id_min"] is not None and b["numeric_raw_id_min"] is not None
                            and max(a["numeric_raw_id_min"], b["numeric_raw_id_min"])
                            <= min(a["numeric_raw_id_max"], b["numeric_raw_id_max"]))
            shared_ids = sorted(id_sets[game_a] & id_sets[game_b])
            shared_literal_ids = sorted(raw_value_sets[game_a] & raw_value_sets[game_b])
            shared_composite_ids = sorted(composite_id_sets[game_a] & composite_id_sets[game_b])
            shared_jerseys = sorted(jersey_sets[game_a] & jersey_sets[game_b])
            shared_numeric_jerseys = sorted(numeric_jersey_sets[game_a] & numeric_jersey_sets[game_b], key=int)
            interval_pairs += int(interval)
            exact_pairs += int(bool(shared_ids))
            exact_literal_pairs += int(bool(shared_literal_ids))
            jersey_pairs += int(bool(shared_jerseys))
            numeric_jersey_pairs += int(bool(shared_numeric_jerseys))
            composite_exact_pairs += int(bool(shared_composite_ids))
            pair_rows.append({"game_a": game_a, "game_b": game_b,
                              "numeric_raw_id_ranges_overlap": interval,
                              "exact_raw_id_intersection_count": len(shared_ids),
                              "exact_raw_id_intersection_values": shared_ids,
                              "exact_raw_id_literal_intersection_count": len(shared_literal_ids),
                              "exact_raw_id_literal_intersection_values": shared_literal_ids,
                              "exact_composite_id_intersection_count": len(shared_composite_ids),
                              "exact_composite_id_intersection_values": shared_composite_ids,
                              "jersey_intersection_count": len(shared_jerseys),
                              "jersey_intersection_values": shared_jerseys,
                              "numeric_jersey_intersection_count": len(shared_numeric_jerseys),
                              "numeric_jersey_intersection_values": shared_numeric_jerseys})
    return {"per_game": ranges, "pairwise_comparison_count": len(pair_rows),
            "numeric_raw_id_range_overlap_pairs": interval_pairs,
            "exact_numeric_raw_id_value_overlap_pairs": exact_pairs,
            "exact_raw_id_literal_overlap_pairs": exact_literal_pairs,
            "composite_id_exact_overlap_pairs": composite_exact_pairs,
            "composite_id_ranges_applicable": False,
            "composite_id_interpretation": "id is a non-numeric composite containing game, period, team, and raw_id; its zero cross-game exact intersection is mechanical, not evidence of unique athletes.",
            "jersey_value_overlap_pairs": jersey_pairs,
            "numeric_jersey_value_overlap_pairs": numeric_jersey_pairs,
            "pairwise_intersections": pair_rows,
            "interpretation": "These are numeric collisions/range overlaps among game-scoped IDs and jersey numbers only; no cross-game identity join is inferred."}


def build_inventory(gate: dict, d7: dict, source_manifest: dict, extraction: dict) -> dict:
    id_sets = defaultdict(set)
    jersey_sets = defaultdict(set)
    numeric_jersey_sets = defaultdict(set)
    composite_id_sets = defaultdict(set)
    raw_value_sets = defaultdict(set)
    raw_counts = defaultdict(lambda: Counter())
    assets = []
    release_game_keys = set()
    for item in source_manifest["files"]:
        path = RELEASE_DATA / item["name"]
        row = count_csv_asset(path, item, id_sets, jersey_sets, numeric_jersey_sets,
                              composite_id_sets, raw_value_sets, raw_counts)
        assets.append(row)
        if row["game_key_from_filename"]:
            release_game_keys.add(row["game_key_from_filename"])
    if release_game_keys != set(EXPECTED_GAMES):
        raise RuntimeError(f"raw source game coverage differs from DIAG7: {sorted(release_game_keys)}")

    normalized_path = MOVEMENT_DATA / "normalized_observations.jsonl.gz"
    normalized = scan_normalized_jsonl(normalized_path, EXPECTED_GAMES)
    rollout = scan_rollout_starts(MOVEMENT_DATA / "rollout_starts.json.gz")
    npz = scan_npz_members(MOVEMENT_DATA / "training_windows.npz")
    repo_scenarios = scan_scenario_archive(RESEARCH / "results/scenario_archive-bc91d1610de5.json.gz")
    repo_id_artifacts = read_repo_identity_artifacts()

    expected_observation_count = extraction["counts"]["normalized_observation_groups"]
    expected_player_rows = extraction["counts"]["normalized_player_rows"]
    if normalized["row_count"] != expected_observation_count:
        raise RuntimeError(f"normalized row count differs from pinned extraction metadata: {normalized['row_count']} != {expected_observation_count}")
    if normalized["player_object_count"] != expected_player_rows:
        raise RuntimeError(f"normalized player-object count differs from pinned extraction metadata: {normalized['player_object_count']} != {expected_player_rows}")

    overlap = identity_overlap_summary(id_sets, jersey_sets, composite_id_sets,
                                       raw_value_sets, raw_counts, numeric_jersey_sets)
    for row in repo_id_artifacts:
        row["candidate_source"] = True
        row["external_local_source"] = row["path"].endswith("published-identity-names.json")
        row["game_coverage"] = []
        row["documented_persistent_athlete_id"] = bool(row.get("persistent_athlete_id_documented"))
        row["documented_game_identifier"] = bool(row.get("game_identifier_present"))
        row["direct_tracking_to_athlete_link"] = bool(row.get("direct_tracking_identity_crosswalk"))
        row["direct_frozen_game_to_source_game_link"] = False
        row["persistent_athlete_id_field"] = "nhl_id" if row.get("persistent_athlete_id_documented") else None
        row["source_game_id_field"] = None
        row["qualifies_as_verified_identity_source"] = False
    for row in assets:
        if row["class"] in ("tracking", "events", "shifts"):
            row["source_semantics"] = "Anonymized Big Data Cup event/tracking/shift records; player IDs are local source identifiers."
            row["local_identity_documentation"] = {
                "path": "docs/research/NHL-TEN-GAME-KINEMATICS-REPORT-2026-10-22.md",
                "statement": "The release's Player Id is retained only as a game/period-scoped tracking identity; it is not merged across games or treated as a verified athlete identity.",
            }
            row["identity_source_decision"] = "does_not_supply_documented_persistent_athlete_id_or_direct_external_crosswalk"

    row_count_by_type = Counter(row["class"] for row in assets)
    csv_rows_by_type = Counter()
    for row in assets:
        csv_rows_by_type[row["class"]] += row["row_count"]

    repo_db_files = find_repository_databases()
    discovered_files = inventory_research_data_files(gate)
    candidate_assets = [row for row in assets if row["candidate_source"]]
    candidate_sources = candidate_assets + repo_id_artifacts
    qualifying_sources = [row for row in candidate_sources
                          if row.get("documented_persistent_athlete_id")
                          and row.get("documented_game_identifier")
                          and row.get("direct_tracking_to_athlete_link")
                          and row.get("direct_frozen_game_to_source_game_link")]
    if qualifying_sources:
        raise RuntimeError("A candidate appears to qualify; implement and preregister verified Q2 linkage before reporting.")
    return {
        "identity_field_inventory": {
            "DIAG7_player_object_fields": PLAYER_FIELDS_DIAG7,
            "normalized_observation_top_level_fields": normalized["top_level_fields_observed"],
            "normalized_observation_player_fields": normalized["player_fields_observed"],
            "normalized_observation_puck_fields": normalized["puck_fields_observed"],
            "scenario_archive_player_fields": repo_scenarios["player_fields"],
            "raw_release_identity_columns_by_asset_type": {
                category: sorted({field for row in assets if row["class"] == category for field in row["identity_bearing_fields"]})
                for category in ("tracking", "events", "shifts")},
            "field_semantics": [
                {"field": "history", "meaning": "past state/history payload", "persistent_athlete_id": False},
                {"field": "id / track_id", "meaning": "composite game-period-team-source-track key", "persistent_athlete_id": False},
                {"field": "raw_id / player_id_source / Player Id / Player_Id / Player_Id_2", "meaning": "source local track/actor ID", "persistent_athlete_id": False},
                {"field": "jersey / Player Jersey Number", "meaning": "jersey number; values may recur across games", "persistent_athlete_id": False},
                {"field": "team / Team / Home_Team / Away_Team", "meaning": "anonymized team or within-game side", "persistent_athlete_id": False},
                {"field": "x / y", "meaning": "rink coordinates", "persistent_athlete_id": False},
            ],
            "local_documentation": [
                {"path": "docs/research/NHL-TEN-GAME-KINEMATICS-REPORT-2026-10-22.md",
                 "quote": "The release's `Player Id` is retained only as a game/period-scoped tracking identity; it is not merged across games or treated as a verified athlete identity."},
                {"path": "docs/research/NHL-MULTI-AGENT-MOVEMENT-PROTOCOL-2026-10-23.md",
                 "quote": "Never join track IDs across games."},
                {"path": "research/nhl-multi-agent-movement-2026-10-23/prepare_movement_data.py",
                 "quote": "track_id = f'{game}|{period}|{team}|{raw_id}'"},
            ],
            "local_source_data_dictionary_for_cross_game_athlete_identity": None,
        },
        "raw_source_asset_counts": {"assets": len(assets), "asset_files_by_type": dict(sorted(row_count_by_type.items())),
                                     "data_rows_by_type": dict(sorted(csv_rows_by_type.items()))},
        "source_release_asset_inventory": assets,
        "candidate_source_paths": candidate_sources,
        "qualifying_identity_source_count": len(qualifying_sources),
        "tracking_id_overlap": overlap,
        "normalized_observations": normalized,
        "rollout_starts": rollout,
        "training_windows": npz,
        "scenario_archive": repo_scenarios,
        "repository_identity_artifacts": repo_id_artifacts,
        "repository_database_candidates": repo_db_files,
        "research_data_file_inventory": discovered_files,
        "research_data_file_count": len(discovered_files),
        "research_data_bytes_total": sum(row["bytes"] for row in discovered_files),
        "verified_cross_game_identity_source": "none",
        "q1_status": "none",
        "coverage_basis": {"games": EXPECTED_GAMES, "games_count": 10,
                           "DIAG7_plus45_pairs": 2164, "DIAG7_pairs_by_distance_bin": {str(i): 541 for i in range(1, 5)},
                           "cross_game_track_id_join_performed": False,
                           "jersey_join_performed": False, "name_join_performed": False},
        "q2": {"status": "not_applicable", "unmatched_pair_count": 2164,
               "unmatched_pair_pct": 100.0, "unmatched_game_count": 10, "unmatched_game_pct": 100.0,
               "unmatched_distance_bins": {str(i): {"unmatched": 541, "total": 541, "pct": 100.0}
                                           for i in range(1, 5)},
               "pairs_with_at_least_two_training_observations": None,
               "pairs_with_at_least_two_training_observations_status": "not_applicable; not estimated",
               "reason": "Q1 found no documented source linking the frozen tracking IDs to persistent athlete IDs and source game IDs."},
    }


def render_report(result: dict, runtime: float, result_sha: str, result_bytes: int, evaluator_sha: str) -> str:
    inv = result["Q1"]
    first = "verified_cross_game_identity_source = none. The pair-identity question is closed permanently on this source."
    lines = [
        "# NHL JC-DIAG8: cross-game identity feasibility", "",
        first, "",
        f"This is a data-availability finding on ten inspected development games, not an independent evaluation. The DIAG7 Step 0 correction at `docs/research/NHL-JC-DIAG7-REPORT-2026-10-23.md` corrected the interpretation of its structural-zero intervals; DIAG8 applies that evidentiary framing. No network, provider, or database was accessed.", "",
        f"Source base: `{SOURCE_BASE}`. Step 0 correction: `{STEP0_COMMIT}`. Preregistration: `{PREREG_COMMITS[-1]}`.", "",
        "## Provenance gate", "",
        f"**{'PASS' if result['provenance_gate']['all_assertions_passed'] else 'FAIL'}** — {result['provenance_gate']['passed_count']}/{result['provenance_gate']['check_count']} assertions. DIAG7 pinned result was 76,326 bytes; its 17 inherited source hashes were checked against disk. The source-release manifest's 54 assets and all three pinned movement-data artifacts were hash/size checked before Q1.", "",
        "## Identity fields and semantics", "",
        "Fields below are the union observed in DIAG7 player objects, the full normalized observation stream, the 200 rollout starts, and the archived scenarios.", "",
        "| Observed player-object field | Local meaning / evidence | Stable athlete key across games? |", "|---|---|---|",
    ]
    field_notes = {
        "history": ("Prior observed position history; not a person identifier.", "No"),
        "id": ("Composite `game|period|team|raw_id` built by `prepare_movement_data.py`; scoped to game/period.", "No; scoped composite"),
        "track_id": ("Generated composite `game|period|team|raw_id`; scoped to game/period.", "No; scoped composite"),
        "raw_id": ("Source `Player Id`; the kinematics report documents it as game/period-scoped.", "No; local track identity"),
        "player_id_source": ("Copied source `Player Id`; local track/actor ID.", "No; local track identity"),
        "jersey": ("Source `Player Jersey Number`; recurring values are possible.", "No; recurrence is not identity evidence"),
        "team": ("Anonymized source team or within-game Home/Away label.", "No"),
        "kind": ("Player/puck record type.", "Not an athlete identifier"),
        "x": ("Rink X coordinate.", "Not an athlete identifier"),
        "y": ("Rink Y coordinate.", "Not an athlete identifier"),
        "coordinate_valid": ("Whether source XY coordinates passed the local validity check.", "Not an athlete identifier"),
        "coordinate_missing": ("Derived inverse of coordinate validity.", "Not an athlete identifier"),
        "row_visible": ("Source row was present in the observation.", "Not an athlete identifier"),
        "identity_conflict": ("Local quarantine flag for conflicting source identity mapping.", "Not a persistent identity key"),
        "visibility_confidence": ("Confidence metadata; source value is unknown.", "Not an athlete identifier"),
        "past_displacement": ("Displacement derived from past observations.", "Not an athlete identifier"),
        "heading_rad": ("Heading derived from past displacement.", "Not an athlete identifier"),
        "past_kinematic_state": ("Kinematic features derived from past observations.", "Not an athlete identifier"),
    }
    all_player_fields = sorted(set(PLAYER_FIELDS_DIAG7)
                               | set(inv["identity_field_inventory"]["normalized_observation_player_fields"])
                               | set(inv["rollout_starts"]["player_fields"])
                               | set(inv["scenario_archive"]["player_fields"]))
    for field in all_player_fields:
        meaning, stability = field_notes.get(field, ("Observed in the normalized player object; no local definition identifies it as a persistent athlete key.", "No documented stable key"))
        lines.append(f"| `{field}` | {meaning} | {stability} |")
    extra = inv["identity_field_inventory"]
    lines += ["", "Raw event identity/game-context columns: " + ", ".join(f"`{x}`" for x in extra["raw_release_identity_columns_by_asset_type"]["events"]) + ". Raw shift columns: " + ", ".join(f"`{x}`" for x in extra["raw_release_identity_columns_by_asset_type"]["shifts"]) + ". Raw tracking columns: " + ", ".join(f"`{x}`" for x in extra["raw_release_identity_columns_by_asset_type"]["tracking"]) + ". `Image Id` is separately recognized as an ordered observation identifier, not an athlete or canonical game identity. The local release bundle has no data dictionary defining these player IDs as persistent across games.", "",
              "Among player-level fields, jersey is the only exposed human-facing label that could plausibly recur for the same person; it is not stable or unique identity evidence. Game labels are dates plus anonymized team labels; there is no NHL game ID or direct track-to-NHL-ID crosswalk.", "",
              "Local documentation: the ten games are described as anonymized in `docs/research/NHL-TEN-GAME-KINEMATICS-REPORT-2026-10-22.md`; it states: “The release's `Player Id` is retained only as a game/period-scoped tracking identity; it is not merged across games or treated as a verified athlete identity.”", "",
              "### Track-ID and jersey collision check", "",
              f"`id` is a non-numeric composite, so it has no numeric interval; its exact cross-game intersection is {inv['tracking_id_overlap']['composite_id_exact_overlap_pairs']}/{inv['tracking_id_overlap']['pairwise_comparison_count']} game pairs by construction because its key embeds the game. `raw_id` numeric intervals overlap in {inv['tracking_id_overlap']['numeric_raw_id_range_overlap_pairs']}/{inv['tracking_id_overlap']['pairwise_comparison_count']} pairs; exact numeric values intersect in {inv['tracking_id_overlap']['exact_numeric_raw_id_value_overlap_pairs']}/{inv['tracking_id_overlap']['pairwise_comparison_count']}, and exact source-string values intersect in {inv['tracking_id_overlap']['exact_raw_id_literal_overlap_pairs']}/{inv['tracking_id_overlap']['pairwise_comparison_count']}. Numeric jersey field values recur in {inv['tracking_id_overlap']['numeric_jersey_value_overlap_pairs']}/{inv['tracking_id_overlap']['pairwise_comparison_count']} game pairs; raw field labels recur in {inv['tracking_id_overlap']['jersey_value_overlap_pairs']}/{inv['tracking_id_overlap']['pairwise_comparison_count']}. Non-numeric values are retained as raw labels and not assigned jersey semantics. These are collision diagnostics only; neither ID nor jersey recurrence is an identity match.", "",
              "| Game | Numeric raw_id min–max | Distinct raw IDs | Composite id count | Raw Player Jersey Number field values |", "|---|---:|---:|---:|---|"]
    for game, row in inv["tracking_id_overlap"]["per_game"].items():
        jersey_text = ", ".join(row["jersey_values"])
        lines.append(f"| {game} | {row['numeric_raw_id_min']}–{row['numeric_raw_id_max']} | {row['distinct_numeric_raw_ids']} | {row['distinct_composite_ids']} | {jersey_text} |")
    raw_candidate_count = sum(row.get("class") in {"tracking", "events", "shifts"} for row in inv["candidate_source_paths"])
    lines += ["", "## Candidate local sources", "",
              f"Inspected {len(inv['candidate_source_paths'])} identity-source candidates: {raw_candidate_count} raw Stathletes Events/Shifts/Tracking files and {len(inv['repository_identity_artifacts'])} repository identity/sample files. The local research-data inventory covered {result['inventory_scope']['research_data_files_seen']} files ({result['inventory_scope']['research_data_bytes_seen']:,} bytes). The source-release manifest (`{SOURCE_MANIFEST}`, SHA-256 `{next((c['actual'] for c in result['provenance_gate']['checks'] if c['name'] == 'Stathletes_download_manifest_sha256'), None)}`) pins all 54 downloaded assets; the separate camera-orientation file is not an identity-source candidate.", "",
              "| Candidate path | SHA-256 | Data rows / unit | Frozen-game coverage | Documented persistent athlete ID + game ID + direct tracking link? |", "|---|---|---:|---|---|"]
    for row in inv["candidate_source_paths"]:
        coverage = ", ".join(row.get("game_coverage", [])) or "none verified"
        count = f"{row['row_count']} {row.get('row_count_unit', 'records')}"
        if row.get("candidate_source") and row.get("class") in {"tracking", "events", "shifts"}:
            evidence = "No: no persistent athlete ID; filename/date-team label is not a canonical game key; no direct crosswalk."
        else:
            identity_field = row.get("persistent_athlete_id_field") or "none"
            game_field = row.get("source_game_id_field") or "none"
            evidence = f"No: athlete field `{identity_field}`; game field `{game_field}`; direct track link: no. {row.get('reason', '')}"
        lines.append(f"| `{row['path']}` | `{row['sha256']}` | {count} | {coverage} | {evidence} |")
    lines += ["", "No local roster/boxscore/gamebook or official NHL play-by-play file was found that supplies a direct mapping from these anonymized track IDs to persistent athlete IDs and source game IDs. The NHL publisher identity snapshot contains `nhl_id` plus names, but not the required game key or tracking crosswalk. Names, jersey matches, dates/team similarities, and numeric track-ID collisions were not used as joins.", "",
              "`verified_cross_game_identity_source = none`.", "",
              "## Q2 — not applicable", "",
              "All 2,164 +45 pairs remain unmatched (100%); all 10 games are unmatched; each of the four frozen bins has 541/541 unmatched pairs (100%). The count retaining at least two LOOG training observations is not applicable and was not estimated.", "",
              "## Decision", "",
              "Registered reading applied (verbatim):", "",
              "> `verified_cross_game_identity_source = none` → **the pair-identity question is closed permanently on this source.** No further diagnostics on these ten games; any resumption requires new data acquisition (an identity-bearing roster/boxscore feed or a tracking vendor with persistent athlete IDs), and that acquisition is a data question, not a modelling one.", "",
              "This closes the identity question only for this source and these inspected games. DIAG2–DIAG6 persistence remains descriptive; this is not an independent evaluation.", "",
              "## Reproduction", "",
              "`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_jc_diag8_identity_feasibility.py`", "",
              "`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_jc_diag8_identity_feasibility.py --output /tmp/jc-diag8-identity-feasibility-repeat.json --no-report`", "",
              "Checks: `ast.parse`; `git diff --check`; deterministic rerun and `cmp` against the committed JSON.", "",
              f"Primary runtime: {runtime:.3f} seconds. Evaluator SHA-256: `{evaluator_sha}`. Result SHA-256: `{result_sha}`; byte count: {result_bytes}.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-only", action="store_true", help="check pinned inputs without computing Q1/Q2")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()
    started = time.monotonic()
    gate, d7, source_manifest, extraction = verify_gate()
    if not gate["all_assertions_passed"]:
        failed = [row for row in gate["checks"] if not row["passed"]]
        result = {"schema_version": 1, "source_base": SOURCE_BASE,
                  "preregistration_commit": PREREG_COMMITS[-1],
                  "provenance_gate": gate, "Q1_Q2_calculated": False,
                  "failure": "DIAG8 provenance gate failed; Q1/Q2 were not run"}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"gate_passed": False, "failed_checks": failed, "output": str(args.output)}, indent=2))
        return 2
    if args.gate_only:
        print(json.dumps({"gate_passed": True, "checks": gate["passed_count"],
                          "asset_hashes": len(gate["source_asset_hashes"]),
                          "Q1_Q2_calculated": False}, indent=2))
        return 0

    inventory = build_inventory(gate, d7, source_manifest, extraction)
    result = {
        "schema_version": 1, "source_base": SOURCE_BASE,
        "step0_correction_commit": STEP0_COMMIT,
        "preregistration_commits": list(PREREG_COMMITS),
        "preregistration_sha256": PREREG_SHA256,
        "Q1_Q2_calculated": True,
        "provenance_gate": gate,
        "inventory_scope": {
            "repository": str(ROOT), "vendored_data_root": str(RESEARCH_DATA),
            "network_access": False, "provider_contact": False, "database_access": False,
            "production_database_opened": False,
            "research_data_files_seen": inventory["research_data_file_count"],
            "research_data_bytes_seen": inventory["research_data_bytes_total"],
            "repository_database_candidates": inventory["repository_database_candidates"],
            "excluded": [".git internals", "dependency/build caches", "files outside the declared repository and /root/lp-research-data roots"],
        },
        "Q1": {key: value for key, value in inventory.items() if key != "q2"},
        "Q2": inventory["q2"],
        "registered_reading": "verified_cross_game_identity_source = none → the pair-identity question is closed permanently on this source. No further diagnostics on these ten games; any resumption requires new data acquisition (an identity-bearing roster/boxscore feed or a tracking vendor with persistent athlete IDs), and that acquisition is a data question, not a modelling one.",
    }
    result["evaluator_sha256"] = sha256_file(Path(__file__).resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    args.output.write_text(encoded, encoding="utf-8")
    result_sha = sha256_file(args.output)
    result_bytes = args.output.stat().st_size
    runtime = time.monotonic() - started
    if not args.no_report:
        report = render_report(result, runtime, result_sha, result_bytes, result["evaluator_sha256"])
        REPORT.write_text(report, encoding="utf-8")
    print(json.dumps({"gate_passed": True, "gate_checks": gate["passed_count"],
                      "source_assets": len(gate["source_asset_hashes"]),
                      "verified_cross_game_identity_source": inventory["verified_cross_game_identity_source"],
                      "Q2": inventory["q2"]["status"], "bytes": result_bytes,
                      "sha256": result_sha, "runtime_seconds": round(runtime, 3),
                      "output": str(args.output), "report": None if args.no_report else str(REPORT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
