import random
import sys
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lineup_participation as lp  # noqa: E402


def roster(**counts):
    """roster(QB=2, RB=2, ...) -> {'QB1': 'QB', 'QB2': 'QB', 'RB1': 'RB', ...}; the number is the depth order."""
    return {f'{group}{i}': group for group, n in counts.items() for i in range(1, n + 1)}


FULL = roster(QB=2, RB=3, FB=1, TE=3, WR=6, OL=8)
DEPTH_WEIGHTS = {p: 10.0 / int(p[-1]) for p in FULL}  # the starter is the likeliest to be sent in


def offense(seed=7, team=FULL, **kwargs):
    kwargs.setdefault('entry_weight', DEPTH_WEIGHTS)
    return lp.new_offense(team, seed, **kwargs)


def groups(off):
    return Counter(off.roster[p] for p in off.on_field)


class Package(unittest.TestCase):
    def test_eleven_personnel(self):
        self.assertEqual(lp.package('113'), {'QB': 1, 'BACK': 1, 'TE': 1, 'WR': 3, 'OL': 5})

    def test_six_and_seven_linemen_are_valid(self):
        self.assertEqual(lp.package('112-OL6')['OL'], 6)
        self.assertEqual(lp.package('111-OL7'), {'QB': 1, 'BACK': 1, 'TE': 1, 'WR': 1, 'OL': 7})

    def test_two_qb_package_keeps_the_second_qb(self):
        self.assertEqual(lp.package('112')['QB'], 2)

    def test_refusals_keep_their_reason(self):
        for code, reason in [('SPECIAL:P', 'not an offensive'), ('INVALID:size12', 'not an offensive'),
                             ('UNKNOWN', 'not an offensive'), ('116', 'no QB'), ('104-OL4', '4 linemen'),
                             ('011-OL8', '8 linemen'), ('1x3', 'unreadable')]:
            with self.assertRaisesRegex(lp.InvalidPackage, reason, msg=code):
                lp.package(code)


class SingleSnap(unittest.TestCase):
    def test_ac1_eleven_players_with_offensive_groups_and_one_qb(self):
        off = offense()
        off.advance('113')
        self.assertEqual(len(off.on_field), 11)
        self.assertEqual(len(set(off.on_field)), 11)
        g = groups(off)
        self.assertEqual(g['QB'], 1)
        self.assertEqual(g['OL'], 5)
        self.assertEqual(g['WR'], 3)
        self.assertEqual(g['TE'], 1)
        self.assertEqual(g['RB'] + g['FB'], 1)

    def test_ac2_six_linemen_build(self):
        off = offense()
        off.advance('112-OL6')
        self.assertEqual(groups(off)['OL'], 6)
        self.assertEqual(len(off.on_field), 11)

    def test_ac5_missing_group_raises_and_nothing_is_borrowed(self):
        off = offense(team=roster(QB=1, RB=1, TE=0, WR=4, OL=5))
        with self.assertRaisesRegex(lp.ShortRoster, 'needs 1 TE'):
            off.advance('113')
        self.assertEqual(off.on_field, [])
        self.assertEqual(off.ledger.team_snaps, 0)

    def test_ac5_entrants_come_only_from_the_eligible_roster(self):
        off = offense()
        for code in ['113', '122', '113', '212', '112-OL6', '113'] * 20:
            off.advance(code)
            self.assertTrue(set(off.on_field) <= set(FULL))

    def test_roster_with_a_defensive_group_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'not offensive'):
            lp.new_offense({'X': 'CB'}, 1)

    def test_ac6_carrier_and_target_only_from_the_field(self):
        off = offense()
        usage = {p: 1.0 for p in FULL}  # every rostered player would be a candidate if the field were ignored
        for code in ['113', '122', '212', '113'] * 50:
            off.advance(code)
            on = set(off.on_field)
            self.assertIn(off.carry(usage), on)
            target = off.target(usage)
            self.assertIn(target, on)
            self.assertNotIn(off.roster[target], ('QB', 'OL'))

    def test_ac6_backup_qb_off_the_field_never_carries_or_throws(self):
        off = offense()
        usage = {'QB2': 1000.0, 'QB1': 0.001}
        for _ in range(200):
            off.advance('113')
            self.assertEqual(off.passer(usage), 'QB1')
            self.assertNotEqual(off.carry(usage), 'QB2')
            self.assertEqual(off.scramble(usage), 'QB1')
        self.assertNotIn('QB2', off.ledger.snaps)

    def test_ac7_scramble_is_not_a_designed_carry(self):
        off = offense()
        off.advance('113')
        qb = off.scramble()
        self.assertEqual(off.ledger.scrambles, {qb: 1})
        self.assertEqual(off.ledger.carries, {})
        self.assertEqual(off.ledger.qb_designed_runs, {})
        off.carry({qb: 1e9})
        self.assertEqual(off.ledger.qb_designed_runs, {qb: 1})
        self.assertEqual(off.ledger.scrambles, {qb: 1})


