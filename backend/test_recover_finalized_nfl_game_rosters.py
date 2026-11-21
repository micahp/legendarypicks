"""Synthetic, offline contracts for finalized *postgame* NFL gamebook recovery."""
import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import recover_finalized_nfl_game_rosters as recovery


def book_words(emergency_three_qb=True):
    words = []
    def add(y, x, *parts):
        for i, part in enumerate(parts):
            words.append((float(y), float(x + 30 * i), part))

    add(0, 0, "Lineups")
    add(100, 0, "Substitutions")
    add(100, 500, "Substitutions")
    add(200, 0, "Did", "Not", "Play")
    add(200, 500, "Did", "Not", "Play")
    add(300, 0, "Not", "Active")
    add(300, 500, "Not", "Active")
    add(400, 0, "Field", "Goals")
    roster = {}
    for team, x, extra in (("AAA", 20, 1), ("BBB", 520, 0)):
        rows = []
        index = 0
        for role, count, start_y, delta in (
            ("START", 22, 5, 4),
            ("SUB", 26 + extra, 105, 3),
            ("INA", 6, 305, 3),
        ):
            for n in range(count):
                index += 1
                last = "Last" + chr(97 + index // 26) + chr(97 + index % 26)
                position = ("3QB" if team == "AAA" and role == "SUB"
                            and n == 26 and emergency_three_qb else "RB")
                add(start_y + delta * n, x, position, str(index), "A." + last)
                rows.append({
                    "gsis_id": team + str(index), "full_name": "Alex " + last,
                    "last_name": last, "jersey_number": index,
                    "status": "INA" if role == "INA" else "ACT",
                })
        roster[(2, team)] = rows
    return sorted(words), roster


class GamebookSections(unittest.TestCase):
    def test_accepts_both_team_columns_in_order(self):
        words, _ = book_words()
        self.assertEqual(recovery.roster_sections(words), {
            "START": (0.0, 100.0), "SUB": (100.0, 200.0),
            "DNP": (200.0, 300.0), "INA": (300.0, 400.0),
        })

    def test_missing_headings_are_refused(self):
        words, _ = book_words()
        words = [row for row in words if row[0] != 300.0]
        with self.assertRaisesRegex(ValueError, "headings missing"):
            recovery.roster_sections(words)

    def test_ordered_gamebook_yields_49_and_48_active_rosters(self):
        words, roster = book_words()
        schedule = {"away": "AAA", "home": "BBB", "week": 2, "url": "https://example.invalid/book"}
        with patch.object(recovery, "page_words", return_value=(1000.0, words)):
            rows, coverage = recovery.extract_gamebook(Path("synthetic.pdf"), "G", schedule, "a" * 64, roster)
        self.assertEqual(coverage["teams"]["AAA"]["active"], 49)
        self.assertEqual(coverage["teams"]["BBB"]["active"], 48)
        self.assertEqual(len(rows), 49 + 48 + 12)
        self.assertEqual(sum(r["actual_gameday_status"] == "INACTIVE" for r in rows), 12)
        self.assertTrue(all(r["gamebook_sha256"] == "a" * 64 for r in rows))

    def test_49_active_players_without_emergency_three_qb_are_rejected(self):
        words, roster = book_words(emergency_three_qb=False)
        schedule = {"away": "AAA", "home": "BBB", "week": 2, "url": "https://example.invalid/book"}
        with patch.object(recovery, "page_words", return_value=(1000.0, words)):
            with self.assertRaisesRegex(ValueError, "emergency 3QB"):
                recovery.extract_gamebook(Path("synthetic.pdf"), "G", schedule, "a" * 64, roster)


class IdentityAndProvenance(unittest.TestCase):
    def test_jersey_surname_match_is_deterministic_and_ambiguous_is_refused(self):
        players = [
            {"gsis_id": "A", "full_name": "Alex Smith", "last_name": "Smith", "jersey_number": 12},
            {"gsis_id": "B", "full_name": "Adam Smith", "last_name": "Smith", "jersey_number": 34},
        ]
        player, method = recovery.resolve_player(players, 34, "A.Smith")
        self.assertEqual((player["gsis_id"], method), ("B", "team_week_jersey_surname"))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            recovery.resolve_player(players, 99, "A.Smith")

    def test_checksums_refuse_altered_gamebook_before_parsing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            games = {f"G{i:03d}": {"week": 2, "away": "AAA", "home": "BBB", "gsis": "Q"}
                     for i in range(120)}
            manifest = root / "manifest.csv"
            with manifest.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=("game_id", "url", "sha256"))
                writer.writeheader()
                for key in games:
                    writer.writerow({"game_id": key, "url": "https://example.invalid/book",
                                     "sha256": "0" * 64})
            (root / "G000.pdf").write_bytes(b"changed and mismatched")
            args = SimpleNamespace(schedule_csv=root / "schedule.csv",
                                   weekly_roster=root / "source.parquet",
                                   gamebook_manifest=manifest, gamebooks_dir=root,
                                   out_dir=root / "out")
            with patch.object(recovery, "read_schedule", return_value=games):
                with patch.object(recovery, "load_weekly_identity", return_value={}):
                    with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                        recovery.build(args)


if __name__ == "__main__":
    unittest.main()
