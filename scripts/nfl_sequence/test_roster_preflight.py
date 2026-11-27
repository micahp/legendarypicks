"""The shared roster preflight: the depth chart is not the game-day roster.

Regression cases from week 11 2026: an Out QB1 who still has a prop line (Carson Beck, ARI), several QBs with lines, an
injury status from a previous game, a starter on two teams, and an Out receiver who still gets simulated targets.
"""
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / 'backend')]
import game_state  # noqa: E402
import oracle  # noqa: E402
import roster_preflight as rp  # noqa: E402

CUTOFF = '2026-11-22T16:30:00Z'
BECK, JOHNSON, AGUILAR, MINSHEW = '00-0041561', '00-0026300', '00-0041203', '00-0035289'


def player(gsis, name, pos, rank, team):
    return {'gsis_id': gsis, 'player_name': name, 'pos_abb': pos, 'pos_rank': rank, 'team': team,
            'snapshot_at': '2026-11-22T15:12:52Z'}


def team_rows(team, prefix, qbs):
    rows = [player(g, n, 'QB', r, team) for g, n, r in qbs]
    rows += [player(f'{prefix}-RB1', f'{team} RB', 'RB', 1, team), player(f'{prefix}-WR1', f'{team} WR1', 'WR', 1, team),
             player(f'{prefix}-WR2', f'{team} WR2', 'WR', 2, team), player(f'{prefix}-WR3', f'{team} WR3', 'WR', 3, team),
             player(f'{prefix}-TE1', f'{team} TE', 'TE', 1, team), player(f'{prefix}-PK', f'{team} K', 'PK', 1, team)]
    return rows


def snapshot(injuries, away_qbs=None, home_extra=()):
    away_qbs = away_qbs or [(BECK, 'Carson Beck', 1), (JOHNSON, 'Josh Johnson', 2), (AGUILAR, 'Joey Aguilar', 3),
                            (MINSHEW, 'Gardner Minshew II', 4)]
    report = {'players': [{'gsis_id': g, 'report_status': s, 'published_utc': '2026-11-21T19:25:31+00:00'}
                          for g, s in injuries.items()], 'obsolete': []}
    snap = {'as_of': CUTOFF, 'snapshot_sha256': 'x',
            'schedule': {'game_id': '2026_11_ARI_KC', 'away_team': 'ARI', 'home_team': 'KC', 'week': 11},
            'rosters': {'away': {'team': 'ARI', 'snapshot_at': '2026-11-22T15:12:52Z', 'injury_report': report,
                                 'players': team_rows('ARI', 'ARI', away_qbs)},
                        'home': {'team': 'KC', 'snapshot_at': '2026-11-22T15:12:52Z', 'injury_report': report,
                                 'players': team_rows('KC', 'KC', [('00-0033873', 'Patrick Mahomes', 1)]) + list(home_extra)}}}
    for side in ('away', 'home'):
        snap['rosters'][side]['membership'] = {'week': 11, 'players': [
            {'gsis_id': p['gsis_id'], 'name': p['player_name'], 'position': p['pos_abb'], 'status': 'ACT'}
            for p in snap['rosters'][side]['players']]}
    return snap


def set_status(snap, side, gsis, status, name=None, position=None):
    members = snap['rosters'][side]['membership']['players']
    row = next((m for m in members if m['gsis_id'] == gsis), None)
    if row is None:
        members.append({'gsis_id': gsis, 'name': name, 'position': position, 'status': status})
    else:
        row['status'] = status


def result(rows, name):
    return next(r for r in rows if r[0] == name)


