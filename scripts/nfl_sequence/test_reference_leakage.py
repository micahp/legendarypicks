"""Leakage tests across the whole reference path.

Each test appends one row dated after the cutoff to one source, reloads the reference with the cutoff, and requires the loaded
content to be unchanged. A precondition in each test checks that the uncut loader really reads the injected row, so a test
cannot pass by never seeing it. The reference's pinned file checksums are not compared: an injected file has a new checksum by
design, and its manifest is rewritten to match.

Each reload takes about ten seconds, so the class loads the baseline once.
"""
import csv
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_try_fallback as btf  # noqa: E402
import e1_drive as e1  # noqa: E402
import e2_reference as er  # noqa: E402
import measure_kick_outcomes as mk  # noqa: E402

CUTOFF = (2024, 8)
CONTENT_FIELDS = ('kicks', 'safety_kick_pool', 'overtime_pool', 'overtime_try_p_two', 'overtime_p_kick', 'participants',
                  'missed_field_goal_pool')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canon(value):
    if isinstance(value, dict):
        return sorted((repr(k), canon(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [canon(v) for v in value]
    return value


def content(ref):
    out = {name: canon(getattr(ref, name)) for name in CONTENT_FIELDS}
    out['blocked_records'] = canon(ref.blocked_kicks['records'])
    out['blocked_rates'] = canon(ref.blocked_kicks['rates'])
    return json.dumps(out, sort_keys=True, default=str)


def read_csv(path):
    with open(path, newline='') as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def write_csv(path, header, rows):
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def future(template, **changes):
    row = dict(template)
    row.update({'season': '2025', 'week': '1'})
    row.update(changes)
    return row


def write_with_manifest(src, dst, new_rows, **manifest_changes):
    """Copy a CSV, append rows, and rewrite its manifest's checksum and counts from the copy."""
    header, rows = read_csv(src)
    write_csv(dst, header, rows + new_rows)
    manifest_src = src.with_suffix(src.suffix + '.manifest.json')
    manifest = json.loads(manifest_src.read_text())
    manifest['output']['sha256'] = sha256(dst)
    for key, delta in manifest_changes.items():
        manifest[key] = manifest[key] + delta
    dst.with_suffix(dst.suffix + '.manifest.json').write_text(json.dumps(manifest))
    return dst


@contextmanager
def default_path(function, index, value):
    """Point a loader's default path at a temporary copy for the duration of the block."""
    original = function.__defaults__
    replaced = list(original)
    replaced[index] = value
    function.__defaults__ = tuple(replaced)
    try:
        yield
    finally:
        function.__defaults__ = original


def database_play_2025_week_1():
    con = sqlite3.connect(f'file:{e1.DEFAULT_DB}?mode=ro', uri=True)
    try:
        return con.execute("SELECT game_id, play_id, posteam FROM nfl_pbp WHERE season=2025 AND week=1 "
                           "AND play_type='pass' ORDER BY game_id, play_id LIMIT 1").fetchone()
    finally:
        con.close()


class LeakageAcrossTheReferencePath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        with mock.patch.dict(er.COHORT_UNSAFE_SOURCES, {}, clear=True):
            ref, _ = er.load(eligible_before=CUTOFF)
        cls.baseline = content(ref)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def assertUnchangedAfterInjection(self, patches, name):
        with ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            with mock.patch.dict(er.COHORT_UNSAFE_SOURCES, {}, clear=True):
                ref, _ = er.load(eligible_before=CUTOFF)
        self.assertEqual(content(ref), self.baseline, f'{name} changed the reference after the cutoff')

    def test_a_future_blocked_kick_record_does_not_change_the_reference(self):
        header, rows = read_csv(er.BLOCKED_KICKS)
        template = next(r for r in rows if r['kick_type'] == 'field_goal' and r['blocked'] == '1')
        path = write_with_manifest(er.BLOCKED_KICKS, self.dir / 'blocked.csv',
                                   [future(template, game_id='2025_01_TST_TST', play_id='999901')], record_count=1)
        self.assertEqual(len(er.load_blocked_kicks(path)['records']['field_goal']),
                         len(er.load_blocked_kicks()['records']['field_goal']) + 1)
        self.assertUnchangedAfterInjection([default_path(er.load_blocked_kicks, 0, path)], 'blocked kicks')

    def test_a_future_field_goal_or_try_result_does_not_change_the_reference(self):
        header, rows = read_csv(mk.KICK_RESULTS)
        field_goal = next(r for r in rows if r['play_type'] == 'field_goal' and r['field_goal_result'] == 'made'
                          and r['yardline_100'])
        extra_point = next(r for r in rows if r['play_type'] == 'extra_point' and r['extra_point_result'] == 'good')
        path = self.dir / 'kick_results.csv'
        write_csv(path, header, rows + [future(field_goal, game_id='2025_01_TST_TST', play_id='999902'),
                                        future(extra_point, game_id='2025_01_TST_TST', play_id='999903')])
        before = mk.load_field_goal_results()['field_goal_outcomes']
        after = mk.load_field_goal_results(path)['field_goal_outcomes']
        self.assertNotEqual(before, after)
        self.assertUnchangedAfterInjection([default_path(mk.load_field_goal_results, 0, path),
                                            default_path(mk.load_try_results, 0, path)], 'kick results')

    def test_a_future_safety_kick_does_not_change_the_reference(self):
        header, rows = read_csv(er.SAFETY_KICKS)
        template = next(r for r in rows if r['status'] == 'usable')
        path = write_with_manifest(er.SAFETY_KICKS, self.dir / 'safety.csv',
                                   [future(template, game_id='2025_01_TST_TST', game_date='2025-09-07',
                                           safety_play_id='999904', kick_play_id='999905',
                                           receiving_snap_play_id='999906')],
                                   record_count=1, usable_count=1)
        self.assertEqual(len(er.load_safety_kick_pool(path)[0]), len(er.load_safety_kick_pool()[0]) + 1)
        self.assertUnchangedAfterInjection([default_path(er.load_safety_kick_pool, 0, path)], 'safety kicks')

    def test_a_future_overtime_drive_does_not_change_the_reference(self):
        header, rows = read_csv(er.OVERTIME_DRIVES)
        template = next(r for r in rows if r['status'] == 'usable')
        path = write_with_manifest(er.OVERTIME_DRIVES, self.dir / 'overtime.csv',
                                   [future(template, game_id='2025_01_TST_TST', drive='999907')],
                                   drive_count=1, usable_count=1)
        self.assertEqual(len(er.load_overtime_drive_pool(path)[0]), len(er.load_overtime_drive_pool()[0]) + 1)
        self.assertUnchangedAfterInjection([default_path(er.load_overtime_drive_pool, 0, path)], 'overtime drives')

    def test_a_future_participant_extra_does_not_change_the_reference(self):
        game_id, play_id, posteam = database_play_2025_week_1()
        header, rows = read_csv(er.PLAY_EXTRAS)
        template = rows[0]
        path = self.dir / 'extras.csv'
        write_csv(path, header, rows + [future(template, game_id=game_id, play_id=str(play_id), posteam=posteam,
                                               timeout='1', timeout_team=posteam)])
        self.assertUnchangedAfterInjection([default_path(er.load_participants, 1, path)], 'participant extras')

    def test_a_future_two_point_try_does_not_change_the_reference(self):
        header, rows = read_csv(btf.SOURCE)
        template = next(r for r in rows if r['kind'] == 'two_point')
        path = self.dir / 'try_situation.csv'
        write_csv(path, header, rows + [future(template, game_id='2025_01_TST_TST', play_id='999908',
                                               period='Q4_le5', margin='0')])
        self.assertEqual(len(btf.load_rows(path)), len(btf.load_rows()) + 1)
        self.assertUnchangedAfterInjection([mock.patch.object(btf, 'SOURCE', path)], 'two-point tries')


if __name__ == '__main__':
    unittest.main()
