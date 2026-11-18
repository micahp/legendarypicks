"""The roster resolver: the spec's automated tests (SLC-NFL-ROSTER-RESOLUTION-V2, section 14) on synthetic evidence."""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roster_resolution as rr  # noqa: E402

AS_OF = '2026-11-17T22:00:00Z'


def row(gsis, name, pos, membership='ACTIVE_ROSTER', depth=None, injury=None):
    return {'gsis_id': gsis, 'name': name, 'pos': pos, 'membership': membership, 'depth_rank': depth, 'injury': injury}


def event(eid, gsis, kind, effective='2026-11-16T15:00:00Z', observed=None):
    return {'id': eid, 'gsis_id': gsis, 'kind': kind, 'effective_utc': effective,
            'observed_utc': observed or effective}


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


if __name__ == '__main__':
    unittest.main()
