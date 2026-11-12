"""Offline V1.7 penalty trainer must consume the verified JSONL contract safely."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from penalty_train import train, opportunities_jsonl, adapt_historical_jsonl
from penalty_fit import Context, PenaltyModel

CUTOFF = "2025-01-01T00:00:00+00:00"


def row(i, *, year=2024, foul=False):
    return {
        "context": {
            "phase": "pre_snap", "rule_era": year, "offense_team": "ARI",
            "defense_team": "DAL", "down": 1, "to_go": 10,
            "yardline_100": 65, "play_class": "pre_snap",
        },
        "opportunity_id": f"{year}-test-{i}",
        "game_kickoff_utc": f"{year}-10-12T17:00:00+00:00",
        "source_published_utc": f"{year}-10-13T17:00:00+00:00",
        "outcome": "offense:false_start" if foul else "none",
        "label_verified": True,
        "foul_count": int(foul),
        "disposition": "accepted" if foul else "none",
    }


class PenaltyTrainingTests(unittest.TestCase):
    def test_fit_writes_versioned_immutable_model_and_out_of_sample_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            train_path = Path(tmp) / "train.jsonl"
            holdout_path = Path(tmp) / "holdout.jsonl"
            target = Path(tmp) / "penalty-model.json"
            train_path.write_text("".join(json.dumps(row(i, foul=i % 7 == 0)) + "\n"
                                          for i in range(100)))
            holdout_path.write_text("".join(
                json.dumps(row(i, year=2025, foul=i % 9 == 0)) + "\n"
                for i in range(20)))
            result = train(train_jsonl=train_path, holdout_jsonl=holdout_path,
                           model_out=target, as_of_utc=CUTOFF,
                           source_sha256="f" * 64)
            self.assertEqual(result["observed_opportunities"], 100)
            self.assertEqual(result["validation"]["team_adjusted"]["n"], 20)
            self.assertEqual(result["validation"]["context_only_control"]["n"], 20)
            self.assertEqual(PenaltyModel.from_json(target.read_text()).sha256(),
                             result["model_sha256"])
            self.assertTrue(target.with_name(target.name + ".manifest.json").exists())
            with self.assertRaises(FileExistsError):
                train(train_jsonl=train_path, model_out=target,
                      as_of_utc=CUTOFF, source_sha256="f" * 64)

    def test_malformed_row_has_line_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.jsonl"
            path.write_text(json.dumps(row(1)) + "\n{}\n")
            iterator = opportunities_jsonl(path)
            next(iterator)
            with self.assertRaisesRegex(ValueError, "bad.jsonl:2"):
                next(iterator)

    def test_historical_adapter_requires_independent_verification_and_keeps_audit_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "audited.jsonl"
            output = Path(tmp) / "adapted.jsonl"
            doc = row(1, foul=True)
            doc["audit_evidence"] = {
                "official_record_verified": True,
                "opportunity_denominator_verified": True,
                "official_record_url": "https://official.example/gamebook.pdf#page=3",
                "source_row_id": "2024_01_ARI_DAL:1",
            }
            source.write_text(json.dumps(doc) + "\n")
            result = adapt_historical_jsonl(source, output)
            adapted = list(opportunities_jsonl(output))
            self.assertEqual(len(adapted), 1)
            self.assertEqual(result["rows"], 1)
            audit = json.loads(Path(result["audit_manifest"]).read_text())
            self.assertEqual(audit["evidence"][0]["source_row_id"],
                             "2024_01_ARI_DAL:1")

    def test_text_only_clause_candidate_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "text-only.jsonl"
            output = Path(tmp) / "adapted.jsonl"
            doc = row(1, foul=True)
            doc["audit_evidence"] = {
                "official_record_verified": False,
                "opportunity_denominator_verified": False,
                "official_record_url": "",
                "source_row_id": "2024_01_ARI_DAL:1",
                "source_text_disposition_only": True,
            }
            source.write_text(json.dumps(doc) + "\n")
            with self.assertRaisesRegex(ValueError, "official_record_verified"):
                adapt_historical_jsonl(source, output)


if __name__ == "__main__":
    unittest.main()
