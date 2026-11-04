"""Tests for formal play classes. The published-file test reproduces DET 2025 from the nflverse release and the playbook file.

Run from this folder: python3 -m unittest test_formal_playcall
"""
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import formal_playcall as fp  # noqa: E402

RAW = Path('/root/gridiron-playbooks-research/data/raw')
PLAYBOOK = Path('/root/gridiron-playbooks-research/data/playbooks/DET-2025.json')

# 1 QB, 5 OL, 1 RB, 1 TE, 3 WR: 11 personnel
ELEVEN = '1 C, 2 G, 1 QB, 1 RB, 2 T, 1 TE, 3 WR'
ELEVEN_CODE = '113'


class PersonnelCodeTest(unittest.TestCase):
    def test_eleven_personnel_uses_the_playbook_digits(self):
        self.assertEqual(fp.offense_personnel_code(ELEVEN), ELEVEN_CODE)

    def test_fullback_counts_with_the_running_backs(self):
        self.assertEqual(fp.offense_personnel_code('1 FB, 1 RB, 1 TE, 2 WR, 5 OL, 1 QB'), '212')

    def test_six_linemen_are_kept_with_a_suffix_not_dropped(self):
        self.assertEqual(fp.offense_personnel_code('1 C, 2 G, 1 QB, 1 RB, 3 T, 2 TE, 1 WR'), '121-OL6')

    def test_seven_linemen_are_kept(self):
        self.assertEqual(fp.offense_personnel_code('3 C, 2 G, 1 QB, 1 RB, 2 T, 1 TE, 1 WR'), '111-OL7')

    def test_a_defensive_label_is_invalid_with_its_reason(self):
        code = fp.offense_personnel_code('1 C, 2 G, 1 QB, 1 RB, 2 T, 1 TE, 2 WR, 1 DE')
        self.assertTrue(code.startswith(fp.INVALID))
        self.assertIn('DE', code)

    def test_wrong_total_is_invalid_with_the_size(self):
        self.assertEqual(fp.offense_personnel_code('1 C, 2 G, 1 QB, 1 RB, 2 T, 1 TE'), f'{fp.INVALID}:size8')

    def test_punt_team_personnel_is_a_special_play_not_invalid(self):
        code = fp.offense_personnel_code('1 LS, 3 MLB, 1 OLB, 1 P, 2 RB, 1 SS, 1 TE, 1 WR')
        self.assertEqual(code, f'{fp.SPECIAL}:LS/P')

    def test_blank_personnel_is_unknown_not_filled(self):
        self.assertEqual(fp.offense_personnel_code(''), fp.UNKNOWN)
        self.assertEqual(fp.offense_personnel_code(None), fp.UNKNOWN)

    def test_unreadable_text_raises(self):
        with self.assertRaises(ValueError):
            fp.offense_personnel_code('five linemen')


class FormationAndConceptTest(unittest.TestCase):
    def test_formation_is_one_of_three_or_unknown(self):
        self.assertEqual(fp.formation_key('SHOTGUN'), 'SHOTGUN')
        self.assertEqual(fp.formation_key(''), fp.UNKNOWN)
        self.assertEqual(fp.formation_key('WILDCAT'), fp.UNKNOWN)

    def test_run_concept_is_the_gap(self):
        self.assertEqual(fp.concept('run', 'guard', '', ''), 'run|guard')
        self.assertEqual(fp.concept('run', '', '', ''), f'run|{fp.UNKNOWN}')

    def test_pass_concept_is_depth_and_route(self):
        self.assertEqual(fp.concept('pass', '', 'short', 'HITCH/CURL'), 'pass|short|HITCH/CURL')
        self.assertEqual(fp.concept('pass', '', 'deep', ''), f'pass|deep|{fp.UNKNOWN}')

    def test_offense_class_is_the_four_part_key(self):
        cls = fp.offense_class('SHOTGUN', ELEVEN, 'pass', '', 'short', 'SCREEN')
        self.assertEqual(cls, ('SHOTGUN', ELEVEN_CODE, 'pass', 'pass|short|SCREEN'))

    def test_defense_class(self):
        code = fp.defense_personnel_code('2 CB, 2 DE, 2 DT, 2 MLB, 1 OLB, 2 SS')
        self.assertEqual(code, 'DL4-LB3-DB4')
        self.assertEqual(fp.defense_class('2 CB, 2 DE, 2 DT, 2 MLB, 1 OLB, 2 SS', 'COVER_3', 'ZONE_COVERAGE', '5'),
                         ('DL4-LB3-DB4', 'COVER_3', 'ZONE_COVERAGE', '5'))


@unittest.skipUnless(RAW.exists() and PLAYBOOK.exists(), 'raw nflverse files or the DET 2025 playbook not found')
class PublishedPlaybookTest(unittest.TestCase):
    """The classes must reproduce the published DET 2025 playbook, and the one place they differ is the six-lineman plays."""

    @classmethod
    def setUpClass(cls):
        cls.rows = [r for r in fp.load_season(RAW, 2025, 'DET') if r['play_type'] in ('run', 'pass')]
        cls.profile = json.loads(PLAYBOOK.read_text(encoding='utf-8'))['offense']['profile']

    def test_offense_play_count_matches_the_playbook(self):
        self.assertEqual(len(self.rows), self.profile['eligible_scrimmage_plays'])

    def test_formations_match_the_playbook_exactly(self):
        ours = Counter(fp.formation_key(r['formation']) for r in self.rows)
        published = {k: v['count'] for k, v in self.profile['formation']['categories'].items()}
        for key, count in published.items():
            self.assertEqual(ours[key], count, key)
        self.assertEqual(ours[fp.UNKNOWN], 1)  # one play with no formation recorded: kept, not filled

    def test_five_lineman_personnel_matches_the_playbook_exactly(self):
        ours = Counter(fp.offense_personnel_code(r['personnel']) for r in self.rows)
        published = {k: v['count'] for k, v in self.profile['personnel_code']['categories'].items()}
        for code, count in published.items():
            self.assertEqual(ours[code], count, code)

    def test_the_playbook_leaves_out_exactly_the_six_lineman_and_fake_punt_plays(self):
        published_total = sum(v['count'] for v in self.profile['personnel_code']['categories'].values())
        codes = [fp.offense_personnel_code(r['personnel']) for r in self.rows]
        six_plus = [c for c in codes if c.endswith(('-OL6', '-OL7'))]
        special = [c for c in codes if c.startswith(fp.SPECIAL)]
        self.assertEqual(len(six_plus), 81)
        self.assertEqual(len(special), 1)  # a run with punt-team personnel: a fake punt, kept as SPECIAL
        self.assertEqual(len(self.rows) - published_total, len(six_plus) + len(special))

    def test_no_play_is_left_invalid(self):
        bad = [r for r in self.rows if fp.offense_personnel_code(r['personnel']).startswith(fp.INVALID)]
        self.assertEqual(bad, [])


if __name__ == '__main__':
    unittest.main()
