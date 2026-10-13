#!/usr/bin/env python3
"""A superseded script must refuse, and the registry must stay true.

The trap this guards: on 2026-08-24 spine_merge.py replaced five per-league dedupers and it
was all written down. Three weeks later the old scripts were still runnable, AGENTS.md still
named two of them, and on 2026-09-06 a session wrote a worse copy of spine_merge because it
never found the original. A record is not a guardrail.
"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import superseded


class EverySupersededScriptRefuses(unittest.TestCase):
    def test_the_registry_is_not_empty(self):
        """An empty registry would make every test below vacuously pass."""
        self.assertTrue(superseded.REGISTRY)

    def test_each_named_script_exists_and_exits_non_zero(self):
        for name in superseded.REGISTRY:
            path = os.path.join(HERE, name + ".py")
            with self.subTest(script=name):
                self.assertTrue(os.path.isfile(path), "{} is registered but missing".format(name))
                result = subprocess.run(
                    [sys.executable, path], cwd=HERE,
                    capture_output=True, text=True, timeout=120)
                self.assertNotEqual(result.returncode, 0,
                                    "{} ran instead of refusing".format(name))
                self.assertIn("REFUSED", result.stderr)

    def test_the_refusal_names_the_replacement(self):
        """A refusal that does not say what to use instead just moves the confusion."""
        for name, entry in superseded.REGISTRY.items():
            path = os.path.join(HERE, name + ".py")
            with self.subTest(script=name):
                result = subprocess.run(
                    [sys.executable, path], cwd=HERE,
                    capture_output=True, text=True, timeout=120)
                self.assertIn(entry.replacement, result.stderr)
                self.assertIn(entry.why.split(";")[0][:40], result.stderr)

    def test_every_replacement_actually_exists(self):
        """Pointing at a tool that is not there is worse than pointing at nothing."""
        for name, entry in superseded.REGISTRY.items():
            with self.subTest(script=name):
                self.assertTrue(
                    os.path.isfile(os.path.join(HERE, entry.replacement)),
                    "{} points at {}, which does not exist".format(name, entry.replacement))

    def test_a_script_that_is_not_registered_is_untouched(self):
        superseded.refuse("spine_merge")  # returns rather than raising

    def test_no_script_is_registered_as_superseding_itself(self):
        for name, entry in superseded.REGISTRY.items():
            self.assertNotEqual(entry.replacement, name + ".py")


if __name__ == "__main__":
    unittest.main()
