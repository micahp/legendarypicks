#!/usr/bin/env python3
"""The resolver's fifth step: consult the publisher's own roster before giving up.

Giving up used to mean dropping every prop for a real player. Measured on prod 2026-09-06:
1,254 names and 873,559 attempts from bovada alone, plus 254 from espn_roster, which is proof
the spine is missing people ESPN itself names rather than that a sportsbook spells oddly.
"""
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import published_roster as pr


def _con(rows=()):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    pr.ensure(con)
    for league, key, name, team, position, group in rows:
        con.execute(
            "INSERT INTO published_roster(league, source, source_player_key, name, "
            "name_folded, team, position, position_group, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?, 'now')",
            (league, "fotmob", key, name, pr.fold(name), team, position, group))
    con.commit()
    return con


class ItResolvesWhatThePublisherNames(unittest.TestCase):
    def test_a_single_match_resolves(self):
        con = _con([("mls", "1", "Lautaro Giaccone", "Columbus", "M", "Midfielder")])
        self.assertEqual(pr.lookup(con, "mls", "Lautaro Giaccone"),
                         ("fotmob", "1", "M", "Midfielder", "Lautaro Giaccone"))

    def test_accents_and_punctuation_do_not_prevent_a_match(self):
        """`Djé D'Avilla` reaches us from a sportsbook in several spellings."""
        con = _con([("mls", "1", "Djé D'Avilla", "Chicago", "M", "Midfielder")])
        for spelling in ("Dje DAvilla", "DJE D'AVILLA", "Djé D`Avilla"):
            with self.subTest(spelling=spelling):
                self.assertIsNotNone(pr.lookup(con, "mls", spelling))

    def test_a_league_it_has_never_heard_of_is_not_a_match(self):
        con = _con([("mls", "1", "Someone", "Chicago", "M", "Midfielder")])
        self.assertIsNone(pr.lookup(con, "nfl", "Someone"))


class ItRefusesRatherThanGuesses(unittest.TestCase):
    def test_two_players_of_the_same_name_resolve_to_neither(self):
        """Guessing between them is how 124 of 317 MLB duplicate groups became two people."""
        con = _con([("mls", "1", "Common Name", "Chicago", "M", "Midfielder"),
                    ("mls", "2", "Common Name", "Austin", "D", "Defender")])
        self.assertIsNone(pr.lookup(con, "mls", "Common Name"))

    def test_a_team_narrows_an_otherwise_ambiguous_name(self):
        con = _con([("mls", "1", "Common Name", "Chicago", "M", "Midfielder"),
                    ("mls", "2", "Common Name", "Austin", "D", "Defender")])
        self.assertEqual(pr.lookup(con, "mls", "Common Name", team="Austin")[1], "2")

    def test_it_returns_the_PUBLISHERS_spelling_not_the_callers(self):
        """We resolve BY the publisher's identity, so their rendering of the name is the
        fact and a sportsbook's is a display artifact."""
        con = _con([("mls", "1", "Dj\u00e9 D'Avilla", "Chicago", "M", "Midfielder")])
        self.assertEqual(pr.lookup(con, "mls", "Dje DAvilla")[4], "Dj\u00e9 D'Avilla")

    def test_a_wrong_team_does_not_exclude_the_only_candidate(self):
        """A sportsbook's team string is often absent or in its own vocabulary; requiring it
        would refuse real players for a reason about the publisher, not the person."""
        con = _con([("mls", "1", "Only One", "Chicago", "M", "Midfielder")])
        self.assertIsNotNone(pr.lookup(con, "mls", "Only One", team="NOT-A-CLUB"))

    def test_an_empty_name_is_never_a_match(self):
        con = _con([("mls", "1", "Someone", "Chicago", "M", "Midfielder")])
        for empty in ("", "   ", None, "!!!"):
            with self.subTest(name=empty):
                self.assertIsNone(pr.lookup(con, "mls", empty))

    def test_a_database_without_the_table_does_not_raise(self):
        """The resolver runs on the serving path; a missing table must degrade, not 500."""
        bare = sqlite3.connect(":memory:")
        bare.row_factory = sqlite3.Row
        self.assertIsNone(pr.lookup(bare, "mls", "Anyone"))


