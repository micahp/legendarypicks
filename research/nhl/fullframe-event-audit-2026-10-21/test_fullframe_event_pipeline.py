#!/usr/bin/env python3
"""Deterministic import and source-verification failure-injection tests."""
from __future__ import annotations

import csv
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audit_full_frame as audit  # noqa: E402
import fetch_full_frame_evidence as importer  # noqa: E402


GAME1 = "2018020001"
GAME2 = "2018020002"


class ShootoutScoreConventionTests(unittest.TestCase):
    def test_shootout_winner_adjustment_handles_side_with_no_ordinary_goal(self):
        adjusted = audit.apply_shootout_score_convention(
            {"home": 1}, {"home": 1, "away": 2}, shootout=True)
        self.assertEqual(adjusted, {"home": 1, "away": 1})
        zero_zero = audit.apply_shootout_score_convention(
            {}, {"home": 0, "away": 1}, shootout=True)
        self.assertEqual(zero_zero, {"home": 0, "away": 1})

    def test_tied_score_does_not_invent_shootout_winner(self):
        adjusted = audit.apply_shootout_score_convention(
            {}, {"home": 0, "away": 0}, shootout=True)
        self.assertEqual(adjusted, {"home": 0, "away": 0})


class SeasonMetricAggregationTests(unittest.TestCase):
    def test_medians_and_maxima_are_not_summed_across_games(self):
        self.assertEqual(audit.aggregate_season_metric(
            "median_shift_to_official_toi_ratio", [1.0, 1.2, 2.0]), 1.2)
        self.assertEqual(audit.aggregate_season_metric(
            "skater_toi_max_delta_seconds", [10, 900, 40]), 900)
        self.assertEqual(audit.aggregate_season_metric("event_rows", [10, 20, 30]), 60)


class TimelineSequenceTests(unittest.TestCase):
    def test_period_regression_is_separate_from_monotonic_publisher_order(self):
        quality = audit.timeline_sequence_quality([
            {"sortOrder": 8, "periodDescriptor": {"number": 1, "periodType": "REG"}},
            {"sortOrder": 9, "periodDescriptor": {"number": 2, "periodType": "REG"}},
            {"sortOrder": 10, "periodDescriptor": {"number": 1, "periodType": "REG"}},
        ])
        self.assertEqual(quality, {"sort_order_issue_count": 0, "period_number_regressions": 1})

    def test_duplicate_and_decreasing_publisher_order_are_flagged(self):
        quality = audit.timeline_sequence_quality([
            {"sortOrder": 8, "periodDescriptor": {"number": 1, "periodType": "REG"}},
            {"sortOrder": 8, "periodDescriptor": {"number": 1, "periodType": "REG"}},
            {"sortOrder": 7, "periodDescriptor": {"number": 1, "periodType": "REG"}},
        ])
        self.assertEqual(quality["sort_order_issue_count"], 2)


def pbp_body(game_id: str = GAME1) -> bytes:
    return json.dumps({
        "id": game_id, "gameType": 2,
        "homeTeam": {"id": 10, "abbrev": "TOR"},
        "awayTeam": {"id": 8, "abbrev": "MTL"},
        "plays": [{"eventId": 1, "typeDescKey": "shot-on-goal"}],
    }, separators=(",", ":")).encode()


def shifts_body(game_id: str = GAME1) -> bytes:
    return json.dumps({"data": [{"gameId": int(game_id), "typeCode": 517, "playerId": 123}],
                       "total": 1}, separators=(",", ":")).encode()


def create_cache(root: Path, game_id: str, kind: str, raw: bytes | None = None,
                 url: str | None = None) -> dict:
    raw = raw if raw is not None else (pbp_body(game_id) if kind == "pbp" else shifts_body(game_id))
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    rows = importer.validate_payload(kind, game_id, raw)
    meta = {
        "game_id": game_id, "kind": kind,
        "url": url or importer.source_url(kind, game_id), "http_status": 200,
        "content_type": "application/json", "bytes_raw": len(raw),
        "sha256_raw": importer.sha256(raw), "bytes_gz": len(compressed),
        "sha256_gz": importer.sha256(compressed), "rows": rows, "attempts": 1,
        "retrieved_at_utc": "2026-10-21T00:00:00+00:00", "evidence_origin": "test_fixture",
    }
    gz_path, meta_path = importer.body_paths(root, game_id, kind)
    gz_path.parent.mkdir(parents=True, exist_ok=True)
    gz_path.write_bytes(compressed)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return meta