class Drive(unittest.TestCase):
    def test_ac3_same_package_and_no_leave_means_no_change(self):
        off = offense()
        off.advance('113')
        first = list(off.on_field)
        for _ in range(30):
            entered, left = off.advance('113')
            self.assertEqual((entered, left), ([], []))
            self.assertEqual(off.on_field, first)

    def test_ac4_minimal_substitution_between_packages(self):
        off = offense()
        off.advance('113')
        before = set(off.on_field)
        wrs = [p for p in off.on_field if off.roster[p] == 'WR']
        entered, left = off.advance('122')
        self.assertEqual(len(entered), 1)
        self.assertEqual(off.roster[entered[0]], 'TE')
        self.assertEqual(len(left), 1)
        # the WR with the lowest entry weight is the one who comes off
        self.assertEqual(left[0], min(wrs, key=lambda p: (DEPTH_WEIGHTS[p], p)))
        self.assertEqual(before - set(left), set(off.on_field) - set(entered))

    def test_ac4_incumbents_that_fit_stay_through_a_heavy_package(self):
        off = offense()
        off.advance('113')
        qb_ol = {p for p in off.on_field if off.roster[p] in ('QB', 'OL')}
        entered, left = off.advance('112-OL6')
        self.assertTrue(qb_ol <= set(off.on_field))
        # 11 personnel to a six-lineman 12: one WR off, one lineman on, nobody else moves
        self.assertEqual([off.roster[p] for p in entered], ['OL'])
        self.assertEqual([off.roster[p] for p in left], ['WR'])

    def test_voluntary_leave_is_replaced_from_the_bench(self):
        off = offense(leave_hazard=lambda p, g, stint: 1.0 if g in ('RB', 'FB') else 0.0)
        off.advance('113')
        rb_before = [p for p in off.on_field if off.roster[p] in ('RB', 'FB')]
        entered, left = off.advance('113')
        self.assertEqual(left, rb_before)
        self.assertEqual(len(entered), 1)
        self.assertNotEqual(entered, rb_before)

    def test_voluntary_leaver_stays_when_nobody_can_replace_him(self):
        off = offense(team=roster(QB=1, RB=1, TE=1, WR=3, OL=5), leave_hazard=lambda p, g, s: 1.0)
        off.advance('113')
        first = list(off.on_field)
        self.assertEqual(off.advance('113'), ([], []))
        self.assertEqual(off.on_field, first)

    def test_unlisted_bench_player_can_enter_at_the_floor(self):
        team = roster(QB=1, RB=1, TE=1, WR=4, OL=5)
        off = lp.new_offense(team, 3, entry_weight={'WR1': 1.0, 'WR2': 1.0, 'WR3': 1.0},
                             leave_hazard=lambda p, g, s: 0.5 if g == 'WR' else 0.0, floor_weight=0.2)
        for _ in range(300):
            off.advance('113')
        self.assertGreater(off.ledger.snaps.get('WR4', 0), 0)

    def test_ac8_same_seed_same_game(self):
        def play(seed):
            off = offense(seed, leave_hazard=lambda p, g, s: 0.05 * min(s, 6))
            usage = {p: 1.0 + i for i, p in enumerate(sorted(FULL))}
            trace = []
            rng = random.Random(seed)
            for _ in range(150):
                off.advance(rng.choice(['113', '122', '212', '112-OL6', '113', '113']))
                trace.append((tuple(off.on_field), off.carry(usage), off.target(usage)))
            return trace, off.ledger.__dict__
        self.assertEqual(play(11), play(11))
        self.assertNotEqual(play(11)[0], play(12)[0])

    def test_ac9_snap_share_is_snaps_over_team_snaps(self):
        off = offense(leave_hazard=lambda p, g, s: 0.3 if g == 'WR' else 0.0)
        codes = ['113', '122', '113', '212'] * 25
        for code in codes:
            off.advance(code)
        ledger = off.ledger
        self.assertEqual(ledger.team_snaps, len(codes))
        self.assertEqual(sum(ledger.snaps.values()), 11 * len(codes))
        self.assertEqual(ledger.snap_share('OL1'), 1.0)
        for p, n in ledger.snaps.items():
            self.assertAlmostEqual(ledger.snap_share(p), n / len(codes))
        self.assertEqual(ledger.snap_share('nobody'), 0.0)
        self.assertEqual(sum(ledger.entries.values()) - sum(ledger.exits.values()), 11)


if __name__ == '__main__':
    unittest.main()
