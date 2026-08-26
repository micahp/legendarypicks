#!/usr/bin/env python3
"""Contracts for the RotoWire props ingest.

The fixture below is shaped from the real 2026-08-19 payload, field for field, because a
fixture is a claim about what the publisher sends: `props[].lines[]` carries one entry per
book with its own `line`, `entities` is a list of ids into `entities[]`, an entity's
`link` is where its stable player id lives, and `events[].gameID` is the stable fixture id
while `eventID` is only an index inside one day's payload.
"""
import datetime as dt
import json
import os
import sqlite3
import tempfile
import unittest

_IMPORT_TMP = tempfile.TemporaryDirectory()
os.environ["LP_DB_PATH"] = os.path.join(_IMPORT_TMP.name, "import-only.db")

import ingest_rotowire_props as rw


def create_schema(path):
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE players(
              id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
              team TEXT, league TEXT NOT NULL, active INTEGER DEFAULT 1
            );
            CREATE TABLE prop_games(
              id INTEGER PRIMARY KEY AUTOINCREMENT, league TEXT NOT NULL,
              date TEXT NOT NULL, home TEXT, away TEXT, espn_event_id TEXT,
              start_time TEXT
            );
            CREATE TABLE props(
              id INTEGER PRIMARY KEY AUTOINCREMENT, game_id INTEGER,
              player_id INTEGER, market TEXT NOT NULL, line REAL NOT NULL,
              side TEXT NOT NULL, source TEXT, captured_at TEXT NOT NULL,
              odds INTEGER, odds_captured_at TEXT
            );
            CREATE TABLE nfl_schedule(
              game_id TEXT, season INTEGER, week INTEGER, gameday TEXT,
              away_team TEXT, home_team TEXT
            );
            CREATE TABLE unresolved_players(
              id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
              raw_name TEXT NOT NULL, league TEXT NOT NULL, team TEXT,
              first_seen TEXT NOT NULL, count INTEGER DEFAULT 1,
              source_player_key TEXT, reason TEXT
            );
            CREATE TABLE scoreboard_snapshots(league TEXT, payload TEXT);
        """)
        # The league's own calendar is where the team vocabulary comes from.
        con.executemany(
            "INSERT INTO nfl_schedule(game_id,season,week,gameday,away_team,home_team) "
            "VALUES(?,2026,1,'2026-09-13',?,?)",
            [("2026_01_SF_LA", "SF", "LAR"), ("2026_01_WAS_PHI", "WSH", "PHI"),
             ("2026_01_ATL_TB", "ATL", "TB"), ("2026_01_NYJ_NE", "NYJ", "NE")])


# 2026-09-13 13:00 ET kickoff, published as a UTC instant the way the relay does.
# Deliberately a Sunday afternoon: the UTC instant is 17:00 the same day, so this
# fixture does NOT hide a date bug behind a kickoff that never crosses midnight.
KICKOFF = 1789318800


MLB_DISPLAY_NAMES = {
    "ATH": "Athletics",
    "CHW": "Chicago White Sox",
    "MIN": "Minnesota Twins",
    "NYM": "New York Mets",
    "NYY": "New York Yankees",
    "SD": "San Diego Padres",
    "TOR": "Toronto Blue Jays",
}


def seed_mlb_scoreboard_vocabulary(con, omit=None):
    """A complete durable 30-club snapshot fixture, with key display-name edges."""
    for code in sorted(rw.CANONICAL_TEAM_CODES["mlb"]):
        if code == omit:
            continue
        name = MLB_DISPLAY_NAMES.get(code, "{} Club".format(code))
        con.execute(
            "INSERT INTO scoreboard_snapshots(league,payload) VALUES('mlb',?)",
            (json.dumps({
                "home": {"abbrev": code, "name": name},
                "away": {"abbrev": code, "name": name},
            }),),
        )
    con.commit()


def mlb_payload(market_id=222, market_name="Walks", player_name="Miguel Vargas",
                team="CWS", home="CWS", away="NYM"):
    return {
        "markets": [{
            "marketID": market_id, "sport": "MLB", "category": "Game",
            "marketName": market_name,
        }],
        "entities": [{
            "entityID": 39, "eventID": 29, "sport": "MLB",
            "name": player_name, "team": team, "pos": "3B",
            "link": "https://www.rotowire.com/baseball/player/miguel-vargas-15650",
        }],
        "events": [{
            "eventID": 29, "gameID": 76769, "eventTime": KICKOFF,
            "homeTeam": home, "awayTeam": away,
        }],
        "props": [{
            "propID": "mlb-39", "marketID": market_id, "entities": [39],
            "lines": [{"book": "prizepicks", "over": -120, "under": -110,
                       "line": 0.5}],
        }],
    }


def payload(market_id=13, market_name="Passing Yards", category="Game",
            player_name="Matthew Stafford", team="LAR", home="LAR", away="SF",
            link="https://www.rotowire.com/football/player/matthew-stafford-5971"):
    return {
        "markets": [
            {"marketID": market_id, "sport": "NFL", "category": category,
             "marketName": market_name},
            {"marketID": 152, "sport": "Soccer", "category": "Game",
             "marketName": "Shots on Target"},
        ],
        "entities": [
            {"entityID": 6, "eventID": 6, "sport": "NFL", "name": player_name,
             "team": team, "pos": "QB", "link": link, "photo": None},
        ],
        "events": [
            {"eventID": 6, "gameID": 7583, "eventTime": KICKOFF,
             "homeTeam": home, "awayTeam": away, "oddsSource": "draftkings"},
        ],
        "props": [
            {"propID": "ee6f7059", "marketID": market_id, "entities": [6],
             "projection": 231.16,
             "lines": [
                 {"book": "underdog", "over": -137, "under": -137, "line": 264.5},
                 {"book": "prizepicks", "over": -119, "under": -125, "line": 263.5},
             ],
             "hitRates": []},
        ],
    }


class RotowirePropsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "rw.db")
        create_schema(self.db_path)
        self.old_db = rw.DB
        rw.DB = self.db_path
        self.con = sqlite3.connect(self.db_path)
        self.con.row_factory = sqlite3.Row

    def tearDown(self):
        self.con.close()
        rw.DB = self.old_db
        self.tmp.cleanup()

    def player(self, name, team, active=1):
        player_id = self.con.execute(
            "INSERT INTO players(name,team,league,active) VALUES(?,?,'nfl',?)",
            (name, team, active)).lastrowid
        self.con.commit()
        return player_id

    def scalar(self, sql, params=()):
        return self.con.execute(sql, params).fetchone()[0]

    def test_each_book_is_its_own_row_and_both_sides_are_written(self):
        stafford = self.player("Matthew Stafford", "LAR")
        rows, _ = rw.parse(payload(), "nfl")

        summary = rw.ingest(rows, "nfl")

        self.assertEqual(summary["new"], 4)  # two books x over/under
        written = self.con.execute(
            "SELECT source, line, side, odds FROM props ORDER BY source, side").fetchall()
        self.assertEqual([(r["source"], r["line"], r["side"], r["odds"]) for r in written], [
            ("rotowire:prizepicks", 263.5, "over", -119),
            ("rotowire:prizepicks", 263.5, "under", -125),
            ("rotowire:underdog", 264.5, "over", -137),
            ("rotowire:underdog", 264.5, "under", -137),
        ])
        self.assertEqual(self.scalar("SELECT COUNT(DISTINCT player_id) FROM props"), 1)
        self.assertEqual(self.scalar("SELECT player_id FROM props LIMIT 1"), stafford)
        self.assertEqual(self.scalar("SELECT market FROM props LIMIT 1"), "passing_yards")

    def test_a_second_run_refreshes_rather_than_duplicating(self):
        self.player("Matthew Stafford", "LAR")
        rows, _ = rw.parse(payload(), "nfl")

        rw.ingest(rows, "nfl")
        summary = rw.ingest(rows, "nfl")

        self.assertEqual((summary["new"], summary["refreshed"]), (0, 4))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM props"), 4)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_games"), 1)

    def test_season_futures_are_counted_and_never_ingested(self):
        self.player("Matthew Stafford", "LAR")

        rows, report = rw.parse(payload(market_id=168, market_name="Passing Yards",
                                        category="Season"), "nfl")

        self.assertEqual(rows, [])
        self.assertEqual(report["counts"]["season_props"], 1)
        self.assertEqual(report["counts"]["game_props"], 0)
        self.assertEqual(len(report["unmapped_markets"]), 0)

    def test_an_unmapped_market_is_reported_not_guessed_at(self):
        self.player("Matthew Stafford", "LAR")

        rows, report = rw.parse(payload(market_id=999, market_name="Rushing Attempts"),
                                "nfl")

        self.assertEqual(rows, [])
        self.assertEqual(dict(report["unmapped_markets"]), {(999, "Rushing Attempts"): 1})

    def test_a_market_id_whose_name_moved_refuses(self):
        """13 is Passing Yards. If the relay renames it, it is a different market."""
        self.player("Matthew Stafford", "LAR")

        rows, report = rw.parse(payload(market_id=13, market_name="Pass Attempts"), "nfl")

        self.assertEqual(rows, [])
        self.assertEqual(report["renamed_markets"],
                         {13: ("Passing Yards", "Pass Attempts")})

    def test_the_publisher_team_code_is_mapped_onto_the_espn_vocabulary(self):
        """RotoWire says WAS, ESPN says WSH, and ESPN is canonical here."""
        self.player("Jayden Daniels", "WSH")
        rows, _ = rw.parse(payload(player_name="Jayden Daniels", team="WAS",
                                   home="WAS", away="PHI"), "nfl")

        rw.ingest(rows, "nfl")

        game = self.con.execute("SELECT home, away, date FROM prop_games").fetchone()
        self.assertEqual((game["home"], game["away"]), ("WSH", "PHI"))
        self.assertEqual(game["date"], "2026-09-13")  # the ET day, not the UTC one

    def test_a_dropped_generational_suffix_still_resolves_and_binds(self):
        """The relay says `Chris Godwin`; our spine says `Chris Godwin Jr.`."""
        godwin = self.player("Chris Godwin Jr.", "TB")
        rows, _ = rw.parse(payload(
            player_name="Chris Godwin", team="TB", home="TB", away="ATL",
            link="https://www.rotowire.com/football/player/chris-godwin-11718"), "nfl")

        rw.ingest(rows, "nfl")

        self.assertEqual(self.scalar("SELECT DISTINCT player_id FROM props"), godwin)
        bound = self.con.execute(
            "SELECT source_player_key, player_id FROM player_source_ids").fetchone()
        self.assertEqual((bound["source_player_key"], bound["player_id"]), ("11718", godwin))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM unresolved_players"), 0)

    def test_a_suffix_match_requires_the_team_to_agree(self):
        """Two `Chris Godwin`s and no team agreement is a miss, not a coin flip."""
        self.player("Chris Godwin Jr.", "NYJ")
        rows, _ = rw.parse(payload(player_name="Chris Godwin", team="TB",
                                   home="TB", away="ATL"), "nfl")

        summary = rw.ingest(rows, "nfl")

        self.assertEqual(summary["new"], 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM props"), 0)
        queued = self.con.execute("SELECT raw_name, team, reason FROM unresolved_players").fetchone()
        self.assertEqual((queued["raw_name"], queued["team"], queued["reason"]),
                         ("Chris Godwin", "TB", "not_in_spine"))

    def test_a_duplicate_spine_row_resolves_to_the_active_one(self):
        """Measured 2026-08-19: Mahomes and Davante Adams each have two NFL rows."""
        self.player("Matthew Stafford", "LAR", active=0)
        live = self.player("Matthew Stafford", "LAR", active=1)
        rows, _ = rw.parse(payload(), "nfl")

        rw.ingest(rows, "nfl")

        self.assertEqual(self.scalar("SELECT DISTINCT player_id FROM props"), live)

    def test_two_live_duplicates_refuse_rather_than_pick_one(self):
        self.player("Matthew Stafford", "LAR", active=1)
        self.player("Matthew Stafford", "LAR", active=1)
        rows, _ = rw.parse(payload(), "nfl")

        summary = rw.ingest(rows, "nfl")

        self.assertEqual(summary["new"], 0)
        self.assertEqual(self.scalar("SELECT reason FROM unresolved_players"), "ambiguous")

    def test_a_bound_source_id_wins_over_the_display_name(self):
        """The point of the crosswalk: a renamed player still lands on the same row."""
        stafford = self.player("Matthew Stafford", "LAR")
        rw.ingest(rw.parse(payload(), "nfl")[0], "nfl")
        self.con.execute("UPDATE players SET name='Matt Stafford' WHERE id=?", (stafford,))
        self.con.commit()

        summary = rw.ingest(rw.parse(payload(), "nfl")[0], "nfl")

        self.assertEqual((summary["new"], summary["refreshed"]), (0, 4))
        self.assertEqual(self.scalar("SELECT DISTINCT player_id FROM props"), stafford)

    def test_a_source_id_that_moves_to_another_player_raises(self):
        self.player("Matthew Stafford", "LAR")
        rw.ingest(rw.parse(payload(), "nfl")[0], "nfl")
        other = self.player("Puka Nacua", "LAR")
        now = "2026-08-19T00:00:00+00:00"

        with self.assertRaises(rw.SourceIdentityConflict):
            rw.bind_player_source_key(self.con, "nfl", "5971", other, now)

    def test_an_unknown_team_code_is_skipped_not_invented(self):
        self.player("Matthew Stafford", "LAR")
        rows, _ = rw.parse(payload(team="XXX", home="XXX", away="SF"), "nfl")

        summary = rw.ingest(rows, "nfl")

        self.assertEqual(summary["unknown_team"], 4)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_games"), 0)

    def test_the_soccer_market_in_the_same_payload_is_left_alone(self):
        self.player("Matthew Stafford", "LAR")
        rows, report = rw.parse(payload(), "nfl")
        self.assertEqual(report["counts"]["sport_props"], 1)
        self.assertTrue(all(r["market"] == "passing_yards" for r in rows))

    def test_a_late_kickoff_is_filed_under_the_day_it_is_played(self):
        """A 22:30 ET kickoff is tonight's game, not tomorrow's, in every league.

        The UTC date of that instant is the next day, and filing it there is what puts a
        game the scoreboard calls tonight onto the prop board's tomorrow.
        """
        import datetime as _dt
        late = _dt.datetime.fromtimestamp(1789266600, _dt.timezone.utc)  # 2026-09-13 02:30Z
        self.assertEqual(late.date().isoformat(), "2026-09-13")          # the UTC day
        for league in ("nfl", "mls"):
            self.assertEqual(rw._board_day(league, late), "2026-09-12", league)

    def test_a_dry_run_writes_nothing(self):
        self.player("Matthew Stafford", "LAR")
        rows, _ = rw.parse(payload(), "nfl")

        rw.ingest(rows, "nfl", dry_run=True)

        self.assertEqual(self.scalar("SELECT COUNT(*) FROM props"), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_games"), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM player_source_ids"), 0)


class MlbUsesDurableScoreboardVocabulary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "rw-mlb.db")
        create_schema(self.db_path)
        self.old_db = rw.DB
        rw.DB = self.db_path
        self.con = sqlite3.connect(self.db_path)
        self.con.row_factory = sqlite3.Row
        seed_mlb_scoreboard_vocabulary(self.con)

    def tearDown(self):
        self.con.close()
        rw.DB = self.old_db
        self.tmp.cleanup()

    def player(self, name="Miguel Vargas", team="CHW"):
        player_id = self.con.execute(
            "INSERT INTO players(name,team,league,active) VALUES(?,?,'mlb',1)",
            (name, team),
        ).lastrowid
        self.con.commit()
        return player_id

    def scalar(self, sql, params=()):
        return self.con.execute(sql, params).fetchone()[0]

    def test_batter_and_pitcher_walk_markets_have_distinct_canonical_keys(self):
        batter, _ = rw.parse(mlb_payload(222, "Walks"), "mlb")
        pitcher, _ = rw.parse(mlb_payload(232, "Walks Allowed"), "mlb")

        self.assertEqual({row["market"] for row in batter}, {"batter_walks"})
        self.assertEqual({row["market"] for row in pitcher}, {"walks"})

    def test_fantasy_score_is_reported_and_not_ingested(self):
        self.player()
        rows, report = rw.parse(mlb_payload(236, "Fantasy Score"), "mlb")

        summary = rw.ingest(rows, "mlb")

        self.assertEqual(rows, [])
        self.assertEqual(
            dict(report["unmapped_markets"]), {(236, "Fantasy Score"): 1}
        )
        self.assertEqual(summary["new"], 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM props"), 0)

    def test_code_identity_matches_but_new_game_stores_scoreboard_display_names(self):
        self.player()
        rows, _ = rw.parse(mlb_payload(), "mlb")

        summary = rw.ingest(rows, "mlb")

        self.assertEqual(summary["new"], 2)
        game = self.con.execute("SELECT home,away FROM prop_games").fetchone()
        self.assertEqual((game["home"], game["away"]),
                         ("Chicago White Sox", "New York Mets"))

    def test_consecutive_day_series_does_not_reuse_yesterdays_fixture(self):
        self.player()
        rows, _ = rw.parse(mlb_payload(), "mlb")
        board_date = rows[0]["date"]
        prior_date = (
            dt.date.fromisoformat(board_date) - dt.timedelta(days=1)
        ).isoformat()
        prior_id = self.con.execute(
            "INSERT INTO prop_games(league,date,home,away,espn_event_id,start_time) "
            "VALUES('mlb',?,'Chicago White Sox','New York Mets','old-event','')",
            (prior_date,),
        ).lastrowid
        self.con.commit()

        rw.ingest(rows, "mlb")

        games = self.con.execute(
            "SELECT id,date FROM prop_games ORDER BY date"
        ).fetchall()
        self.assertEqual(len(games), 2)
        self.assertEqual(games[0]["id"], prior_id)
        self.assertEqual(games[1]["date"], board_date)
        self.assertNotEqual(games[1]["id"], prior_id)

    def test_athletics_display_name_has_no_invented_city_prefix(self):
        self.player("Some Athletic", "ATH")
        rows, _ = rw.parse(mlb_payload(
            player_name="Some Athletic", team="ATH", home="ATH", away="NYY"
        ), "mlb")

        rw.ingest(rows, "mlb")

        self.assertEqual(self.scalar("SELECT home FROM prop_games"), "Athletics")

    def test_incomplete_29_club_vocabulary_fails_before_any_fixture_write(self):
        self.con.execute(
            "DELETE FROM scoreboard_snapshots "
            "WHERE json_extract(payload,'$.home.abbrev')='WSH'"
        )
        self.con.commit()
        self.player()

        with self.assertRaises(rw.TeamVocabularyError):
            rw.ingest(rw.parse(mlb_payload(), "mlb")[0], "mlb")

        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_games"), 0)

    def test_unpublished_source_code_is_refused_not_minted(self):
        self.player()
        rows, _ = rw.parse(mlb_payload(team="XXX", home="XXX"), "mlb")

        summary = rw.ingest(rows, "mlb")

        self.assertEqual(summary["unknown_team"], 2)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_games"), 0)


class SoccerIsFiveCompetitionsUnderOneLabel(unittest.TestCase):
    """MLS shares the `Soccer` sport label with La Liga, Ligue 1, Serie A and the EPL.

    So resolving both clubs against MLS's own roster IS the membership test, and the
    club vocabulary is stubbed here rather than fetched: a unit test must not decide
    what it asserts by making a live request.
    """

    VOCABULARY = {
        "atlanta united": "ATL", "atlanta united fc": "ATL",
        "minnesota united": "MIN", "minnesota united fc": "MIN",
        "cf montreal": "MTL", "d c united": "DC",
        "new york red bulls": "RBNY", "red bull new york": "RBNY",
        "los angeles football club": "LAFC", "lafc": "LAFC",
        "vancouver whitecaps": "VAN", "vancouver whitecaps fc": "VAN",
    }
    LCUP_VOCABULARY = rw.TeamVocabulary(
        {
            **VOCABULARY,
            "san diego fc": "SD",
            "guadalajara": "GDL",
            "chivas guadalajara": "GDL",
        },
        memberships={
            "mls": {"ATL", "MIN", "MTL", "DC", "RBNY", "LAFC", "VAN", "SD"},
            "ligamx": {"GDL"},
        },
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "rw-mls.db")
        create_schema(self.db_path)
        self.old_db = rw.DB
        rw.DB = self.db_path
        self.old_vocab = rw.team_vocabulary
        rw.team_vocabulary = lambda con, league: (
            self.LCUP_VOCABULARY if league == "lcup" else dict(self.VOCABULARY)
        )
        self.con = sqlite3.connect(self.db_path)
        self.con.row_factory = sqlite3.Row

    def tearDown(self):
        self.con.close()
        rw.DB = self.old_db
        rw.team_vocabulary = self.old_vocab
        self.tmp.cleanup()

    def player(self, name, team, league="mls"):
        player_id = self.con.execute(
            "INSERT INTO players(name,team,league,active) VALUES(?,?,?,1)",
            (name, team, league)).lastrowid
        self.con.commit()
        return player_id

    def scalar(self, sql, params=()):
        return self.con.execute(sql, params).fetchone()[0]

    def soccer(self, player_name, team, home, away, market_id=152,
               market_name="Shots on Target", link="https://www.rotowire.com/soccer/player/x-99"):
        return {
            "markets": [{"marketID": market_id, "sport": "Soccer", "category": "Game",
                         "marketName": market_name}],
            "entities": [{"entityID": 70, "eventID": 70, "sport": "Soccer",
                          "name": player_name, "team": team, "pos": "F", "link": link}],
            "events": [{"eventID": 70, "gameID": 263106, "eventTime": KICKOFF,
                        "homeTeam": home, "awayTeam": away}],
            "props": [{"propID": "a", "marketID": market_id, "entities": [70],
                       "lines": [{"book": "prizepicks", "over": -120, "under": -110,
                                  "line": 1.5}]}],
        }

    def test_a_non_mls_fixture_under_the_same_label_is_not_ingested(self):
        self.player("Some Forward", "ATL")
        rows, _ = rw.parse(self.soccer("Some Forward", "Atletico Madrid",
                                       "Atletico Madrid", "Malaga"), "mls")

        summary = rw.ingest(rows, "mls")

        self.assertEqual(summary["new"], 0)
        self.assertEqual(summary["unknown_team"], 2)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_games"), 0)

    def test_mls_v_liga_mx_files_under_lcup_while_europe_stays_refused(self):
        """The Soccer bucket may partially succeed, but only on a proven cross fixture."""
        player_id = self.player("Some Forward", "SD")
        cross = self.soccer(
            "Some Forward", "San Diego FC", "San Diego FC", "Guadalajara")
        europe = self.soccer(
            "European Forward", "Chelsea", "Chelsea", "Fulham",
            link="https://www.rotowire.com/soccer/player/europe-100")
        europe["entities"][0]["entityID"] = 71
        europe["entities"][0]["eventID"] = 71
        europe["events"][0]["eventID"] = 71
        europe["events"][0]["gameID"] = 263107
        europe["props"][0]["propID"] = "b"
        europe["props"][0]["entities"] = [71]
        for key in ("entities", "events", "props"):
            cross[key].extend(europe[key])

        rows, _ = rw.parse(cross, "lcup")
        summary = rw.ingest(rows, "lcup")

        self.assertEqual(summary["new"], 2)
        self.assertEqual(summary["unknown_team"], 2)
        game = self.con.execute("SELECT league,home,away FROM prop_games").fetchone()
        self.assertEqual(tuple(game), ("lcup", "San Diego FC", "Guadalajara"))
        self.assertEqual(self.scalar("SELECT DISTINCT player_id FROM props"), player_id)

    def test_both_sides_of_a_leagues_cup_fixture_reach_the_board(self):
        """The Liga MX half is the half that was silently missing.

        `test_mls_v_liga_mx_files_under_lcup_while_europe_stays_refused` proves
        the fixture files correctly and that the MLS-side player resolves. It
        asserts nothing about the other club, and `_roster_league` used to send
        those athletes to `players WHERE league='lcup'`, a table that holds zero
        rows, so they queued as `not_in_spine` while the game still looked
        ingested. A fixture is two teams; a test that checks one of them will
        pass through exactly this defect.
        """
        mls_id = self.player("Some Forward", "SD")
        liga_id = self.player("Otro Delantero", "GDL", league="ligamx")
        cross = self.soccer(
            "Some Forward", "San Diego FC", "San Diego FC", "Guadalajara")
        mexican = self.soccer(
            "Otro Delantero", "Guadalajara", "San Diego FC", "Guadalajara",
            link="https://www.rotowire.com/soccer/player/gdl-101")
        mexican["entities"][0]["entityID"] = 72
        mexican["props"][0]["propID"] = "c"
        mexican["props"][0]["entities"] = [72]
        for key in ("entities", "props"):
            cross[key].extend(mexican[key])

        summary = rw.ingest(rw.parse(cross, "lcup")[0], "lcup")

        self.assertEqual(summary["unresolved_players"], 0)
        self.assertEqual(
            self.scalar("SELECT COUNT(*) FROM unresolved_players"), 0)
        self.assertEqual(
            sorted(r[0] for r in self.con.execute(
                "SELECT DISTINCT player_id FROM props")),
            sorted([mls_id, liga_id]))

    def test_a_liga_mx_player_is_never_resolved_off_the_mls_spine(self):
        """Routing by club must not become "try the other league next".

        The shadow-player defect is a Liga MX name matching an MLS row. Here the
        spine holds the name ONLY under `mls`, so a correct run refuses it.
        """
        self.player("Otro Delantero", "GDL", league="mls")
        payload = self.soccer(
            "Otro Delantero", "Guadalajara", "San Diego FC", "Guadalajara",
            link="https://www.rotowire.com/soccer/player/gdl-102")

        summary = rw.ingest(rw.parse(payload, "lcup")[0], "lcup")

        self.assertEqual(summary["unresolved_players"], 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM props"), 0)
        queued = self.con.execute(
            "SELECT league, reason FROM unresolved_players").fetchone()
        self.assertEqual(tuple(queued), ("lcup", "not_in_spine"))

    def test_mls_v_mls_files_only_under_mls(self):
        self.player("Some Forward", "ATL")
        payload = self.soccer(
            "Some Forward", "Atlanta United", "Atlanta United", "Minnesota United")

        mls_summary = rw.ingest(rw.parse(payload, "mls")[0], "mls")
        lcup_summary = rw.ingest(rw.parse(payload, "lcup")[0], "lcup")

        self.assertEqual(mls_summary["new"], 2)
        self.assertEqual(lcup_summary["new"], 0)
        self.assertEqual(lcup_summary["unknown_team"], 2)
        self.assertEqual(
            self.con.execute("SELECT DISTINCT league FROM prop_games").fetchone()[0],
            "mls",
        )

    def test_lcup_vocabulary_reads_liga_mx_name_from_stored_snapshot(self):
        self.con.execute("DELETE FROM scoreboard_snapshots")
        for code in sorted(rw.CANONICAL_TEAM_CODES["mls"]):
            self.con.execute(
                "INSERT INTO scoreboard_snapshots(league,payload) VALUES('mls',?)",
                (json.dumps({
                    "home": {"abbrev": code, "name": "{} Club".format(code)},
                    "away": {"abbrev": code, "name": "{} Club".format(code)},
                }),),
            )
        self.con.execute(
            "INSERT INTO scoreboard_snapshots(league,payload) VALUES('lcup',?)",
            (json.dumps({
                "home": {"abbrev": "UANL", "name": "Tigres UANL"},
                "away": {"abbrev": "ATL", "name": "ATL Club"},
            }),),
        )
        self.con.execute(
            "INSERT INTO scoreboard_snapshots(league,payload) VALUES('lcup',?)",
            (json.dumps({
                "home": {"abbrev": "ATL", "name": "Atlante"},
                "away": {"abbrev": "ATL", "name": "ATL Club"},
            }),),
        )
        self.con.commit()

        vocabulary = rw._lcup_team_vocabulary(
            self.con, len(rw.CANONICAL_TEAM_CODES["mls"]), 2)

        self.assertEqual(
            rw.resolve_team(vocabulary, "Tigres UANL"), "ligamx:UANL")
        self.assertIn("ligamx:UANL", vocabulary.memberships["ligamx"])
        self.assertEqual(rw.resolve_team(vocabulary, "Atlante"), "ligamx:ATL")
        self.assertEqual(rw.resolve_team(vocabulary, "ATL Club"), "mls:ATL")
        self.assertIsNone(rw.resolve_team(vocabulary, "ATL"))
        self.assertEqual(
            rw.resolve_team(vocabulary, "Los Angeles Football Club"), "mls:LAFC")

    def test_the_same_club_spelled_three_ways_finds_one_game(self):
        """`CF Montreal`, `CF Montréal` and `MTL` are one club, so one fixture."""
        self.player("Some Forward", "ATL")
        existing = self.con.execute(
            "INSERT INTO prop_games(league,date,home,away) "
            "VALUES('mls','2026-09-13','CF Montréal','Atlanta United FC')").lastrowid
        self.con.commit()

        rows, _ = rw.parse(self.soccer("Some Forward", "Atlanta United",
                                       "CF Montreal", "Atlanta United"), "mls")
        rw.ingest(rows, "mls")

        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_games"), 1)
        self.assertEqual(self.scalar("SELECT DISTINCT game_id FROM props"), existing)

    def test_a_matched_row_with_no_kickoff_gets_one_from_the_publisher(self):
        """The board cannot place a game with no start_time, and the relay publishes it."""
        self.player("Some Forward", "RBNY")
        bare = self.con.execute(
            "INSERT INTO prop_games(league,date,home,away,espn_event_id,start_time) "
            "VALUES('mls','2026-09-13','New York Red Bulls','Atlanta United','761739',NULL)"
        ).lastrowid
        self.con.commit()

        rw.ingest(rw.parse(self.soccer("Some Forward", "New York Red Bulls",
                                       "New York Red Bulls", "Atlanta United"), "mls")[0], "mls")

        self.assertEqual(self.scalar("SELECT COUNT(*) FROM prop_games"), 1)
        self.assertEqual(self.scalar("SELECT start_time FROM prop_games WHERE id=?", (bare,)),
                         "2026-09-13T17:00:00Z")

    def test_an_existing_kickoff_is_never_overwritten(self):
        """Filling a hole is safe. Replacing the publisher's own corrected time is not."""
        self.player("Some Forward", "RBNY")
        held = self.con.execute(
            "INSERT INTO prop_games(league,date,home,away,start_time) "
            "VALUES('mls','2026-09-13','New York Red Bulls','Atlanta United',"
            "'2026-09-13T19:45:00+00:00')").lastrowid
        self.con.commit()

        rw.ingest(rw.parse(self.soccer("Some Forward", "New York Red Bulls",
                                       "New York Red Bulls", "Atlanta United"), "mls")[0], "mls")

        self.assertEqual(self.scalar("SELECT start_time FROM prop_games WHERE id=?", (held,)),
                         "2026-09-13T19:45:00+00:00")

    def test_a_club_alias_resolves(self):
        """The relay says `New York Red Bulls`; ESPN says `Red Bull New York`."""
        self.player("Some Forward", "RBNY")
        rows, _ = rw.parse(self.soccer("Some Forward", "New York Red Bulls",
                                       "New York Red Bulls", "Atlanta United"), "mls")

        summary = rw.ingest(rows, "mls")

        self.assertEqual(summary["new"], 2)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM unresolved_players"), 0)

    def test_a_dropped_middle_name_resolves_inside_the_club(self):
        """`Juan Sanabria` on RSL is our `Juan Manuel Sanabria` on RSL."""
        sanabria = self.player("Juan Manuel Sanabria", "RBNY")
        rows, _ = rw.parse(self.soccer("Juan Sanabria", "New York Red Bulls",
                                       "New York Red Bulls", "Atlanta United"), "mls")

        rw.ingest(rows, "mls")

        self.assertEqual(self.scalar("SELECT DISTINCT player_id FROM props"), sanabria)

    def test_a_mononym_resolves_inside_the_club(self):
        """`Luighi` is our `Luighi Hanri`. Common in MLS, and not a surname match."""
        luighi = self.player("Luighi Hanri", "RBNY")
        rows, _ = rw.parse(self.soccer("Luighi", "New York Red Bulls",
                                       "New York Red Bulls", "Atlanta United"), "mls")

        rw.ingest(rows, "mls")

        self.assertEqual(self.scalar("SELECT DISTINCT player_id FROM props"), luighi)

    def test_a_nickname_is_queued_rather_than_guessed(self):
        """`Andrew Thomas` against our `Andy Thomas` is not derivable, so it refuses."""
        self.player("Andy Thomas", "RBNY")
        rows, _ = rw.parse(self.soccer("Andrew Thomas", "New York Red Bulls",
                                       "New York Red Bulls", "Atlanta United"), "mls")

        summary = rw.ingest(rows, "mls")

        self.assertEqual(summary["new"], 0)
        self.assertEqual(self.scalar("SELECT raw_name FROM unresolved_players"),
                         "Andrew Thomas")

    def test_a_fallback_never_reaches_outside_the_club(self):
        """The same dropped-middle-name shape, on another club, must not resolve."""
        self.player("Juan Manuel Sanabria", "ATL")
        rows, _ = rw.parse(self.soccer("Juan Sanabria", "New York Red Bulls",
                                       "New York Red Bulls", "Atlanta United"), "mls")

        summary = rw.ingest(rows, "mls")

        self.assertEqual(summary["new"], 0)
        self.assertEqual(self.scalar("SELECT reason FROM unresolved_players"),
                         "not_in_spine")


