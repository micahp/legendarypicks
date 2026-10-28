import csv
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e2_reference as er  # noqa: E402
import measure_kick_outcomes as mk  # noqa: E402

PAST = {'season': '2024', 'week': '5'}
FUTURE = {'season': '2025', 'week': '1'}
CUTOFF = (2024, 8)


def write_csv(path, header, rows):
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def manifest_for(path, **fields):
    manifest = {'output': {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}
    manifest.update(fields)
    path.with_suffix(path.suffix + '.manifest.json').write_text(json.dumps(manifest))


SAFETY_HEADER = ['status', 'safety_play_id', 'kick_play_id', 'receiving_snap_play_id', 'receiving_snap_yardline_100',
                 'clock_runoff_seconds', 'game_id', 'game_date', 'kick_type', 'season', 'week']


def safety_row(game_id, season_week, play):
    return {'status': 'usable', 'safety_play_id': str(play), 'kick_play_id': str(play + 1),
            'receiving_snap_play_id': str(play + 2), 'receiving_snap_yardline_100': '25',
            'clock_runoff_seconds': '4', 'game_id': game_id, 'game_date': '2024-10-01', 'kick_type': 'kickoff',
            **season_week}


class SafetyKickRows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'safety.csv'
        write_csv(self.path, SAFETY_HEADER, [safety_row('2024_05_AAA_BBB', PAST, 10),
                                             safety_row('2025_01_AAA_BBB', FUTURE, 20)])
        manifest_for(self.path, record_count=2, usable_count=2)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_future_row_is_dropped_under_a_cutoff_and_kept_without_one(self):
        self.assertEqual({p['game_id'] for p in er.load_safety_kick_pool(self.path, eligible_before=CUTOFF)[0]},
                         {'2024_05_AAA_BBB'})
        self.assertEqual(len(er.load_safety_kick_pool(self.path)[0]), 2)

    def test_a_cutoff_still_refuses_a_checksum_mismatch(self):
        self.path.write_text(self.path.read_text() + '\n')
        with self.assertRaises(ValueError):
            er.load_safety_kick_pool(self.path, eligible_before=CUTOFF)

    def test_the_full_path_still_checks_the_usable_count(self):
        manifest_for(self.path, record_count=2, usable_count=3)
        with self.assertRaises(ValueError):
            er.load_safety_kick_pool(self.path)
        self.assertEqual(len(er.load_safety_kick_pool(self.path, eligible_before=CUTOFF)[0]), 1)


OVERTIME_HEADER = ['status', 'game_id', 'season', 'week', 'outcome', 'duration_seconds', 'points_offense',
                   'points_defense', 'next_offense', 'next_start_yardline_100', 'try_kind', 'try_made', 'turnover_kind',
                   'drive']


def overtime_row(game_id, season_week, drive):
    return {'status': 'usable', 'game_id': game_id, 'outcome': 'period_end', 'duration_seconds': '120',
            'points_offense': '0', 'points_defense': '0', 'next_offense': '', 'next_start_yardline_100': '',
            'try_kind': '', 'try_made': '', 'turnover_kind': 'other', 'drive': str(drive), **season_week}


class OvertimeDriveRows(unittest.TestCase):
    def test_a_future_drive_is_dropped_under_a_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'overtime.csv'
            write_csv(path, OVERTIME_HEADER, [overtime_row('2024_05_AAA_BBB', PAST, 1),
                                              overtime_row('2025_01_AAA_BBB', FUTURE, 2)])
            manifest_for(path, drive_count=2, usable_count=2)
            self.assertEqual([d['game_id'] for d in er.load_overtime_drive_pool(path, eligible_before=CUTOFF)[0]],
                             ['2024_05_AAA_BBB'])
            self.assertEqual(len(er.load_overtime_drive_pool(path)[0]), 2)


EXTRAS_HEADER = ['game_id', 'play_id', 'season', 'week', 'posteam', 'defteam', 'timeout', 'timeout_team', 'out_of_bounds']
PBP_COLUMNS = ('game_id', 'play_id', 'passer_player_id', 'rusher_player_id', 'receiver_player_id', 'posteam', 'defteam',
               'air_yards', 'receiving_yards', 'play_type', 'season', 'week')


class ParticipantRows(unittest.TestCase):
    def test_future_plays_and_extras_are_dropped_under_a_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'pbp.sqlite3'
            con = sqlite3.connect(db)
            con.execute(f"CREATE TABLE nfl_pbp ({', '.join(PBP_COLUMNS)})")
            con.execute("INSERT INTO nfl_pbp VALUES ('2024_05_AAA_BBB', 1, 'P1', 'R1', 'W1', 'AAA', 'BBB', 7, 5, 'pass', 2024, 5)")
            con.execute("INSERT INTO nfl_pbp VALUES ('2025_01_AAA_BBB', 2, 'P2', 'R2', 'W2', 'AAA', 'BBB', 7, 5, 'pass', 2025, 1)")
            con.commit()
            con.close()
            extras = Path(tmp) / 'extras.csv'
            write_csv(extras, EXTRAS_HEADER, [
                {'game_id': '2024_05_AAA_BBB', 'play_id': '1', 'season': '2024', 'week': '5', 'posteam': 'AAA',
                 'defteam': 'BBB', 'timeout': '1', 'timeout_team': 'AAA', 'out_of_bounds': '0'},
                {'game_id': '2025_01_AAA_BBB', 'play_id': '2', 'season': '2025', 'week': '1', 'posteam': 'AAA',
                 'defteam': 'BBB', 'timeout': '1', 'timeout_team': 'AAA', 'out_of_bounds': '0'}])
            cut = er.load_participants(str(db), extras=str(extras), eligible_before=CUTOFF)
            self.assertEqual(set(cut), {('2024_05_AAA_BBB', 1)})
            self.assertEqual(cut[('2024_05_AAA_BBB', 1)]['timeout'], 1)
            self.assertEqual(set(er.load_participants(str(db), extras=str(extras))),
                             {('2024_05_AAA_BBB', 1), ('2025_01_AAA_BBB', 2)})


class BlockedKickRows(unittest.TestCase):
    def test_future_records_are_dropped_and_pinned_rates_are_withheld_under_a_cutoff(self):
        integer_fields = ('play_id', 'season', 'week', 'down', 'ydstogo', 'yardline_100', 'quarter',
                          'clock_seconds_remaining', 'clock_runoff_seconds', 'crossed_line',
                          'recovery_spot_yardline_100', 'return_endpoint_yardline_100', 'return_yards',
                          'recovery_yards_from_los', 'return_endpoint_yards_from_los', 'dead_ball_yards_from_los',
                          'next_snap_yardline_100', 'next_snap_down', 'next_snap_ydstogo', 'touchdown', 'safety',
                          'return_yards_field', 'return_touchdown_field', 'receiving_team_touched_beyond_line')
        header = ['kick_type', 'game_id', 'blocked', 'source_file', 'source_sha256'] + list(integer_fields)

        def row(game_id, season_week, play):
            base = {field: '' for field in header}
            base.update({'kick_type': 'field_goal', 'game_id': game_id, 'play_id': str(play), 'blocked': '1',
                         'source_file': 'x.csv', 'source_sha256': 'abc', **season_week})
            return base

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'blocked.csv'
            write_csv(path, header, [row('2024_05_AAA_BBB', PAST, 1), row('2025_01_AAA_BBB', FUTURE, 2)])
            manifest_for(path, record_count=2, sources={'x.csv': 'abc'}, observed_rates={'k': 1},
                         source_dataset='test', window='test')
            cut = er.load_blocked_kicks(path, eligible_before=CUTOFF)
            self.assertEqual([r['game_id'] for r in cut['records']['field_goal']], ['2024_05_AAA_BBB'])
            self.assertIsNone(cut['rates'])
            full = er.load_blocked_kicks(path)
            self.assertEqual(len(full['records']['field_goal']), 2)
            self.assertEqual(full['rates'], {'k': 1})


if __name__ == '__main__':
    unittest.main()
