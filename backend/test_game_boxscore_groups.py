"""The football box score names each player group from ESPN's `name` field (2026-11-21).

ESPN names NFL groups in `name` (passing, interceptions, kickReturns, ...); only MLB uses `type`. Reading `type` alone
sent every NFL group unnamed, and the page guessed from columns: interceptions (INT, YDS, TD) became Passing, and
kicking, punting and both return groups were merged under one heading.
"""
import os
import sys
import unittest
from importlib import import_module
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

game_detail = import_module("routers.games.game_detail")


def _group(name, labels, athletes, key="name"):
    return {key: name, "labels": labels,
            "athletes": [{"athlete": {"displayName": n, "position": {"abbreviation": "X"}}, "stats": s} for n, s in athletes]}


SUMMARY = {
    "header": {"competitions": [{"status": {"type": {"state": "post", "completed": True}}}]},
    "boxscore": {
        "teams": [{"team": {"displayName": "Indianapolis Colts", "abbreviation": "IND"}, "statistics": []}],
        "players": [{"team": {"abbreviation": "IND"}, "statistics": [
            _group("passing", ["C/ATT", "YDS"], [("Daniel Jones", ["12/27", "144"])]),
            _group("interceptions", ["INT", "YDS", "TD"], [("A.J. Haulcy", ["1", "2", "0"])]),
            _group("kickReturns", ["NO", "YDS"], [("Anthony Gould", ["2", "48"])]),
            _group("puntReturns", ["NO", "YDS"], [("Deion Burks", ["1", "0"])]),
            _group("batting", ["AB"], [("Someone", ["4"])], key="type"),
        ]}],
    },
}


class FootballGroupNames(unittest.TestCase):
    def test_each_group_carries_espns_name(self):
        with patch.object(game_detail, "_summary_not_started", return_value=False), \
                patch.object(game_detail.espn, "summary", return_value=SUMMARY):
            payload = game_detail.get_game_boxscore("nfl", "401873066")
        self.assertEqual([g["group"] for g in payload["players"]],
                         ["Passing", "Interceptions", "Kick Returns", "Punt Returns", "Batting"])
        self.assertEqual(payload["players"][1]["rows"][0]["name"], "A.J. Haulcy")


if __name__ == "__main__":
    unittest.main()
