#!/usr/bin/env python3
"""Network-free regression tests for Breaking Point normalization."""

import unittest
from unittest import mock

import breakingpoint_client


class EmbeddedTeamFallbackTests(unittest.TestCase):
    def test_match_embedded_ewc_teams_fill_incomplete_global_dictionary(self):
        payload = {
            "teams": {},
            "events": {211: "Esports World Cup 2026"},
            "matches": [{
                "id": 356982,
                "status": "complete",
                "datetime": "2026-08-08T21:00:00+00:00",
                "team_1_id": 99,
                "team_2_id": 712,
                "team_1_score": 0,
                "team_2_score": 4,
                "event_id": 211,
                "round": {"name": "Quarterfinals"},
                "team1": {"id": 99, "name": "FaZe Esports"},
                "team2": {"id": 712, "name": "OpTic Gaming"},
            }],
        }
        with mock.patch.object(breakingpoint_client, "_fetch_all", return_value=payload):
            rows = breakingpoint_client.get_cod_matches("2026-08-08")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["home"]["name"], "FaZe Esports")
        self.assertEqual(rows[0]["away"]["name"], "OpTic Gaming")
        self.assertEqual(rows[0]["home"]["score"], 0)
        self.assertEqual(rows[0]["away"]["score"], 4)
        self.assertNotIn("TBD", (rows[0]["home"]["name"], rows[0]["away"]["name"]))


if __name__ == "__main__":
    unittest.main()
