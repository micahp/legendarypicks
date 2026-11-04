"""The participation field hook in pre_event (research flag, off by default).

With the flag off nothing changes and no lineup is recorded. With it on, each side's skill lineup carries from snap to snap,
the runner and receiver are players on the field, the personnel label is the lineup's grouping, and the same seed replays the
same lineups. A team code the table does not use is refused.
"""
import copy
from collections import Counter
import json
import random
import unittest
from pathlib import Path

import participation_field as pf
import pre_event as pe
from test_pre_event import SNAPSHOT as FAKE

ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / 'docs/research/participation-model-2026-11-02/outputs/field_2022_2025.json'
TABLE_SHA256 = 'f5ec825afde037a268c09224a0ff07bf5b6b8405e6101dd7fa55791fa7a28b81'
REAL = json.loads((ROOT / 'docs/research/slc-week8-2026/snapshots/2026_08_KC_DEN.json').read_text())
SNAPSHOT = {**copy.deepcopy(FAKE), 'rosters': REAL['rosters']}  # real DEN and KC rosters, the fake usage reference
FIELD = pf.Field.load(TABLE, TABLE_SHA256)


def states(n, seed=3):
    rng = random.Random(seed)
    return [{'down': rng.choice([1, 2, 3, 4]), 'togo': rng.choice([1, 3, 6, 10, 15]), 'yl': rng.choice([5, 18, 45, 75, 92]),
             'quarter': 1, 'clock': 900, 'score_diff': 0} for _ in range(n)]


def game(seed, field=FIELD, plays=80, side_offense='A'):
    pick = pe.chooser(SNAPSHOT, seed, seed_root='r' * 64, field=field)
    rng = random.Random(seed)
    return [pick(rng.choice(['run', 'dropback']), side_offense, state) for state in states(plays, seed)]


class FlagOff(unittest.TestCase):
    def test_no_lineup_and_the_same_choice(self):
        state = states(1)[0]
        for intent in ('run', 'dropback'):
            plain = pe.choose(SNAPSHOT, 'home', intent, seed=7, index=0, state=state, seed_root='r' * 64)
            off = pe.choose(SNAPSHOT, 'home', intent, seed=7, index=0, state=state, seed_root='r' * 64, field=None)
            self.assertEqual(plain, off)
            self.assertNotIn('lineup', off)


