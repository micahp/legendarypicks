import sqlite3
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import qb_decisions as qbd  # noqa: E402
import e1_drive as e1  # noqa: E402


class QbDecisionModel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / 'model.db')
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE players (nfl_gsis_id TEXT, league TEXT, position TEXT)')
        con.executemany('INSERT INTO players VALUES (?,?,?)', [
            ('QA', 'nfl', 'QB'), ('QB', 'nfl', 'QB'), ('QNEW', 'nfl', 'QB'),
            ('RWR', 'nfl', 'WR'), ('RRB', 'nfl', 'RB'), ('RTE', 'nfl', 'TE'),
        ])
        con.execute('''CREATE TABLE nfl_pbp (
            season INT, game_id TEXT, play_id INT, posteam TEXT, passer_player_id TEXT, rusher_player_id TEXT,
            qb_dropback INT, qb_scramble INT, pass_attempt INT, receiver_player_id TEXT,
            down INT, ydstogo INT, yardline_100 INT, week INT, penalty INT, two_point_attempt INT,
            play_type TEXT, rush_attempt INT, qb_kneel INT)''')
        rows = []
        for i in range(20):
            scramble = int(i < 10)
            rows.append((2024, 'g24', i + 1, 'AAA', 'QA', 'QA' if scramble else None, 1, scramble, 0 if scramble else 1,
                         None if scramble else 'RWR', 1, 10, 75, 3))
        for i in range(10):
            rows.append((2024, 'g24b', i + 1, 'AAA', 'QB', None, 1, 0, 1, 'RRB', 1, 10, 75, 3))
        rows.append((2024, 'g24c', 1, 'BBB', 'QA', None, 1, 0, 1, 'RTE', 1, 10, 75, 3))
        rows.append((2025, 'g25', 1, 'AAA', 'QA', None, 1, 0, 1, 'RTE', 1, 10, 75, 3))
        rows.append((2026, 'g26', 1, 'AAA', 'QA', None, 1, 0, 1, 'RTE', 1, 10, 75, 3))
        rows.extend([
            (2024, 'penalty', 1, 'AAA', 'QA', 'QA', 1, 1, 0, None, 1, 10, 75, 3, 1, 0),
            (2024, 'two-point', 1, 'AAA', 'QA', 'QA', 1, 1, 0, None, 1, 10, 75, 3, 0, 1),
        ])
        rows = [row + (0, 0) if len(row) == 14 else row for row in rows]
        con.executemany('''INSERT INTO nfl_pbp
            (season,game_id,play_id,posteam,passer_player_id,rusher_player_id,qb_dropback,qb_scramble,
             pass_attempt,receiver_player_id,down,ydstogo,yardline_100,week,penalty,two_point_attempt)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', rows)
        run_rows = []
        for i in range(10):
            run_rows.append((2024, 'g24', 100 + i, 'AAA', 'QA' if i < 2 else 'RRB', 1, 10, 75,
                             3, 'run', 1, 0, 0, 0, 0, 0))
        for i in range(5):
            run_rows.append((2024, 'g24b', 100 + i, 'AAA', 'QB' if i < 3 else 'RRB', 1, 10, 75,
                             3, 'run', 1, 0, 0, 0, 0, 0))
        run_rows.extend([
            (2025, 'g25', 100, 'AAA', 'QA', 1, 10, 75, 3, 'run', 1, 0, 0, 0, 0, 0),
            (2024, 'g24', 110, 'AAA', 'QA', 1, 10, 75, 3, 'run', 1, 1, 0, 0, 0, 0),
            (2024, 'g24', 111, 'AAA', 'QA', 1, 10, 75, 3, 'qb_kneel', 1, 0, 1, 0, 0, 0),
            (2024, 'g24', 112, 'AAA', 'QA', 1, 10, 75, 3, 'run', 1, 0, 0, 0, 0, 1),
            (2024, 'g24', 113, 'AAA', 'QA', 1, 10, 75, 3, 'run', 1, 0, 0, 0, 1, 0),
        ])
        con.executemany('''INSERT INTO nfl_pbp
            (season,game_id,play_id,posteam,rusher_player_id,down,ydstogo,yardline_100,week,play_type,
             rush_attempt,qb_scramble,qb_kneel,qb_dropback,two_point_attempt,penalty)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', run_rows)
        con.commit()
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_fit_is_chronological_and_keeps_qb_histories_team_specific(self):
        table = qbd.load(self.db, 2025)
        self.assertEqual(table['source_seasons'], [2022, 2023, 2024])
        self.assertNotIn(('g25', 1), table['row_target_roles'])
        cell = qbd.cell_of(1, 10, 75)
        result = qbd.draw(table, 'AAA', 'QA', 1, 10, 75, {'WR', 'RB'}, 'seed-a')
        self.assertEqual(result['target_role_history_n'], 10)
        self.assertEqual(result['scramble_history_n'], 20)
        self.assertEqual(table['source_counts']['primary_qb_run_opportunities'], 15)
        self.assertEqual(table['source_counts']['primary_qb_non_scramble_run_rows'], 5)
        style = qbd.qb_run_role_style(table, 'AAA', 'QA', cell)
        self.assertLess(style['style_odds_ratio'], 1.0)
        manifest = qbd.manifest(table, 'fixture-commit')
        self.assertEqual(manifest['qb_sneak_classification']['status'], 'unavailable')
        self.assertTrue(manifest['qb_sneak_classification']['included_in_qb_run_role_residual'])
        moved = qbd.draw(table, 'BBB', 'QA', 1, 10, 75, {'TE', 'WR'}, 'seed-a')
        self.assertEqual(moved['target_role_history_n'], 1)
        self.assertEqual(table['target_qb_cell'][('AAA', 'QA', cell)]['WR'], 10)

    def test_cutoff_excludes_target_season_and_invalid_penalty_or_try_scrambles(self):
        table = qbd.load(self.db, 2026)
        cell = qbd.cell_of(1, 10, 75)
        self.assertEqual(table['source_seasons'], [2022, 2023, 2024, 2025])
        self.assertNotIn(('g26', 1), table['row_target_roles'])
        self.assertEqual(table['league_cell'][cell]['scramble'], 10)
        self.assertEqual(table['source_counts']['primary_qb_run_opportunities'], 16)
        self.assertEqual(table['qb_run_player_all'][('AAA', 'QA')]['qb'], 3)
        self.assertEqual(table['qb_run_player_all'][('AAA', 'QA')]['other'], 8)

    def test_target_role_draw_uses_qb_history_and_restricts_to_available_roles(self):
        table = qbd.load(self.db, 2025)
        table['scramble_cells'] = set()
        draws = [qbd.draw(table, 'AAA', 'QA', 1, 10, 75, {'WR', 'RB'}, f'seed-{i}')
                 for i in range(300)]
        roles = [result['target_role'] for result in draws if result['action'] == 'pass']
        self.assertGreater(roles.count('WR'), roles.count('RB'))
        self.assertEqual(set(draws[0]['target_role_probabilities']), {'WR', 'RB'})
        self.assertAlmostEqual(sum(draws[0]['target_role_probabilities'].values()), 1.0)
        only_rb = qbd.draw(table, 'AAA', 'QA', 1, 10, 75, {'RB'}, 'one-role')
        self.assertEqual(only_rb['target_role'], 'RB')
        self.assertEqual(only_rb['target_role_probabilities'], {'RB': 1.0})
        with self.assertRaises(ValueError):
            qbd.draw(table, 'AAA', 'QA', 1, 10, 75, set(), 'empty-role-group')

    def test_qb_role_history_is_team_specific_after_a_transfer(self):
        table = qbd.load(self.db, 2025)
        cell = qbd.cell_of(1, 10, 75)
        old_team, old_n = qbd._target_distribution(table, 'AAA', 'QA', cell)
        new_team, new_n = qbd._target_distribution(table, 'BBB', 'QA', cell)

        self.assertEqual((old_n, new_n), (10, 1))
        self.assertGreater(old_team['WR'], new_team['WR'])
        self.assertGreater(new_team['TE'], old_team['TE'])
        self.assertEqual(table['target_qb_cell'][('AAA', 'QA', cell)]['WR'], 10)
        self.assertEqual(table['target_qb_cell'][('BBB', 'QA', cell)]['TE'], 1)

    def test_new_qb_with_no_cell_history_uses_the_team_prior(self):
        table = qbd.load(self.db, 2025)
        cell = qbd.cell_of(1, 10, 75)
        team_prior, _ = qbd._target_distribution(table, 'AAA', None, cell)
        new_qb, support = qbd._target_distribution(table, 'AAA', 'QNEW', cell)

        self.assertEqual(support, 0)
        self.assertEqual(new_qb, team_prior)

    def test_zero_mass_on_available_roles_falls_back_to_a_normalized_roster_draw(self):
        table = qbd.load(self.db, 2025)
        cell = qbd.cell_of(1, 10, 75)
        table['scramble_cells'] = set()
        table['target_qb_cell'][('AAA', 'QNEW', cell)] = Counter({'Other': 5})
        table['target_team_cell'][('AAA', cell)] = Counter({'Other': 5})
        table['target_league_cell'][cell] = Counter({'Other': 5})

        draws = [qbd.draw(table, 'AAA', 'QNEW', 1, 10, 75, {'WR', 'TE'}, f'fallback-{i}')
                 for i in range(80)]
        self.assertTrue(all(draw['target_role_fallback'] == 'no_model_mass_for_available_roles' for draw in draws))
        self.assertTrue(all(set(draw['target_role_probabilities']) == {'WR', 'TE'} for draw in draws))
        self.assertTrue(all(sum(draw['target_role_probabilities'].values()) == 1.0 for draw in draws))
        self.assertEqual({draw['target_role'] for draw in draws}, {'WR', 'TE'})

    def test_new_qb_backs_off_and_unsupported_scrambles_are_disabled(self):
        table = qbd.load(self.db, 2025)
        table['scramble_cells'] = set()
        result = qbd.draw(table, 'AAA', 'QNEW', 1, 10, 75, {'WR', 'RB'}, 'seed')
        self.assertEqual(result['scramble_probability'], 0.0)
        self.assertEqual(result['scramble_fallback'], 'no_eligible_scramble_rows_in_cell')
        self.assertIn(result['target_role'], ('WR', 'RB'))

    def test_scramble_rows_stay_out_of_the_control_pool(self):
        row = {'game_id': 'g', 'play_id': 1, 'qtr': 1, 'down': 1, 'ydstogo': 10, 'yardline_100': 75,
               'game_seconds_remaining': 800, 'play_type': 'run', 'yards_gained': 6, 'penalty': 0,
               'two_point_attempt': 0, 'qb_scramble': 1, 'interception': 0, 'fumble_lost': 0, 'sack': 0,
               'complete_pass': 0}
        nxt = {'game_id': 'g', 'qtr': 1, 'game_seconds_remaining': 790, 'play_type': 'run', 'posteam': 'AAA'}
        self.assertIsNone(e1.classify(row, nxt, Counter()))
        self.assertEqual(e1.classify(row, nxt, Counter(), include_qb_scrambles=True), ('run', 10, None))

    def test_player_specific_qb_run_role_style_adjusts_only_the_qb_role(self):
        table = qbd.load(self.db, 2026)
        cell = qbd.cell_of(1, 10, 75)
        role, style = qbd.adjust_qb_run_role(
            table, 'AAA', 'QA', 1, 10, 75,
            {'RB': 0.45, 'QB': 0.40, 'WR_TE': 0.10, 'Other': 0.05}, 'pocket-qb-run-style')
        self.assertTrue(style['adjusted'])
        self.assertLess(style['adjusted_qb_probability'], style['base_qb_probability'])
        self.assertIn(role, {'RB', 'QB', 'WR_TE', 'Other'})
        self.assertEqual(qbd.cell_of(1, 10, 75), cell)

        role, style = qbd.adjust_qb_run_role(
            table, 'AAA', 'QA', 1, 10, 75,
            {'RB': 1.0, 'QB': 0.0, 'WR_TE': 0.0, 'Other': 0.0}, 'sparse-team-run-role')
        self.assertEqual(style['base_probability_fallback'], 'historical_team_run_rate')
        self.assertGreater(style['adjusted_qb_probability'], 0.0)
        self.assertIn(role, {'RB', 'QB', 'WR_TE', 'Other'})

    def test_new_qb_without_primary_run_history_keeps_the_team_prior(self):
        table = qbd.load(self.db, 2026)
        role, style = qbd.adjust_qb_run_role(
            table, 'AAA', 'QNEW', 1, 10, 75,
            {'RB': 0.45, 'QB': 0.40, 'WR_TE': 0.10, 'Other': 0.05}, 'new-qb-run-style')
        self.assertIsNone(role)
        self.assertIsNone(style)


if __name__ == '__main__':
    unittest.main()
