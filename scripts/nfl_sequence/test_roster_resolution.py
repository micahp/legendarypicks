"""The roster resolver: the spec's automated tests (SLC-NFL-ROSTER-RESOLUTION-V2, section 14) on synthetic evidence."""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roster_resolution as rr  # noqa: E402

AS_OF = '2026-11-17T22:00:00Z'


def row(gsis, name, pos, membership='ACTIVE_ROSTER', depth=None, injury=None, observed='2026-11-16T12:00:00Z'):
    return {'gsis_id': gsis, 'name': name, 'pos': pos, 'membership': membership, 'depth_rank': depth, 'injury': injury,
            'observed_utc': observed}


def event(eid, gsis, kind, effective='2026-11-16T15:00:00Z', observed=None, **extra):
    return dict({'id': eid, 'gsis_id': gsis, 'kind': kind, 'effective_utc': effective,
                 'observed_utc': observed or effective}, **extra)


def qb1():
    return {'role': 'QB1', 'positions': ['QB'], 'required': True}


def pk():
    return {'role': 'PK', 'positions': ['K'], 'required': True, 'kind': 'PK'}


def resolve(roster, roles, events=(), **kw):
    return rr.resolve_team('2026_11_MIA_BUF', 'MIA', kw.pop('as_of', AS_OF), roster, list(events), roles, **kw)


def role_of(result, name):
    return next(r for r in result['roles'] if r['role'] == name)


def player_of(result, gsis):
    return next(p for p in result['players'] if p['gsis_id'] == gsis)


# Miami's known transactions from the spec's table (identities are placeholders in these tests).
MIA_ROSTER = [
    row('WILLIS', 'Malik Willis', 'QB', depth=1),
    row('COOK', 'Brady Cook', 'QB'),
    row('SIELER', 'Zach Sieler', 'DL', depth=1),
    row('BIGGERS', 'Zeek Biggers', 'DL', depth=2),
    row('PHILLIPS', 'Jordan Phillips', 'DL', depth=3),
    row('GONZALEZ', 'Zane Gonzalez', 'K', depth=1),
    row('JEFFERSON', 'Jordan Jefferson', 'DL'),
    row('WATTS', 'Eric Watts', 'DL'),
    row('CARLSON', 'Daniel Carlson', 'K', membership='PRACTICE_SQUAD'),
]
MIA_EVENTS = [
    event('e1', 'WILLIS', 'ir'), event('e2', 'SIELER', 'ir'), event('e3', 'BIGGERS', 'ir'),
    event('e4', 'PHILLIPS', 'ir'), event('e5', 'GONZALEZ', 'release'),
]
DL1 = {'role': 'DL1', 'positions': ['DL'], 'required': True}


class Membership(unittest.TestCase):
    def test_ir_player_on_an_old_depth_chart_is_excluded(self):
        result = resolve([row('WILLIS', 'Malik Willis', 'QB', depth=1), row('COOK', 'Brady Cook', 'QB')],
                         [qb1()], [event('e1', 'WILLIS', 'ir')])
        self.assertEqual('RESERVE', player_of(result, 'WILLIS')['membership'])
        self.assertFalse(player_of(result, 'WILLIS')['official_eligible'])
        self.assertEqual('COOK', role_of(result, 'QB1')['gsis_id'])

    def test_an_active_signing_missing_from_the_depth_chart_enters_the_pool(self):
        result = resolve([row('NEW', 'New Signee', 'QB', membership='PRACTICE_SQUAD')], [qb1()],
                         [event('e1', 'NEW', 'signing_active')])
        self.assertEqual('ACTIVE_ROSTER', player_of(result, 'NEW')['membership'])
        self.assertEqual('NEW', role_of(result, 'QB1')['gsis_id'])

    def test_a_contradictory_transaction_makes_membership_unknown(self):
        result = resolve([row('X', 'X', 'QB')], [qb1()],
                         [event('e1', 'X', 'release'), event('e2', 'X', 'signing_active')])
        self.assertEqual('UNKNOWN', player_of(result, 'X')['membership'])
        self.assertIn('contradictory_membership', result['blocks'])

    def test_a_transaction_from_the_wrong_state_is_a_contradiction(self):
        result = resolve([row('X', 'X', 'DL', membership='ACTIVE_ROSTER')], [DL1], [event('e1', 'X', 'activation')])
        self.assertEqual('UNKNOWN', player_of(result, 'X')['membership'])

    def test_return_to_practice_does_not_activate_a_reserve_player(self):
        result = resolve([row('X', 'X', 'DL', membership='RESERVE', depth=1)], [DL1],
                         [event('e1', 'X', 'return_to_practice')])
        self.assertEqual('RESERVE', player_of(result, 'X')['membership'])
        self.assertFalse(player_of(result, 'X')['official_eligible'])


