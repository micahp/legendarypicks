"""Monotonic evidence rules: accepted outcomes, identities and links only gain evidence; changes become conflicts."""
import sqlite3
import unittest

import research_evidence as rpe
import research_player_outcomes as rpo


def outcome(**over):
    row = {"tour": "atp", "event": "shanghai-atp-2026", "espn_game_id": "1", "espn_athlete_id": "A", "side": "home",
           "opponent_athlete_id": "B", "espn_status": "Final", "aces": 6, "double_faults": 1,
           "verification_tier": "id_consistent", "provider": "tennis24", "provider_match_id": "m1",
           "official_url": None, "raw_values": "{}", "eligible_cp4": 0, "built_at": "t0"}
    row.update(over)
    return row


class OutcomeRulesTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript(rpo.DDL)
        rpe.ensure(self.con)

    def stored(self):
        return dict(self.con.execute("SELECT aces, double_faults, verification_tier, eligible_cp4 FROM "
                                     "research_player_match_outcomes WHERE espn_athlete_id='A'").fetchone())

    def test_a_new_outcome_is_inserted(self):
        self.assertEqual(rpe.upsert_outcome(self.con, outcome()), "inserted")
        self.assertEqual(self.stored()["aces"], 6)

    def test_different_values_never_overwrite_an_accepted_outcome(self):
        rpe.upsert_outcome(self.con, outcome(verification_tier="official_labelled", eligible_cp4=1))
        self.assertEqual(rpe.upsert_outcome(self.con, outcome(aces=9, verification_tier="official_labelled",
                                                              eligible_cp4=1)), "conflict")
        self.assertEqual(self.stored()["aces"], 6)
        conflict = self.con.execute("SELECT kind, accepted, incoming FROM evidence_conflicts").fetchone()
        self.assertEqual(conflict["kind"], "outcome")
        self.assertIn('"aces": 9', conflict["incoming"])

    def test_a_stronger_tier_with_the_same_values_upgrades_the_tier(self):
        rpe.upsert_outcome(self.con, outcome(verification_tier="id_consistent", eligible_cp4=1))
        self.assertEqual(rpe.upsert_outcome(self.con, outcome(verification_tier="official_labelled", eligible_cp4=1)), "upgraded")
        self.assertEqual(self.stored()["verification_tier"], "official_labelled")

    def test_a_weaker_tier_with_the_same_values_keeps_the_stronger_tier(self):
        rpe.upsert_outcome(self.con, outcome(verification_tier="official_labelled", eligible_cp4=1))
        rpe.upsert_outcome(self.con, outcome(verification_tier="id_consistent", eligible_cp4=0))
        self.assertEqual(self.stored()["verification_tier"], "official_labelled")
        self.assertEqual(self.stored()["eligible_cp4"], 1)

    def test_eligibility_is_never_removed_by_a_later_run(self):
        rpe.upsert_outcome(self.con, outcome(verification_tier="official_labelled", eligible_cp4=1))
        rpe.upsert_outcome(self.con, outcome(verification_tier="official_labelled", eligible_cp4=0))
        self.assertEqual(self.stored()["eligible_cp4"], 1)

    def test_a_refresh_with_the_same_values_keeps_the_row(self):
        rpe.upsert_outcome(self.con, outcome(verification_tier="id_consistent", eligible_cp4=1))
        self.assertEqual(rpe.upsert_outcome(self.con, outcome(verification_tier="id_consistent", eligible_cp4=1,
                                                              built_at="t1")), "refreshed")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM research_player_match_outcomes").fetchone()[0], 1)


class IdentityAndLinkRulesTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript(rpo.DDL)
        self.con.executescript("""CREATE TABLE provider_espn_links(provider TEXT, provider_match_id TEXT, event TEXT,
            espn_game_id TEXT, status TEXT, method TEXT, candidates TEXT, PRIMARY KEY(provider, provider_match_id));
            CREATE TABLE provider_player_map(provider TEXT, provider_player_code TEXT, event TEXT, espn_athlete_id TEXT,
            status TEXT, matches_seen INTEGER, PRIMARY KEY(provider, provider_player_code, event));""")
        rpe.ensure(self.con)

    def test_an_identity_with_a_different_athlete_is_a_conflict(self):
        rpe.upsert_identity(self.con, "tennis24", "jyngIesG", "e", "1797", "id_consistent_multi_match", "x", 3)
        self.assertEqual(rpe.upsert_identity(self.con, "tennis24", "jyngIesG", "e", "9999",
                                             "id_consistent_multi_match", "y", 4), "conflict")
        self.assertEqual(self.con.execute("SELECT espn_athlete_id FROM provider_player_identity").fetchone()[0], "1797")

    def test_an_unverified_identity_is_upgraded_when_evidence_arrives(self):
        rpe.upsert_identity(self.con, "tennis24", "GlqMuuhi", "e", None, "unverified_single_match", "x", 1)
        self.assertEqual(rpe.upsert_identity(self.con, "tennis24", "GlqMuuhi", "e", "13478",
                                             "id_consistent_multi_match", "y", 2), "upgraded")

    def test_a_link_to_a_different_game_is_a_conflict_not_an_overwrite(self):
        rpe.upsert_link(self.con, "tennis24", "m1", "e", "185371", "proposed", "name", "[]")
        self.assertEqual(rpe.upsert_link(self.con, "tennis24", "m1", "e", "185314", "proposed", "name", "[]"), "conflict")
        self.assertEqual(self.con.execute("SELECT espn_game_id FROM provider_espn_links").fetchone()[0], "185371")

    def test_a_review_link_is_upgraded_to_a_proposal(self):
        rpe.upsert_link(self.con, "tennis24", "m2", "e", None, "review", "none", "[]")
        self.assertEqual(rpe.upsert_link(self.con, "tennis24", "m2", "e", "185318", "proposed", "name", "[]"), "upgraded")


class OfficialPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        rpe.ensure(self.con)

    def test_official_pages_are_kept_for_later_runs(self):
        page = {"url": "ms001", "names": ["A B", "C D"], "home_aces": 6, "away_aces": 12,
                "home_double_faults": 1, "away_double_faults": 2, "parse_status": "ok"}
        rpe.store_official_pages(self.con, "shanghai-atp-2026", [page])
        loaded = rpe.load_official_pages(self.con, "shanghai-atp-2026")
        self.assertEqual(loaded[0]["home_aces"], 6)
        self.assertEqual(loaded[0]["names"], ["A B", "C D"])

    def test_a_changed_official_page_is_a_conflict_and_the_stored_one_stays(self):
        page = {"url": "ms001", "names": ["A B", "C D"], "home_aces": 6, "away_aces": 12,
                "home_double_faults": 1, "away_double_faults": 2, "parse_status": "ok"}
        rpe.store_official_pages(self.con, "shanghai-atp-2026", [page])
        counts = rpe.store_official_pages(self.con, "shanghai-atp-2026", [dict(page, home_aces=7)])
        self.assertEqual(counts["conflict"], 1)
        self.assertEqual(rpe.load_official_pages(self.con, "shanghai-atp-2026")[0]["home_aces"], 6)


if __name__ == "__main__":
    unittest.main()