class OutQuarterback(unittest.TestCase):
    def test_oracle_direct_builder_attaches_and_seals_roster(self):
        import pandas as pd
        import pregame_snapshot
        snap = snapshot({BECK: 'Out'})
        weekly = [{'team': snap['rosters'][side]['team'], 'week': 11,
                   'gsis_id': p['gsis_id'], 'full_name': p['player_name'],
                   'position': p['pos_abb'], 'status': 'ACT', 'status_description_abbr': None}
                  for side in ('away', 'home') for p in snap['rosters'][side]['players']]
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {'game_id': '2026_11_ARI_KC'}
        with tempfile.TemporaryDirectory() as folder:
            roster_path = Path(folder) / 'weekly.parquet'
            roster_path.write_bytes(b'frozen')
            with patch.object(oracle, 'connect', return_value=conn), \
                 patch.object(oracle, 'scoreboard_kickoff', return_value=(datetime(2026, 11, 22, 18, tzinfo=timezone.utc), 'source')), \
                 patch.object(pregame_snapshot, 'build', return_value=snap), \
                 patch.object(pd, 'read_parquet', return_value=pd.DataFrame(weekly)):
                result_snapshot = oracle.build_snapshot('unused', '2026_11_ARI_KC', CUTOFF, fetch=object(),
                    weekly_roster=roster_path, weekly_roster_available_at=CUTOFF,
                    injury_report={'players': []}, injury_available_at=CUTOFF)
        self.assertEqual(result_snapshot['roster_resolution']['content_hash'], rp.resolve(result_snapshot)['content_hash'])
        self.assertTrue(result_snapshot['snapshot_sha256'])

    def test_oracle_finalizes_roster_and_refuses_missing_membership(self):
        snap = snapshot({BECK: 'Out'})
        set_status(snap, 'away', 'ARI-WR2', 'RES')
        result_snapshot = oracle.finalize_model_snapshot(snap)
        self.assertEqual(result_snapshot['roster_resolution']['content_hash'], rp.resolve(result_snapshot)['content_hash'])
        self.assertEqual(rp.exclusions_applied(result_snapshot, rp.resolve(result_snapshot))[1], 'PASS')
        self.assertTrue(any(p['gsis_id'] == 'ARI-WR2' and p['report_status'] == 'Out'
                            for p in result_snapshot['rosters']['away']['injury_report']['players']))
        bad = snapshot({BECK: 'Out'})
        del bad['rosters']['away']['membership']
        with self.assertRaisesRegex(ValueError, 'SNAPSHOT_ROSTER_PREFLIGHT_FAILED'):
            oracle.finalize_model_snapshot(bad)
        bad = snapshot({BECK: 'Out'})
        bad['rosters']['away']['membership']['week'] = 10
        with self.assertRaisesRegex(ValueError, 'SNAPSHOT_ROSTER_PREFLIGHT_FAILED'):
            oracle.finalize_model_snapshot(bad)

    def test_oracle_snapshot_refuses_unavailable_or_late_roster_inputs(self):
        with self.assertRaisesRegex(ValueError, 'SNAPSHOT_ROSTER_INPUTS_REQUIRED'):
            oracle.build_snapshot('unused', 'unused', CUTOFF)
        with self.assertRaisesRegex(ValueError, 'SNAPSHOT_SOURCE_AFTER_CUTOFF: weekly_roster'):
            oracle.build_snapshot('unused', 'unused', CUTOFF, weekly_roster='unused',
                                  weekly_roster_available_at='2026-11-22T16:31:00Z',
                                  injury_report={}, injury_available_at=CUTOFF)
        with self.assertRaisesRegex(ValueError, 'SNAPSHOT_SOURCE_AFTER_CUTOFF: depth_chart'):
            oracle.build_snapshot('unused', 'unused', CUTOFF, weekly_roster='unused',
                                  weekly_roster_available_at=CUTOFF, injury_report={}, injury_available_at=CUTOFF,
                                  depth_parquet='unused', depth_available_at='2026-11-22T16:31:00Z')
        snap = snapshot({BECK: 'Out'})
        snap['rosters']['away']['snapshot_at'] = '2026-11-22T16:31:00Z'
        with self.assertRaisesRegex(ValueError, 'SNAPSHOT_SOURCE_AFTER_CUTOFF: away_depth_chart'):
            oracle.finalize_model_snapshot(snap)
        snap = snapshot({BECK: 'Out'})
        snap['rosters']['away']['injury_report']['source_available_utc'] = '2026-11-22T16:31:00Z'
        with self.assertRaisesRegex(ValueError, 'SNAPSHOT_SOURCE_AFTER_CUTOFF'):
            oracle.finalize_model_snapshot(snap)

    def test_an_out_qb1_with_a_prop_line_is_excluded_and_the_backup_promoted(self):
        snap = snapshot({BECK: 'Out', AGUILAR: 'Out', MINSHEW: 'Out'})
        rows, resolved = rp.check(snap, {'ARI': {BECK, JOHNSON}, 'KC': {'00-0033873'}})
        self.assertEqual(rp.resolved_qb1(resolved['away']), JOHNSON)
        self.assertEqual(result(rows, 'ARI resolved eligible QB1')[1], 'PASS')
        self.assertIn('promoted over Carson Beck [injury_out]', result(rows, 'ARI resolved eligible QB1')[2])
        self.assertEqual(result(rows, 'ARI resolved QB1 has a passing-yards prop')[1], 'PASS')
        role = next(r for r in resolved['away']['roles'] if r['role'] == 'QB1')
        self.assertEqual(role['extra']['excluded_ranked_ahead'], [BECK])
        beck = next(p for p in resolved['away']['players'] if p['gsis_id'] == BECK)
        self.assertEqual((beck['depth_rank'], beck['exclusion_reason']), (1, 'injury_out'))  # original rank kept

    def test_a_prop_line_on_the_out_qb_does_not_validate_the_game(self):
        # only Beck is priced: the resolved starter (Johnson) has no line, so the market check fails
        rows, _ = rp.check(snapshot({BECK: 'Out'}), {'ARI': {BECK}, 'KC': {'00-0033873'}})
        self.assertEqual(result(rows, 'ARI resolved QB1 has a passing-yards prop')[1], 'FAIL')

    def test_no_eligible_qb_blocks(self):
        snap = snapshot({BECK: 'Out', JOHNSON: 'Out', AGUILAR: 'Out', MINSHEW: 'Out'})
        rows, resolved = rp.check(snap)
        self.assertEqual(result(rows, 'ARI resolved eligible QB1')[1], 'FAIL')
        self.assertIn('unresolved_QB1', resolved['away']['blocks'])

    def test_an_injury_report_without_publish_times_fails(self):
        snap = snapshot({BECK: 'Out'})
        for p in snap['rosters']['away']['injury_report']['players']:
            del p['published_utc']
        rows, _ = rp.check(snap)
        self.assertEqual(result(rows, 'ARI injury report applies to this game')[1], 'FAIL')