class PracticeSquadAndKickers(unittest.TestCase):
    def test_a_practice_squad_player_not_elevated_is_outside_the_official_pool(self):
        result = resolve([row('CARLSON', 'Daniel Carlson', 'K', membership='PRACTICE_SQUAD')], [pk()])
        self.assertFalse(player_of(result, 'CARLSON')['official_eligible'])
        self.assertEqual('PROJECTED', role_of(result, 'PK')['status'])

    def test_a_sole_practice_squad_kicker_is_a_provisional_projection(self):
        result = resolve(MIA_ROSTER, [qb1(), pk(), DL1], MIA_EVENTS)
        self.assertEqual('PROJECTED', role_of(result, 'PK')['status'])
        self.assertEqual('CARLSON', role_of(result, 'PK')['gsis_id'])
        self.assertEqual('sole_practice_squad_candidate', role_of(result, 'PK')['basis'])
        self.assertNotIn('unresolved_kicking_role', result['blocks'])

    def test_a_departed_kicker_is_never_used(self):
        result = resolve([row('GONZALEZ', 'Zane Gonzalez', 'K', depth=1)], [pk()],
                         [event('e1', 'GONZALEZ', 'release')])
        self.assertEqual('UNRESOLVED', role_of(result, 'PK')['status'])
        self.assertIn('unresolved_kicking_role', result['blocks'])

    def test_a_projected_kicker_blocks_a_gameday_final_roster(self):
        result = resolve(MIA_ROSTER, [qb1(), pk()], MIA_EVENTS, forecast_class='GAMEDAY_FINAL',
                         inactives_verified=True)
        self.assertIn('gameday_final_unverified_elevation', result['blocks'])

    def test_a_provisional_roster_may_carry_the_projection(self):
        result = resolve(MIA_ROSTER, [qb1(), pk()], MIA_EVENTS, forecast_class='PROVISIONAL')
        self.assertNotIn('gameday_final_unverified_elevation', result['blocks'])


class StarterSelection(unittest.TestCase):
    def test_an_official_inactive_is_removed_whatever_his_depth_rank(self):
        roster = [row('A', 'A', 'QB', depth=1), row('B', 'B', 'QB', depth=2)]
        result = resolve(roster, [qb1()], inactives=['A'])
        self.assertEqual('B', role_of(result, 'QB1')['gsis_id'])
        self.assertEqual('official_inactive', player_of(result, 'A')['exclusion_reason'])

    def test_a_questionable_player_stays_in_with_a_flag(self):
        result = resolve([row('A', 'A', 'QB', depth=1, injury='QUESTIONABLE')], [qb1()])
        self.assertEqual('A', role_of(result, 'QB1')['gsis_id'])
        self.assertIn('game_status_questionable', player_of(result, 'A')['flags'])

    def test_a_backup_fills_an_excluded_starters_role_and_the_promotion_is_recorded(self):
        roster = [row('STARTER', 'Starter', 'QB', depth=1), row('BACKUP', 'Backup', 'QB', depth=2)]
        result = resolve(roster, [qb1()], [event('e1', 'STARTER', 'ir')])
        extra = role_of(result, 'QB1')['extra']
        self.assertEqual('BACKUP', role_of(result, 'QB1')['gsis_id'])
        self.assertTrue(extra['promoted'])
        self.assertEqual(['STARTER'], extra['excluded_ranked_ahead'])

    def test_several_unranked_replacements_are_unresolved_not_chosen(self):
        result = resolve([row('JEFFERSON', 'J', 'DL'), row('WATTS', 'W', 'DL')], [DL1])
        self.assertEqual('UNRESOLVED', role_of(result, 'DL1')['status'])
        self.assertEqual('multiple_unranked_candidates', role_of(result, 'DL1')['basis'])
        self.assertIn('unresolved_DL1', result['blocks'])

    def test_an_announced_starter_is_used_when_eligible_and_blocks_when_not(self):
        roster = [row('JEFFERSON', 'J', 'DL'), row('WATTS', 'W', 'DL', injury='OUT')]
        ok = resolve(roster, [dict(DL1, announced_starter='JEFFERSON')])
        self.assertEqual('JEFFERSON', role_of(ok, 'DL1')['gsis_id'])
        bad = resolve(roster, [dict(DL1, announced_starter='WATTS')])
        self.assertIn('starter_officially_ineligible', bad['blocks'])


