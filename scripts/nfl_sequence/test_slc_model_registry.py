import unittest
import tempfile
from pathlib import Path

from slc_model_registry import MODELS, get_model
import slc_cli


class Registry(unittest.TestCase):
    def test_all_six_model_families_have_pinned_source_and_policy(self):
        self.assertEqual(set(MODELS), {"v1", "v1.5", "v1.6", "v1.7", "v2", "pbv1"})
        for model_id, entry in MODELS.items():
            with self.subTest(model=model_id):
                self.assertRegex(entry["code_commit"], r"^[0-9a-f]{40}$")
                self.assertTrue(entry["rules_policy"])
                self.assertTrue(entry["enabled_layers"])
                self.assertIn("training_cutoff", entry)
                self.assertIn("experimental_flags", entry)

    def test_only_implemented_loader_can_build(self):
        self.assertTrue(get_model("v1")["build_supported"])
        self.assertFalse(any(MODELS[model]["build_supported"]
                             for model in ("v1.5", "v1.6", "v1.7", "v2", "pbv1")))

    def test_build_all_fails_before_creating_any_package_while_models_are_gated(self):
        with tempfile.TemporaryDirectory() as temp:
            out_dir = Path(temp)
            with self.assertRaisesRegex(RuntimeError, "BUILD_ALL_INCOMPLETE.*v1.5.*pbv1"):
                slc_cli.main(["pack", "build", "--all", "--out-dir", str(out_dir)])
            self.assertEqual(list(out_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
