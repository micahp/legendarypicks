"""Consumer check for the compact historical C/D/E prior (research only; no SLC default changes).

The compact artifact holds counts per team-season, cell, family and label, with no play IDs or source IDs. Rebuilding the
decision layer's table from those counts must give the same canonical digest as the full loader reading the team
profiles, for each cutoff. The artifact is pinned by SHA-256. No 2026 file is opened.
"""
import hashlib
import json
import os
import unittest

import decision_layer as dl
import nfl_team_codes
import playbook_prior as pp

BUILD_DIR = os.environ.get("HISTORICAL_PLAYBOOK_DIR", "/root/gridiron-playbook-builds/historical-2022-2024-v2")
COMPACT = os.environ.get("HISTORICAL_CDE_PRIOR", os.path.join(BUILD_DIR, "cde-prior-2022-2024-v2.json"))
PINNED_COMPACT_SHA256 = "00e3c8b22db60233db7447517409d461ea579ce13d80f3aaca2ab55243852a27"
CUTOFFS = (2023, 2024, 2025)


def sha256(path):
    with open(path, "rb") as stream:
        return hashlib.sha256(stream.read()).hexdigest()


def canonical(obj):
    if isinstance(obj, dict):
        return sorted((repr(k), canonical(v)) for k, v in obj.items())
    return obj


def table_digest(table):
    return hashlib.sha256(repr(canonical(table)).encode()).hexdigest()


def rows_from_compact(artifact, season):
    rows = []
    for team_id, cells in artifact["counts"][str(season)].items():
        team = nfl_team_codes.to_pbp_team_code(team_id)
        for cell, families in cells.items():
            for family, labels in families.items():
                for label, n in labels.items():
                    rows.extend({"season": season, "team": team, "cell": cell, "labels": {family: label}}
                                for _ in range(n))
    return rows


@unittest.skipUnless(os.path.isfile(COMPACT), f"compact historical prior not found: {COMPACT}")
class CompactHistoricalPrior(unittest.TestCase):
    def setUp(self):
        with open(COMPACT, encoding="utf-8") as stream:
            self.artifact = json.load(stream)

    def test_artifact_is_the_pinned_file(self):
        self.assertEqual(sha256(COMPACT), PINNED_COMPACT_SHA256)

    def test_artifact_holds_counts_only(self):
        with open(COMPACT, encoding="utf-8") as stream:
            text = stream.read()
        for key in ("play_id", "source_ids", "old_game_id", "game_id"):
            self.assertNotIn(f'"{key}"', text, key)
        self.assertEqual(self.artifact["seasons"], [2022, 2023, 2024])

    def test_compact_table_matches_the_full_loader_for_each_cutoff(self):
        for cutoff in CUTOFFS:
            season = cutoff - 1
            full = pp.load(cutoff, playbook_dir=BUILD_DIR)
            compact = dl.fit(rows_from_compact(self.artifact, season), prior_season=season)
            self.assertEqual(table_digest(compact), table_digest(full), cutoff)
            self.assertEqual(compact["prior_season"], season)


if __name__ == "__main__":
    unittest.main()
