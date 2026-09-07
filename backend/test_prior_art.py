#!/usr/bin/env python3
"""prior_art.py must find the things that were actually re-derived.

Each test below is a duplication that really happened on 2026-09-06. If the tool cannot
surface the prior work for a query someone would plausibly type, it does not close the trap.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import prior_art


def _paths(terms):
    return [path for _, _, path, _, _ in prior_art.search(terms, limit=60)]


class ItFindsWhatWasReDerived(unittest.TestCase):
    def test_the_generic_merge_that_got_rebuilt(self):
        """player_merge.py was written as a worse copy of this."""
        self.assertIn("backend/spine_merge.py", _paths(["generic repair"]))

    def test_the_id_drift_measurement_that_got_re_measured(self):
        """The drift, the id and the two players were recorded on 2026-08-17."""
        self.assertIn("backend/promote_player_positions.py", _paths(["same integer"]))

    def test_a_docstring_beats_a_context_summary(self):
        """Docstrings lead because that is where measurements actually live; grepping docs/
        alone is what missed the drift measurement."""
        hits = prior_art.search(["same integer"], limit=20)
        self.assertEqual(hits[0][1], "docstring")


class ItIsHonestAboutFindingNothing(unittest.TestCase):
    def test_no_prior_art_returns_nothing_rather_than_a_weak_match(self):
        self.assertEqual(_paths(["zzzzz-not-a-real-term-anywhere"]), [])

    def test_all_terms_must_appear_on_the_same_line(self):
        """Otherwise every query matches half the repo and the tool stops being read."""
        self.assertEqual(_paths(["spine_merge", "zzzzz-not-a-real-term"]), [])


class ItSearchesTheRightPlaces(unittest.TestCase):
    def test_it_reads_agents_md(self):
        self.assertIn("AGENTS.md", _paths(["prior_art.py"]))

    def test_it_reads_context_summaries(self):
        self.assertTrue(any(p.startswith("docs/CONTEXT-") for p in _paths(["spine_merge"])))

    def test_it_skips_vendored_trees(self):
        for path in _paths(["def "]):
            self.assertNotIn("node_modules", path)
            self.assertNotIn("/venv/", path)