class TheResolverUsesIt(unittest.TestCase):
    """End to end through _core, which is what /api/props/ingest actually calls."""

    def _db(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript("""
            CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT,
                position TEXT, position_group TEXT, active INT, updated_at TEXT,
                espn_id TEXT);
            CREATE TABLE player_source_ids(id INTEGER PRIMARY KEY, source TEXT, league TEXT,
                source_player_key TEXT, player_id INT, first_seen TEXT, last_seen TEXT,
                UNIQUE(source, league, source_player_key));
            CREATE TABLE unresolved_players(id INTEGER PRIMARY KEY, source TEXT,
                raw_name TEXT, league TEXT, team TEXT, first_seen TEXT, count INT);
            CREATE TABLE name_alias(player_id INT, alias_norm TEXT);
        """)
        pr.ensure(con)
        con.commit()
        return con

    def test_an_unbound_published_player_is_queued_not_created(self):
        import _core
        con = self._db()
        con.execute(
            "INSERT INTO published_roster(league, source, source_player_key, name, "
            "name_folded, team, position, position_group, team_code, updated_at) "
            "VALUES('mls','fotmob','999','Lautaro Giaccone',?,'Columbus','M',"
            "'Midfielder','CLB','now')",
            (pr.fold("Lautaro Giaccone"),))
        con.commit()
        player_id, confidence = _core._resolve_player_for_ingest(
            con, "Lautaro Giaccone", "CLB", "mls", source="bovada")
        self.assertIsNone(player_id)
        self.assertIsNone(confidence)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 0)
        self.assertEqual(con.execute(
            "SELECT raw_name FROM unresolved_players").fetchone()[0], "Lautaro Giaccone")

    def test_roster_publication_owns_creation_and_binds_both_publishers(self):
        import ingest_published_rosters as ipr
        import _core
        con = self._db()
        members = [
            {"source": "fotmob", "source_player_key": "F1", "name": "Jacob Davis",
             "names": ["Jacob Davis"], "team": "Sporting Kansas City", "position": "M",
             "position_group": "Midfielder"},
            {"source": "mlssoccer", "source_player_key": "M1", "name": "Jake Davis",
             "names": ["Jake Davis", "jacob-davis"], "team": "Sporting Kansas City",
             "position": "M", "position_group": "Midfielder"},
        ]
        ipr._write(con, "mls", members, "now")
        stats = pr.publish_identities(
            con, "mls", "now", [(m["source"], m["source_player_key"]) for m in members])
        con.commit()
        self.assertEqual(stats["inserted"], 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 1)
        self.assertEqual(con.execute(
            "SELECT COUNT(DISTINCT player_id) FROM player_source_ids").fetchone()[0], 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM player_source_ids").fetchone()[0], 2)
        published_id = pr.lookup_player(con, "mls", "Jake Davis", "SKC")
        self.assertIsNotNone(published_id)
        self.assertEqual(
            _core._resolve_player_for_ingest(con, "Jake Davis", "SKC", "mls"),
            (published_id, "high"))

    def test_an_unpublished_name_still_goes_to_the_review_queue(self):
        """The queue keeps its job: only names no publisher confirms."""
        import _core
        con = self._db()
        player_id, _ = _core._resolve_player_for_ingest(
            con, "Nobody Published", "CLB", "mls", source="bovada")
        self.assertIsNone(player_id)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 0)
        self.assertEqual(
            con.execute("SELECT raw_name FROM unresolved_players").fetchone()[0],
            "Nobody Published")

    def test_an_ambiguous_published_name_is_queued_not_guessed(self):
        import _core
        con = self._db()
        for key, team, position in (("1", "Chicago", "M"), ("2", "Austin", "D")):
            con.execute(
                "INSERT INTO published_roster(league, source, source_player_key, name, "
                "name_folded, team, position, position_group, updated_at) "
                "VALUES('mls','fotmob',?,'Common Name',?,?,?,'X','now')",
                (key, pr.fold("Common Name"), team, position))
        con.commit()
        player_id, _ = _core._resolve_player_for_ingest(con, "Common Name", None, "mls")
        self.assertIsNone(player_id)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()


def _add(con, league, source, key, name, team, position="M", group="Midfielder",
         also=()):
    """One publisher's record of one person, with every spelling that publisher prints."""
    con.execute(
        "INSERT INTO published_roster(league, source, source_player_key, name, "
        "name_folded, team, position, position_group, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,'now')",
        (league, source, key, name, pr.fold(name), team, position, group))
    for spelling in (name,) + tuple(also):
        con.execute(
            "INSERT OR IGNORE INTO published_roster_name(league, source, source_player_key, "
            "name, name_folded) VALUES(?,?,?,?,?)",
            (league, source, key, spelling, pr.fold(spelling)))
    con.commit()


