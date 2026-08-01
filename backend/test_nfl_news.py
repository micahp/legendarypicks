#!/usr/bin/env python3

import os
import sqlite3
import tempfile
import unittest
from unittest import mock


_IMPORT_DB = tempfile.NamedTemporaryFile(prefix="nfl-news-import-", suffix=".db", delete=False)
_IMPORT_DB.close()
os.environ["LP_DB_PATH"] = _IMPORT_DB.name

import nfl_news  # noqa: E402
from routers import players  # noqa: E402


def tearDownModule():
    try:
        os.unlink(_IMPORT_DB.name)
    except FileNotFoundError:
        pass


def update_xml(
    update_id,
    player_id,
    first,
    last,
    team,
    position,
    published,
    headline=None,
    return_date="",
):
    return f"""
    <Update Id="{update_id}">
      <DateTime>{published}</DateTime>
      <Headline>{headline or f'Headline {update_id}'}</Headline>
      <Notes>Notes {update_id}</Notes>
      <Analysis>Analysis {update_id}</Analysis>
      <Injury Status="" Type="" Location="" ReturnDate="{return_date}" />
      <Player Id="{player_id}">
        <FirstName>{first}</FirstName><LastName>{last}</LastName>
        <Position>{position}</Position>
        <Link>https://www.rotowire.com/football/player/{first.lower()}-{last.lower()}-{player_id}</Link>
      </Player>
      <Team Code="{team}" />
    </Update>
    """


def feed_xml(updates):
    return (
        "<News><League>NFL</League><Date>2026-07-31</Date><Updates>"
        + "".join(updates)
        + "</Updates></News>"
    ).encode()


def valid_feed():
    updates = [
        update_xml(
            1000 + i,
            2000 + i,
            f"First{i}",
            f"Last{i}",
            "DET",
            "RB",
            f"2026-07-31T{(i % 20):02d}:00:00-05:00",
        )
        for i in range(20)
    ]
    return feed_xml(updates)


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.body


class NflNewsFeedTests(unittest.TestCase):
    def tearDown(self):
        nfl_news.reset_news_cache()

    def test_parser_validates_and_orders_newest_first(self):
        parsed = nfl_news.parse_news_feed(valid_feed())

        self.assertEqual(20, len(parsed["items"]))
        self.assertEqual(1019, parsed["items"][0]["id"])
        self.assertEqual(1000, parsed["items"][-1]["id"])
        self.assertEqual("2019", parsed["items"][0]["source_player_id"])

    def test_partial_refresh_preserves_last_validated_snapshot(self):
        ready = nfl_news.load_news_feed(
            now=0,
            opener=lambda *_args, **_kwargs: FakeResponse(valid_feed()),
        )
        stale = nfl_news.load_news_feed(
            now=601,
            opener=lambda *_args, **_kwargs: FakeResponse(
                b"<News><League>NFL</League><Date>2026-07-31</Date><Updates/></News>"
            ),
        )

        self.assertEqual("ready", ready["status"])
        self.assertEqual("stale", stale["status"])
        self.assertEqual(ready["items"], stale["items"])

    def test_cold_source_failure_is_explicitly_unavailable(self):
        result = nfl_news.load_news_feed(
            now=0,
            opener=mock.Mock(side_effect=TimeoutError("source timeout")),
        )

        self.assertEqual("unavailable", result["status"])
        self.assertEqual([], result["items"])
        self.assertIn("temporarily unavailable", result["message"])


class NflNewsIdentityAndApiTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(prefix="nfl-news-", suffix=".db", delete=False)
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))

        con = sqlite3.connect(self.path)
        con.executescript(
            """
            CREATE TABLE players(
              id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT, position TEXT
            );
            """
        )
        con.executemany(
            "INSERT INTO players VALUES(?,?,?,?,?)",
            [
                (1, "Michael Penix Jr.", "ATL", "nfl", "QB"),
                (2, "Carl Davis", "WSH", "nfl", "DT"),
                (3, "Carlton Davis III", "NE", "nfl", "CB"),
                (4, "Marcus Harris", "KC", "nfl", "DT"),
                (5, "Marcus Harris", "TEN", "nfl", "CB"),
                (6, "Deebo Samuel Sr.", "WSH", "nfl", "WR"),
                (7, "Alex Skater", "CHI", "nhl", "C"),
            ],
        )
        con.commit()
        con.close()

        def connection():
            db = sqlite3.connect(self.path)
            db.row_factory = sqlite3.Row
            return db

        patcher = mock.patch.object(players, "_db", side_effect=connection)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def item(source_id, first, last, team, position, update_id=1):
        return {
            "id": update_id,
            "source_player_id": str(source_id),
            "first_name": first,
            "last_name": last,
            "team": team,
            "position": position,
            "headline": "Headline",
            "notes": "Notes",
            "analysis": "Analysis",
            "injury_status": "",
            "injury_type": "",
            "injury_location": "",
            "return_date": "2026-08-13",
            "published": "2026-07-31T12:00:00-05:00",
            "link": "https://www.rotowire.com/football/player/example",
        }

    def snapshot(self, items, status="ready"):
        return {
            "status": status,
            "items": items,
            "feed_date": "2026-07-31",
            "fetched_at": "2026-07-31T12:01:00-05:00",
            "message": "Latest fantasy news refresh is delayed." if status == "stale" else None,
        }

    def test_suffix_resolves_with_team_and_position_evidence(self):
        item = self.item(17700, "Michael", "Penix", "ATL", "QB")
        with sqlite3.connect(self.path) as con:
            con.row_factory = sqlite3.Row
            result = nfl_news.resolve_source_player(con, item)

        self.assertEqual(1, result["player_id"])
        self.assertEqual("name_team_position", result["method"])

    def test_prefix_collision_and_same_name_people_do_not_cross_assign(self):
        carlton = self.item(12531, "Carlton", "Davis", "NE", "CB")
        marcus = self.item(18599, "Marcus", "Harris", "TEN", "CB")
        with sqlite3.connect(self.path) as con:
            con.row_factory = sqlite3.Row
            self.assertEqual(3, nfl_news.resolve_source_player(con, carlton)["player_id"])
            self.assertEqual(5, nfl_news.resolve_source_player(con, marcus)["player_id"])

    def test_existing_source_id_crosswalk_wins(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute(
            "CREATE TABLE player_external_ids(player_id INTEGER, source TEXT, source_id TEXT)"
        )
        con.execute("INSERT INTO player_external_ids VALUES(?,?,?)", (6, "rotowire", "13429"))
        con.commit()
        item = self.item(13429, "Deebo", "Samuel", "SF", "WR")

        result = nfl_news.resolve_source_player(con, item)
        con.close()

        self.assertEqual(6, result["player_id"])
        self.assertEqual("source_id", result["method"])

    def test_api_returns_verified_suffix_news_and_rejects_false_prefix(self):
        items = [
            self.item(17700, "Michael", "Penix", "ATL", "QB", update_id=20),
            self.item(12531, "Carlton", "Davis", "NE", "CB", update_id=21),
        ]
        with mock.patch.object(players, "load_news_feed", return_value=self.snapshot(items)):
            penix = players.player_news(1, 10)
            carl = players.player_news(2, 10)

        self.assertEqual("ready", penix["data_status"])
        self.assertEqual([20], [article["id"] for article in penix["articles"]])
        self.assertEqual("no_news", carl["data_status"])
        self.assertEqual([], carl["articles"])

    def test_api_fails_closed_on_identity_disagreement(self):
        item = self.item(13429, "Deebo", "Samuel", "SF", "WR")
        with mock.patch.object(players, "load_news_feed", return_value=self.snapshot([item])):
            result = players.player_news(6, 10)

        self.assertEqual("unavailable", result["data_status"])
        self.assertEqual([], result["articles"])
        self.assertIn("identity", result["message"])

    def test_api_exposes_source_outage_instead_of_no_news(self):
        with mock.patch.object(
            players,
            "load_news_feed",
            return_value={
                "status": "unavailable",
                "items": [],
                "feed_date": None,
                "fetched_at": None,
                "message": "Fantasy news is temporarily unavailable.",
            },
        ):
            result = players.player_news(1, 10)

        self.assertEqual("unavailable", result["data_status"])
        self.assertNotEqual("no_news", result["data_status"])

    def test_non_nfl_response_is_explicitly_unsupported(self):
        result = players.player_news(7, 10)

        self.assertEqual("unsupported", result["data_status"])
        self.assertEqual([], result["articles"])


if __name__ == "__main__":
    unittest.main()
