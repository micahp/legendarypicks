#!/usr/bin/env python3
"""Regression checks for the pinned NHL quality adjudication outputs."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path


ARTIFACT_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("build_research_labels", ARTIFACT_DIR / "build_research_labels.py")
builder = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(builder)


def rows(name: str) -> list[dict[str, str]]:
    path = builder.DEFAULT_LABEL_OUTPUT if name == "research_label_quality.csv" else ARTIFACT_DIR / name
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class ResearchLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.issues = rows("official_quality_issues.csv")
        cls.ledger = rows("adjudication_ledger.csv")
        cls.labels_path = builder.DEFAULT_LABEL_OUTPUT
        cls.goalies = rows("official_goalie_outcomes.csv")
        cls.skaters = rows("official_skater_outcomes.csv")
        cls.summary = json.loads((ARTIFACT_DIR / "research_label_summary.json").read_text())

    def test_all_22_issues_have_explicit_dispositions(self) -> None:
        source_rows = [row for row in self.ledger if row["row_type"] == "SOURCE_ISSUE"]
        self.assertEqual(len(self.issues), 22)
        self.assertEqual(len(source_rows), 22)
        dispositions = Counter(row["quality_status"] for row in source_rows)
        self.assertEqual(dispositions, {"ADJUDICATED": 20, "QUARANTINED": 2})
        self.assertEqual(sum(row["quality_status"] == "ADJUDICATED" for row in self.ledger if row["row_type"] == "PLAYER_STAT_FIELD"), 0)
        self.assertEqual(sum(row["quality_status"] == "QUARANTINED" for row in self.ledger if row["row_type"] == "PLAYER_STAT_FIELD"), 6)
        source_issue_ids = {row["source_issue_id"] for row in source_rows}
        for row in rows("research_label_quality.csv"):
            if row["quality_status"] in {"ADJUDICATED", "QUARANTINED"}:
                self.assertIn(row["source_issue_id"], source_issue_ids)

    def test_original_inputs_and_all_22_raw_games_stay_pinned(self) -> None:
        pins = builder.verify_source_pins(ARTIFACT_DIR, builder.DEFAULT_EVIDENCE_ROOT)
        manifest = builder.manifest_by_game(ARTIFACT_DIR / "manifest.jsonl")
        for game_id in sorted({row["game_id"] for row in self.issues}, key=int):
            _entry, raw, _payload = builder.verify_original_game(game_id, manifest, builder.DEFAULT_BACKFILL_ROOT)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), manifest[int(game_id)]["raw_sha256"])
        self.assertEqual(pins["base_commit"], builder.BASE_COMMIT)

    def test_adjudications_have_provenance_and_no_corrections(self) -> None:
        for row in self.ledger:
            if row["quality_status"] == "ADJUDICATED":
                self.assertTrue(row["source_url"])
                self.assertTrue(row["source_sha256"])
                self.assertTrue(row["independent_evidence_value"])
                self.assertEqual(row["corrected_value"], "")
        for row in self.ledger:
            if row["quality_status"] == "QUARANTINED" and row["row_type"] == "PLAYER_STAT_FIELD":
                self.assertTrue(row["original_official_value"])
                self.assertTrue(row["source_url"])
                self.assertTrue(row["source_sha256"])
                self.assertEqual(row["corrected_value"], "")
                self.assertEqual(row["eligible_training"], "false")

    def test_quarantined_values_remain_visible_but_are_not_eligible(self) -> None:
        all_rows = list(builder.read_research_labels(path=self.labels_path, purpose="audit"))
        quarantined = [row for row in all_rows if row["quality_status"] == "QUARANTINED"]
        self.assertEqual(len(quarantined), 6)
        self.assertTrue(all(row["official_value"] is not None and row["accepted_value"] is None and row["value"] is None for row in quarantined))
        for target in ("training", "evaluation", "grading"):
            eligible = list(builder.read_research_labels(path=self.labels_path, purpose=target))
            self.assertFalse(any(row["quality_status"] in {"QUARANTINED", "NOT_APPLICABLE"} for row in eligible))
        with self.assertRaisesRegex(ValueError, "INVALID_RESEARCH_PURPOSE"):
            list(builder.read_research_labels(path=self.labels_path, purpose="roi"))

    def test_unaffected_skaters_remain_eligible(self) -> None:
        affected = {(row["game_id"], row["team"]) for row in self.issues if row["issue_type"] == "PLAYER_SOG_SUM_VS_TEAM_TOTAL"}
        eligible = next(
            row for row in builder.read_research_labels(path=self.labels_path, statistic="SOG", purpose="training")
            if (row["game_id"], row["team"]) not in affected
        )
        self.assertEqual(eligible["quality_status"], "VERIFIED")
        self.assertEqual(eligible["accepted_value"], eligible["official_value"])
        self.assertEqual(eligible["value"], eligible["accepted_value"])

    def test_zero_toi_goalies_are_not_played_game_outcomes(self) -> None:
        zero = next(row for row in self.goalies if row["appeared"] == "0")
        found = [row for row in rows("research_label_quality.csv") if row["record_key"] == zero["record_key"]]
        self.assertEqual({row["statistic"] for row in found}, {"SAVES", "SHOTS_AGAINST", "GOALS_AGAINST"})
        self.assertTrue(all(row["quality_status"] == "NOT_APPLICABLE" for row in found))
        self.assertTrue(all(row["eligible_training"] == "false" and row["accepted_value"] == "" for row in found))

    def test_goalie_arithmetic_is_not_repaired_by_subtraction(self) -> None:
        expected = {"2022020158": ("8476932", "40", "44", "5"), "2022020276": ("8480045", "19", "23", "5")}
        labels = rows("research_label_quality.csv")
        for game_id, (player_id, saves, sa, ga) in expected.items():
            record = next(row for row in self.goalies if row["game_id"] == game_id and row["player_id"] == player_id)
            self.assertEqual((record["saves"], record["shots_against"], record["goals_against"]), (saves, sa, ga))
            self.assertNotEqual(int(saves), int(sa) - int(ga))
            target = [row for row in labels if row["game_id"] == game_id and row["player_id"] == player_id]
            self.assertEqual(len(target), 3)
            self.assertTrue(all(row["quality_status"] == "QUARANTINED" for row in target))
            self.assertTrue(all(row["official_value"] and row["accepted_value"] == "" for row in target))
        self.assertEqual(self.summary["adjudication"]["corrected_official_values"], 0)

    def test_event_join_uses_game_and_numeric_player_id(self) -> None:
        skater_key = {(row["game_id"], row["player_id"]): row for row in self.skaters}
        event_rows = rows("sog_event_reconciliation.csv")
        skater_events = [row for row in event_rows if row["player_class"] == "SKATER"]
        self.assertEqual(len(skater_events), 360)
        for event in skater_events:
            self.assertTrue(event["player_id"].isdigit())
            source = skater_key[(event["game_id"], event["player_id"])]
            self.assertEqual(event["official_sog"], source["sog"])
            self.assertEqual(event["player_count_match"], "true")
        self.assertEqual(len({(row["game_id"], row["player_id"]) for row in skater_events}), 360)
        goalie_rows = {(row["game_id"], row["player_id"]): row for row in self.goalies}
        for event in rows("goalie_event_reconciliation.csv"):
            source = goalie_rows[(event["game_id"], event["player_id"])]
            self.assertTrue(event["player_id"].isdigit())
            self.assertEqual(event["team"], source["team"])
            self.assertEqual(event["toi_seconds"], source["toi_seconds"])

    def test_archive_one_sided_and_alias_overlap_keeps_numeric_identity(self) -> None:
        one_sided = rows("played_goalie_one_sided_rows.csv")
        ayres = next(row for row in one_sided if row["game_id"] == "2019020951" and row["player_id"] == "8479188")
        self.assertEqual(ayres["status"], "OFFICIAL_ONLY")
        self.assertEqual(ayres["official_toi"], "28:41")
        goalie_event = next(
            row for row in rows("sog_event_reconciliation.csv")
            if row["game_id"] == "2019020951" and row["player_id"] == "8479188" and row["player_class"] == "GOALIE"
        )
        self.assertEqual(goalie_event["quality_status"], "ADJUDICATED")

        alias = next(
            row for row in rows("archive_name_crosscheck.csv")
            if row["player_id"] == "8482109" and row["review_status"] == "POTENTIAL_NAME_ALIAS_OR_ID_CONFLICT"
        )
        self.assertEqual(alias["official_names"], "A. Lafrenière")
        skater_events = rows("sog_event_reconciliation.csv")
        for game_id in ("2020020266", "2020020613"):
            self.assertTrue(any(row["game_id"] == game_id and row["player_id"] == "8482109" for row in skater_events))

    def test_repeated_build_produces_identical_output_hashes(self) -> None:
        expected = self.summary["derived_output_sha256"]
        rebuilt = builder.build_outputs()
        actual = {name: hashlib.sha256(body).hexdigest() for name, body in rebuilt.items() if name != "research_label_summary.json"}
        self.assertEqual(actual, expected)
        second = builder.build_outputs()
        self.assertEqual(rebuilt, second)

    def test_changed_evidence_or_derived_output_fails_visibly(self) -> None:
        pins = json.loads((ARTIFACT_DIR / builder.PIN_FILE).read_text())
        relative = next(name for name in pins["external_evidence"] if name.startswith("play-by-play/"))
        with tempfile.TemporaryDirectory() as temp_name:
            temp_root = Path(temp_name)
            for name in pins["external_evidence"]:
                destination = temp_root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = builder.DEFAULT_EVIDENCE_ROOT / name
                if name == relative:
                    destination.write_bytes(source.read_bytes() + b"tamper")
                else:
                    destination.symlink_to(source)
            with self.assertRaisesRegex(ValueError, "SOURCE_HASH_MISMATCH"):
                builder.verify_source_pins(ARTIFACT_DIR, temp_root)

        manifest = builder.manifest_by_game(ARTIFACT_DIR / "manifest.jsonl")
        non_issue_game = next(gid for gid in manifest if str(gid) not in {row["game_id"] for row in self.issues})
        with tempfile.TemporaryDirectory() as temp_name:
            temp_root = Path(temp_name)
            (temp_root / "raw").mkdir()
            source = builder.DEFAULT_BACKFILL_ROOT / "raw" / f"{non_issue_game}.json.gz"
            (temp_root / "raw" / source.name).write_bytes(source.read_bytes() + b"tamper")
            with self.assertRaisesRegex(ValueError, "SOURCE_HASH_MISMATCH"):
                builder.verify_original_game(str(non_issue_game), manifest, temp_root)

        with tempfile.TemporaryDirectory() as temp_name:
            output_dir = Path(temp_name)
            (output_dir / "one.csv").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "DERIVED_OUTPUT_HASH_MISMATCH"):
                builder.verify_outputs({"one.csv": b"expected"}, output_dir)


if __name__ == "__main__":
    unittest.main(verbosity=2)