class TheSoccerCatalogueIsThePublishersNotOurs(unittest.TestCase):
    """The gap that hid until 2026-08-25: we mapped eight Soccer Game markets while the
    relay published twelve, so Tackles, Passes and Fouls Committed were counted as
    UNMAPPED and discarded on every run. Nothing failed, because no test had ever asked
    the publisher what its catalogue contains.

    These two assertions are deliberately different in kind. The first pins what we claim
    to map, so weakening it shows up in a diff. The second reads the archived payloads --
    real observations, not a fixture we wrote -- and fails when the publisher ships an id
    we do not carry.
    """

    EXPECTED = {
        147: "chances_created",
        148: "fouls_committed",
        151: "goals_allowed",
        152: "shots_on_target",
        154: "saves",
        155: "shots",
        156: "passes",
        157: "clearances",
        158: "tackles",
        159: "crosses",
        161: "passes_attempted",
    }
    # 160 Fantasy Score is a composite of a scoring formula the publisher does not send.
    # It is omitted on purpose and must keep being reported rather than quietly ingested.
    DELIBERATELY_ABSENT = {160}

    def test_the_mapping_is_what_we_say_it_is(self):
        self.assertEqual(
            {mid: key for mid, (_, key) in rw.SOCCER_GAME_MARKETS.items()},
            self.EXPECTED)

    def test_every_market_the_publisher_shipped_is_mapped_or_named_absent(self):
        import glob
        import gzip

        pattern = os.path.join(rw.archive.ARCHIVE_DIR, "rotowire-*.json*")
        payloads = sorted(glob.glob(pattern))
        # A gate with no evidence behind it is a FAIL, not a skip: an empty archive
        # directory would otherwise let this pass while checking nothing at all.
        self.assertTrue(payloads, "no archived payloads under {}".format(pattern))

        published = {}
        for path in payloads:
            opener = gzip.open if path.endswith(".gz") else open
            with opener(path, "rt") as handle:
                payload = json.load(handle)
            for market in payload.get("markets", []):
                if market.get("sport") == "Soccer" and market.get("category") == "Game":
                    published[market["marketID"]] = market.get("marketName")

        unmapped = {mid: name for mid, name in published.items()
                    if mid not in rw.SOCCER_GAME_MARKETS
                    and mid not in self.DELIBERATELY_ABSENT}
        self.assertEqual(unmapped, {},
                         "the relay publishes Soccer markets we would discard")

        # The id is only half the contract. `parse` refuses a market whose name has
        # changed under a known id, so a stale name here would silently take nothing.
        for mid, (expected_name, _) in rw.SOCCER_GAME_MARKETS.items():
            if mid in published:
                self.assertEqual(published[mid], expected_name,
                                 "market {} is published as {!r}".format(
                                     mid, published[mid]))


if __name__ == "__main__":
    unittest.main()