class FlagOn(unittest.TestCase):
    def test_runner_and_receiver_are_on_the_field(self):
        checked = 0
        for chosen in game(11):
            on_field = set(chosen['lineup']['on_field'])
            for role in ('rusher', 'receiver'):
                player = chosen.get(role)
                if player is not None and player['pos_abb'] in pf.SKILL:
                    self.assertIn(player['gsis_id'], on_field)
                    checked += 1
        self.assertGreater(checked, 40)

    def test_lineup_matches_its_grouping_and_is_the_label(self):
        for chosen in game(12):
            lineup = chosen['lineup']
            self.assertEqual(chosen['personnel'], lineup['group'])
            if lineup['status'] == 'ok':
                self.assertEqual(len(lineup['on_field']), 5)

    def test_lineups_persist(self):
        lineups = [tuple(c['lineup']['on_field']) for c in game(13, plays=120)]
        same = sum(a == b for a, b in zip(lineups, lineups[1:]))
        self.assertGreater(same, 0.1 * len(lineups))  # an independent draw each snap would rarely repeat five players

    def test_same_seed_same_game(self):
        self.assertEqual(game(14), game(14))
        self.assertNotEqual([c['lineup'] for c in game(14)], [c['lineup'] for c in game(15)])

    def test_each_side_keeps_its_own_lineup(self):
        pick = pe.chooser(SNAPSHOT, 5, seed_root='r' * 64, field=FIELD)
        home_ids = {p['gsis_id'] for p in SNAPSHOT['rosters']['home']['players']}
        for i, state in enumerate(states(40)):
            chosen = pick('dropback', 'A' if i % 2 else 'B', state)
            expected_home = i % 2 == 1
            self.assertEqual(set(chosen['lineup']['on_field']) <= home_ids, expected_home)

    def test_lineup_is_in_the_decision_record(self):
        chosen = game(16, plays=1)[0]
        self.assertEqual(pe.ids(chosen)['lineup'], chosen['lineup'])

    def test_unknown_team_code_is_refused(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        snapshot['rosters']['home']['team'] = 'DNV'
        pick = pe.chooser(snapshot, 1, seed_root='r' * 64, field=FIELD)
        with self.assertRaisesRegex(ValueError, "unknown NFL team code 'DNV'"):  # refused by nfl_team_codes.TeamKeyed
            pick('run', 'A', states(1)[0])

    def test_a_real_club_the_table_lacks_is_refused(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        snapshot['rosters']['home']['team'] = 'MIA'
        field = copy.deepcopy(FIELD)
        del field.teams['MIA']
        pick = pe.chooser(snapshot, 1, seed_root='r' * 64, field=field)
        with self.assertRaisesRegex(ValueError, "no transitions for team 'MIA'"):
            pick('run', 'A', states(1)[0])


class Summary(unittest.TestCase):
    def test_lineup_summary_counts_team_and_player_snaps(self):
        import slc_engine
        decisions = [{'participants': pe.ids(chosen)} for chosen in game(17, plays=30)]
        decisions.append({'participants': {'participant_share_model': 'position_usage'}})  # a play without a lineup
        summary = slc_engine.lineup_summary(decisions)
        team = SNAPSHOT['rosters']['home']['team']
        self.assertEqual(summary[team]['team_snaps'], 30)
        self.assertEqual(sum(summary[team]['player_snaps'].values()),
                         sum(len(d['participants']['lineup']['on_field']) for d in decisions[:-1]))
        self.assertEqual(sum(summary[team]['groups'].values()), 30)

    def test_no_lineup_no_summary(self):
        import slc_engine
        self.assertIsNone(slc_engine.lineup_summary([{'participants': {}}, {'participants': None}]))


class Cells(unittest.TestCase):
    def test_a_supported_cell_is_kept(self):
        self.assertEqual(FIELD.supported_cell('3|mid|mid'), '3|mid|mid')

    def test_a_missing_cell_borrows_the_nearest_distance_at_the_same_down_and_field(self):
        self.assertEqual(FIELD.supported_cell('1|short|deep'), '1|xl|deep')

    def test_the_borrowed_cell_is_recorded_on_the_play(self):
        state = {'down': 1, 'togo': 2, 'yl': 92, 'quarter': 1, 'clock': 900, 'score_diff': 0}
        chosen = pe.choose(SNAPSHOT, 'home', 'run', seed=1, index=0, state=state, seed_root='r' * 64, field=FIELD,
                           lineup_state={'lineup': {}, 'group': None})
        self.assertEqual(chosen['lineup']['cell_fallback_from'], '1|short|deep')
        self.assertEqual(chosen['lineup']['cell'], FIELD.supported_cell('1|short|deep'))


V3_TABLE = ROOT / 'docs/research/participation-model-2026-11-02/outputs/field_v3_2022_2025.json'
V3_SHA256 = 'a31fc7150c107b3c15b11e2e643ace88828c033f8da3576b51348e4b5a677107'


class LineAndQbGroupings(unittest.TestCase):
    """v3 codes: a sixth lineman or a second QB takes a skill spot, and only a second QB in the grouping can carry."""

    def setUp(self):
        self.field = pf.Field.load(V3_TABLE, V3_SHA256)
        self.roster = [p for p in SNAPSHOT['rosters']['home']['players'] if p['pos_abb'] in pf.SKILL or p['pos_abb'] == 'QB']
        self.starter = pf.starter_qb(self.roster)

    def _advance(self, group):
        lineup, record = self.field.advance('DEN', {}, group, self.roster, random.Random(1), prev_group=None)
        return lineup, record

    def test_a_six_lineman_grouping_puts_four_skill_players_on(self):
        lineup, record = self._advance('12-OL6')
        self.assertEqual(record['status'], 'ok')
        self.assertEqual(len(lineup), 4)

    def test_a_two_qb_grouping_puts_a_backup_qb_on_never_the_starter(self):
        backups = [p['gsis_id'] for p in self.roster if p['pos_abb'] == 'QB' and p['gsis_id'] != self.starter]
        self.assertTrue(backups, 'the fixture roster needs a backup QB')
        lineup, record = self._advance('11-QB2')
        self.assertEqual(record['status'], 'ok')
        self.assertEqual(len(lineup), 5)
        self.assertEqual(len(set(lineup) & set(backups)), 1)
        self.assertNotIn(self.starter, lineup)

    def test_a_backup_qb_carries_only_when_on_the_field(self):
        backups = {p['gsis_id'] for p in self.roster if p['pos_abb'] == 'QB' and p['gsis_id'] != self.starter}
        pick = pe.chooser(SNAPSHOT, 21, seed_root='r' * 64, field=self.field)
        rng = random.Random(21)
        for state in states(150, 21):
            chosen = pick(rng.choice(['run', 'dropback']), 'A', state)
            for role in ('rusher', 'receiver'):
                player = chosen.get(role)
                if player is not None and player['gsis_id'] in backups:
                    self.assertIn(player['gsis_id'], chosen['lineup']['on_field'])
            passer = chosen.get('passer')
            if passer is not None and passer['pos_abb'] == 'QB':
                self.assertEqual(passer['gsis_id'], self.starter)


V4_TABLE = ROOT / 'docs/research/participation-model-2026-11-02/outputs/field_v4_2022_2025.json'
V4_SHA256 = 'b53b2566e3abf3874f738f1c26f3e2975c6f03d65887bad9590c276006c9a4c3'


class GroupingGivenCall(unittest.TestCase):
    def test_heavy_groupings_go_with_runs(self):
        field = pf.Field.load(V4_TABLE, V4_SHA256)
        self.assertTrue(field.conditions_on_call)
        pick = pe.chooser(SNAPSHOT, 31, seed_root='r' * 64, field=field)
        rng = random.Random(31)
        calls = {'heavy': Counter(), 'eleven': Counter()}
        for state in states(600, 31):
            intent = rng.choice(['run', 'dropback'])
            group = pick(intent, 'A', state)['lineup']['group']
            heavy = '-OL' in group or pf.group_counts(group)['WR'] <= 1
            if heavy or group == '11':
                calls['heavy' if heavy else 'eleven'][intent] += 1
        share = {k: v['dropback'] / sum(v.values()) for k, v in calls.items()}
        self.assertLess(share['heavy'], share['eleven'] - 0.2, share)

    def test_a_v3_table_ignores_the_call(self):
        field = pf.Field.load(V3_TABLE, V3_SHA256)
        self.assertFalse(field.conditions_on_call)
        self.assertEqual(field.group_probs('DEN', '1|xl|mid', pf.START, 'run'),
                         field.group_probs('DEN', '1|xl|mid', pf.START, 'dropback'))


class Loading(unittest.TestCase):
    def test_a_different_table_hash_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'expected'):
            pf.Field.load(TABLE, '0' * 64)

    def test_the_table_records_its_fit_seasons(self):
        self.assertEqual(FIELD.seasons, [2022, 2023, 2024, 2025])
        self.assertIn('LA', FIELD.teams)
        self.assertIn('LAR', FIELD.teams)  # nfl_team_codes.TeamKeyed: either spelling finds the Rams


if __name__ == '__main__':
    unittest.main()
