import csv
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import playcall_model as pm  # noqa: E402
import playcall_observations as pco  # noqa: E402
import run_coach_playcall_validation as coach  # noqa: E402

SCHEDULE_FIELDS = (
    'game_id', 'season', 'game_type', 'home_team', 'away_team', 'home_coach', 'away_coach',
)
CALLER_FIELDS = ('season', 'team', 'game_id', 'off_play_caller', 'def_play_caller')


def write_csv(path, fields, rows):
    with open(path, 'w', newline='') as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def schedule_row(game_id, season, game_type='REG', home='AAA', away='BBB'):
    return {
        'game_id': game_id, 'season': str(season), 'game_type': game_type,
        'home_team': home, 'away_team': away,
        'home_coach': f'HC {home}', 'away_coach': f'HC {away}',
    }


def caller_row(season, team, game_id, caller):
    return {
        'season': str(season), 'team': team, 'game_id': game_id,
        'off_play_caller': caller, 'def_play_caller': '',
    }


class FixedWindowAndAttribution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.schedule_path = self.root / 'schedule.csv'
        self.caller_path = self.root / 'callers.csv'

    def tearDown(self):
        self.tmp.cleanup()

    def test_schedule_loader_keeps_only_regular_seasons_through_2023(self):
        rows = [
            schedule_row('2010_01_AAA_BBB', 2010),
            schedule_row('2023_01_AAA_BBB', 2023),
            schedule_row('2023_POST_AAA_BBB', 2023, game_type='POST'),
            # Synthetic metadata-only sentinels. These contain no outcomes.
            schedule_row('2024_01_AAA_BBB', 2024),
            schedule_row('2025_01_AAA_BBB', 2025),
        ]
        write_csv(self.schedule_path, SCHEDULE_FIELDS, rows)

        games = coach.load_schedule(self.schedule_path)

        self.assertEqual(set(games), {'2010_01_AAA_BBB', '2023_01_AAA_BBB'})

    def test_published_franchise_aliases_join_without_guessing_callers(self):
        game_id = '2023_01_LA_WAS'
        schedule = {game_id: schedule_row(game_id, 2023, home='LA', away='WAS')}
        write_csv(self.caller_path, CALLER_FIELDS, [
            caller_row(2023, 'LAR', game_id, 'Caller LA'),
            caller_row(2023, 'WSH', game_id, 'Caller Washington'),
        ])

        callers, conflicts, unmapped = coach.load_callers(self.caller_path, schedule)

        self.assertEqual(callers[(game_id, 'LA')], 'Caller LA')
        self.assertEqual(callers[(game_id, 'WAS')], 'Caller Washington')
        self.assertEqual((conflicts, unmapped), (0, 0))

    def test_conflicting_and_missing_caller_labels_remain_unknown(self):
        game_id = '2023_01_LA_WAS'
        schedule = {game_id: schedule_row(game_id, 2023, home='LA', away='WAS')}
        write_csv(self.caller_path, CALLER_FIELDS, [
            caller_row(2023, 'LAR', game_id, 'Caller A'),
            caller_row(2023, 'LA', game_id, 'Caller B'),
        ])

        callers, conflicts, unmapped = coach.load_callers(self.caller_path, schedule)

        self.assertNotIn((game_id, 'LA'), callers)
        self.assertEqual(conflicts, 1)
        self.assertEqual(unmapped, 0)

    def test_ledger_keeps_unknown_callers_blank_and_records_source_provenance(self):
        known_game = '2023_01_LA_WAS'
        unknown_game = '2023_02_MIN_NE'
        schedule_rows = [
            schedule_row(known_game, 2023, home='LA', away='WAS'),
            schedule_row(unknown_game, 2023, home='MIN', away='NE'),
        ]
        caller_rows = [
            caller_row(2023, 'LAR', known_game, 'Caller LA'),
            caller_row(2023, 'WSH', known_game, 'Caller Washington'),
        ]
        write_csv(self.schedule_path, SCHEDULE_FIELDS, schedule_rows)
        write_csv(self.caller_path, CALLER_FIELDS, caller_rows)
        ledger_path = self.root / 'ledger.csv'

        games, callers, summary = coach.build_ledger(
            self.schedule_path, self.caller_path, ledger_path
        )

        self.assertEqual(summary['team_season_rows'], 4)
        self.assertEqual(summary['head_coach_games_known'], 4)
        self.assertEqual(summary['play_caller_games_known'], 2)
        self.assertEqual(callers[(known_game, 'LA')], 'Caller LA')
        self.assertNotIn((unknown_game, 'MIN'), callers)
        with open(ledger_path, newline='') as source:
            rows = {(row['season'], row['team']): row for row in csv.DictReader(source)}
        self.assertEqual(rows[('2023', 'MIN')]['head_coach_names'], 'HC MIN')
        self.assertEqual(rows[('2023', 'MIN')]['off_play_caller_names'], '')
        self.assertEqual(rows[('2023', 'MIN')]['play_caller_source_sha256'], coach.CALLER_SHA256)
        self.assertEqual(rows[('2023', 'MIN')]['play_caller_source_as_of'], coach.CALLER_AS_OF)

    def test_source_hash_check_rejects_changed_fixture(self):
        path = self.root / 'source.csv'
        path.write_text('published fixture\n')
        actual = coach.sha256(path)
        coach.verify_source(path, actual)
        with self.assertRaises(ValueError):
            coach.verify_source(path, '0' * 64)


