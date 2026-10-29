"""The 2024 matched-cohort comparison: one set of games on both sides, one definition of a possession, scrimmage plays, and terminals.

Written before scoring_cohort.py. The rules: a game is in the cohort when at least one of its simulated seeds completed (regulation or
overtime). Blocked seeds are excluded, and the actual side is restricted to the same games. A possession ends with a touchdown, a made
or missed field goal, a punt, a turnover, a turnover on downs or a safety. A clock terminal (halftime, end of regulation, end of
overtime) is not a possession and is counted separately on both sides. Plays per possession count run and pass plays only.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scoring_cohort as sc  # noqa: E402

COMPLETE = ('complete_regulation', 'complete_overtime')


def sim_line(game, seed, status, points, drives):
    return {'game_id': game, 'seed': seed, 'status': status, 'points': points, 'teams': {'A': 'HOM', 'B': 'AWY'},
            'drives': drives}


class Cohort(unittest.TestCase):
    def test_a_game_is_in_the_cohort_when_one_seed_completed_and_blocked_seeds_are_left_out(self):
        lines = [sim_line('g1', 1, 'complete_regulation', {'A': 7, 'B': 3}, []),
                 sim_line('g1', 2, 'blocked', {'A': 0, 'B': 0}, []),
                 sim_line('g2', 1, 'blocked', {'A': 0, 'B': 0}, [])]
        self.assertEqual(sc.cohort_games(lines), {'g1'})
        self.assertEqual([r['seed'] for r in sc.complete_seeds(lines, {'g1'})], [1])

    def test_a_game_with_only_blocked_seeds_is_not_in_the_cohort(self):
        self.assertEqual(sc.cohort_games([sim_line('g9', 1, 'blocked', {'A': 0, 'B': 0}, [])]), set())


class Terminals(unittest.TestCase):
    def test_a_simulated_field_goal_attempt_is_made_only_if_the_drive_scored_three(self):
        self.assertEqual(sc.sim_terminal('field_goal_attempt', 3), 'field_goal')
        self.assertEqual(sc.sim_terminal('field_goal_attempt', 0), 'missed_field_goal')

    def test_clock_terminals_are_not_possessions(self):
        for terminal in ('halftime', 'end_of_regulation', 'end_of_overtime'):
            self.assertEqual(sc.sim_terminal(terminal, 0), 'end_of_period', terminal)

    def test_the_named_possession_terminals_map_to_the_same_names_on_both_sides(self):
        for terminal in ('touchdown', 'punt', 'turnover', 'turnover_on_downs', 'safety'):
            self.assertEqual(sc.sim_terminal(terminal, 0), terminal)


class Plays(unittest.TestCase):
    def test_plays_per_possession_count_only_run_and_pass_events(self):
        drives = [{'offense': 'A', 'terminal': 'punt', 'points': 0, 'plays': 5,
                   'events': ['run', 'pass_complete', 'pass_incomplete', 'punt']},
                  {'offense': 'A', 'terminal': 'touchdown', 'points': 7, 'plays': 2, 'events': ['run', 'touchdown_kick']}]
        self.assertEqual(sc.scrimmage_plays(drives[0]), 3)
        self.assertEqual(sc.scrimmage_plays(drives[1]), 1)


if __name__ == '__main__':
    unittest.main()
