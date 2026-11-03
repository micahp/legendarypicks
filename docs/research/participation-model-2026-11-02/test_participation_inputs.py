"""Regression tests for participation inputs: 2022 snaps are never dropped, and prior groups never use the target season.

Run from this folder: python3 -m unittest test_participation_inputs
Tests that need the local scrimmage table or the outputs skip with a reason when the file is absent, so a missing file is
visible in the run output rather than a silent pass.
"""
import csv
import gzip
import os
import sys
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lineup_fit as lf  # noqa: E402
import participation_labels as pl  # noqa: E402

SCRIMMAGE = Path(os.environ.get('SCRIMMAGE_TABLE', '/tmp/claude-0/-root/744b1ddf-da1c-4751-b1ee-106793d5f525/'
                                'scratchpad/participation/scrimmage_participation.csv.gz'))
RECON = HERE / 'outputs' / 'position_reconstruction_2022_2025.csv'
TARGETS = HERE / 'outputs' / 'snap_share_targets_2023_2025.csv'


def fake_row(season, ids, labels=''):
    return {'season': str(season), 'game_id': f'{season}_01_AAA_BBB', 'posteam': 'AAA', 'play_id': '1',
            'group': '11', 'offense_ids': ';'.join(ids), 'offense_positions': labels, 'ids': ids,
            'down': '1', 'ydstogo': '10', 'yardline_100': '50'}


class TwoTwentyTwoLabelsTest(unittest.TestCase):
    def setUp(self):
        self.ids = [f'00-00{i:05d}' for i in range(11)]

    def test_blank_labels_with_reconstruction_keep_every_id(self):
        recon = {(2022, '2022_01_AAA_BBB', 'AAA', pid): 'WR' for pid in self.ids[:10]}
        out = pl.aligned_labels(fake_row(2022, self.ids), recon)
        self.assertEqual(len(out), 11)
        self.assertEqual(sum(1 for _p, lab, src in out if src == pl.RECONSTRUCTED), 10)
        self.assertEqual([src for _p, _lab, src in out].count(pl.UNLABELLED), 1)

    def test_blank_labels_without_reconstruction_are_counted_not_dropped(self):
        out = pl.aligned_labels(fake_row(2022, self.ids), None)
        self.assertEqual(len(out), 11)
        self.assertTrue(all(src == pl.UNLABELLED for _p, _l, src in out))

    def test_aligned_onfield_labels_are_used_when_lists_match(self):
        labels = ';'.join(['WR'] * 5 + ['TE'] * 6)
        out = pl.aligned_labels(fake_row(2023, self.ids, labels), None)
        self.assertEqual([lab for _p, lab, _s in out], ['WR'] * 5 + ['TE'] * 6)
        self.assertTrue(all(src == pl.ONFIELD for _p, _l, src in out))

    def test_mismatched_lengths_never_pair_by_position(self):
        out = pl.aligned_labels(fake_row(2023, self.ids, 'WR;TE'), None)
        self.assertEqual(len(out), 11)
        self.assertEqual(sum(1 for _p, _l, src in out if src == pl.UNLABELLED), 11)

    def test_sequences_keep_reconstructed_2022_skill_players(self):
        recon = {(2022, '2022_01_AAA_BBB', 'AAA', pid): 'WR' for pid in self.ids[:10]}
        seqs = lf.sequences([fake_row(2022, self.ids)], {}, snap_labels=True, recon=recon)
        skill = next(iter(seqs.values()))[0][2]
        self.assertEqual(len(skill), 10)
        self.assertTrue(all(cls == 'WR' for _pid, cls in skill))

    def test_sequences_without_reconstruction_drop_only_unlabelled_players(self):
        seqs = lf.sequences([fake_row(2022, self.ids)], {}, snap_labels=True, recon=None)
        self.assertEqual(next(iter(seqs.values()))[0][2], frozenset())


@unittest.skipUnless(SCRIMMAGE.exists(), f'scrimmage table not found at {SCRIMMAGE}')
class RealTwoTwentyTwoTest(unittest.TestCase):
    def test_every_2022_snap_keeps_all_offense_ids(self):
        recon = pl.load_reconstruction(RECON) if RECON.exists() else None
        counts = Counter()
        with gzip.open(SCRIMMAGE, 'rt', newline='') as handle:
            for row in csv.DictReader(handle):
                if row['season'] != '2022' or row['season_type'] != 'REG':
                    continue
                out = pl.aligned_labels(row, recon)
                n_ids = len([x for x in row['offense_ids'].split(';') if x])
                self.assertEqual(len(out), n_ids)
                counts.update(src for _p, _l, src in out)
        total = sum(counts.values())
        self.assertGreater(total, 0)
        self.assertGreater(counts[pl.RECONSTRUCTED] / total, 0.9, f'2022 source counts: {dict(counts)}')


@unittest.skipUnless(TARGETS.exists(), f'snap-share targets not found at {TARGETS}')
class PriorGroupSupportTest(unittest.TestCase):
    """Every prior value must be supported by the prior season alone. A same-team prior needs prior-season history on that
    team. A cross-team prior (a transfer) needs prior-season history on any team. A prior group, or a prior value taken from
    the target season, would show up here with no prior-season support."""

    def test_prior_has_prior_season_support(self):
        if not RECON.exists():
            self.skipTest('reconstruction not found')
        if not SCRIMMAGE.exists():
            self.skipTest('scrimmage table not found')
        # Same-team history comes from the participation snaps, which are complete. The reconstruction is only the label
        # source, and it has a few gaps (PFR rows not matched to a GSIS ID), so it cannot define team history.
        same_team, any_team = set(), set()
        with gzip.open(SCRIMMAGE, 'rt', newline='') as handle:
            for row in csv.DictReader(handle):
                if row['season_type'] != 'REG':
                    continue
                for pid in row['offense_ids'].split(';'):
                    if pid:
                        same_team.add((int(row['season']), row['posteam'], pid))
                        any_team.add((int(row['season']), pid))
        bad = Counter()
        with open(TARGETS, newline='', encoding='utf-8') as handle:
            for row in csv.DictReader(handle):
                season, source = int(row['season']), row['prior_source']
                prev = season - 1
                if source == 'same_team' and (prev, row['team'], row['gsis_id']) not in same_team:
                    bad[source] += 1
                elif source == 'cross_team' and (prev, row['gsis_id']) not in any_team:
                    bad[source] += 1
                elif source == 'group_only' and (prev, row['gsis_id']) not in any_team:
                    bad[source] += 1
                elif row['prior_group'] != 'UNK' and (prev, row['gsis_id']) not in any_team:
                    bad['group_without_history'] += 1
        self.assertEqual(sum(bad.values()), 0, f'prior support violations: {dict(bad)}')

    def test_week_one_targets_have_no_in_season_history(self):
        with open(TARGETS, newline='', encoding='utf-8') as handle:
            week_one = [row for row in csv.DictReader(handle) if row['week'] == '1']
        self.assertTrue(week_one)
        for row in week_one:
            self.assertGreaterEqual(float(row['estimate']), 0.0)
            self.assertLessEqual(float(row['estimate']), 1.0)


if __name__ == '__main__':
    unittest.main()
