import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e1_drive as e1  # noqa: E402
import e2_reference as er  # noqa: E402
import team_tendency as tt  # noqa: E402


def sample(event, posteam, defteam, season=2024, number=1, down=1):
    row = {'game_id': f'{season}_{number:03d}', 'play_id': number, 'season': season, 'week': 1, 'posteam': posteam,
           'defteam': defteam, 'down': down, 'ydstogo': 10, 'yardline_100': 50}
    return (event, row, 0, None)


def pool_from(specs, season=2024):
    pool, number = {}, 0
    for event, posteam, defteam, count in specs:
        for _ in range(count):
            number += 1
            item = sample(event, posteam, defteam, season=season, number=number)
            pool.setdefault(tt.cell_key(item[1]), []).append(item)
    return pool


SKEWED = [('run', 'AAA', 'CCC', 40), ('pass_complete', 'AAA', 'CCC', 4),
          ('run', 'BBB', 'CCC', 4), ('pass_complete', 'BBB', 'CCC', 40)]
NEUTRAL = [('run', 'AAA', 'CCC', 20), ('pass_complete', 'AAA', 'CCC', 20),
           ('run', 'BBB', 'DDD', 20), ('pass_complete', 'BBB', 'DDD', 20)]


def game_rows(game, season, posteam, defteam, kinds):
    rows = []
    for i, kind in enumerate(kinds):
        row = {column: None for column in e1.COLUMNS}
        row.update({'game_id': f'{season}_{game:02d}', 'play_id': i + 1, 'season': season, 'week': 1,
                    'posteam': posteam, 'defteam': defteam, 'qtr': 1, 'down': 1, 'ydstogo': 10, 'yardline_100': 50,
                    'game_seconds_remaining': 900 - 20 * i, 'play_type': kind, 'yards_gained': 3, 'touchdown': 0,
                    'interception': 0, 'fumble_lost': 0, 'sack': 0, 'complete_pass': 1 if kind == 'pass' else None,
                    'qb_scramble': 0, 'penalty': 0, 'two_point_attempt': 0})
        rows.append(row)
    return rows


class TendencyRatios(unittest.TestCase):
    def test_a_team_that_matches_the_league_has_ratio_one(self):
        pool = pool_from(NEUTRAL)
        built = tt.build_from_pool(pool, 2025)
        cell = tt.cell_key(next(iter(pool.values()))[0][1])
        for side, team in (('offense', 'AAA'), ('defense', 'CCC')):
            for event in ('run', 'pass_complete'):
                self.assertAlmostEqual(built.ratio(side, team, cell, event), 1.0, places=9)

    def test_run_heavy_offense_gets_more_run_weight_than_pass_heavy_offense(self):
        pool = pool_from(SKEWED)
        built = tt.build_from_pool(pool, 2025)
        cell = tt.cell_key(next(iter(pool.values()))[0][1])
        self.assertGreater(built.ratio('offense', 'AAA', cell, 'run'), 1.0)
        self.assertLess(built.ratio('offense', 'BBB', cell, 'run'), 1.0)
        sampler = tt.TendencySampler(built)
        samples = next(iter(pool.values()))
        rng = random.Random(7)
        draws = [sampler.sample(rng, samples, offense=team, defense='CCC')[0]
                 for team in ('AAA', 'BBB') for _ in range(4000)]
        aaa_run = sum(1 for event in draws[:4000] if event == 'run') / 4000
        bbb_run = sum(1 for event in draws[4000:] if event == 'run') / 4000
        self.assertGreater(aaa_run, 0.7)
        self.assertLess(bbb_run, 0.3)

    def test_a_thin_team_cell_is_shrunk_toward_the_league(self):
        specs = NEUTRAL + [('run', 'ZZZ', 'CCC', 1)]
        pool = pool_from(specs)
        built = tt.build_from_pool(pool, 2025)
        cell = tt.cell_key(next(iter(pool.values()))[0][1])
        self.assertGreater(built.ratio('offense', 'ZZZ', cell, 'run'), 0.9)
        self.assertLess(built.ratio('offense', 'ZZZ', cell, 'run'), 1.1)


