"""Official inactive parsing and strict identity/provenance regression tests."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import recover_official_nfl_inactives as m


HTML = """<html><body>
<main><p>Published: Oct 25, 2026 at 08:11 AM Updated: Oct 25, 2026 at 07:02 PM</p>
<div class="nfl-c-article__container">
<div class="nfl-c-body-part nfl-c-body-part--text"><h3>STEELERS</h3></div>
<div class="nfl-c-body-part nfl-c-body-part--text"><ul>
<li>WR Ben Skowronek</li>
<li>QB Will Howard (emergency third QB)</li></ul></div>
<div class="nfl-c-article__adv">advertising</div>
<div class="nfl-c-body-part nfl-c-body-part--text"><h3>SAINTS</h3></div>
<div class="nfl-c-body-part nfl-c-body-part--text"><ul>
<li>TE Treyton Welch</li></ul></div></div></main></body></html>"""


class OfficialInactivesTests(unittest.TestCase):
    def test_parse_real_article_dom_shape(self):
        got = m.parse_official_article(HTML)
        self.assertEqual([x["name"] for x in got["PIT"]],
                         ["Ben Skowronek", "Will Howard"])
        self.assertEqual(got["NO"][0]["name"], "Treyton Welch")

    def test_dateline_is_real_local_source_time_not_ingest_time(self):
        published, updated = m.article_updated_at(HTML)
        self.assertEqual(published.astimezone(timezone.utc).isoformat(),
                         "2026-10-25T12:11:00+00:00")
        self.assertEqual(updated.astimezone(timezone.utc).isoformat(),
                         "2026-10-25T23:02:00+00:00")

    def test_normalization_only_exact_not_fuzzy(self):
        self.assertEqual(m.normalized_name("D.J. Reed Jr."),
                         m.normalized_name("DJ Reed"))
        self.assertNotEqual(m.normalized_name("Caleb Douglas"),
                            m.normalized_name("Caleb Dougla"))

    def test_strict_gsis_identity_and_after_kickoff_page_is_retrospective(self):
        t = datetime(2026, 10, 25, 13, 30, tzinfo=timezone.utc)
        sched = {(7, "PIT"): {"game_id": "2026_07_PIT_NO", "kickoff": t},
                 (7, "NO"): {"game_id": "2026_07_PIT_NO", "kickoff": t}}
        ident = {
            (7,"PIT",m.normalized_name("Ben Skowronek")): {"gsisA"},
            (7,"PIT",m.normalized_name("Will Howard")): {"gsisB"},
            (7,"NO",m.normalized_name("Treyton Welch")): {"gsisC"},
        }
        got, index, counts = m.recover([{"week": 7, "url": "https://amp.nfl.com/news/inactives"}],
                                       sched, ident, {7: HTML}, {7: "a"*64})
        self.assertEqual(len(got), 3)
        self.assertEqual(len(index), 2)
        self.assertEqual(counts["fully_identity_resolved_team_games"], 2)
        self.assertEqual(counts["retrospective_article_team_games"], 2)
        self.assertIn("gsisA", {row["gsis_id"] for row in got})

    def test_no_false_activation_when_names_not_resolved(self):
        t = datetime(2026, 10, 25, 13, 30, tzinfo=timezone.utc)
        sched = {(7, "PIT"): {"game_id": "2026_07_PIT_NO", "kickoff": t}}
        got, index, counts = m.recover([{"week": 7, "url": "https://amp.nfl.com/news/inactives"}],
                                       sched, {}, {7: HTML}, {7: "a"*64})
        self.assertEqual(len(index), 0)
        self.assertEqual(counts["team_games_needing_identity_review"], 1)
        self.assertTrue(all(x["identity_status"] == "unresolved" for x in got))

    def test_page_updated_before_cutoff_can_be_labeled_as_such(self):
        source = HTML.replace("Oct 25, 2026 at 07:02 PM", "Oct 25, 2026 at 08:11 AM")
        t = datetime(2026, 10, 25, 13, 30, tzinfo=timezone.utc)
        sched = {(7, "NO"): {"game_id": "2026_07_PIT_NO", "kickoff": t}}
        ident = {(7,"NO",m.normalized_name("Treyton Welch")): {"gsisC"}}
        got, index, counts = m.recover([{"week": 7, "url": "https://amp.nfl.com/news/inactives"}],
                                       sched, ident, {7: source}, {7: "a"*64})
        self.assertEqual(counts["article_updated_before_cutoff_team_games"], 1)


if __name__ == "__main__":
    unittest.main()