class TwoPublishersAreOnePerson(unittest.TestCase):
    """The trap the second publisher sets.

    With one publisher a name matched at most one row and uniqueness was the whole rule.
    Load a second and the SAME person matches twice, so the old rule would read 895
    resolvable MLS names as ambiguous and refuse every one of them.
    """

    def setUp(self):
        self.con = _con()

    def test_the_same_person_from_two_publishers_still_resolves(self):
        _add(self.con, "mls", "fotmob", "F1", "Jacob Davis", "Sporting Kansas City")
        _add(self.con, "mls", "mlssoccer", "M1", "Jake Davis", "Sporting Kansas City",
             also=("jacob-davis",))
        self.assertIsNotNone(pr.lookup(self.con, "mls", "Jacob Davis"))

    def test_a_spelling_only_the_second_publisher_prints_reaches_the_person(self):
        """This is what replaces a hand-written alias: MLS prints both spellings itself."""
        _add(self.con, "mls", "fotmob", "F1", "Jacob Davis", "Sporting Kansas City")
        _add(self.con, "mls", "mlssoccer", "M1", "Jake Davis", "Sporting Kansas City",
             also=("jacob-davis",))
        self.assertIsNotNone(pr.lookup(self.con, "mls", "Jake Davis"))

    def test_the_identity_returned_is_the_one_we_can_chart(self):
        """player_game_logs_fotmob joins on FotMob ids, so a collapsed person comes back
        under FotMob's key even when a different publisher's spelling found them."""
        _add(self.con, "mls", "mlssoccer", "M1", "Jake Davis", "Sporting Kansas City",
             also=("jacob-davis",))
        _add(self.con, "mls", "fotmob", "F1", "Jacob Davis", "Sporting Kansas City")
        self.assertEqual(pr.lookup(self.con, "mls", "Jake Davis")[:2], ("fotmob", "F1"))

    def test_two_people_of_one_name_at_two_clubs_are_still_refused(self):
        """A shared spelling alone must never collapse. The club has to agree too."""
        _add(self.con, "mls", "fotmob", "F1", "Common Name", "Chicago Fire FC")
        _add(self.con, "mls", "mlssoccer", "M1", "Common Name", "Austin FC")
        self.assertIsNone(pr.lookup(self.con, "mls", "Common Name"))

    def test_two_people_of_one_name_at_one_club_are_still_refused(self):
        """One publisher naming two squad members the same is two humans, not a collapse."""
        _add(self.con, "mls", "fotmob", "F1", "Common Name", "Chicago Fire FC")
        _add(self.con, "mls", "fotmob", "F2", "Common Name", "Chicago Fire FC")
        self.assertIsNone(pr.lookup(self.con, "mls", "Common Name"))

    def test_a_club_disagreement_refuses_rather_than_picking_a_publisher(self):
        """Mid-transfer, two publishers file one name at two clubs. That is a question
        about the transfer, and answering it by preferring FotMob would be a guess."""
        _add(self.con, "mls", "fotmob", "F1", "Moving Player", "Chicago Fire FC")
        _add(self.con, "mls", "mlssoccer", "M1", "Moving Player", "Austin FC")
        self.assertIsNone(pr.lookup(self.con, "mls", "Moving Player"))

    def test_a_third_publisher_bridging_two_rows_reports_one_person(self):
        """The bridge row is what makes cluster merging have to absorb every overlap."""
        _add(self.con, "mls", "fotmob", "F1", "Jacob Davis", "Sporting Kansas City")
        _add(self.con, "mls", "espn_roster", "E1", "Jake Davis", "Sporting Kansas City")
        _add(self.con, "mls", "mlssoccer", "M1", "Jake Davis", "Sporting Kansas City",
             also=("jacob-davis",))
        self.assertEqual(pr.lookup(self.con, "mls", "Jake Davis")[:2], ("fotmob", "F1"))

    def test_an_accented_club_name_still_collapses(self):
        """SQLite's UPPER is ASCII-only, so comparing clubs in SQL refused all 11 CF
        Montreal players the collapse was written to resolve, and every test passed."""
        _add(self.con, "mls", "fotmob", "F1", "Frankie Amaya", "CF Montr\u00e9al")
        _add(self.con, "mls", "mlssoccer", "M1", "Frankie Amaya", "CF Montr\u00e9al")
        self.assertEqual(pr.lookup(self.con, "mls", "Frankie Amaya")[:2], ("fotmob", "F1"))

    def test_a_roster_row_without_a_club_is_never_collapsed(self):
        """Collapsing needs published evidence, and a missing club is not evidence."""
        _add(self.con, "mls", "fotmob", "F1", "Jacob Davis", None)
        _add(self.con, "mls", "mlssoccer", "M1", "Jake Davis", None, also=("jacob-davis",))
        self.assertIsNone(pr.lookup(self.con, "mls", "Jacob Davis"))

    def test_only_a_genuine_cross_publisher_disagreement_remains_reviewed(self):
        self.assertEqual(set(pr.REVIEWED_ALIASES["mls"]), {"sabalobzhanidze"})


