"""The resolved-roster converter: it converts a clean roster and refuses every gap it cannot prove."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resolved_roster_adapter as ra  # noqa: E402
import roster_resolution as rr  # noqa: E402

AS_OF = '2026-11-18T09:22:21Z'
TEAM = 'AAA'


def full_team(drop=None):
    """A team with one player per starter role, each at his own position. `drop` removes one player (leaves a gap)."""
    roster, roles = [], []
    for name, (group, pos, rank) in sorted(ra.ROLE_SLOTS.items()):
        gsis = f'G-{name}'
        if name != drop:
            roster.append({'gsis_id': gsis, 'name': f'Player {name}', 'pos': pos, 'depth_rank': 1,
                           'membership': 'ACTIVE_ROSTER', 'injury': None, 'observed_utc': '2026-11-18T00:00:00Z'})
        roles.append({'role': name, 'positions': [pos], 'required': True, 'group': group if group != 'ST' else None,
                      'kind': 'PK' if name == 'PK' else None})
    result = rr.resolve_team('2026_11_TST', TEAM, AS_OF, roster, [], roles)
    return result


def frozen(result, forecast_class='PROVISIONAL'):
    return {'schema': rr.SCHEMA, 'game_id': '2026_11_TST', 'as_of_utc': AS_OF, 'forecast_class': forecast_class,
            'teams': {TEAM: result}}


def ids(result):
    lp = {f"G-{name}": 1000 + i for i, name in enumerate(ra.ROLE_SLOTS)}
    jersey = {f"G-{name}": 10 + i for i, name in enumerate(ra.ROLE_SLOTS)}
    return lp, jersey


class Convert(unittest.TestCase):
    def test_a_clean_team_converts_to_twenty_eight_starter_rows_with_slots(self):
        result = full_team()
        lp, jersey = ids(result)
        out = ra.convert(frozen(result), lp, jersey)
        rows = out[TEAM]['players']
        self.assertEqual(28, len(rows))
        wr2 = next(r for r in rows if r['role'] == 'WR2')
        self.assertEqual(('OFF', 'WR', 2), (wr2['group'], wr2['pos_abb'], wr2['pos_rank']))
        self.assertTrue(all(r['starter'] for r in rows))
        self.assertEqual(result['content_hash'], out[TEAM]['content_hash'])

    def test_a_tampered_frozen_file_is_refused(self):
        result = full_team()
        result['players'][0]['name'] = 'Changed'
        lp, jersey = ids(result)
        with self.assertRaisesRegex(ValueError, 'does not recompute'):
            ra.convert(frozen(result), lp, jersey)

    def test_a_team_with_blocks_is_refused(self):
        result = full_team(drop='PK')
        self.assertTrue(result['blocks'])
        lp, jersey = ids(result)
        with self.assertRaisesRegex(ValueError, 'blocks present'):
            ra.convert(frozen(result), lp, jersey)

    def test_a_missing_lp_id_is_refused(self):
        result = full_team()
        lp, jersey = ids(result)
        del lp['G-QB1']
        with self.assertRaisesRegex(ValueError, 'no LP player id'):
            ra.convert(frozen(result), lp, jersey)

    def test_a_missing_jersey_number_is_refused(self):
        result = full_team()
        lp, jersey = ids(result)
        del jersey['G-WR1']
        with self.assertRaisesRegex(ValueError, 'no jersey number'):
            ra.convert(frozen(result), lp, jersey)

    def test_fewer_than_twenty_eight_starter_roles_is_refused(self):
        result = full_team()
        result['roles'] = result['roles'][:-1]
        result = dict(result)
        body = {k: v for k, v in result.items() if k != 'content_hash'}
        result['content_hash'] = rr._digest(body)
        lp, jersey = ids(result)
        with self.assertRaisesRegex(ValueError, 'starter roles'):
            ra.convert(frozen(result), lp, jersey)

    def test_a_gameday_final_roster_is_not_converted(self):
        result = full_team()
        lp, jersey = ids(result)
        with self.assertRaisesRegex(ValueError, 'GAMEDAY_FINAL'):
            ra.convert(frozen(result, forecast_class='GAMEDAY_FINAL'), lp, jersey)


if __name__ == '__main__':
    unittest.main()
