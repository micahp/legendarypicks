#!/usr/bin/env python3
"""Regression coverage for team SOG validation including goalie PBP shots."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import unittest
from collections import defaultdict
from pathlib import Path


ARTIFACT_DIR = Path(__file__).resolve().parent
EVIDENCE_ROOT = Path("/root/lp-data/nhl-official-outcome-quality-adjudication-2026-10-20")
if str(ARTIFACT_DIR) not in sys.path:
    sys.path.insert(0, str(ARTIFACT_DIR))

from nhl_sog_validation import parse_pbp_sog_events, validate_team_sog


def read_rows(name: str) -> list[dict[str, str]]:
    with (ARTIFACT_DIR / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class NHLSogValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.issues = [
            row for row in read_rows("official_quality_issues.csv")
            if row["issue_type"] == "PLAYER_SOG_SUM_VS_TEAM_TOTAL"
        ]
        cls.team_validation = {
            (row["game_id"], row["team"]): row for row in read_rows("official_team_sog_validation.csv")
        }
        cls.skaters: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
        for row in read_rows("official_skater_outcomes.csv"):
            cls.skaters[(row["game_id"], row["team"])][row["player_id"]] = int(row["sog"])
        cls.pbp_manifest = {row["game_id"]: row for row in read_rows("play_by_play_evidence_manifest.csv")}
        cls.parsed = {}
        for game_id in sorted({row["game_id"] for row in cls.issues}, key=int):
            entry = cls.pbp_manifest[game_id]
            path = EVIDENCE_ROOT / "play-by-play" / entry["cache_file"]
            body = path.read_bytes()
            if hashlib.sha256(body).hexdigest() != entry["sha256"]:
                raise AssertionError(f"PINNED_PBP_HASH_MISMATCH {game_id}")
            cls.parsed[game_id] = parse_pbp_sog_events(game_id, json.loads(body), {"PHX": "ARI"})

    def test_all_20_original_skater_only_discrepancies_pass_with_goalie_sog(self) -> None:
        self.assertEqual(len(self.issues), 20)
        results = []
        for issue in self.issues:
            game_id, team, side = issue["game_id"], issue["team"], issue["side"]
            old = self.team_validation[(game_id, team)]
            self.assertEqual(old["validation"], "MISMATCH")
            result = validate_team_sog(
                game_id=game_id,
                team=team,
                side=side,
                official_team_sog=int(old["official_team_sog"]),
                official_skater_sog_by_player=self.skaters[(game_id, team)],
                pbp_sog=self.parsed[game_id],
            )
            results.append(result)
            self.assertEqual(result.status, "PASS", (game_id, team, result))
            self.assertEqual(result.official_skater_sog, int(old["sum_player_sog"]))
            self.assertEqual(result.difference, 0)
            self.assertEqual(result.goalie_pbp_sog, int(old["official_team_sog"]) - int(old["sum_player_sog"]))
        self.assertEqual(len(results), 20)
        self.assertEqual({result.goalie_pbp_sog for result in results}, {1})

    def test_goal_by_goalie_counts_as_sog_when_pbp_has_shot_type(self) -> None:
        game_id = "2019020684"
        goalie_id = "8471469"  # Pekka Rinne
        parsed = self.parsed[game_id]
        events = [
            event for event in parsed.events_by_team_side[("NSH", "away")]
            if event["player_id"] == goalie_id
        ]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "goal")
        self.assertTrue(events[0]["details"].get("shotType"))
        self.assertEqual(parsed.position_by_player("NSH", "away")[goalie_id], "G")

    def test_missing_pbp_evidence_cannot_be_silently_treated_as_zero_goalie_sog(self) -> None:
        issue = self.issues[0]
        old = self.team_validation[(issue["game_id"], issue["team"])]
        with self.assertRaisesRegex(ValueError, "PBP_SOG_EVIDENCE_REQUIRED"):
            validate_team_sog(
                game_id=issue["game_id"],
                team=issue["team"],
                side=issue["side"],
                official_team_sog=int(old["official_team_sog"]),
                official_skater_sog_by_player=self.skaters[(issue["game_id"], issue["team"])],
                pbp_sog=None,  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