class CutoffAndHoldout(unittest.TestCase):
    def test_refuses_samples_from_the_target_season(self):
        with self.assertRaises(ValueError):
            tt.build_from_pool(pool_from(NEUTRAL, season=2025), 2025)

    def test_refuses_the_holdout_season_before_reading_any_sample(self):
        with self.assertRaises(ValueError) as caught:
            tt.build_from_pool(pool_from(NEUTRAL, season=2024), 2026)
        self.assertIn('holdout', str(caught.exception))

    def test_rows_path_refuses_a_target_season_row(self):
        rows = game_rows(1, 2025, 'AAA', 'CCC', ['run', 'run', 'pass', 'run', 'run', 'run'])
        with self.assertRaises(ValueError):
            tt.build_from_rows(rows, 2025)

    def test_rows_path_builds_from_prior_season_plays_only(self):
        rows = []
        for game in range(1, 11):
            rows += game_rows(game, 2024, 'AAA', 'CCC', ['run', 'run', 'run', 'pass', 'run', 'run'])
            rows += game_rows(100 + game, 2024, 'BBB', 'CCC', ['pass', 'pass', 'pass', 'run', 'pass', 'pass'])
        built = tt.build_from_rows(rows, 2025)
        self.assertEqual(built.manifest['tendency_seasons'], [2024])
        cell = tt.cell_key(rows[0])
        self.assertGreater(built.ratio('offense', 'AAA', cell, 'run'), 1.0)
        self.assertLess(built.ratio('offense', 'BBB', cell, 'run'), 1.0)


class FailClosed(unittest.TestCase):
    def test_an_unknown_team_is_an_error_not_a_default(self):
        pool = pool_from(NEUTRAL)
        sampler = tt.TendencySampler(tt.build_from_pool(pool, 2025))
        with self.assertRaises(ValueError):
            sampler.sample(random.Random(1), next(iter(pool.values())), offense='QQQ', defense='CCC')

    def test_a_cell_that_mixes_situations_is_an_error(self):
        pool = pool_from(NEUTRAL)
        sampler = tt.TendencySampler(tt.build_from_pool(pool, 2025))
        samples = list(next(iter(pool.values())))
        samples.append(sample('run', 'AAA', 'CCC', number=999, down=2))
        with self.assertRaises(ValueError):
            sampler.sample(random.Random(1), samples, offense='AAA', defense='CCC')

    def test_manifest_records_the_seasons_and_a_hash(self):
        built = tt.build_from_pool(pool_from(NEUTRAL), 2025)
        self.assertEqual(built.manifest['tendency_seasons'], [2024])
        self.assertEqual(built.manifest['teams'], ['AAA', 'BBB'])
        self.assertEqual(len(built.manifest['sha256']), 64)


class SideLabels(unittest.TestCase):
    def test_engine_side_labels_map_to_team_codes(self):
        pool = pool_from(SKEWED)
        built = tt.build_from_pool(pool, 2025)
        cell = next(iter(pool.values()))
        mapped = tt.TendencySampler(built, side_teams={'A': 'AAA', 'B': 'CCC'})
        direct = tt.TendencySampler(built)
        draws_mapped = [mapped.sample(random.Random(s), cell, offense='A', defense='B')[0] for s in range(300)]
        draws_direct = [direct.sample(random.Random(s), cell, offense='AAA', defense='CCC')[0] for s in range(300)]
        self.assertEqual(draws_mapped, draws_direct)

    def test_an_unmapped_side_label_fails_closed(self):
        pool = pool_from(SKEWED)
        sampler = tt.TendencySampler(tt.build_from_pool(pool, 2025), side_teams={'A': 'AAA', 'B': 'BBB'})
        with self.assertRaises(ValueError):
            sampler.sample(random.Random(1), next(iter(pool.values())), offense='C', defense='CCC')


class WiringGuards(unittest.TestCase):
    def test_team_tendency_needs_an_eligible_before_cutoff(self):
        with self.assertRaises(ValueError):
            er.load(team_tendency=True)

    def test_team_tendency_and_contextual_sampling_are_exclusive(self):
        with self.assertRaises(ValueError):
            er.load(team_tendency=True, eligible_before=(2025, 10), contextual_mode='both')


if __name__ == '__main__':
    unittest.main()
