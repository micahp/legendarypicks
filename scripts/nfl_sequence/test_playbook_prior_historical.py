"""Consumer checks for the historical 2022-2024 playbook artifacts (research only; no SLC default changes).

The build directory is pinned by the SHA-256 of its SHA256SUMS.txt. The loader must read that build, be deterministic,
and read only the season before each cutoff. Its labelled-family totals must equal an independent recount from that
season's observation stream. No 2026 file is opened.
"""
import hashlib
import json
import os
import unittest

import playbook_prior as pp

BUILD_DIR = os.environ.get("HISTORICAL_PLAYBOOK_DIR", "/root/gridiron-playbook-builds/historical-2022-2024-v2")
PINNED_SUMS_SHA256 = "99513e2feab7ba8dd66573f8a0d4c07c37424eba574f689c4954a70b44ea52d5"
V1_BUILD_DIR = "/root/gridiron-playbook-builds/historical-2022-2024"
V1_PINNED_SUMS_SHA256 = "0ade84bc70f0984c088a67eb128fc487a1cccb1d473e5e5fa36099649d5ee5bc"
CUTOFFS = (2023, 2024, 2025)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def table_digest(table):
    return hashlib.sha256(repr(sorted(table.items(), key=lambda kv: repr(kv[0]))).encode()).hexdigest()


def recount(season):
    """Labelled counts by family, with the same rule as playbook_prior.rows_of, from the observation stream."""
    counts = {"C": 0, "D": 0, "E": 0}
    with open(os.path.join(BUILD_DIR, f"observations-{season}.jsonl"), encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if record["team_side"] != "offense":
                continue
            a = record["play"]["attributes"]
            if not (a.get("down") and a.get("ydstogo") and a.get("yardline_100")):
                continue
            if a.get("play_type") == "pass":
                if a.get("pass_length") in ("short", "deep"):
                    counts["D"] += 1
                if a.get("pass_location") in ("left", "middle", "right"):
                    counts["E"] += 1
            elif a.get("play_type") == "run" and a.get("run_gap") in ("guard", "tackle", "end"):
                counts["C"] += 1
    return counts


@unittest.skipUnless(os.path.isdir(BUILD_DIR), f"historical playbook build not found: {BUILD_DIR}")
class HistoricalPlaybookPrior(unittest.TestCase):
    def test_build_is_the_pinned_manifest(self):
        self.assertEqual(sha256(os.path.join(BUILD_DIR, "SHA256SUMS.txt")), PINNED_SUMS_SHA256)

    def test_original_v1_build_manifest_is_unchanged(self):
        path = os.path.join(V1_BUILD_DIR, "SHA256SUMS.txt")
        if not os.path.isfile(path):
            self.skipTest(f"original build not found: {path}")
        self.assertEqual(sha256(path), V1_PINNED_SUMS_SHA256)

    def test_loader_is_deterministic_and_season_correct(self):
        for cutoff in CUTOFFS:
            first = pp.load(cutoff, playbook_dir=BUILD_DIR)
            second = pp.load(cutoff, playbook_dir=BUILD_DIR)
            self.assertEqual(table_digest(first), table_digest(second), cutoff)
            self.assertEqual(first["prior_season"], cutoff - 1)

    def test_labelled_family_totals_match_an_independent_recount(self):
        for cutoff in CUTOFFS:
            table = pp.load(cutoff, playbook_dir=BUILD_DIR)
            expected = recount(cutoff - 1)
            for family, total in expected.items():
                got = sum(sum(counter.values()) for counter in table["league"][family].values())
                self.assertEqual(got, total, (cutoff, family))

    def test_supported_families_have_cells_and_unlabelled_families_stay_empty(self):
        table = pp.load(2024, playbook_dir=BUILD_DIR)
        for family in ("C", "D", "E"):
            self.assertGreater(len(table["league"][family]), 0, family)
            self.assertGreater(len(table["team"][family]), 0, family)
        for family in ("A", "B", "F", "G", "H", "I", "J", "K", "L", "M", "N"):
            self.assertEqual(len(table["league"][family]), 0, family)


if __name__ == "__main__":
    unittest.main()