class PublishedIdentityRefusals(unittest.TestCase):
    def setUp(self):
        import ingest_published_rosters as ipr
        self.ipr = ipr
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript("""
            CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT,
                position TEXT, position_group TEXT, active INT, updated_at TEXT,
                espn_id TEXT);
            CREATE TABLE player_source_ids(id INTEGER PRIMARY KEY, source TEXT, league TEXT,
                source_player_key TEXT, player_id INT, first_seen TEXT, last_seen TEXT,
                UNIQUE(source, league, source_player_key));
            CREATE TABLE player_game_logs(id INTEGER PRIMARY KEY, player_id INT,
                league TEXT, team TEXT, game_date TEXT);
        """)
        pr.ensure(self.con)

    def _logged(self, player_id, team, date="2026-04-05"):
        """A dated appearance for that club. This is the evidence, not `players.team`."""
        self.con.execute(
            "INSERT INTO player_game_logs(player_id, league, team, game_date) "
            "VALUES(?, 'mls', ?, ?)", (player_id, team, date))

    def _write(self, members):
        self.ipr._write(self.con, "mls", members, "now")
        return pr.publish_identities(
            self.con, "mls", "now",
            [(member["source"], member["source_player_key"]) for member in members])

    def test_two_existing_namesakes_are_refused_without_a_binding(self):
        self.con.executemany(
            "INSERT INTO players(name,team,league,position,position_group,active,updated_at) "
            "VALUES('Common Name','CHI','mls','M','Midfielder',1,'old')", [(), ()])
        stats = self._write([{
            "source": "fotmob", "source_player_key": "F1", "name": "Common Name",
            "names": ["Common Name"], "team": "Chicago Fire FC", "position": "M",
            "position_group": "Midfielder"}])
        self.assertEqual(stats["ambiguous"], 1)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM player_source_ids").fetchone()[0], 0)
        self.assertIsNone(self.con.execute(
            "SELECT player_id FROM published_roster").fetchone()[0])

    def test_david_ruiz_is_two_people_and_a_bare_name_stays_ambiguous(self):
        self.con.execute(
            "INSERT INTO players(name,team,league,position,position_group,active,updated_at) "
            "VALUES('David Ruiz','MIA','mls','M','Midfielder',1,'old')")
        members = [
            {"source": "fotmob", "source_player_key": "F-MIA", "name": "David Ruiz",
             "names": ["David Ruiz"], "team": "Inter Miami CF", "position": "M",
             "position_group": "Midfielder"},
            {"source": "fotmob", "source_player_key": "F-NY", "name": "David Ruiz",
             "names": ["David Ruiz"], "team": "Red Bull New York", "position": "M",
             "position_group": "Midfielder"},
            {"source": "mlssoccer", "source_player_key": "M-NY", "name": "David Ruíz",
             "names": ["David Ruíz"], "team": "Red Bull New York", "position": "M",
             "position_group": "Midfielder"},
        ]
        stats = self._write(members)
        self.assertEqual(stats["inserted"], 1)
        self.assertIsNone(pr.lookup_player(self.con, "mls", "David Ruiz"))
        self.assertNotEqual(
            pr.lookup_player(self.con, "mls", "David Ruiz", "MIA"),
            pr.lookup_player(self.con, "mls", "David Ruiz", "RBNY"))

    def test_a_new_club_with_no_logs_at_all_stays_undecided(self):
        """The only genuinely unsafe case: nothing corroborates either club, so a transfer
        and a namesake are still the same shape."""
        self.con.execute(
            "INSERT INTO players(name,team,league,position,position_group,active,updated_at) "
            "VALUES('Moving Name','MIA','mls','M','Midfielder',1,'old')")
        stats = self._write([{
            "source": "mlssoccer", "source_player_key": "M-NY",
            "name": "Moving Name", "names": ["Moving Name"],
            "team": "Red Bull New York", "position": "M",
            "position_group": "Midfielder"}])
        self.assertEqual(stats["unverified_team"], 1)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 1)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM player_source_ids").fetchone()[0], 0)


