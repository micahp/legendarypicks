import unittest

from slc_model_registry import MODELS, get_model


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


if __name__ == "__main__":
    unittest.main()
