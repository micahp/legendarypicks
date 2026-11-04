"""Directional NFL team-code normalization tests."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import nfl_team_codes as teams  # noqa: E402


class TeamCodeDirections(unittest.TestCase):
    def test_pbp_codes_are_canonicalized_from_known_source_aliases(self):
        for source, expected in (
            ('LA', 'LAR'), ('LAR', 'LAR'), ('WAS', 'WSH'), ('WSH', 'WSH'),
            ('JAC', 'JAX'), ('JAX', 'JAX'), ('LV', 'LV'), (None, None),
        ):
            with self.subTest(source=source):
                self.assertEqual(teams.to_pbp_team_code(source), expected)

    def test_nflverse_codes_use_the_source_specific_reverse_alias(self):
        for source, expected in (
            ('LAR', 'LA'), ('LA', 'LA'), ('WSH', 'WAS'), ('WAS', 'WAS'),
            ('JAC', 'JAX'), ('JAX', 'JAX'), ('LV', 'LV'), (None, None),
        ):
            with self.subTest(source=source):
                self.assertEqual(teams.to_nflverse_team_code(source), expected)

    def test_legacy_franchise_codes_collapse_only_in_identity_comparisons(self):
        for source, expected in (
            ('OAK', 'LV'), ('LV', 'LV'), ('LA', 'LAR'), ('LAR', 'LAR'),
            ('WAS', 'WSH'), ('WSH', 'WSH'), ('JAC', 'JAX'), ('JAX', 'JAX'),
        ):
            with self.subTest(source=source):
                self.assertEqual(teams.canonical_franchise_team_code(source), expected)

    def test_coverage_checks_normalize_required_and_available_codes(self):
        self.assertEqual(teams.missing_pbp_team_codes(('LA', 'WAS'), ('LAR', 'WSH')), [])
        with self.assertRaisesRegex(ValueError, 'XYZ'):  # an unknown code raises; it is not reported as merely missing
            teams.missing_pbp_team_codes(('LA', 'XYZ'), ('LAR',))
        self.assertEqual(teams.missing_pbp_team_codes(('LA', 'KC'), ('LAR',)), ['KC'])


class StrictTranslation(unittest.TestCase):
    def test_the_two_vocabularies_differ_only_by_the_rams_and_washington(self):
        self.assertEqual(len(teams.DB_CODES), 32)
        self.assertEqual(len(teams.NFLVERSE_CODES), 32)
        self.assertEqual(teams.DB_CODES - teams.NFLVERSE_CODES, {'LAR', 'WSH'})
        self.assertEqual(teams.NFLVERSE_CODES - teams.DB_CODES, {'LA', 'WAS'})

    def test_every_known_spelling_round_trips_through_both_vocabularies(self):
        for code in teams.TO_DB:
            with self.subTest(code=code):
                self.assertIn(teams.to_db(code), teams.DB_CODES)
                self.assertIn(teams.to_nflverse(code), teams.NFLVERSE_CODES)
                self.assertEqual(teams.to_db(teams.to_nflverse(code)), teams.to_db(code))

    def test_relocated_clubs_map_to_the_current_club(self):
        self.assertEqual([teams.to_db(c) for c in ('STL', 'OAK', 'SD', 'la', ' was ')], ['LAR', 'LV', 'LAC', 'LAR', 'WSH'])

    def test_an_unknown_code_or_a_null_raises_instead_of_passing_through(self):
        for bad in ('XYZ', None, '', 'LOS'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                teams.to_db(bad)

    def test_a_column_fails_whole_and_names_every_unknown_code(self):
        with self.assertRaises(ValueError) as caught:
            teams.convert(['LA', 'XYZ', 'XYZ', None], to='db')
        self.assertIn("'XYZ': 2", str(caught.exception))
        self.assertIn('None: 1', str(caught.exception))

    def test_game_ids_carry_nflverse_codes_and_convert_to_either_side(self):
        self.assertEqual(teams.teams_from_game_id('2026_08_LAC_LA'), ('LAC', 'LAR'))
        self.assertEqual(teams.teams_from_game_id('2026_04_IND_WAS', to='nflverse'), ('IND', 'WAS'))
        with self.assertRaises(ValueError):
            teams.teams_from_game_id('2026_08_LAC')

    def test_a_frame_is_converted_in_a_copy(self):
        import pandas as pd
        frame = pd.DataFrame({'team': ['LA', 'WAS', 'KC'], 'opponent': ['WSH', 'LAR', 'LV']})
        out = teams.normalize_frame(frame, ['team', 'opponent'], to='nflverse')
        self.assertEqual(out['team'].tolist(), ['LA', 'WAS', 'KC'])
        self.assertEqual(out['opponent'].tolist(), ['WAS', 'LA', 'LV'])
        self.assertEqual(frame['opponent'].tolist(), ['WSH', 'LAR', 'LV'])


class TeamKeyedTables(unittest.TestCase):
    """The interface every team-keyed table on the simulation path goes through (2026-11-04)."""

    def test_both_spellings_meet_on_one_key(self):
        table = teams.TeamKeyed([('LA', 1), ('WAS', 2), ('KC', 3)])
        self.assertEqual(dict(table), {'LAR': 1, 'WSH': 2, 'KC': 3})
        for code, value in (('LAR', 1), ('LA', 1), ('STL', 1), ('WSH', 2), ('WAS', 2), ('kc', 3)):
            with self.subTest(code=code):
                self.assertIn(code, table)
                self.assertEqual(table[code], value)
                self.assertEqual(table.get(code), value)

    def test_the_team_inside_a_tuple_key(self):
        table = teams.TeamKeyed([(('pid', 'LA', 'g'), 1.0)], team_at=1)
        self.assertEqual(table[('pid', 'LAR', 'g')], 1.0)
        self.assertNotIn(('pid', 'LAR', 'other'), table)  # a real absence is still an absence
        table.setdefault(('pid', 'WAS', 'g'), 2.0)
        self.assertEqual(table.pop(('pid', 'WSH', 'g')), 2.0)

    def test_an_unknown_code_raises_on_every_read_and_write(self):
        table = teams.TeamKeyed([('KC', 1)])
        for operation in (lambda: table['XYZ'], lambda: table.get('XYZ'), lambda: 'XYZ' in table,
                          lambda: table.__setitem__('XYZ', 1), lambda: teams.TeamKeyed([('AAA', 1)])):
            with self.assertRaisesRegex(ValueError, 'unknown NFL team code'):
                operation()

    def test_it_stays_a_dict_for_json_pickle_and_copies(self):
        import copy, json, pickle
        table = teams.TeamKeyed([(('LA', 3), 5)], team_at=0)
        self.assertEqual(json.loads(json.dumps(teams.TeamKeyed([('WAS', 1)]))), {'WSH': 1})
        for clone in (pickle.loads(pickle.dumps(table)), copy.deepcopy(table), table.copy()):
            self.assertEqual(clone[('LAR', 3)], 5)
            self.assertEqual(clone.team_at, 0)


class SimulationTablesUseTheInterface(unittest.TestCase):
    """Every team-keyed table the SLC engine loads is a TeamKeyed, checked on the pinned tables themselves."""

    def test_streak_kicker_field_and_snap_tables(self):
        sys.path.insert(0, str(HERE))
        import kicker_field_goals as kfg
        import participation_field as pf
        import simulate_pregame_batch as batch
        import slc_engine
        import snap_update
        repo = HERE.parents[1]
        streaks, as_published = slc_engine.current_streaks(repo / 'docs/research/slc-week8-2026/wl-streaks-2026-10-29.json')
        # The hashed view keeps the file's spelling, so the v2 random streams of every other game do not move.
        self.assertIn('LA', as_published)
        self.assertNotIn('LAR', as_published)
        self.assertEqual(len(as_published), len(streaks))
        path, sha = batch.SLC_V2_TABLES['playcall_fg_kicker']
        kicker = kfg.KickerTable.load(repo / path, sha)
        path, sha = batch.SLC_V2_TABLES['participation_field']
        field = pf.Field.load(repo / path, sha)
        snaps = snap_update.SnapCounts({'schema': snap_update.SCHEMA, 'season': 2026, 'team_snaps': [['LA', 1, 60.0]],
                                        'player_snaps': [['WAS', 1, 'p', 'WR', 30.0]], 'active': [['LA', 1, ['p']]]}, 't')
        tables = {'current_streak': streaks, 'kicker.assignments': kicker.assignments, 'field.teams': field.teams,
                  'field.team_transitions': field.team_transitions, 'field.team_by_call': field.team_by_call,
                  'field.appearances': field.appearances, 'field.team_plays': field.team_plays,
                  'field.group_tilt': field.group_tilt, 'field.player_weight': field.player_weight,
                  'snaps.team_snaps': snaps.team_snaps, 'snaps.player': snaps.player, 'snaps.active': snaps.active}
        for name, table in tables.items():
            with self.subTest(table=name):
                self.assertIsInstance(table, teams.TeamKeyed)
        for code in ('LAR', 'WSH'):  # the two clubs whose spelling differs; each must be found by the database code
            with self.subTest(code=code):
                self.assertIn(code, streaks)
                self.assertIn(code, field.teams)
                self.assertTrue(kicker.kicker(2026, 1, code))
        self.assertEqual(snaps.weeks_before('LAR', 2), [1])
        self.assertEqual(snaps.player_share('LAR', 2, 'p')[0], 1)


if __name__ == '__main__':
    unittest.main()