class TheIngestAsksEveryPublisher(unittest.TestCase):
    """`_PROVIDERS` is league -> a LIST, and the club vocabulary has to line up."""

    def setUp(self):
        import ingest_published_rosters as ipr
        self.ipr = ipr
        self.con = sqlite3.connect(":memory:")
        self.con.execute("CREATE TABLE league_clubs(league TEXT, name TEXT, code TEXT, "
                         "source TEXT, updated_at TEXT, PRIMARY KEY(league, name))")
        for name, code in (("Seattle Sounders", "130394"), ("Seattle Sounders FC", "130394"),
                           ("LAFC", "867280"), ("Los Angeles FC", "867280"),
                           ("Sporting KC", "6604"), ("Sporting Kansas City", "6604"),
                           ("Whitecaps", "VAN")):
            self.con.execute("INSERT INTO league_clubs VALUES('mls',?,?,'fotmob','now')",
                             (name, code))
        self.con.commit()

    def test_a_club_stored_under_two_aliases_is_fetched_once(self):
        """Reading league_clubs directly fetched 51 squads for 30 clubs."""
        clubs = self.ipr._clubs(self.con, "mls")
        self.assertEqual(len(clubs), 3)
        self.assertEqual(len({code for _, code in clubs}), 3)

    def test_the_canonical_club_name_is_stable_across_runs(self):
        """It is the string that tells lookup two publishers mean one person, so it cannot
        be whichever alias happened to be written last."""
        names = dict((code, name) for name, code in self.ipr._clubs(self.con, "mls"))
        self.assertEqual(names["130394"], "Seattle Sounders FC")
        self.assertEqual(names["867280"], "Los Angeles FC")

    def test_a_club_with_no_publisher_id_is_not_a_club_here(self):
        """`VAN` is a sportsbook code, not a FotMob id; a squad cannot be fetched with it."""
        self.assertNotIn("VAN", {code for _, code in self.ipr._clubs(self.con, "mls")})

    def test_every_mls_slug_reaches_a_club_on_record(self):
        clubs = self.ipr._clubs(self.con, "mls")
        for slug, expected in (("seattle-sounders-fc", "Seattle Sounders FC"),
                               ("sporting-kansas-city", "Sporting Kansas City"),
                               # MLS writes out "football club" where our record writes FC.
                               ("los-angeles-football-club", "Los Angeles FC")):
            with self.subTest(slug=slug):
                self.assertEqual(self.ipr._match_club(slug, clubs), expected)

    def test_an_unrecognised_club_is_refused_rather_than_invented(self):
        """A squad filed under a club string FotMob's rows do not use could never collapse
        onto them, so it would arrive as a whole extra squad of new people."""
        self.assertIsNone(self.ipr._match_club("some-new-franchise", self.ipr._clubs(self.con, "mls")))

    def test_mls_declares_two_publishers_and_the_others_one(self):
        self.assertEqual(len(self.ipr._PROVIDERS["mls"]), 2)
        self.assertEqual(len(self.ipr._PROVIDERS["ligamx"]), 1)

    def test_a_publisher_that_returns_nothing_does_not_erase_another(self):
        """One publisher going dark must not shrink the roster the resolver reads."""
        pr.ensure(self.con)
        self.ipr._write(self.con, "mls", [{
            "source": "fotmob", "source_player_key": "F1", "name": "Jacob Davis",
            "names": ["Jacob Davis"], "team": "Sporting Kansas City",
            "position": "M", "position_group": "Midfielder"}], "now")
        self.con.commit()
        before = self.con.execute("SELECT COUNT(*) FROM published_roster").fetchone()[0]
        self.ipr._write(self.con, "mls", [], "later")
        self.assertEqual(
            self.con.execute("SELECT COUNT(*) FROM published_roster").fetchone()[0], before)

    def test_every_spelling_a_publisher_prints_is_stored(self):
        pr.ensure(self.con)
        self.ipr._write(self.con, "mls", [{
            "source": "mlssoccer", "source_player_key": "M1", "name": "Jake Davis",
            "names": ["Jake Davis", "jacob davis", "Jake Davis"],
            "team": "Sporting Kansas City", "position": "M",
            "position_group": "Midfielder"}], "now")
        self.con.commit()
        self.assertEqual(
            {row[0] for row in self.con.execute(
                "SELECT name_folded FROM published_roster_name")},
            {"jakedavis", "jacobdavis"})


