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

MAP = {"E1": ("NFC", "NFC East"), "E2": ("NFC", "NFC East"), "E3": ("NFC", "NFC East"),
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
        # E1 and E2 both finish 10-7. E2 beat E1 head-to-head, but E1 has the better division
        # record (2-1 against 1-1), so the division-record criterion would pick E1. Only
        # head-to-head gives E2 the East. The test fails if head-to-head is removed.
        b = Builder()
        b.record("E1", 8, 6)     # 8 AFC wins, 6 AFC losses
        b.record("E2", 9, 6)     # 9 AFC wins, 6 AFC losses
        b.record("E3", 5, 8)     # 5 AFC wins, 8 AFC losses
        b.game("E1", "E3")
        b.game("E1", "E3")       # E1 beats E3 twice
        b.game("E2", "E1")       # E2 beats E1: E2's only win over E1
        b.game("E3", "E2")       # E3 beats E2
        b.record("N1", 11, 6)
        b.record("N2", 7, 9)
        b.game("N2", "S2")       # N2 beats S2 (used by the next test as well)
        b.record("S1", 9, 8)
        b.record("S2", 8, 8)
        b.record("W1", 8, 9)
        b.record("W2", 6, 11)
        t = b.teams()
        self.assertEqual(t["E1"].record(), (10, 7, 0))
        self.assertEqual(t["E2"].record(), (10, 7, 0))
        self.assertEqual(st.division_record(t["E1"], t), (2, 1, 0))
        self.assertEqual(st.division_record(t["E2"], t), (1, 1, 0))
        self.assertEqual(st.head_to_head(t["E2"], t["E1"]), (1, 0, 0))
        got = sd.seeds_for_conference(t, "NFC")
        self.assertEqual(got[1], (2, "E2"))
        self.assertEqual(got[4], (5, "E1"))

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
        t = b.teams()
        ranked = sd.order([t["E1"], t["S1"]], t, "wildcard")
        self.assertEqual(len(ranked), 2)
        self.assertEqual(sd.COIN_FLAGS, [("E1", "S1")])

    def test_coin_with_an_rng_is_random_not_alphabetical(self):
        import random
        b = Builder()
        b.record("E1", 9, 8)
        b.record("S1", 9, 8)
        t = b.teams()
        firsts = {sd.order([t["E1"], t["S1"]], t, "wildcard", rng=random.Random(s))[0].code
                  for s in range(20)}
        self.assertEqual(firsts, {"E1", "S1"})


class Structure(unittest.TestCase):
    def test_every_team_ranked_exactly_once(self):
        b = Builder()
        b.record("E1", 9, 8)
        b.record("E2", 9, 8)
        b.record("N1", 9, 8)
        b.record("N2", 9, 8)
        t = b.teams()
        nfc = [x for x in t.values() if x.conference == "NFC"]
        ranked = sd.order(nfc, t, "wildcard")
        self.assertEqual(sorted(x.code for x in ranked), sorted(x.code for x in nfc))


class Rules(unittest.TestCase):
    """One test per rule. Each docstring names the rule it plants; removing that rule from
    nfl_seeding.py makes the test fail."""

    def test_wild_card_division_reduction_before_sweep(self):
        """Plants: the division reduction in step 1 of the wild-card tie. E2 and E3 are both East
        and tied 9-8. E2 beat E3 twice, so E2 is the East club ranked higher. E3 has the best
        conference record of the three tied clubs, and nobody sweeps (E3 beats N2 but loses to
        E2, so E2 does not sweep either). Only E2 enters step 1, and N2 beats E2 head-to-head.
        Without the reduction the three clubs reach conference record and E3 takes seed 5."""
        b = Builder()
        b.record("N1", 12, 5)
        b.record("E1", 11, 6)
        b.record("S1", 10, 5)
        b.record("W1", 7, 8)
        b.record("E2", 7, 5)
        b.record("E3", 6, 6)
        b.record("N2", 8, 7)
        b.record("S2", 8, 9)
        b.record("W2", 6, 11)
        b.game("E2", "E3")
        b.game("E2", "E3")
        b.game("E3", "N2")
        b.game("N2", "E2")
        b.game("E3", "S1")
        b.game("E3", "S1")
        b.game("W1", "E2")
        b.game("W1", "E2")
        t = b.teams()
        self.assertEqual(t["E2"].record(), (9, 8, 0))
        self.assertEqual(t["E3"].record(), (9, 8, 0))
        self.assertEqual(t["N2"].record(), (9, 8, 0))
        self.assertEqual(st.conference_record(t["E3"], t), (3, 2, 0))
        self.assertEqual(st.conference_record(t["E2"], t), (2, 3, 0))
        got = seeds(b)
        self.assertEqual(got[4], (5, "N2"))
        self.assertEqual(got[5], (6, "E2"))
        self.assertEqual(got[6], (7, "E3"))

    def test_head_to_head_sweep_and_its_absence(self):
        """Plants: the sweep step. E1 beats N2 and S2, so it wins the three-club tie with step 1
        (decision named 'head-to-head sweep'). In a three-club cycle nobody sweeps, the sweep
        step is passed over, and it is not the step that decides."""
        b = Builder()
        b.game("E1", "N2")
        b.game("E1", "S2")
        b.game("N2", "S2")
        t = b.teams()
        group = [t["E1"], t["N2"], t["S2"]]
        sd.DECISIONS.clear()
        self.assertEqual(sd.winner(group, t, "wildcard").code, "E1")
        self.assertEqual(sd.DECISIONS[-1][1:], ("head-to-head sweep", "E1"))

        c = Builder()
        c.game("E1", "N2")
        c.game("N2", "S2")
        c.game("S2", "E1")
        t = c.teams()
        group = [t["E1"], t["N2"], t["S2"]]
        self.assertIsNone(sd._sweep(group, t))
        sd.DECISIONS.clear()
        sd.winner(group, t, "wildcard")
        self.assertNotEqual(sd.DECISIONS[-1][1], "head-to-head sweep")

    def test_positions_share_a_rank_on_ties(self):
        """Plants: competition ranking. Two clubs tied for first both get 1, and the next club
        gets 3, not 2. Lowest-is-best (points allowed) works the same way."""
        self.assertEqual(sd._positions({"A": 30, "B": 30, "C": 20}, True),
                         {"A": 1, "B": 1, "C": 3})
        self.assertEqual(sd._positions({"A": 10, "B": 10, "C": 20}, False),
                         {"A": 1, "B": 1, "C": 3})

    def test_restart_after_elimination_uses_two_club_head_to_head(self):
        """Plants: the restart. E1, E2 and E3 are tied 1-1 among themselves, so their
        head-to-head does not decide. Division record eliminates E3 and leaves E1 and E2 tied.
        The two that remain restart at two-club step 1, head-to-head, which gives E1 the title
        even though E2 has the better conference record. Dropping the restart would let
        conference record decide and pick E2."""
        b = Builder()
        b.game("E1", "E2")
        b.game("E2", "E3")
        b.game("E3", "E1")
        b.game("E1", "E4")
        b.game("E1", "E4")
        b.game("E2", "E4")
        b.game("E2", "E4")
        b.game("E4", "E3")
        b.game("E4", "E3")
        b.game("E2", "N1")
        b.game("E2", "N1")
        b.game("N1", "E1")
        b.game("N1", "E1")
        t = st.build(dict(MAP, E4=("NFC", "NFC East")), b.games)
        self.assertEqual(st.division_record(t["E1"], t), (3, 1, 0))
        self.assertEqual(st.division_record(t["E2"], t), (3, 1, 0))
        self.assertEqual(st.division_record(t["E3"], t), (1, 3, 0))
        self.assertEqual(st.conference_record(t["E1"], t), (3, 3, 0))
        self.assertEqual(st.conference_record(t["E2"], t), (5, 1, 0))
        sd.DECISIONS.clear()
        w = sd.winner([t["E1"], t["E2"], t["E3"]], t, "division")
        self.assertEqual(w.code, "E1")
        self.assertEqual(sd.DECISIONS[-1], (("E1", "E2"), "head-to-head", "E1"))

    def test_division_winners_tied_on_record_use_wild_card_steps(self):
        """Plants: division winners on the wild-card procedure. N1 and E1 are both 10-7 and
        never played each other. N1 has the better division record (2-0 against N2), which
        the division procedure would use first. The wild-card procedure goes to conference
        record first, where E1 is 4-2 and N1 is 2-3, so E1 is first."""
        b = Builder()
        b.record("N1", 8, 4)
        b.record("E1", 6, 5)
        b.game("N1", "N2")
        b.game("N1", "N2")
        b.game("W2", "N1")
        b.game("W2", "N1")
        b.game("W2", "N1")
        b.game("E2", "E1")
        b.game("E2", "E1")
        b.game("E1", "S1")
        b.game("E1", "S1")
        b.game("E1", "W1")
        b.game("E1", "W1")
        t = b.teams()
        self.assertEqual(t["N1"].record(), (10, 7, 0))
        self.assertEqual(t["E1"].record(), (10, 7, 0))
        self.assertEqual(st.division_record(t["N1"], t), (2, 0, 0))
        self.assertEqual(st.conference_record(t["N1"], t), (2, 3, 0))
        self.assertEqual(st.conference_record(t["E1"], t), (4, 2, 0))
        sd.DECISIONS.clear()
        got = sd.order([t["N1"], t["E1"]], t, "wildcard")
        self.assertEqual(got[0].code, "E1")
        self.assertEqual(sd.DECISIONS[-1][1], "conference record")

    def test_six_seed_era(self):
        """Plants: the seed count. Before 2020 there are six seeds (two byes), since 2020
        seven. Ignoring n_seeds would return seven clubs for 2019."""
        self.assertEqual(sd.n_seeds_for(2019), 6)
        self.assertEqual(sd.n_seeds_for(2020), 7)
        six = sd.seeds_for_conference(base_teams(), "NFC", n_seeds=6)
        seven = sd.seeds_for_conference(base_teams(), "NFC")
        self.assertEqual(len(six), 6)
        self.assertEqual(six, seven[:6])


def base_teams():
    b = Builder()
    b.record("E1", 10, 7)
    b.record("E2", 9, 8)
    b.record("N1", 11, 6)
    b.record("N2", 8, 9)
    b.record("S1", 9, 8)
    b.record("S2", 8, 9)
    b.record("W1", 8, 9)
    b.record("W2", 6, 11)
    return b.teams()


if __name__ == "__main__":
    unittest.main()
