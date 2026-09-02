#!/usr/bin/env python3
"""API contract checks for the MLS source replacement policy."""
import os
import tempfile
import unittest


_TMP = tempfile.TemporaryDirectory()
os.environ["LP_DB_PATH"] = os.path.join(_TMP.name, "props-policy.db")

import _core
from routers import props as props_router


class PropsSourcePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = _core.DB
        _core.DB = os.path.join(self.tmp.name, "props.db")
        _core._init_db()
        with _core._db() as con:
            mls_player = con.execute(
                "INSERT INTO players(name,team,league) VALUES('MLS Player','ATX','mls')"
            ).lastrowid
            nfl_player = con.execute(
                "INSERT INTO players(name,team,league) VALUES('NFL Player','DAL','nfl')"
            ).lastrowid
            mls_game = con.execute(
                "INSERT INTO prop_games(league,date,home,away) VALUES('mls','2026-08-17','Austin FC','FC Dallas')"
            ).lastrowid
            nfl_game = con.execute(
                "INSERT INTO prop_games(league,date,home,away) VALUES('nfl','2026-08-17','Dallas Cowboys','New York Giants')"
            ).lastrowid
            for source in ('bovada', 'rotowire_prizepicks_relay'):
                con.execute(
                    "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at,odds) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (mls_game, mls_player, 'shots', 2.5, 'over', source, '2026-08-16T00:00:00Z', -115),
                )
            con.execute(
                "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at,odds) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (nfl_game, nfl_player, 'receiving_yards', 49.5, 'over', 'bovada', '2026-08-16T00:00:00Z', -110),
            )

    def tearDown(self):
        _core.DB = self.old_db
        self.tmp.cleanup()

    def test_mls_returns_only_replacement_source_with_threshold_contract(self):
        rows = props_router.list_props(player=None, market=None, league='mls', date='2026-08-17', limit=50)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['source'], 'rotowire_prizepicks_relay')
        self.assertEqual(rows[0]['offer_kind'], 'pickem_threshold')
        self.assertEqual(rows[0]['source_label'], 'PrizePicks threshold via RotoWire')

    def test_global_props_does_not_leak_legacy_mls_bovada_rows(self):
        rows = props_router.list_props(player=None, market=None, league=None, date='2026-08-17', limit=50)

        self.assertEqual({(row['league'], row['source']) for row in rows}, {
            ('mls', 'rotowire_prizepicks_relay'), ('nfl', 'bovada'),
        })

    def test_slate_summary_and_detail_share_the_mls_source_policy(self):
        summary = props_router.props_slate(league='mls', date='2026-08-17', game_id=None, summary=True)
        detail = props_router.props_slate(league='mls', date='2026-08-17', game_id=None, summary=False)

        self.assertEqual(summary[0]['prop_count'], 1)
        self.assertEqual(summary[0]['markets'], [{'market': 'shots', 'count': 1}])
        self.assertEqual(detail[0]['prop_count'], 1)
        self.assertEqual(detail[0]['players'][0]['props'][0]['offer_kind'], 'pickem_threshold')

    def test_source_status_is_honest_before_any_capture(self):
        status = props_router.prop_source_status(league='mls')

        self.assertEqual(status['status'], 'never_captured')
        self.assertEqual(status['offer_kind'], 'pickem_threshold')

    def test_source_status_exposes_capture_provenance_and_rejection_reasons(self):
        with _core._db() as con:
            con.execute(
                "INSERT INTO prop_source_captures(source,league,captured_at,status,payload_sha256,payload_path,"
                "source_url,parser_version,source_prop_count,candidate_event_count,eligible_event_count,"
                "rejected_event_count,market_counts_json,rejected_reasons_json,message) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ('rotowire_prizepicks_relay', 'mls', '2026-08-16T12:00:00Z', 'REJECTED', 'abc123',
                 '/captures/abc123.json', 'https://www.rotowire.com/picks/api/lines.php', '1',
                 12, 1, 0, 1, '{"market:shots": 12}', '{"source_id_not_in_spine": 1}',
                 'One MLS fixture was rejected.'),
            )
        status = props_router.prop_source_status(league='mls')

        self.assertEqual(status['status'], 'REJECTED')
        self.assertEqual(status['source_url'], 'https://www.rotowire.com/picks/api/lines.php')
        self.assertEqual(status['parser_version'], '1')
        self.assertEqual(status['rejected_reasons'], {'source_id_not_in_spine': 1})