class HistoricalFrameBoundary(unittest.TestCase):
    def test_loader_requests_only_2010_through_2023(self):
        row = {column: None for column in pco.COLUMNS}
        row.update({
            'game_id': '2023_01_AAA_BBB', 'play_id': 1, 'season': 2023, 'week': 1,
            'posteam': 'AAA', 'defteam': 'BBB', 'home_team': 'AAA', 'away_team': 'BBB',
            'qtr': 1, 'down': 1, 'ydstogo': 10, 'yardline_100': 50,
            'game_seconds_remaining': 3600, 'play_type': 'run', 'pass_attempt': 0,
            'rush_attempt': 1, 'qb_dropback': 0, 'sack': 0, 'qb_scramble': 0,
            'two_point_attempt': 0, 'shotgun': 0, 'no_huddle': 0, 'touchdown': 0,
            'interception': 0, 'fumble_lost': 0,
        })
        games = {'2023_01_AAA_BBB': {
            'season': '2023', 'home_team': 'AAA', 'away_team': 'BBB',
            'home_coach': 'HC AAA', 'away_coach': 'HC BBB',
        }}
        callers = {('2023_01_AAA_BBB', 'AAA'): 'Caller AAA'}

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'synthetic.sqlite3'
            con = sqlite3.connect(db)
            con.execute(f"CREATE TABLE nfl_pbp ({', '.join(pco.COLUMNS)})")
            con.execute(
                f"INSERT INTO nfl_pbp ({', '.join(pco.COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in pco.COLUMNS)})",
                [row[column] for column in pco.COLUMNS],
            )
            con.commit()
            con.close()

            requested = []

            def scores_for_season(season):
                requested.append(season)
                if season == 2023:
                    return {('2023_01_AAA_BBB', 1): {
                        'posteam_score': 0, 'defteam_score': 0,
                        'score_differential': 0, 'goal_to_go': 0,
                    }}
                return {}

            with mock.patch.object(coach, 'historical_score_flags', return_value={}), \
                    mock.patch.object(coach.pco, 'scores_for_season', side_effect=scores_for_season):
                frame, _ = coach.load_historical_frame(db, games, callers)

        self.assertEqual(requested, list(range(2010, 2024)))
        self.assertEqual(frame.a['season'].tolist(), [2023])
        self.assertEqual(frame.a['caller'].tolist(), [0])

    def test_training_and_validation_rows_use_the_frozen_season_split(self):
        arrays = {
            'season': np.asarray([2010, 2022, 2023]),
            'flagged': np.asarray([False, False, False]),
        }
        frame = pm.Frame(arrays, {})

        train = coach.rows_for(frame, range(coach.TRAIN_FIRST, coach.TRAIN_LAST + 1))
        validation = coach.rows_for(frame, (coach.VALIDATION,))

        self.assertEqual(frame.a['season'][train].tolist(), [2010, 2022])
        self.assertEqual(frame.a['season'][validation].tolist(), [2023])


class CallerFeature(unittest.TestCase):
    def test_unseen_or_unknown_callers_receive_no_added_feature(self):
        arrays = {
            'season': np.asarray([2022, 2023, 2023]),
            'team': np.asarray([0, 0, 0]),
            'down': np.asarray([0, 0, 0]),
            'dist': np.asarray([0, 1, 0]),
            'field': np.asarray([0, 0, 0]),
            'score': np.asarray([7, 7, 7]),
            'clock': np.asarray([0, 0, 0]),
            'y': np.asarray([0, 1, 0]),
            'flagged': np.asarray([False, False, False]),
            'game': np.asarray([0, 1, 2]),
            'caller': np.asarray([0, 1, -1]),
        }
        frame = pm.Frame(arrays, {'AAA': 0})
        design = coach.CoachDesign(frame, np.asarray([0]))
        added = design.X[:, design.base_width:]

        self.assertEqual(design.feature_width, 24)
        self.assertEqual(added.getrow(0).nnz, 1)
        self.assertEqual(added.getrow(1).nnz, 0)
        self.assertEqual(added.getrow(2).nnz, 0)


if __name__ == '__main__':
    unittest.main()
