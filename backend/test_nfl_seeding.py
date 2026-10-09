"""Tests for nfl_seeding.py with hand-worked seeds.

Eight NFC teams in four divisions. Overall records are set exactly by games against AFC teams
(XAA, XBB), and NFC-internal games only where a tiebreaker needs them. Expected seeds are worked
out on paper from the records, the division winners and the tiebreakers.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_seeding as sd  # noqa: E402
import nfl_standings as st  # noqa: E402

MAP = {"E1": ("NFC", "NFC East"), "E2": ("NFC", "NFC East"),
       "N1": ("NFC", "NFC North"), "N2": ("NFC", "NFC North"),
       "S1": ("NFC", "NFC South"), "S2": ("NFC", "NFC South"),
       "W1": ("NFC", "NFC West"), "W2": ("NFC", "NFC West"),
       "XAA": ("AFC", "AFC North"), "XBB": ("AFC", "AFC North")}


class Builder:
    def __init__(self):
        self.games = []
        self.wk = 0

    def game(self, winner, loser):
        self.wk += 1
        if self.wk % 2:
            self.games.append((self.wk, winner, loser, 24.0, 17.0))
        else:
            self.games.append((self.wk, loser, winner, 17.0, 24.0))

    def record(self, team, wins, losses):
        for _ in range(wins):
            self.game(team, "XAA")
        for _ in range(losses):
            self.game("XAA", team)

    def teams(self):
        return st.build(MAP, self.games)


def seeds(b):
    return sd.seeds_for_conference(b.teams(), "NFC")


class Seeding(unittest.TestCase):
    def base(self):
        b = Builder()
        b.record("E1", 10, 7)
        b.record("E2", 9, 8)
        b.record("N1", 11, 6)
        b.record("N2", 8, 9)
        b.record("S1", 9, 8)
        b.record("S2", 8, 9)
        b.record("W1", 8, 9)
        b.record("W2", 6, 11)
        return b

    def test_clean_order_division_winners_then_wild_cards(self):
        got = seeds(self.base())
        self.assertEqual(got, [(1, "N1"), (2, "E1"), (3, "S1"), (4, "W1"),
                               (5, "E2"), (6, "N2"), (7, "S2")])
        self.assertEqual(len({c for _, c in got}), 7)

    def test_division_tie_broken_by_head_to_head(self):
        # E1 and E2 both finish 10-7. E2 beat E1, so E2 wins the East.
        b = Builder()
        b.record("E1", 10, 6)      # 10 wins and 6 losses to AFC, plus one NFC loss = 10-7
        b.record("E2", 9, 7)       # 9 wins to AFC, plus one NFC win = 10-7
        b.game("E2", "E1")
        b.record("N1", 11, 6)
        b.record("N2", 8, 9)
        b.record("S1", 9, 8)
        b.record("S2", 8, 9)
        b.record("W1", 8, 9)
        b.record("W2", 6, 11)
        t = b.teams()
        self.assertEqual(t["E1"].record(), (10, 7, 0))
        self.assertEqual(t["E2"].record(), (10, 7, 0))
        got = sd.seeds_for_conference(t, "NFC")
        self.assertEqual(got, [(1, "N1"), (2, "E2"), (3, "S1"), (4, "W1"),
                               (5, "E1"), (6, "N2"), (7, "S2")])

    def test_wild_card_tie_broken_by_head_to_head_across_divisions(self):
        # N2 and S2 both finish 8-9. N2 beat S2, so N2 takes the sixth seed.
        b = Builder()
        b.record("E1", 10, 7)
        b.record("E2", 9, 8)
        b.record("N1", 11, 6)
        b.record("N2", 7, 9)       # 7 wins to AFC, plus one NFC win over S2 = 8-9
        b.game("N2", "S2")
        b.record("S1", 9, 8)
        b.record("S2", 8, 8)       # 8 wins to AFC, plus one NFC loss to N2 = 8-9
        b.record("W1", 8, 9)
        b.record("W2", 6, 11)
        t = b.teams()
        self.assertEqual(t["N2"].record(), (8, 9, 0))
        self.assertEqual(t["S2"].record(), (8, 9, 0))
        got = sd.seeds_for_conference(t, "NFC")
        self.assertEqual(got, [(1, "N1"), (2, "E1"), (3, "S1"), (4, "W1"),
                               (5, "E2"), (6, "N2"), (7, "S2")])


class Flags(unittest.TestCase):
    def test_full_tie_is_flagged_not_silent(self):
        # Two identical teams in different divisions with no games between them and no
        # distinguishing record: every criterion fails and the coin flip is recorded.
        b = Builder()
        b.record("E1", 9, 8)
        b.record("S1", 9, 8)
        sd.COIN_FLAGS.clear()
        ranked = sd.rank_group([b.teams()["E1"], b.teams()["S1"]], b.teams(), same_division=False)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(len(sd.COIN_FLAGS), 1)


class Structure(unittest.TestCase):
    def test_every_team_ranked_exactly_once(self):
        b = Builder()
        b.record("E1", 9, 8)
        b.record("E2", 9, 8)
        b.record("N1", 9, 8)
        b.record("N2", 9, 8)
        t = b.teams()
        nfc = [x for x in t.values() if x.conference == "NFC"]
        ranked = sd.rank_group(nfc, t, same_division=False)
        self.assertEqual(sorted(x.code for x in ranked), sorted(x.code for x in nfc))


if __name__ == "__main__":
    unittest.main()