class ATransferIsNotAFailure(unittest.TestCase):
    """A player who changes clubs does not change which club his old logs belong to.

    Refusing every one of these compared `players.team`, a last-known value with no
    timestamp, against the publisher's current squad, and called the difference evidence
    of two different humans. Measured on prod 2026-09-07, all three San Diego FC refusals
    were real transfers with corroborating game logs.
    """

    def setUp(self):
        import ingest_published_rosters as ipr
        self.ipr = ipr
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript("""
            CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT,
                position TEXT, position_group TEXT, active INT, updated_at TEXT,
                espn_id TEXT);
            CREATE TABLE player_source_ids(id INTEGER PRIMARY KEY, source TEXT, league TEXT,
                source_player_key TEXT, player_id INT, first_seen TEXT, last_seen TEXT,
                UNIQUE(source, league, source_player_key));
            CREATE TABLE player_game_logs(id INTEGER PRIMARY KEY, player_id INT,
                league TEXT, team TEXT, game_date TEXT);
        """)
        pr.ensure(self.con)

    def _player(self, name, team):
        return self.con.execute(
            "INSERT INTO players(name,team,league,position,position_group,active,updated_at) "
            "VALUES(?,?,'mls','M','Midfielder',1,'old')", (name, team)).lastrowid

    def _logged(self, player_id, team):
        self.con.execute(
            "INSERT INTO player_game_logs(player_id, league, team, game_date) "
            "VALUES(?, 'mls', ?, '2026-04-05')", (player_id, team))

    def _publish(self, name, published_team):
        members = [{"source": "mlssoccer", "source_player_key": "M1", "name": name,
                    "names": [name], "team": published_team, "position": "M",
                    "position_group": "Midfielder"}]
        self.ipr._write(self.con, "mls", members, "now")
        return pr.publish_identities(self.con, "mls", "now",
                                     [("mlssoccer", "M1")])

    def _bound_to(self):
        row = self.con.execute("SELECT player_id FROM player_source_ids").fetchone()
        return row[0] if row else None

    def test_logs_at_the_stored_club_make_it_a_transfer(self):
        """Jacob Jackson: stored DAL, four logs at DAL, MLS now publishes San Diego."""
        pid = self._player("Jacob Jackson", "DAL")
        self._logged(pid, "DAL")
        stats = self._publish("Jacob Jackson", "San Diego FC")
        self.assertEqual(stats["transfers"], 1)
        self.assertEqual(self._bound_to(), pid, "the transfer binds to the existing person")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 1,
                         "and does not mint a second one")

    def test_logs_at_the_PUBLISHED_club_mean_our_stored_team_is_wrong(self):
        """Wilson Eisner: stored SJ, but his own four logs say San Diego, which is also
        what the publisher says. The stored team is the outlier, not the publisher."""
        pid = self._player("Wilson Eisner", "SJ")
        self._logged(pid, "SD")
        stats = self._publish("Wilson Eisner", "SD")
        self.assertEqual(stats["stale_team"], 1)
        self.assertEqual(stats.get("transfers", 0), 0)
        self.assertEqual(self._bound_to(), pid)

    def test_a_multi_club_history_still_reads_as_a_transfer(self):
        """Sam Vines: 22 logs at COL, 3 at HOU, stored HOU, now published at San Diego."""
        pid = self._player("Sam Vines", "HOU")
        self._logged(pid, "COL")
        self._logged(pid, "HOU")
        stats = self._publish("Sam Vines", "San Diego FC")
        self.assertEqual(stats["transfers"], 1)
        self.assertEqual(self._bound_to(), pid)

    def test_no_logs_anywhere_is_still_refused(self):
        """Nothing corroborates either club, so transfer and namesake stay the same shape.
        This is the case that should keep the job red."""
        self._player("Ghost Player", "MIA")
        stats = self._publish("Ghost Player", "Red Bull New York")
        self.assertEqual(stats["unverified_team"], 1)
        self.assertIsNone(self._bound_to())

    def test_two_namesakes_at_other_clubs_are_ambiguous_not_a_transfer(self):
        """Corroborating logs cannot pick between two people, so this stays a refusal."""
        first = self._player("Twin Name", "MIA")
        second = self._player("Twin Name", "CHI")
        self._logged(first, "MIA")
        self._logged(second, "CHI")
        stats = self._publish("Twin Name", "San Diego FC")
        self.assertEqual(stats["ambiguous"], 1)
        self.assertIsNone(self._bound_to())