class ObsoleteStatus(unittest.TestCase):
    def test_a_game_status_from_the_previous_game_is_dropped_and_a_reserve_status_is_kept(self):
        last = {'ARI': datetime(2026, 11, 15, 21, 5, tzinfo=timezone.utc)}
        latest = {AGUILAR: ('INACTIVE', '2026-11-15T19:51:13+00:00', 'ARZ'),
                  BECK: ('OUT', '2026-11-21T19:25:31+00:00', 'ARZ'),
                  MINSHEW: ('IR', '2026-11-10T04:40:51+00:00', 'ARZ')}
        players, obsolete = oracle.split_obsolete(latest, last)
        self.assertEqual(sorted(p['gsis_id'] for p in players), sorted([BECK, MINSHEW]))
        self.assertEqual([p['gsis_id'] for p in obsolete], [AGUILAR])


class Membership(unittest.TestCase):
    def test_an_active_kicker_off_the_depth_chart_replaces_a_reserve_kicker(self):
        # BAL week 9: Tyler Loop on a reserve list, Jake Moody active (elevated) but not on the depth chart
        snap = snapshot({})
        set_status(snap, 'away', 'ARI-PK', 'RES')
        set_status(snap, 'away', 'MOODY', 'ACT', 'Jake Moody', 'K')
        rows, resolved = rp.check(snap)
        pk = next(r for r in resolved['away']['roles'] if r['role'] == 'PK')
        self.assertEqual((pk['gsis_id'], pk['basis']), ('MOODY', 'unique_candidate'))

    def test_a_sole_practice_squad_kicker_is_projected(self):
        snap = snapshot({})
        set_status(snap, 'away', 'ARI-PK', 'RES')
        set_status(snap, 'away', 'SQUAD', 'DEV', 'Squad Kicker', 'K')
        _, resolved = rp.check(snap)
        pk = next(r for r in resolved['away']['roles'] if r['role'] == 'PK')
        self.assertEqual((pk['gsis_id'], pk['status']), ('SQUAD', 'PROJECTED'))

    def test_a_depth_chart_qb_cut_or_not_yet_signed_is_not_used(self):
        # BAL week 9: Brissett on the depth chart, cut by ARI and not yet on BAL's weekly roster
        snap = snapshot({})
        set_status(snap, 'away', BECK, 'CUT')
        _, resolved = rp.check(snap)
        self.assertEqual(rp.resolved_qb1(resolved['away']), JOHNSON)

    def test_a_game_day_inactive_is_excluded(self):
        snap = snapshot({})
        set_status(snap, 'away', BECK, 'INA')
        _, resolved = rp.check(snap)
        self.assertEqual(rp.resolved_qb1(resolved['away']), JOHNSON)

    def test_no_weekly_roster_fails(self):
        snap = snapshot({})
        del snap['rosters']['away']['membership']
        rows, _ = rp.check(snap)
        self.assertEqual(result(rows, 'ARI roster membership from the weekly roster')[1], 'FAIL')

    def test_a_starter_listed_on_both_teams_blocks(self):
        traded = player(JOHNSON, 'Josh Johnson', 'QB', 2, 'KC')
        rows, _ = rp.check(snapshot({BECK: 'Out'}, home_extra=[traded]))
        self.assertEqual(result(rows, 'conflicting player-team memberships')[1], 'FAIL')