def write_ids(path: Path, ids: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["game_id"])
        writer.writerows((gid,) for gid in ids)


def manifest_row(meta: dict) -> dict:
    return {field: meta.get(field, "") for field in importer.MANIFEST_FIELDS}


class ImporterFailureInjectionTests(unittest.TestCase):
    def test_external_cache_reuse_does_not_call_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache, raw = root / "sample", root / "full"
            meta = create_cache(cache, GAME1, "pbp")
            meta["sample_event_manifest_sha256"] = "a" * 64
            meta["sample_source_commit"] = "485b7561adc5b7f44d83579e7fd406a735781abf"
            _gz_path, meta_path = importer.body_paths(cache, GAME1, "pbp")
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            games, manifest, report = root / "games.csv", root / "manifest.csv", root / "report.json"
            write_ids(games, [GAME1])
            def forbidden(*_args, **_kwargs):
                raise AssertionError("network called for a verified reusable body")
            result = importer.run_import(
                kind="pbp", games_file=games, raw_dir=raw, manifest=manifest,
                report_out=report, reuse_dirs=[cache], pause=0, fetcher=forbidden,
                sleeper=lambda _seconds: None)
            self.assertEqual(result["reused_from_secondary_cache"], 1)
            self.assertEqual(result["network_bodies_new"], 0)
            adopted = importer.verified_existing(raw, GAME1, "pbp")
            self.assertEqual(adopted["sha256_raw"], meta["sha256_raw"])
            self.assertIn(str(cache.resolve()), adopted["evidence_origin"])
            with manifest.open(newline="", encoding="utf-8") as handle:
                manifest_row_value = next(csv.DictReader(handle))
            self.assertEqual(manifest_row_value["sample_event_manifest_sha256"], "a" * 64)
            self.assertEqual(manifest_row_value["sample_source_commit"],
                             "485b7561adc5b7f44d83579e7fd406a735781abf")

    def test_cache_rejects_source_url_identity_hash_and_payload_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            meta = create_cache(root, GAME1, "pbp", url="https://example.invalid/wrong")
            with self.assertRaisesRegex(ValueError, "CACHE_SOURCE_URL_OR_STATUS_MISMATCH"):
                importer.verified_existing(root, GAME1, "pbp")
            gz_path, meta_path = importer.body_paths(root, GAME1, "pbp")
            meta["url"] = importer.source_url("pbp", GAME1)
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            meta["sha256_gz"] = "0" * 64
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "CACHE_COMPRESSED_HASH_MISMATCH"):
                importer.verified_existing(root, GAME1, "pbp")
            with self.assertRaisesRegex(ValueError, "PBP_GAME_ID_MISMATCH"):
                importer.validate_payload("pbp", GAME1, pbp_body(GAME2))
            with self.assertRaisesRegex(ValueError, "PBP_PLAYS_MISSING_OR_INVALID"):
                importer.validate_payload("pbp", GAME1, json.dumps({
                    "id": GAME1, "gameType": 2,
                    "homeTeam": {"id": 10}, "awayTeam": {"id": 8}, "plays": []}).encode())
            with self.assertRaisesRegex(ValueError, "SHIFT_TOTAL_COUNT_MISMATCH"):
                importer.validate_payload("shifts", GAME1, json.dumps({
                    "data": [{"gameId": int(GAME1)}], "total": 2}).encode())

    def test_doubled_shift_chart_rejects_all_intervals(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            issue_writer = audit.CsvGzipWriter(root / "issues.csv.gz", ["reason_code"])
            shift_writer = audit.CsvGzipWriter(root / "shifts.csv.gz", ["disposition"])
            reason_counts, issue_games = {}, {}
            import collections
            reason_counts = collections.Counter()
            issue_games = collections.defaultdict(set)
            payload = {"data": [{
                "id": 1, "typeCode": 517, "playerId": 123, "period": 1,
                "startTime": "0:00", "endTime": "20:00", "duration": "20:00",
                "teamId": 10, "teamAbbrev": "TOR",
            }]}
            intervals, totals = audit.parse_shift_rows(
                payload, "2018", GAME1, shift_writer, issue_writer, reason_counts, issue_games,
                {123: {"appeared": "1", "identity_status": "OK", "team": "TOR", "toi_seconds": "600"}},
                {}, {123}, {"TOR": 10})
            issue_writer.close()
            shift_writer.close()
            self.assertEqual(totals["duplicate_shift_chart"], 1)
            self.assertEqual(totals["shift_intervals_rejected"], 1)
            self.assertEqual(intervals[0]["disposition"], "REJECT")
            self.assertIn(("2018", "DUPLICATE_SHIFT_CHART"), reason_counts)
            with gzip.open(root / "issues.csv.gz", "rt", newline="", encoding="utf-8") as handle:
                issue_rows = list(csv.DictReader(handle))
            with gzip.open(root / "shifts.csv.gz", "rt", newline="", encoding="utf-8") as handle:
                shift_rows = list(csv.DictReader(handle))
            self.assertIn("DUPLICATE_SHIFT_CHART", {row["reason_code"] for row in issue_rows})
            self.assertEqual(shift_rows[0]["disposition"], "REJECT")

    def test_shift_duration_disagreement_quarantines_player_deployment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            issue_writer = audit.CsvGzipWriter(root / "issues.csv.gz", ["reason_code"])
            shift_writer = audit.CsvGzipWriter(root / "shifts.csv.gz", ["disposition"])
            import collections
            reason_counts = collections.Counter()
            issue_games = collections.defaultdict(set)
            payload = {"data": [{
                "id": 1, "typeCode": 517, "playerId": 123, "period": 1,
                "startTime": "0:00", "endTime": "10:00", "duration": "9:00",
                "teamId": 10, "teamAbbrev": "TOR",
            }]}
            intervals, totals = audit.parse_shift_rows(
                payload, "2018", GAME1, shift_writer, issue_writer, reason_counts, issue_games,
                {123: {"appeared": "1", "identity_status": "OK", "team": "TOR", "toi_seconds": "540"}},
                {}, {123}, {"TOR": 10})
            issue_writer.close()
            shift_writer.close()
            self.assertEqual(totals["skater_player_games_eligible"], 0)
            self.assertEqual(totals["shift_intervals_quarantined"], 1)
            self.assertEqual(intervals[0]["disposition"], "QUARANTINE")
            self.assertIn(("2018", "SHIFT_DURATION_DISAGREES_WITH_INTERVAL"), reason_counts)

    def test_shift_without_team_identity_quarantines_player_deployment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            issue_writer = audit.CsvGzipWriter(root / "issues.csv.gz", ["reason_code"])
            shift_writer = audit.CsvGzipWriter(root / "shifts.csv.gz", ["disposition"])
            import collections
            reason_counts = collections.Counter()
            issue_games = collections.defaultdict(set)
            payload = {"data": [{
                "id": 1, "typeCode": 517, "playerId": 123, "period": 1,
                "startTime": "0:00", "endTime": "10:00", "duration": "10:00",
            }]}
            intervals, totals = audit.parse_shift_rows(
                payload, "2018", GAME1, shift_writer, issue_writer, reason_counts, issue_games,
                {123: {"appeared": "1", "identity_status": "OK", "team": "TOR", "toi_seconds": "600"}},
                {}, {123}, {"TOR": 10})
            issue_writer.close()
            shift_writer.close()
            self.assertEqual(totals["skater_player_games_eligible"], 0)
            self.assertEqual(totals["shift_intervals_quarantined"], 1)
            self.assertEqual(intervals[0]["disposition"], "QUARANTINE")
            self.assertIn(("2018", "SHIFT_TEAM_IDENTITY_MISSING"), reason_counts)

    def test_interruption_resumes_from_valid_bodies_without_redownloading(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            games, raw, manifest, report = (root / "games.csv", root / "raw", root / "manifest.csv", root / "report.json")
            write_ids(games, [GAME1, GAME2])
            calls = []
            def interrupted_fetch(gid, kind, raw_dir, _retries):
                calls.append(gid)
                if gid == GAME2:
                    raise KeyboardInterrupt()
                return importer._store_network_body(raw_dir, gid, kind, pbp_body(gid),
                                                     "application/json", importer.dt.datetime.now(importer.dt.timezone.utc), 1, 0.01)
            first = importer.run_import(kind="pbp", games_file=games, raw_dir=raw,
                                        manifest=manifest, report_out=report, pause=0,
                                        fetcher=interrupted_fetch, sleeper=lambda _s: None)
            self.assertEqual(first["stop_reason"], "interrupted")
            self.assertEqual(calls, [GAME1, GAME2])
            calls.clear()
            def second_fetch(gid, kind, raw_dir, _retries):
                calls.append(gid)
                return importer._store_network_body(raw_dir, gid, kind, pbp_body(gid),
                                                     "application/json", importer.dt.datetime.now(importer.dt.timezone.utc), 1, 0.01)
            second = importer.run_import(kind="pbp", games_file=games, raw_dir=raw,
                                         manifest=manifest, report_out=report, pause=0,
                                         fetcher=second_fetch, sleeper=lambda _s: None)
            self.assertEqual(calls, [GAME2])
            self.assertEqual(second["verified_bodies"], 2)
            self.assertEqual(second["stop_reason"], "complete")

    def test_orphaned_valid_body_recovers_sidecar_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gz_path, meta_path = importer.body_paths(root, GAME1, "pbp")
            gz_path.parent.mkdir(parents=True)
            gz_path.write_bytes(gzip.compress(pbp_body(), mtime=0))
            recovered = importer.verified_existing(root, GAME1, "pbp")
            self.assertTrue(meta_path.exists())
            self.assertEqual(recovered["evidence_origin"], "recovered_valid_orphan_body_after_interruption")

    def test_manifest_replace_failure_preserves_previous_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.csv"
            original = b"previous-manifest\nverified\n"
            path.write_bytes(original)
            with mock.patch.object(importer.os, "replace", side_effect=OSError("injected replace failure")):
                with self.assertRaisesRegex(OSError, "injected replace failure"):
                    importer.write_manifest(path, [{"game_id": GAME1, "kind": "pbp"}])
            self.assertEqual(path.read_bytes(), original)

    def test_refusal_stops_and_requires_explicit_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            games, raw, manifest, report = root / "games.csv", root / "raw", root / "manifest.csv", root / "report.json"
            write_ids(games, [GAME1, GAME2])
            previous_meta = create_cache(raw, GAME1, "pbp")
            importer.write_manifest(manifest, [manifest_row(previous_meta)])
            previous_manifest = manifest.read_bytes()
            calls = []
            def refuse(gid, *_args):
                calls.append(gid)
                raise importer.AccessRefused("SOURCE_REFUSED_429")
            first = importer.run_import(kind="pbp", games_file=games, raw_dir=raw,
                                        manifest=manifest, report_out=report, pause=0,
                                        fetcher=refuse, sleeper=lambda _s: None)
            self.assertEqual(first["stop_reason"], "access_refused")
            self.assertEqual(calls, [GAME2])
            self.assertFalse(first["manifest_published"])
            self.assertEqual(manifest.read_bytes(), previous_manifest)
            self.assertTrue(Path(first["progress_manifest"]).is_file())
            with self.assertRaisesRegex(importer.AccessRefused, "PREVIOUS_ACCESS_REFUSAL_IN_REPORT"):
                importer.run_import(kind="pbp", games_file=games, raw_dir=raw,
                                    manifest=manifest, report_out=report, pause=0,
                                    fetcher=refuse, sleeper=lambda _s: None)
            self.assertEqual(manifest.read_bytes(), previous_manifest)
            calls.clear()
            def fetch_after_restore(gid, kind, raw_dir, _retries):
                calls.append(gid)
                return importer._store_network_body(
                    raw_dir, gid, kind, pbp_body(gid), "application/json",
                    importer.dt.datetime.now(importer.dt.timezone.utc), 1, 0.01)
            resumed = importer.run_import(kind="pbp", games_file=games, raw_dir=raw,
                                          manifest=manifest, report_out=report, pause=0,
                                          fetcher=fetch_after_restore, sleeper=lambda _s: None,
                                          resume_after_refusal=True)
            self.assertEqual(resumed["stop_reason"], "complete")
            self.assertTrue(resumed["manifest_published"])
            self.assertEqual(calls, [GAME2])

    def test_existing_body_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create_cache(root, GAME1, "pbp")
            gz_path, meta_path = importer.body_paths(root, GAME1, "pbp")
            before = (gz_path.read_bytes(), meta_path.read_bytes())
            with self.assertRaisesRegex(ValueError, "REFUSE_BODY_OVERWRITE"):
                importer._store_network_body(root, GAME1, "pbp", pbp_body(), "application/json",
                                             importer.dt.datetime.now(importer.dt.timezone.utc), 1, 0.1)
            self.assertEqual((gz_path.read_bytes(), meta_path.read_bytes()), before)

    def test_invalid_cache_stops_without_replacing_manifest_or_fetching(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            games, raw = root / "games.csv", root / "raw"
            manifest, report = root / "manifest.csv", root / "report.json"
            write_ids(games, [GAME1])
            create_cache(raw, GAME1, "pbp")
            _gz_path, meta_path = importer.body_paths(raw, GAME1, "pbp")
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["sha256_gz"] = "0" * 64
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            previous_manifest = b"previous verified manifest\n"
            manifest.write_bytes(previous_manifest)
            def forbidden(*_args, **_kwargs):
                raise AssertionError("invalid cached body must never be silently replaced")
            result = importer.run_import(kind="pbp", games_file=games, raw_dir=raw,
                                        manifest=manifest, report_out=report, pause=0,
                                        fetcher=forbidden, sleeper=lambda _s: None)
            self.assertEqual(result["stop_reason"], "cache_verification_failed")
            self.assertIn("CACHE_COMPRESSED_HASH_MISMATCH", result["failure_note"])
            self.assertFalse(result["manifest_published"])
            self.assertEqual(manifest.read_bytes(), previous_manifest)


class FullFrameManifestVerificationTests(unittest.TestCase):
    def test_derived_gzip_csv_is_byte_reproducible(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            hashes = []
            for name in ("one.csv.gz", "two.csv.gz"):
                writer = audit.CsvGzipWriter(root / name, ["game_id", "value"])
                writer.row({"game_id": GAME1, "value": 7})
                writer.close()
                hashes.append(audit.sha256_file(root / name))
            self.assertEqual(hashes[0], hashes[1])

    def test_missing_duplicate_and_hash_mismatch_are_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw_root = root / "raw"
            meta = create_cache(raw_root, GAME1, "pbp")
            manifest = root / "manifest.csv"
            fields = ["game_id", "kind", "url", "http_status", "content_type", "bytes_raw",
                      "sha256_raw", "bytes_gz", "sha256_gz", "rows", "retrieved_at_utc", "note"]
            good = {field: meta.get(field, "") for field in fields}
            def write_manifest(rows):
                with manifest.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(rows)
            write_manifest([good])
            verified, issues, summary = audit.verify_source("pbp", [GAME1, GAME2], manifest, raw_root)
            codes = {row["reason_code"] for row in issues}
            self.assertIn("MANIFEST_ROW_MISSING", codes)
            self.assertEqual(summary["verified_bodies"], 1)
            self.assertNotIn("payload", verified[GAME1])
            loaded = audit.load_verified_payload("pbp", GAME1, verified[GAME1])
            self.assertEqual(loaded["payload"]["id"], GAME1)
            provenance_mismatch = dict(good, retrieved_at_utc="2026-10-22T00:00:00+00:00")
            write_manifest([provenance_mismatch])
            _verified, issues, _summary = audit.verify_source("pbp", [GAME1], manifest, raw_root)
            self.assertIn("SIDECAR_MANIFEST_MISMATCH_RETRIEVED_AT_UTC",
                          {row["detail"] for row in issues})
            write_manifest([good, good])
            duplicate_verified, issues, _summary = audit.verify_source("pbp", [GAME1], manifest, raw_root)
            self.assertIn("DUPLICATE_MANIFEST_ROW", {row["reason_code"] for row in issues})
            self.assertNotIn(GAME1, duplicate_verified)
            corrupt = dict(good, sha256_raw="0" * 64)
            write_manifest([corrupt])
            _verified, issues, _summary = audit.verify_source("pbp", [GAME1], manifest, raw_root)
            self.assertIn("BODY_VERIFICATION_FAILED", {row["reason_code"] for row in issues})

    def test_prior_manifest_comparison_accepts_exact_rows_and_exposes_hash_conflicts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            meta = create_cache(root / "raw", GAME1, "pbp")
            current, prior = root / "current.csv", root / "prior.csv"

            def write(path, row):
                with path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=importer.MANIFEST_FIELDS,
                                            lineterminator="\n")
                    writer.writeheader()
                    writer.writerow({field: row.get(field, "") for field in importer.MANIFEST_FIELDS})

            write(current, meta)
            write(prior, meta)
            summary, issues = audit.compare_prior_manifest("pbp", [GAME1], current, prior)
            self.assertEqual(summary["matched_rows"], 1)
            self.assertEqual(issues, [])
            write(prior, dict(meta, sha256_raw="0" * 64))
            summary, issues = audit.compare_prior_manifest("pbp", [GAME1], current, prior)
            self.assertEqual(summary["matched_rows"], 0)
            self.assertIn("PRIOR_MANIFEST_SOURCE_MISMATCH",
                          {issue["reason_code"] for issue in issues})


if __name__ == "__main__":
    unittest.main(verbosity=2)
