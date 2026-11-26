"""Offline fixtures for the read-only simulated-props reporting utility."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import props_sim_comparison as psc


class PropsSimComparison(unittest.TestCase):
    def test_market_comparison_counts_seeds_and_skips_unmodelled_markets(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            db = root / "picks.db"
            con = sqlite3.connect(db)
            con.executescript("""
                CREATE TABLE players (id INTEGER PRIMARY KEY, name TEXT, team TEXT, position TEXT);
                CREATE TABLE props (game_id INTEGER, player_id INTEGER, market TEXT, line REAL, source TEXT, side TEXT);
            """)
            con.execute("INSERT INTO players VALUES (1, 'Tester', 'HOU', 'RB')")
            con.executemany("INSERT INTO props VALUES (?,?,?,?,?,?)", [
                (123, 1, 'rushing_yards', 40.5, 'book1', 'over'),
                (123, 1, 'rushing_yards', 40.5, 'book2', 'over'),
                (123, 1, 'field_goals_made', 1.5, 'book1', 'over'),
            ])
            con.commit()
            con.close()

            arm = root / "arm"
            arm.mkdir()
            with (arm / "sample.boxscores.jsonl").open("w") as out:
                for yards in (50, 30):
                    out.write(json.dumps({
                        "type": "game",
                        "players": [{"lp_player_id": 1, "rushing": {"yds": yards}}]
                    }) + "\n")

            dest = root / "out"
            self.assertEqual(
                psc.main(["--db", str(db), "--prop-game-id", "123",
                          "--arm", f"V1={arm}", "--out-dir", str(dest)]), 0)
            report = json.loads((dest / "props_sim_comparison.json").read_text())
            self.assertEqual(report["seeds_by_arm"], {"V1": 2})
            self.assertEqual(report["skipped_markets_not_simulated"], ["field_goals_made"])
            self.assertEqual(len(report["rows"]), 1)
            row = report["rows"][0]
            self.assertEqual((row["market"], row["line"], row["books"]),
                             ("rushing_yards", 40.5, 2))
            self.assertEqual((row["sim_mean"], row["sim_p_over"]), (40.0, 0.5))

    def test_empty_arm_is_refused_instead_of_reporting_zero_probability(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "no simulated game records"):
                psc.load_arm(root)


if __name__ == "__main__":
    unittest.main()
