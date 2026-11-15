"""Regression tests for the family grader's home-win Brier.

The bug these lock down: the grader scored every game as if the home team had
won, so an away victory was scored (p_home - 1)^2 instead of p_home^2. On
BUF-NYJ (home = NYJ, final 12-31) that turned v2's 0.147 into 0.379.
"""
import importlib.util, json, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
GRADER = HERE / "grade_ne_det.py"


def load_grader():
    spec = importlib.util.spec_from_file_location("grade_ne_det", GRADER)
    assert spec is not None and spec.loader is not None, "cannot load the grader module"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HomeWinOutcomeTest(unittest.TestCase):
    def setUp(self):
        self.g = load_grader()

    def test_away_win_scores_against_the_home_probability(self):
        self.assertEqual(self.g.home_win_outcome(12, 31), 0)
        self.assertAlmostEqual(self.g.home_win_brier(0.384, 12, 31), 0.384 ** 2)

    def test_home_win_scores_against_one_minus_the_home_probability(self):
        self.assertEqual(self.g.home_win_outcome(35, 10), 1)
        self.assertAlmostEqual(self.g.home_win_brier(0.654, 35, 10), (0.654 - 1) ** 2)

    def test_tie_counts_as_not_a_home_win(self):
        self.assertEqual(self.g.home_win_outcome(20, 20), 0)
        self.assertAlmostEqual(self.g.home_win_brier(0.30, 20, 20), 0.09)

    def test_away_win_brier_is_not_the_complement(self):
        away = self.g.home_win_brier(0.384, 12, 31)
        wrong = (0.384 - 1) ** 2
        self.assertNotAlmostEqual(away, wrong, places=6)


class EndToEndTest(unittest.TestCase):
    """Runs the real grader over a synthetic away-win game."""

    GAME = "2026_10_TST_AWAY"

    def build_fixture(self, root):
        runs = root / "runs"
        for arm in ("v1", "v1.5", "v1.6", "v1.7", "v1.7-pr43", "v2"):
            (runs / arm).mkdir(parents=True)
            rows = []
            for seed in (1, 2):
                rows.append(json.dumps({"seed": seed, "status": "valid_complete", "players": [],
                                        "teams": [{"team": "HOM", "stats": {"points": 12}},
                                                  {"team": "AWY", "stats": {"points": 31}}]}))
            (runs / arm / ("%s-seed-1-2.boxscores.jsonl" % self.GAME)).write_text("\n".join(rows) + "\n")
        espn = {"header": {"competitions": [{"competitors": [
                    {"team": {"abbreviation": "HOM"}, "score": "12"},
                    {"team": {"abbreviation": "AWY"}, "score": "31"}]}]},
                "boxscore": {"players": [{"team": {"abbreviation": "HOM"}, "statistics": []},
                                         {"team": {"abbreviation": "AWY"}, "statistics": []}]}}
        path = root / "espn.json"
        path.write_text(json.dumps(espn))
        return runs, path

    def test_away_win_produces_p_home_squared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs, espn = self.build_fixture(root)
            out = root / "out"
            proc = subprocess.run([sys.executable, str(GRADER), "--runs", str(runs), "--espn", str(espn),
                                   "--game", self.GAME, "--home-away", "HOM,AWY",
                                   "--out-dir", str(out)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads((out / ("%s-family-grading.json" % self.GAME)).read_text())
            self.assertEqual(report["actual_home_win"], 0)
            for arm, block in report["game_level"].items():
                self.assertEqual(block["actual_home_win"], 0)
                self.assertAlmostEqual(block["home_win_brier"], block["p_home_win"] ** 2)
            markdown = (out / "TST-AWAY-FAMILY-GRADING.md").read_text()
            self.assertIn("home win = 0", markdown)
            self.assertIn("Final:** HOM 12, AWY 31", markdown)


if __name__ == "__main__":
    unittest.main(verbosity=2)