class Evidence(unittest.TestCase):
    def test_a_transaction_published_after_the_cutoff_does_not_change_the_snapshot(self):
        roster = [row('COOK', 'Brady Cook', 'QB')]
        before = resolve(roster, [qb1()])
        late = event('late', 'COOK', 'ir', effective='2026-11-18T09:00:00Z')
        after = resolve(roster, [qb1()], [late])
        self.assertEqual(before['content_hash'], after['content_hash'])
        self.assertEqual('ACTIVE_ROSTER', player_of(after, 'COOK')['membership'])

    def test_an_identical_bundle_gives_an_identical_hash_whatever_the_input_order(self):
        events = list(MIA_EVENTS)
        roster = list(MIA_ROSTER)
        first = resolve(roster, [qb1(), pk(), DL1], events)
        random.Random(7).shuffle(roster)
        random.Random(9).shuffle(events)
        second = resolve(roster, [DL1, pk(), qb1()], events)
        self.assertEqual(first['content_hash'], second['content_hash'])

    def test_a_resolvable_provisional_roster_has_no_blocks(self):
        roster = [row('COOK', 'Brady Cook', 'QB'), row('CARLSON', 'D', 'K', membership='PRACTICE_SQUAD')]
        result = resolve(roster, [qb1(), pk()])
        self.assertEqual([], result['blocks'])

    def test_a_bad_timestamp_is_refused(self):
        with self.assertRaises(ValueError):
            resolve([row('COOK', 'Brady Cook', 'QB')], [qb1()], as_of='2026-11-17 22:00')

    def test_an_unknown_event_kind_is_refused(self):
        with self.assertRaises(ValueError):
            resolve([row('COOK', 'Brady Cook', 'QB')], [qb1()], [event('e1', 'COOK', 'teleport')])


class MiamiBuffalo(unittest.TestCase):
    def test_miami_provisional_resolution_from_the_spec_table(self):
        result = resolve(MIA_ROSTER, [qb1(), pk(), DL1], MIA_EVENTS)
        self.assertEqual('COOK', role_of(result, 'QB1')['gsis_id'])
        self.assertEqual('unique_candidate', role_of(result, 'QB1')['basis'])
        self.assertEqual('CARLSON', role_of(result, 'PK')['gsis_id'])
        self.assertEqual(['unresolved_DL1'], result['blocks'])
        self.assertEqual({'WILLIS', 'SIELER', 'BIGGERS', 'PHILLIPS', 'GONZALEZ', 'CARLSON'},
                         {p['gsis_id'] for p in result['players'] if not p['official_eligible']})

    def test_check_matchup_refuses_a_player_active_for_both_teams(self):
        mia = resolve([row('X', 'X', 'QB')], [qb1()])
        buf = rr.resolve_team('2026_11_MIA_BUF', 'BUF', AS_OF, [row('X', 'X', 'QB')], [], [qb1()])
        self.assertEqual(['double_membership'], rr.check_matchup([mia, buf]))


