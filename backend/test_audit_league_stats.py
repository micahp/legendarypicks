#!/usr/bin/env python3
"""The audit must fail on the shapes that fooled every previous check.

Each test builds the exact condition that was live on prod 2026-08-04 and
asserts the audit catches it. A checker nobody has proven can fail is a checker
that will report green over anything.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import audit_league_stats as audit  # noqa: E402

SCHEMA = """
CREATE TABLE players(
  id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT, position TEXT,
  espn_id TEXT, mlbam_id TEXT, nfl_gsis_id TEXT, nhl_id TEXT, nba_id TEXT
);
CREATE TABLE player_stats(
  player_id INTEGER, league TEXT, season INTEGER, stat_type TEXT,
  games INTEGER, goals INTEGER, assists INTEGER, points_nhl INTEGER,
  shots INTEGER, plus_minus INTEGER, toi REAL
);
CREATE TABLE player_game_logs(
  player_id INTEGER, league TEXT, season INTEGER, stats TEXT
);
"""


class AuditTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(prefix="audit-", suffix=".db", delete=False)
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        self.con = sqlite3.connect(self.path)
        self.addCleanup(self.con.close)
        self.con.executescript(SCHEMA)

    def player(self, pid, position, team="WPG", league="nhl", **ids):
        self.con.execute(
            "INSERT INTO players(id,name,team,league,position,espn_id,mlbam_id,"
            "nfl_gsis_id,nhl_id,nba_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (pid, f"Player {pid}", team, league, position,
             ids.get("espn_id"), ids.get("mlbam_id"), ids.get("nfl_gsis_id"),
             ids.get("nhl_id"), ids.get("nba_id")))

    def log(self, pid, stats, league="nhl", season=2026):
        self.con.execute("INSERT INTO player_game_logs VALUES(?,?,?,?)",
                         (pid, league, season, json.dumps(stats)))

    def stat_row(self, pid, league="nhl", season=2026):
        self.con.execute(
            "INSERT INTO player_stats(player_id,league,season,stat_type,games,"
            "goals,assists,points_nhl,shots,plus_minus,toi) "
            "VALUES(?,?,?,'season',82,30,40,70,200,5,1200.0)", (pid, league, season))

    def states(self, league, prefix):
        out = audit.audit(self.con, [league])
        return {check: state for state, lg, check, _ in out.rows
                if check.startswith(prefix)}

    def row(self, league, check_name):
        """The state AND the note -- a gate's message is part of its contract."""
        out = audit.audit(self.con, [league])
        for state, _lg, check, note in out.rows:
            if check == check_name:
                return state, note
        raise AssertionError(f"{check_name} not reported")

    # ── B: a position's logs must carry that position's stats ────────────────
    def test_goalie_logs_full_of_skater_keys_fail(self):
        """The one that was live: 78 of 90 goalies logged, zero saves recorded.

        Vejmelka had 64 games in this shape. Row counts were healthy the whole
        time, which is why nothing caught it.
        """
        self.player(1, "G")
        for _ in range(5):
            self.log(1, {"goals": 0, "assists": 0, "pim": 0, "toi": 3600})
        self.con.commit()

        states = self.states("nhl", "B/position-content[G]")
        self.assertEqual(audit.FAIL, states["B/position-content[G]"])

    def test_goalie_logs_that_record_saves_pass(self):
        self.player(1, "G")
        for _ in range(5):
            self.log(1, {"saves": 31, "shotsAgainst": 33, "toi": 3600})
        self.con.commit()

        states = self.states("nhl", "B/position-content[G]")
        self.assertEqual(audit.PASS, states["B/position-content[G]"])

    def test_an_alternate_spelling_still_counts_as_recorded(self):
        """`shots_against` and `shotsAgainst` are the same measurement.

        The check asks whether the stat is recorded, not whose word for it is in
        the JSON -- otherwise a rename reads as data loss.
        """
        self.player(1, "G")
        for _ in range(5):
            self.log(1, {"saves": 28, "shots_against": 30})
        self.con.commit()

        self.assertEqual(audit.PASS,
                         self.states("nhl", "B/position-content[G]")["B/position-content[G]"])

    def test_a_position_with_no_logs_is_unverified_not_passing(self):
        """Nothing to sample is not proof of health. It is absence of evidence."""
        self.player(1, "C")
        self.con.commit()

        states = self.states("nhl", "B/position-content[G]")
        self.assertEqual(audit.UNVERIFIED, states["B/position-content[G]"])

    # ── C: one column, one vocabulary ────────────────────────────────────────
    def test_two_position_vocabularies_in_one_column_fail(self):
        """`G/F/C` from one ingest beside `PG/SG/SF/PF` from another.

        Live on NBA: the two populations barely intersect, so 472 of 525
        leaders clicked through to an empty page.
        """
        for pid, pos in ((1, "G"), (2, "F"), (3, "PG"), (4, "SG")):
            self.player(pid, pos, team="BOS", league="nba")
        self.con.commit()

        states = self.states("nba", "C/vocabulary[position]")
        self.assertEqual(audit.FAIL, states["C/vocabulary[position]"])

    def test_one_vocabulary_passes(self):
        for pid, pos in ((1, "PG"), (2, "SG"), (3, "SF"), (4, "PF")):
            self.player(pid, pos, team="BOS", league="nba")
        self.con.commit()

        states = self.states("nba", "C/vocabulary[position]")
        self.assertEqual(audit.PASS, states["C/vocabulary[position]"])


    def test_an_inactive_player_without_a_team_is_not_a_defect(self):
        """`team` is a CURRENT roster spot. A retired player has none."""
        self.con.execute("ALTER TABLE players ADD COLUMN active INTEGER")
        self.player(1, "C", team="WPG")
        self.player(2, "D", team=None)
        self.con.execute("UPDATE players SET active=1 WHERE id=1")
        self.con.execute("UPDATE players SET active=0 WHERE id=2")
        state, note = self.row("nhl", "C/vocabulary[team]")
        self.assertEqual(state, audit.PASS, note)
        self.assertIn("1 inactive", note)

    def test_an_active_player_without_a_team_still_fails(self):
        """The scoping must not become a way to pass by marking rows inactive."""
        self.con.execute("ALTER TABLE players ADD COLUMN active INTEGER")
        self.player(1, "C", team="WPG")
        self.player(2, "D", team=None)
        self.con.execute("UPDATE players SET active=1")
        state, note = self.row("nhl", "C/vocabulary[team]")
        self.assertEqual(state, audit.FAIL, note)
        self.assertIn("ACTIVE", note)

    def test_blank_values_fail_even_when_the_vocabulary_is_consistent(self):
        self.player(1, "C")
        self.player(2, None)
        self.con.commit()

        states = self.states("nhl", "C/vocabulary[position]")
        self.assertEqual(audit.FAIL, states["C/vocabulary[position]"])

    # ── the parent/child exception (MLB's position_group) ──────────────────
    def test_mlb_parent_child_coexists_when_group_column_declared(self):
        """MLB publishes OF (Pache) beside LF/CF/RF. position_group carries the
        parent, so C accepts the coexistence instead of calling it a clash."""
        self.con.execute("ALTER TABLE players ADD COLUMN position_group TEXT")
        for pid, pos in ((1, "OF"), (2, "LF"), (3, "CF"), (4, "RF")):
            self.player(pid, pos, team="NYM", league="mlb")
        self.con.execute("UPDATE players SET position_group='Outfielder'")
        self.con.commit()

        states = self.states("mlb", "C/vocabulary[position]")
        self.assertEqual(audit.PASS, states["C/vocabulary[position]"])

    def test_mlb_parent_child_still_fails_without_a_group_column(self):
        """No group column -> the old defect stands: OF beside LF must fail."""
        for pid, pos in ((1, "OF"), (2, "LF")):
            self.player(pid, pos, team="NYM", league="mlb")
        self.con.commit()

        states = self.states("mlb", "C/vocabulary[position]")
        self.assertEqual(audit.FAIL, states["C/vocabulary[position]"])

    def test_mlb_parent_child_fails_when_group_column_is_empty(self):
        """A declared column that carries nothing must not vouch for the split."""
        self.con.execute("ALTER TABLE players ADD COLUMN position_group TEXT")
        for pid, pos in ((1, "OF"), (2, "LF")):
            self.player(pid, pos, team="NYM", league="mlb")
        self.con.commit()

        states = self.states("mlb", "C/vocabulary[position]")
        self.assertEqual(audit.FAIL, states["C/vocabulary[position]"])

    # ── D: a leader you can actually click into ──────────────────────────────
    def test_leaders_without_game_logs_fail(self):
        """The NBA condition: a leaderboard of dead ends."""
        for pid in range(1, 11):
            self.player(pid, "C")
            self.stat_row(pid)
        self.log(1, {"goals": 1})          # 1 of 10 reachable
        self.con.commit()

        states = self.states("nhl", "D/leaders-reach-logs")
        self.assertEqual(audit.FAIL, states["D/leaders-reach-logs"])

    def test_leaders_with_logs_pass(self):
        for pid in range(1, 11):
            self.player(pid, "C")
            self.stat_row(pid)
            self.log(pid, {"goals": 1})
        self.con.commit()

        states = self.states("nhl", "D/leaders-reach-logs")
        self.assertEqual(audit.PASS, states["D/leaders-reach-logs"])

    def test_no_stats_at_all_fails_rather_than_dividing_by_zero(self):
        self.con.commit()
        states = self.states("nhl", "D/leaders-reach-logs")
        self.assertEqual(audit.FAIL, states["D/leaders-reach-logs"])

    def test_league_without_leaderboard_surface_is_unverified_not_fail(self):
        """UFC/WC declare no stat_types (rankings/dormant, not a stats league).

        D previously FAILed them for 'no player_stats rows at all' -- asserting
        a defect in a leaderboard surface that does not exist. The manifest's
        'nothing to declare, said out loud' is the contract; D must honor it.
        """
        self.con.commit()
        states = self.states("ufc", "D/leaders-reach-logs")
        self.assertEqual(audit.UNVERIFIED, states["D/leaders-reach-logs"])

    # ── A / E: the columns a claim needs ─────────────────────────────────────
    def test_a_missing_stat_column_fails(self):
        """`saves` is declared required for NHL and does not exist here."""
        self.player(1, "C")
        self.stat_row(1)
        self.con.commit()

        states = self.states("nhl", "A/required-stats")
        self.assertEqual(audit.FAIL, states["A/required-stats[season]"])

    def test_a_qualifier_with_no_column_to_measure_it_fails(self):
        """MLB's published rule is 3.1 PA x team games and `pa` is not a column.

        A qualifier denominated in a unit we do not store cannot be applied, and
        `min_games` standing in for it is what put a 38-game player atop a
        112-game season's batting average.
        """
        out = audit.audit(self.con, ["mlb"])
        by_check = {check: state for state, _, check, _ in out.rows}
        self.assertEqual(audit.FAIL, by_check["E/qualifier[batting]"])

    def test_an_unverifiable_qualifier_is_unverified_not_passing(self):
        """A qualifier with no published source stays UNVERIFIED.

        Convention is not a rule, and a gate must not launder one into the
        other by going green. NHL's rule WAS published though (re-asked
        2026-08-05): goalie rate stats require 25 games played per
        Hockey-Reference rate_stat_req.html; skater totals have no floor.
        The unit column (games) exists, so E passes with the published
        source named.
        """
        out = audit.audit(self.con, ["nhl"])
        by_check = {check: state for state, _, check, _ in out.rows}
        self.assertEqual(audit.PASS, by_check["E/qualifier[season]"])
        note = next(note for state, _, check, note in out.rows
                    if check == "E/qualifier[season]")
        self.assertIn("rate_stat_req.html", note)

    # ── the runner's own contract ────────────────────────────────────────────
    def test_a_league_with_no_manifest_is_reported_not_skipped(self):
        """A new league must not pass by being unknown.

        This is the whole reason the manifest is the integration point: adding a
        league without describing it should be loud.
        """
        self.con.execute(
            "INSERT INTO player_stats(player_id,league,season,stat_type) "
            "VALUES(1,'epl',2026,'season')")
        self.con.commit()

        out = audit.audit(self.con, None)
        epl = [r for r in out.rows if r[1] == "epl"]
        self.assertEqual(1, len(epl))
        self.assertEqual(audit.UNVERIFIED, epl[0][0])
        self.assertIn("no MANIFEST entry", epl[0][3])

    def test_unverified_counts_as_a_failure(self):
        result = audit.Result()
        result.add(audit.PASS, "nhl", "x", "")
        result.add(audit.UNVERIFIED, "nhl", "y", "")
        self.assertEqual(1, len(result.failures))

    # ── F: can every publisher reach this league's players? ──────────────────
    def test_one_athlete_on_two_rows_fails(self):
        """The live NBA condition: 269 athletes split across two players.id rows.

        hoopR's athlete_id IS ESPN's, but legacy imports wrote it to `nba_id`
        while roster and log jobs wrote it to `espn_id`. When those land on
        different rows, one real player's historical stats and current game
        logs belong to two different people and no join reunites them.
        """
        self.player(1, "C", league="nba", nba_id="4066261")
        self.player(2, "C", league="nba", espn_id="4066261")
        self.con.commit()

        states = self.states("nba", "F/identity-crosswalk")
        self.assertEqual(audit.FAIL, states["F/identity-crosswalk"])

    def test_two_populated_id_columns_with_no_overlap_fail(self):
        """The condition immediately BEFORE the damage.

        Nothing is split pairwise yet, but no row carries both ids, so there is
        no crosswalk — and the next ingest keyed on the other id builds a second
        population instead of enriching this one.
        """
        self.player(1, "C", league="nba", nba_id="111")
        self.player(2, "C", league="nba", espn_id="222")
        self.con.commit()

        states = self.states("nba", "F/identity-crosswalk")
        self.assertEqual(audit.FAIL, states["F/identity-crosswalk"])

    def test_a_real_crosswalk_passes(self):
        """What NFL looks like: 16,774 rows carrying both ids."""
        self.player(1, "C", league="nba", nba_id="4066261", espn_id="4066261")
        self.player(2, "C", league="nba", nba_id="999", espn_id="999")
        self.con.commit()

        states = self.states("nba", "F/identity-crosswalk")
        self.assertEqual(audit.PASS, states["F/identity-crosswalk"])

    def test_a_single_publisher_league_is_unverified_not_passing(self):
        """MLB and NHL carry no espn_id at all.

        Not a defect by itself — one publisher is a legitimate choice. But it
        is the REASON those leagues cannot have what only the other publisher
        prints (MLB's team and position; NHL's goalie stats), so it is reported
        rather than passed over in silence.
        """
        self.player(1, "C", league="nhl", nhl_id="8477939")
        self.con.commit()

        states = self.states("nhl", "F/identity-crosswalk")
        self.assertEqual(audit.UNVERIFIED, states["F/identity-crosswalk"])

    # ── G: an external id must point at the person named on the row ──────────
    def _publish(self, names, id_column="mlbam_id", league="mlb"):
        """Stand in for the committed artifact fetch_identity_names.py writes."""
        audit._IDENTITY_NAMES_CACHE.clear()
        audit._IDENTITY_NAMES_CACHE["data"] = {
            "leagues": {league: {"id_column": id_column, "names": names}}}
        self.addCleanup(audit._IDENTITY_NAMES_CACHE.clear)

    def named(self, pid, name, mlbam_id, league="mlb"):
        self.con.execute(
            "INSERT INTO players(id,name,team,league,position,mlbam_id) "
            "VALUES(?,?,?,?,?,?)", (pid, name, "LAD", league, "P", mlbam_id))

    def test_an_id_belonging_to_a_different_player_fails(self):
        # Live on prod 2026-08-04: 224 rows like this one, and dedupe_mlb.py
        # would have merged them as "provably the same person".
        self._publish({"702616": "Jackson Holliday"})
        self.named(1, "Mason Miller", "702616")
        self.con.commit()

        state, note = self.row("mlb", "G/published-identity")
        self.assertEqual(audit.FAIL, state)
        self.assertIn("Jackson Holliday", note)

    def test_an_accent_is_not_a_wrong_id(self):
        # 25 rows differ from MLB only by diacritics. Calling those corrupt
        # buries the real signal in noise.
        self._publish({"665161": "Jeremy Peña", "683083": "Nasim Nuñez"})
        self.named(1, "Jeremy Pena", "665161")
        self.named(2, "Nasim Nunez", "683083")
        self.con.commit()

        self.assertEqual(audit.PASS, self.row("mlb", "G/published-identity")[0])

    def test_a_locally_disambiguated_middle_initial_is_not_a_wrong_id(self):
        # MLB publishes BOTH Max Muncys as 'Max Muncy'; this database writes
        # 'Max P. Muncy' for one of them on purpose.
        self._publish({"691777": "Max Muncy"})
        self.named(1, "Max P. Muncy", "691777")
        self.con.commit()

        self.assertEqual(audit.PASS, self.row("mlb", "G/published-identity")[0])

    def test_two_different_people_never_fold_together(self):
        # The fold must forgive decoration and nothing else. 'Kyle Harrison'
        # and 'Edmundo Sosa' shared an mlbam_id on prod.
        self.assertNotEqual(audit._identity_name_key("Kyle Harrison"),
                            audit._identity_name_key("Edmundo Sosa"))

    def test_an_id_the_publisher_does_not_list_is_not_a_defect(self):
        # A retired player is absent from a season roster. That is not evidence
        # of a wrong pairing, and counting it as one would make the gate lie.
        self._publish({"702616": "Jackson Holliday"})
        self.named(1, "Some Retired Guy", "111111")
        self.named(2, "Jackson Holliday", "702616")
        self.con.commit()

        state, note = self.row("mlb", "G/published-identity")
        self.assertEqual(audit.PASS, state)
        self.assertIn("1 checked", note)

    def test_no_published_map_is_unverified_not_passing(self):
        audit._IDENTITY_NAMES_CACHE.clear()
        audit._IDENTITY_NAMES_CACHE["data"] = None
        self.addCleanup(audit._IDENTITY_NAMES_CACHE.clear)
        self.named(1, "Mason Miller", "702616")
        self.con.commit()

        self.assertEqual(audit.UNVERIFIED, self.row("mlb", "G/published-identity")[0])

    def test_a_missing_database_exits_nonzero(self):
        self.assertEqual(1, audit.main(["--db", "/nonexistent/picks.db"]))

    # ── B (rewritten): coverage, not presence ────────────────────────────────
    def test_30_percent_coverage_fails(self):
        """The live NHL shape. The old check read PASS at 30% coverage because
        it only failed a stat that never appeared; a goalie whose log records
        saves in 150 of 500 games is not being observed goaltending."""
        self.player(1, "G")
        for i in range(500):
            self.log(1, {"goals": 0, "assists": 0, "pim": 0,
                         "saves": 30 if i < 150 else None})
        self.con.commit()

        state, note = self.row("nhl", "B/position-content[G]")
        self.assertEqual(audit.FAIL, state)
        self.assertIn("30%", note)

    def test_one_row_in_five_hundred_is_not_a_pass(self):
        """1 of 500 logs carrying the key is a 0.2% observation, not a pass."""
        self.player(1, "G")
        for i in range(500):
            self.log(1, {"goals": 0, "assists": 0,
                         "saves": 28 if i == 0 else None})
        self.con.commit()

        self.assertEqual(audit.FAIL, self.row("nhl", "B/position-content[G]")[0])

    def test_legacy_list_form_entries_still_work(self):
        """A position_content entry in the old list shape defaults to the floor."""
        spec = {"position_content": {"G": [["saves"], ["shotsAgainst", "shots_against"]]}}
        self.player(1, "G")
        for _ in range(5):
            self.log(1, {"saves": 31, "shotsAgainst": 33})
        self.con.commit()

        out = audit.Result()
        audit.check_position_content(self.con, "nhl", spec, out)
        self.assertEqual(audit.PASS, out.rows[0][0])

    # ── D (rewritten): the join is season-scoped on BOTH sides ───────────────
    def test_logs_from_a_different_season_do_not_count_as_reachable(self):
        """The NHL prod shape: 48,017 rows on nhle.com's raw '20252026' key
        meant a season-scoped join returned 0 while the unscoped check read
        PASS. A 2025 log is not reachable for a 2026 leaderboard."""
        for pid in range(1, 11):
            self.player(pid, "C")
            self.stat_row(pid)                        # player_stats in 2026
            self.log(pid, {"goals": 1}, season=2025)  # logs ONLY in 2025
        self.con.commit()

        states = self.states("nhl", "D/leaders-reach-logs")
        self.assertEqual(audit.FAIL, states["D/leaders-reach-logs"])

    def test_same_season_logs_still_count(self):
        for pid in range(1, 11):
            self.player(pid, "C")
            self.stat_row(pid)
            self.log(pid, {"goals": 1})               # season 2026
        self.con.commit()

        states = self.states("nhl", "D/leaders-reach-logs")
        self.assertEqual(audit.PASS, states["D/leaders-reach-logs"])

    # ── C (entity-aware): a team defence plays no position ──────────────────
    def test_fantasy_constructs_are_not_blank_positions(self):
        """entity_type='team_defense' with position NULL is the honest answer
        for a D/ST, not a blank to fail. This is what item 5 of P0 produces."""
        self.con.execute("ALTER TABLE players ADD COLUMN active INTEGER")
        self.con.execute("ALTER TABLE players ADD COLUMN entity_type TEXT")
        self.con.execute(
            "INSERT INTO players(id,name,team,league,position,espn_id,mlbam_id,"
            "nfl_gsis_id,nhl_id,nba_id,active,entity_type) "
            "VALUES(1,'Dak Prescott','DAL','nfl','QB','1',NULL,NULL,NULL,NULL,1,'player')")
        self.con.execute(
            "INSERT INTO players(id,name,team,league,position,espn_id,mlbam_id,"
            "nfl_gsis_id,nhl_id,nba_id,active,entity_type) "
            "VALUES(2,'DAL D/ST','DAL','nfl',NULL,'-16000',NULL,NULL,NULL,NULL,1,'team_defense')")
        self.con.commit()

        state, note = self.row("nfl", "C/vocabulary[position]")
        self.assertEqual(state, audit.PASS, note)

    def test_a_null_position_on_a_real_player_still_fails(self):
        """The entity exclusion must not become a way to pass by relabelling."""
        self.con.execute("ALTER TABLE players ADD COLUMN active INTEGER")
        self.con.execute("ALTER TABLE players ADD COLUMN entity_type TEXT")
        self.con.execute(
            "INSERT INTO players(id,name,team,league,position,espn_id,mlbam_id,"
            "nfl_gsis_id,nhl_id,nba_id,active,entity_type) "
            "VALUES(1,'Some Wideout','DAL','nfl',NULL,'1',NULL,NULL,NULL,NULL,1,'player')")
        self.con.commit()

        state, note = self.row("nfl", "C/vocabulary[position]")
        self.assertEqual(audit.FAIL, state)

    # ── H: the pool's injury fields are populated ────────────────────────────
    def _injury_db(self, with_status=True):
        self.con.execute("ALTER TABLE players ADD COLUMN injury_status TEXT")
        self.con.execute("ALTER TABLE players ADD COLUMN last_news_date TEXT")
        self.con.execute(
            "CREATE TABLE nfl_adp(player_id INTEGER, season INTEGER, position TEXT)")
        for pid in range(1, 6):
            status = ("Probable", "2026-08-01") if with_status else (None, None)
            self.con.execute(
                "INSERT INTO players(id,name,team,league,position,injury_status,"
                "last_news_date) VALUES(?,?,?,'nfl','QB',?,?)",
                (pid, f"Player {pid}", "DAL", *status))
            self.con.execute("INSERT INTO nfl_adp VALUES(?,2026,'QB')", (pid,))
        self.con.commit()

    def test_injury_population_below_floor_fails(self):
        """The prod shape: a 4,508-player pool with injury_status on 0 of them
        served for ~18 hours with no error anywhere."""
        self._injury_db(with_status=False)

        state, note = self.row("nfl", "H/injury-population")
        self.assertEqual(audit.FAIL, state)
        self.assertIn("0%", note)

    def test_injury_population_healthy_passes(self):
        self._injury_db(with_status=True)

        state, note = self.row("nfl", "H/injury-population")
        self.assertEqual(audit.PASS, state)
        self.assertIn("100%", note)


if __name__ == "__main__":
    unittest.main(verbosity=2)