class Postflight(unittest.TestCase):
    def test_an_out_receiver_with_simulated_targets_fails(self):
        snap = snapshot({BECK: 'Out', 'ARI-WR1': 'Out'})
        run = {'player_boxscores_by_seed': [{'seed': 1, 'players': [
            {'player_id': JOHNSON, 'player_name': 'Josh Johnson', 'player_team': 'ARI', 'passing': {'att': 30}},
            {'player_id': '00-0033873', 'player_name': 'Patrick Mahomes', 'player_team': 'KC', 'passing': {'att': 35}},
            {'player_id': 'ARI-WR1', 'player_name': 'ARI WR1', 'player_team': 'ARI', 'receiving': {'tgt': 4}}]}]}
        rows = rp.postflight(snap, run)
        self.assertEqual(result(rows, 'excluded players receiving stats')[1], 'FAIL')
        self.assertEqual(result(rows, 'ARI simulated passer is the resolved QB1')[1], 'PASS')

    def test_a_simulated_passer_who_is_not_the_resolved_qb1_fails(self):
        snap = snapshot({BECK: 'Out'})
        run = {'player_boxscores_by_seed': [{'seed': 1, 'players': [
            {'player_id': BECK, 'player_name': 'Carson Beck', 'player_team': 'ARI', 'passing': {'att': 30}},
            {'player_id': '00-0033873', 'player_name': 'Patrick Mahomes', 'player_team': 'KC', 'passing': {'att': 35}}]}]}
        rows = rp.postflight(snap, run)
        self.assertEqual(result(rows, 'ARI simulated passer is the resolved QB1')[1], 'FAIL')
        self.assertEqual(result(rows, 'excluded players receiving stats')[1], 'FAIL')

    def test_a_receiver_trick_pass_listed_first_does_not_make_him_the_passer(self):
        # 2026-11-23 CIN at WAS v1.6 smoke seed: Van Jefferson 1 attempt, Jayden Daniels 36
        snap = snapshot({BECK: 'Out'})
        run = {'player_boxscores_by_seed': [{'seed': 1, 'players': [
            {'player_id': 'ARI-WR1', 'player_name': 'ARI WR1', 'player_team': 'ARI', 'passing': {'att': 1}},
            {'player_id': JOHNSON, 'player_name': 'Josh Johnson', 'player_team': 'ARI', 'passing': {'att': 36}},
            {'player_id': '00-0033873', 'player_name': 'Patrick Mahomes', 'player_team': 'KC', 'passing': {'att': 35}}]}]}
        rows = rp.postflight(snap, run)
        self.assertEqual(result(rows, 'ARI simulated passer is the resolved QB1')[1], 'PASS')


class Exclusions(unittest.TestCase):
    def test_reserve_and_practice_squad_depth_players_reach_the_engine_as_out_without_changing_the_resolution(self):
        snap = snapshot({BECK: 'Out'})
        set_status(snap, 'away', 'ARI-WR2', 'RES')
        set_status(snap, 'away', 'ARI-WR3', 'DEV')
        resolved = rp.resolve(snap)
        rp.apply_exclusions(snap, resolved)
        added = {p['gsis_id']: p['reason'] for p in snap['rosters']['away']['injury_report']['players']
                 if p.get('source') == rp.EXCLUSION_SOURCE}
        self.assertEqual(added, {'ARI-WR2': 'membership_reserve', 'ARI-WR3': 'membership_practice_squad'})
        self.assertNotIn(BECK, added)  # already Out in the report
        self.assertEqual(rp.resolve(snap)['content_hash'], resolved['content_hash'])
        rows, _ = rp.check(snap)
        self.assertEqual(result(rows, 'ARI injury report applies to this game')[1], 'PASS')

    def test_a_snapshot_built_without_exclusions_fails_the_batch_check(self):
        # 2026-11-23 CIN at WAS: built before apply_exclusions, same resolution hash, McLaurin (RES) got targets
        snap = snapshot({BECK: 'Out'})
        set_status(snap, 'away', 'ARI-WR2', 'RES')
        resolved = rp.resolve(snap)
        name, status, detail = rp.exclusions_applied(snap, resolved)
        self.assertEqual(status, 'FAIL')
        self.assertIn('1 excluded', detail)
        rp.apply_exclusions(snap, resolved)
        self.assertEqual(rp.exclusions_applied(snap, resolved)[1], 'PASS')


class EngineSelection(unittest.TestCase):
    def test_the_engine_never_picks_an_out_qb1_as_passer(self):
        snap = snapshot({BECK: 'Out'})
        snap['roster_resolution'] = rp.resolve(snap)
        ref = game_state.Reference.__new__(game_state.Reference)
        ref.participants = {}
        play = {'event_type': 'pass_incomplete', 'sequence': 1,
                'outcome': {'sampled_from': {'game_id': 'g', 'play_id': 1}}}
        snap['model_reference'] = {}
        out = ref.participants_for(play, offense_team='B', snapshot=snap, seed=1)
        self.assertEqual(out['passer_id'], JOHNSON)


if __name__ == '__main__':
    unittest.main()
