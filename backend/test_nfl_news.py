#!/usr/bin/env python3

import os
import sqlite3
from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from unittest import mock


_IMPORT_DB = tempfile.NamedTemporaryFile(prefix="nfl-news-import-", suffix=".db", delete=False)
_IMPORT_DB.close()
os.environ["LP_DB_PATH"] = _IMPORT_DB.name

import ingest_nfl_player_news as ingest
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

    def test_player_page_parser_adds_history_without_exposing_locked_analysis(self):
        html = b"""
        <main><div id="news">
          <div class="news-update has-no-player-name">
            <div class="news-update__headline">Back in San Francisco</div>
            <div class="news-update__timestamp">July 30, 2026</div>
            <div class="news-update__news">Samuel agreed to a one-year deal.</div>
            <div class="news-update__analysis"><b>ANALYSIS</b><br>Useful fantasy context.</div>
          </div>
          <div class="news-update has-no-player-name">
            <div class="news-update__headline">Older update</div>
            <div class="news-update__timestamp">January 4, 2026</div>
            <div class="news-update__news">Caught two passes.</div>
            <div class="news-update__analysis"><b>ANALYSIS</b><br><a href="/subscribe/">Subscribe now</a> for analysis.</div>
          </div>
          <button class="get-more-player-news">More</button>
        </div></main>
        """
        items = nfl_news.parse_player_news_page(html, "13429")

        self.assertEqual(2, len(items))
        self.assertEqual("2026-07-30", items[0]["published"])
        self.assertEqual("Useful fantasy context.", items[0]["analysis"])
        self.assertEqual("", items[1]["analysis"])

    def test_sleeper_crosswalk_keeps_rotowire_native_ids(self):
        players = {
            str(index): {
                "full_name": f"Player {index}",
                "position": "WR",
                "rotowire_id": 10000 + index,
                "espn_id": 20000 + index,
                "gsis_id": f"00-{index:07d}",
            }
            for index in range(1000)
        }
        parsed = nfl_news.parse_sleeper_crosswalk(__import__("json").dumps(players).encode())

        self.assertEqual({"10042"}, parsed["by_espn"]["20042"])
        self.assertEqual({"10042"}, parsed["by_gsis"]["00-0000042"])


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
              id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT, position TEXT,
              espn_id TEXT, nfl_gsis_id TEXT
            );
            """
        )
        con.executemany(
            "INSERT INTO players VALUES(?,?,?,?,?,?,?)",
            [
                (1, "Michael Penix Jr.", "ATL", "nfl", "QB", "4361653", "00-0039910"),
                (2, "Carl Davis", "WSH", "nfl", "DT", "16945", "00-0031131"),
                (3, "Carlton Davis III", "NE", "nfl", "CB", "3122786", "00-0034391"),
                (4, "Marcus Harris", "KC", "nfl", "DT", None, None),
                (5, "Marcus Harris", "TEN", "nfl", "CB", None, None),
                (6, "Deebo Samuel Sr.", "WSH", "nfl", "WR", "3126486", "00-0035719"),
                (7, "Alex Skater", "CHI", "nhl", "C", None, None),
                (8, "Josh Allen", "BUF", "nfl", "QB", "3918298", "00-0034857"),
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

    @staticmethod
    def crosswalk(**espn_to_rotowire):
        return {
            "status": "ready",
            "crosswalk": {
                "by_espn": {key: {str(value)} for key, value in espn_to_rotowire.items()},
                "by_gsis": {},
                "by_name_position": {},
                "mapped_players": 1000,
            },
            "fetched_at": "2026-07-31T12:01:00-05:00",
            "message": None,
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

    def test_sleeper_native_id_crosswalk_survives_a_team_change(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        player = con.execute("SELECT * FROM players WHERE id=6").fetchone()
        result = nfl_news.resolve_rotowire_id(
            con,
            player,
            self.crosswalk(**{"3126486": 13429}),
        )
        con.close()

        self.assertEqual("13429", result["source_player_id"])
        self.assertEqual("sleeper_native_id", result["method"])

    def test_general_player_news_keeps_espn_search_on_the_profile(self):
        payload = {
            "results": [
                {
                    "type": "player",
                    "contents": [{"uid": "s:20~l:28~a:3126486"}],
                },
                {
                    "type": "article",
                    "contents": [
                        {
                            "id": "older",
                            "displayName": "Older Deebo report",
                            "date": "2026-07-30T12:00:00Z",
                            "byline": "Reporter Two",
                            "link": {"web": "https://www.espn.com/nfl/story/_/id/2/older-deebo-samuel-report"},
                            "images": [],
                        },
                        {
                            "id": "newer",
                            "displayName": "Deebo returns to San Francisco",
                            "date": "2026-07-31T12:00:00Z",
                            "byline": "Reporter One",
                            "link": {"web": "https://www.espn.com/nfl/story/_/id/3/deebo-samuel-returns"},
                            "images": [],
                        },
                        {
                            "id": "fantasy",
                            "displayName": "Fantasy spin on Deebo",
                            "date": "2026-08-01T12:00:00Z",
                            "byline": "Fantasy Reporter",
                            "link": {"web": "https://www.espn.com/fantasy/football/story/_/id/1"},
                            "images": [],
                        },
                        {
                            "id": "other-luke",
                            "displayName": "Luke Littler unveils hometown mural",
                            "date": "2026-08-01T11:00:00Z",
                            "byline": "Darts Reporter",
                            "link": {"web": "https://www.espn.com/darts/story/_/id/4/luke-littler-mural"},
                            "images": [],
                        },
                        {
                            "id": "other-nfl",
                            "displayName": "Panthers offseason moves and signings",
                            "date": "2026-08-01T10:00:00Z",
                            "byline": "NFL Reporter",
                            "link": {"web": "https://www.espn.com/nfl/story/_/id/5/panthers-offseason"},
                            "images": [],
                        },
                    ],
                }
            ]
        }
        with mock.patch("espn_client._get", return_value=payload):
            result = players.player_news(6, 10)

        self.assertEqual(
            ["Deebo returns to San Francisco", "Older Deebo report"],
            [article["headline"] for article in result["articles"]],
        )
        self.assertEqual("By Reporter One", result["articles"][0]["description"])

    def test_general_news_survives_same_name_nfl_athletes(self):
        # Josh Allen (BUF QB, espn 3918298) shares a name with other NFL
        # athletes in ESPN search (Josh Hines-Allen a:3915239, Josh Allen
        # a:17102). The athlete is confirmed by espn_id; the extra same-name
        # athletes must not blank the whole News tab.
        payload = {
            "results": [
                {
                    "type": "player",
                    "contents": [
                        {"uid": "s:20~l:28~a:3915239"},
                        {"uid": "s:20~l:28~a:17102"},
                        {"uid": "s:20~l:28~a:3918298"},
                    ],
                },
                {
                    "type": "article",
                    "contents": [
                        {
                            "id": "49470315",
                            "displayName": "Myles Garrett, Josh Allen and more earn spots in Madden 27 99 Club",
                            "date": "2026-07-28T16:12:50.000+00:00",
                            "byline": "ESPN Staff",
                            "link": {"web": "https://www.espn.com/nfl/story/_/id/49470315/madden-27-99-club-myles-garrett-josh-allen-jamarr-chase"},
                            "images": [],
                        },
                        {
                            "id": "49481725",
                            "displayName": "Josh Allen on Bills' alternate uniforms: 'Stop hating on the jerseys'",
                            "date": "2026-07-29T23:02:02.000+00:00",
                            "byline": "Alaina Getzenberg",
                            "link": {"web": "https://www.espn.com/nfl/story/_/id/49481725/josh-allen-bills-alternate-uniforms-stop-hating-jerseys"},
                            "images": [],
                        },
                    ],
                },
            ]
        }
        with mock.patch("espn_client._get", return_value=payload):
            result = players.player_news(8, 10)

        self.assertEqual(
            ["Josh Allen on Bills' alternate uniforms: 'Stop hating on the jerseys'",
             "Myles Garrett, Josh Allen and more earn spots in Madden 27 99 Club"],
            [article["headline"] for article in result["articles"]],
        )

    def test_general_news_requires_confirmed_athlete(self):
        # The espn_id identity gate stays: if ESPN search does not return the
        # profile's own athlete, articles are not assigned to it.
        payload = {
            "results": [
                {
                    "type": "player",
                    "contents": [{"uid": "s:20~l:28~a:9999999"}],
                },
                {
                    "type": "article",
                    "contents": [
                        {
                            "id": "x",
                            "displayName": "Josh Allen signs extension",
                            "date": "2026-07-30T12:00:00Z",
                            "byline": "Reporter",
                            "link": {"web": "https://www.espn.com/nfl/story/_/id/x/josh-allen-signs-extension"},
                            "images": [],
                        }
                    ],
                },
            ]
        }
        with mock.patch("espn_client._get", return_value=payload):
            result = players.player_news(8, 10)

        self.assertEqual([], result["articles"])

    def link(self, player_id, rotowire_key):
        con = sqlite3.connect(self.path)
        con.execute("CREATE TABLE IF NOT EXISTS player_source_ids(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, "
                    "league TEXT, source_player_key TEXT, player_id INTEGER, first_seen TEXT, last_seen TEXT)")
        con.execute("INSERT INTO player_source_ids(source, league, source_player_key, player_id) "
                    "VALUES ('rotowire', 'nfl', ?, ?)", (rotowire_key, player_id))
        con.commit()
        con.close()

    def store_update(self, update_id, player_id, headline="Headline", first_seen="2026-11-03T17:00:00+00:00"):
        self.link(player_id, f"link-{player_id}")
        con = sqlite3.connect(self.path)
        ingest.ensure_schema(con)
        con.execute(
            """INSERT INTO nfl_player_news_updates(update_id, content_sha256, rotowire_player_id, player_id, match,
                 team, first_name, last_name, position, injury_status, injury_type, injury_location, return_date,
                 headline, notes, analysis, link, published_utc, published_raw, first_seen_utc, poll_id)
               VALUES (?, 'sha', '4000', ?, 'crosswalk', 'ATL', 'Michael', 'Penix', 'QB', '', '', '', '', ?,
                 'Notes', 'Analysis', 'https://www.rotowire.com/football/player/x', '2026-11-03T17:00:00+00:00',
                 '2026-11-03T09:00:00-08:00', ?, 1)""",
            (update_id, player_id, headline, first_seen))
        con.commit()
        con.close()

    def store_poll(self, polled_at):
        con = sqlite3.connect(self.path)
        ingest.ensure_schema(con)
        con.execute(
            """INSERT INTO nfl_player_news_polls(polled_at_utc, feed_min_id, feed_max_id, feed_count, new_updates,
                 changed_updates, new_claims, claim_counts, matched, unmatched, boundary_gap_count, internal_gap_count,
                 gap_ids) VALUES (?,1,2,2,0,0,0,'{}',0,0,0,0,'[]')""", (polled_at,))
        con.commit()
        con.close()

    @staticmethod
    def now_iso():
        return datetime.now(timezone.utc).isoformat()

    def test_api_returns_stored_news_and_never_fetches_during_the_request(self):
        self.store_update(20, 1, headline="Penix named starter")
        self.store_poll(self.now_iso())
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("no fetch per request")):
            penix = players.player_fantasy_news(1, 10)

        self.assertEqual("ready", penix["data_status"])
        self.assertEqual([20], [article["id"] for article in penix["articles"]])
        self.assertEqual("Penix named starter", penix["articles"][0]["headline"])
        self.assertEqual("https://www.rotowire.com/football/player/x", penix["articles"][0]["link"])
        self.assertEqual("2026-11-03T09:00:00-08:00", penix["articles"][0]["published"])

    def test_api_reports_no_news_for_a_linked_player_with_nothing_stored(self):
        self.store_update(20, 1)
        self.link(2, "link-2")
        self.store_poll(self.now_iso())
        result = players.player_fantasy_news(2, 10)

        self.assertEqual("no_news", result["data_status"])
        self.assertEqual([], result["articles"])

    def test_api_says_identity_is_missing_rather_than_no_news_for_an_unlinked_player(self):
        self.store_update(20, 1)
        self.store_poll(self.now_iso())
        result = players.player_fantasy_news(2, 10)

        self.assertEqual("unavailable", result["data_status"])
        self.assertIn("not linked", result["message"])
        self.assertNotEqual("no_news", result["data_status"])

    def test_api_matches_on_the_stored_player_id_not_the_team_name(self):
        self.store_update(31, 6, headline="Samuel status")
        self.store_poll(self.now_iso())
        result = players.player_fantasy_news(6, 10)

        self.assertEqual("ready", result["data_status"])
        self.assertEqual([31], [article["id"] for article in result["articles"]])

    def test_api_reports_a_stale_store_and_keeps_the_last_news(self):
        self.store_update(20, 1)
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.store_poll(old)
        result = players.player_fantasy_news(1, 10)

        self.assertEqual("stale", result["data_status"])
        self.assertIn("minutes old", result["message"])
        self.assertEqual([20], [article["id"] for article in result["articles"]])

    def test_api_without_any_ingested_poll_is_unavailable_not_no_news(self):
        self.store_update(20, 1)
        con = sqlite3.connect(self.path)
        ingest.ensure_schema(con)
        con.execute("DELETE FROM nfl_player_news_polls")
        con.commit()
        con.close()
        result = players.player_fantasy_news(1, 10)

        self.assertEqual("unavailable", result["data_status"])
        self.assertIn("not been ingested", result["message"])
        self.assertNotEqual("no_news", result["data_status"])

    def test_api_returns_a_teammate_claim_under_the_teammate_and_keeps_the_article_with_its_player(self):
        self.store_update(30, 1, headline="Injury update")
        self.link(8, "link-8")
        con = sqlite3.connect(self.path)
        con.execute(
            """INSERT INTO nfl_player_news_claims(update_id, content_sha256, claim_index, extractor, subject_player_id,
                 update_player_id, attribution, claim_class, field, span, poll_id)
               VALUES (30, 'sha', 0, 'claims-v1', 8, 1, 'named_in_other_update', 'starter_named', 'notes',
                 'Coach named Josh Allen the starter.', 1)""")
        con.commit()
        con.close()
        self.store_poll(self.now_iso())

        about_teammate = players.player_fantasy_news(8, 10)
        own = players.player_fantasy_news(1, 10)

        self.assertEqual([30], [article["id"] for article in about_teammate["articles"]])
        self.assertTrue(about_teammate["articles"][0]["about_player"])
        self.assertEqual(1, own["articles"][0]["player_id"])
        self.assertEqual(8, own["articles"][0]["claims"][0]["subject_player_id"])

    def test_non_nfl_response_is_explicitly_unsupported(self):
        result = players.player_fantasy_news(7, 10)

        self.assertEqual("unsupported", result["data_status"])
        self.assertEqual([], result["articles"])


if __name__ == "__main__":
    unittest.main()
