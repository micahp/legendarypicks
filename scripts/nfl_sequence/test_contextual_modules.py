"""The contextual modules are interface stubs. Each behavior must fail loudly until its phase implements it."""
import unittest

import contextual_evaluation
import contextual_pool
import game_context
import pregame_context


class ContextualStubs(unittest.TestCase):
    def test_context_schema_is_versioned(self):
        self.assertEqual(pregame_context.CONTEXT_SCHEMA, 'lp-nfl-pregame-context-1')

    def test_unimplemented_behavior_raises(self):
        cases = [
            lambda: pregame_context.build_pregame_context('g', '2026-10-25T00:00:00Z', ()),
            lambda: contextual_pool.eligible_games([], '2026-10-25T00:00:00Z'),
            lambda: contextual_pool.build_context_pool([], None),
            lambda: game_context.advance_game_context(game_context.GameContext(), {}),
            lambda: contextual_evaluation.chronological_split([], '2026-10-25T00:00:00Z'),
            lambda: contextual_evaluation.compare_to_v1([], []),
        ]
        for case in cases:
            with self.assertRaises(NotImplementedError):
                case()

    def test_game_context_defaults(self):
        ctx = game_context.GameContext()
        self.assertEqual((ctx.score_differential, ctx.seconds_remaining), (0, 3600))


if __name__ == '__main__':
    unittest.main()
