import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import game_info_snapshot as gis  # noqa: E402

VENUES = {'shared_venue_teams': {'NYJ': 'NYG', 'LAC': 'LA', 'LAR': 'LA'},
          'capacity_source': 'test', 'fetched_at_utc': '2026-10-27T00:00:00Z',
          'venues': {'GB': {'stadium': 'Lambeau Field', 'city': 'Green Bay', 'state': 'Wisconsin', 'roof': 'Open',
                            'listed_capacity': 81441, 'geo': {'lat': 44.501, 'lon': -88.062}},
                     'NYG': {'stadium': 'MetLife Stadium', 'city': 'East Rutherford', 'state': 'New Jersey',
                             'roof': 'Open', 'listed_capacity': 82500, 'geo': {'lat': 40.8, 'lon': -74.1}},
                     'MIA': {'stadium': 'Hard Rock Stadium', 'city': 'Miami Gardens', 'state': 'Florida',
                             'roof': 'Open', 'listed_capacity': 65326, 'geo': {'lat': 25.96, 'lon': -80.24}}}}
FORECASTS = {'source': 'test', 'fetched_at_utc': '2026-10-27T00:00:00Z',
             'games': {'2026_08_CAR_GB': {'forecast': {'temperature_f': 56, 'short': 'Mostly Clear'}}}}


class GameInfoSnapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.venues = root / 'venues.json'
        self.forecasts = root / 'forecasts.json'
        self.venues.write_text(json.dumps(VENUES))
        self.forecasts.write_text(json.dumps(FORECASTS))
        self.db = root / 'dev.db'
        con = sqlite3.connect(self.db)
        con.execute("create table nfl_schedule (game_id text, season int, week int, game_type text, gameday text, "
                    "gametime text, away_team text, home_team text, stadium text, roof text, referee text, location text)")
        con.execute("insert into nfl_schedule values ('2026_08_CAR_GB', 2026, 8, 'REG', '2026-10-29', '20:15', "
                    "'CAR', 'GB', 'Lambeau Field', 'outdoors', NULL, 'Home')")
        con.execute("insert into nfl_schedule values ('2026_08_NE_MIA', 2026, 8, 'REG', '2026-11-01', '13:00', "
                    "'NE', 'MIA', 'Hard Rock Stadium', 'outdoors', NULL, 'Home')")
        con.commit()
        con.close()
        self.store = str(root / 'store')

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_writes_read_only_snapshot_that_verifies(self):
        result = gis.build(str(self.venues), str(self.forecasts), str(self.db), self.store)
        self.assertEqual(result['games'], 2)
        path = Path(result['path'])
        self.assertEqual(path.stat().st_mode & 0o777, 0o444)
        snapshot = gis.load(str(path))
        self.assertFalse(snapshot['used_by_model'])
        car = snapshot['games']['2026_08_CAR_GB']
        self.assertEqual(car['venue']['listed_capacity'], 81441)
        self.assertEqual(car['kickoff_utc'], '2026-10-30T00:15:00Z')
        self.assertEqual(car['weekday_local'], 'Thursday')
        self.assertEqual(car['forecast']['temperature_f'], 56)
        self.assertIsNone(snapshot['games']['2026_08_NE_MIA']['forecast'])
        self.assertEqual(snapshot['games']['2026_08_NE_MIA']['forecast_note'], 'no forecast fetched')
        self.assertEqual(car['referee']['status'], 'not assigned as of freeze')

    def test_shared_venue_maps_to_the_host_stadium(self):
        result = gis.build(str(self.venues), str(self.forecasts), str(self.db), self.store)
        snapshot = gis.load(result['path'])
        self.assertEqual(snapshot['games']['2026_08_NE_MIA']['venue']['stadium'], 'Hard Rock Stadium')

    def test_tampered_snapshot_is_refused(self):
        result = gis.build(str(self.venues), str(self.forecasts), str(self.db), self.store)
        path = Path(result['path'])
        path.chmod(0o644)
        doc = json.loads(path.read_text())
        doc['games']['2026_08_CAR_GB']['venue']['listed_capacity'] = 1
        path.write_text(json.dumps(doc))
        with self.assertRaisesRegex(ValueError, 'does not match its hash'):
            gis.load(str(path))

    def test_attach_refuses_a_game_not_in_the_snapshot(self):
        result = gis.build(str(self.venues), str(self.forecasts), str(self.db), self.store)
        with self.assertRaisesRegex(ValueError, 'is not in game-information snapshot'):
            gis.attach(result['path'], '2026_08_KC_DEN')

    def test_attach_marks_the_block_as_not_used_by_the_model(self):
        result = gis.build(str(self.venues), str(self.forecasts), str(self.db), self.store)
        block = gis.attach(result['path'], '2026_08_CAR_GB')
        self.assertFalse(block['used_by_model'])
        self.assertEqual(block['snapshot_id'], result['snapshot_id'])
        self.assertEqual(block['game']['venue']['stadium'], 'Lambeau Field')


if __name__ == '__main__':
    unittest.main()
