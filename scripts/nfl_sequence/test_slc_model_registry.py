import unittest
import tempfile
from unittest.mock import patch
from pathlib import Path

from slc_model_registry import MODELS, get_model
import slc_cli


class Registry(unittest.TestCase):
    def test_registry_pins_overtime_required_family_releases(self):
        expected = {
            "v1": "58ef3861e5f3cc4006ab627102e55bd432ab399d",
            "v1.5": "2eab8a89efffad23c00a1d451ac80e856579ac5a",
            "v1.6": "1bb3bd50c4df5896e4d693245e48329c20c63254",
            "v1.7": "1ca59e0d038b594b87c0dd5b4c78b0711b022043",
            "v2": "8a1d984229cdc20f5ad076ebd81edc7f1be90c75",
            "pbv1": "8a1d984229cdc20f5ad076ebd81edc7f1be90c75",
            "pbv1-off": "8a1d984229cdc20f5ad076ebd81edc7f1be90c75",
        }
        self.assertEqual({model_id: entry["code_commit"]
                          for model_id, entry in MODELS.items()}, expected)

    def test_model_variants_have_pinned_source_and_policy(self):
        self.assertEqual(set(MODELS), {"v1", "v1.5", "v1.6", "v1.7", "v2", "pbv1", "pbv1-off"})
        for model_id, entry in MODELS.items():
            with self.subTest(model=model_id):
                self.assertRegex(entry["code_commit"], r"^[0-9a-f]{40}$")
                self.assertTrue(entry["rules_policy"])
                self.assertTrue(entry["enabled_layers"])
                self.assertIn("training_cutoff", entry)
                self.assertIn("experimental_flags", entry)
                self.assertTrue(entry["runtime_supported"])

    def test_v15_and_v16_use_registered_batch_loader_inputs(self):
        for model_id in ("v1.5", "v1.6"):
            spec = get_model(model_id)
            self.assertTrue(spec["build_supported"])
            self.assertEqual(spec["profile_model_id"],
                             "SLC_v1_full_stack" if model_id == "v1.5" else "SLC_v1_6_candidate")
            self.assertEqual([item["flag"] for item in spec["build_inputs"]],
                             ["--playcall-artifact", "--playcall-streak-file"]
                             + (["--slc-materialized-history"] if model_id == "v1.6" else []))
        self.assertEqual(get_model("v1.6")["build_args"],
                         ["--playcall-pass-label-mode", "conditional"])

    def test_v17_uses_pinned_materialization_and_penalty_inputs(self):
        spec = get_model("v1.7")
        self.assertTrue(spec["build_supported"])
        self.assertEqual([item["flag"] for item in spec["build_inputs"]], [
            "--playcall-artifact", "--playcall-streak-file", "--slc-materialized-history",
            "--slc-penalty-model", "--slc-penalty-manifest", "--slc-penalty-source-manifest",
        ])
        self.assertTrue(all(MODELS[model]["build_supported"]
                            for model in ("v2", "pbv1", "pbv1-off")))
        with self.assertRaisesRegex(RuntimeError, "MODEL_PYTHON_VERSION_UNSUPPORTED.*requires Python 3.10+"):
            slc_cli._check_python("v1.7", MODELS["v1.7"], (3, 8))
        slc_cli._check_python("v1.7", MODELS["v1.7"], (3, 10))

    def test_v2_and_pbv1_keep_distinct_week10_configurations(self):
        self.assertIn("--slc-v2", MODELS["v2"]["build_args"])
        self.assertIn("--rng-protocol", MODELS["v2"]["build_args"])
        self.assertIn("--slc-blocker-fix", MODELS["v2"]["build_args"])
        self.assertIn("--playcall-pbv1-package", [item["flag"] for item in MODELS["pbv1"]["build_inputs"]])
        self.assertNotIn("--slc-v2", MODELS["pbv1"]["build_args"])
        self.assertNotIn("--playcall-pbv1-package", [item["flag"] for item in MODELS["pbv1-off"]["build_inputs"]])
        self.assertEqual(MODELS["pbv1"]["experimental_flags"]["pbv1_integration"], "label_only")

    def test_build_all_reaches_data_host_preflight_when_all_models_are_enabled(self):
        with tempfile.TemporaryDirectory() as temp:
            out_dir = Path(temp)
            with patch.dict("os.environ", {}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "BUILD_CONFIGURATION_MISSING.*SLC_GAME_SNAPSHOT"):
                    slc_cli.main(["pack", "build", "--all", "--out-dir", str(out_dir)])
            self.assertEqual(list(out_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
