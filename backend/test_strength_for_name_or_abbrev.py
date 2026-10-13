#!/usr/bin/env python3
"""`_strength_for` resolves a context team key that is sometimes an abbreviation
and sometimes a full display name against `team_strength_map`, which is always
abbrev-keyed.

Reported by Micah 2026-08-30 on MLB 401816747: `context.home_team` /
`away_team` held full names ("Washington Nationals") because that game's
context came from the scoreboard snapshot's team-NAME fallback rather than the
ESPN abbrev fallback. `game_detail.py` looked those names up directly in
`team_strength_map(lg)` (abbrev-keyed) and always missed, so the GameInfo
"Season Records" card rendered its heading over an empty grid for every league
whose context takes this path -- confirmed on MLB and NFL, both real data
sitting unused in `team_strength_map`.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_IMPORT_DB = tempfile.NamedTemporaryFile(prefix="strength-", suffix=".db", delete=False)
_IMPORT_DB.close()
os.environ["LP_DB_PATH"] = _IMPORT_DB.name

import _core  # noqa: E402

_ROWS = {
    "WSH": {"abbrev": "WSH", "name": "Washington Nationals", "wins": 65, "losses": 74},
    "MIA": {"abbrev": "MIA", "name": "Miami Marlins", "wins": 69, "losses": 68},
}


class StrengthResolvesByAbbrevOrName(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(_core.espn, "team_strength_map", return_value=_ROWS)
        patch.start()
        self.addCleanup(patch.stop)

    def test_resolves_by_abbrev(self):
        self.assertEqual(_core._strength_for("mlb", "WSH")["name"], "Washington Nationals")

    def test_resolves_by_full_display_name(self):
        """This is the case that silently missed: context held the full name."""
        row = _core._strength_for("mlb", "Washington Nationals")
        self.assertIsNotNone(row)
        self.assertEqual(row["abbrev"], "WSH")

    def test_unknown_team_returns_none(self):
        self.assertIsNone(_core._strength_for("mlb", "Nonexistent Team"))


if __name__ == "__main__":
    unittest.main()