class RegressionFromReview(unittest.TestCase):
    """Each test here failed on the first slice, before the review fixes."""

    def test_a_signing_for_a_player_not_on_the_roster_adds_him(self):
        result = resolve([], [qb1()], [event('e1', 'NEW', 'signing_active', name='New Signee', pos='QB')])
        self.assertEqual('ACTIVE_ROSTER', player_of(result, 'NEW')['membership'])
        self.assertEqual('NEW', role_of(result, 'QB1')['gsis_id'])

    def test_a_transaction_for_an_unknown_player_without_identity_blocks_the_roster(self):
        result = resolve([], [qb1()], [event('e1', 'GHOST', 'signing_active')])
        self.assertIn('transaction_for_unidentified_player', result['blocks'])
        result = resolve([], [qb1()], [event('e2', 'GHOST', 'release')])
        self.assertIn('transaction_for_unidentified_player', result['blocks'])

    def test_a_projected_kicker_is_marked_as_a_projected_participant(self):
        result = resolve(MIA_ROSTER, [qb1(), pk(), DL1], MIA_EVENTS)
        carlson = player_of(result, 'CARLSON')
        self.assertFalse(carlson['official_eligible'])
        self.assertTrue(carlson['projected_participant'])
        self.assertEqual('PROJECTED_ELEVATION', carlson['projection_status'])

    def test_roles_in_one_group_never_fill_two_slots_with_the_same_player(self):
        roster = [row('A', 'A', 'WR', depth=1), row('B', 'B', 'WR', depth=2)]
        roles = [{'role': 'WR1', 'positions': ['WR'], 'required': True, 'group': 'WR'},
                 {'role': 'WR2', 'positions': ['WR'], 'required': True, 'group': 'WR'},
                 {'role': 'WR3', 'positions': ['WR'], 'required': True, 'group': 'WR'}]
        result = resolve(roster, roles)
        self.assertEqual(['A', 'B'], sorted(r['gsis_id'] for r in result['roles'] if r['gsis_id']))
        self.assertEqual('UNRESOLVED', role_of(result, 'WR3')['status'])
        self.assertIn('unresolved_WR3', result['blocks'])

    def test_a_roster_row_observed_after_the_cutoff_is_refused(self):
        with self.assertRaises(ValueError):
            resolve([row('COOK', 'Brady Cook', 'QB', observed='2026-11-18T09:00:00Z')], [qb1()])

    def test_a_roster_row_without_an_observed_time_is_refused(self):
        bare = {'gsis_id': 'COOK', 'name': 'Brady Cook', 'pos': 'QB', 'membership': 'ACTIVE_ROSTER',
                'depth_rank': None, 'injury': None}
        with self.assertRaises(ValueError):
            resolve([bare], [qb1()])


class MultiPosition(unittest.TestCase):
    def test_a_player_in_two_depth_rows_can_fill_both_roles_in_different_groups(self):
        roster = [dict(row('WRKR', 'Two Way', 'WR', depth=1), positions=[('WR', 1), ('KR', 1)])]
        roles = [{'role': 'WR1', 'positions': ['WR'], 'required': True, 'group': 'WR'},
                 {'role': 'KR', 'positions': ['KR'], 'required': True}]
        result = resolve(roster, roles)
        self.assertEqual('WRKR', role_of(result, 'WR1')['gsis_id'])
        self.assertEqual('WRKR', role_of(result, 'KR')['gsis_id'])
        self.assertEqual([], result['blocks'])


class ExtraFlags(unittest.TestCase):
    def test_a_source_flag_on_a_row_reaches_the_player_record_without_changing_eligibility(self):
        roster = [dict(row('B', 'B', 'DB', depth=1), extra_flags=['week10_ruled_out_no_week11_report'])]
        result = resolve(roster, [{'role': 'DB1', 'positions': ['DB'], 'required': True}])
        record = player_of(result, 'B')
        self.assertIn('week10_ruled_out_no_week11_report', record['flags'])
        self.assertTrue(record['official_eligible'])


if __name__ == '__main__':
    unittest.main()
