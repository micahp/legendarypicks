"""Shared research pre-snap participation policy, version 1.

No outcome, realized targets or future-game opportunities enter the lineup.
Retains skill-player stints by team; commit only a physically executed snap.
"""
import random
import participation_field as pf
import roster_preflight
import v1_complete_roster
import snap_update

VERSION = 'shared-participation-v1'


def configure(field, snapshot, snaps=None, entry_current=False):
    season, week = (int(snapshot['schedule'][k]) for k in ('season', 'week'))
    if not field.seasons or max(field.seasons) >= season:
        raise ValueError('shared_participation_fit_cutoff')
    checks, resolved = roster_preflight.check(snapshot)
    if (snapshot.get('roster_resolution') or {}).get('content_hash') != resolved['content_hash']:
        raise ValueError('shared_participation_frozen_roster_resolution_mismatch')
    if roster_preflight.failed(checks) or roster_preflight.exclusions_applied(snapshot, resolved)[1] != 'PASS':
        raise ValueError('shared_participation_roster_preflight_failed')
    rosters, qbs = {}, {}
    for side in ('home', 'away'):
        team = snapshot['rosters'][side]['team']
        rosters[team] = v1_complete_roster.eligible_rows(resolved[side])
        qbs[team] = next(r['gsis_id'] for r in resolved[side]['roles'] if r['role'] == 'QB1')
        if pf.starter_qb(rosters[team]) != qbs[team]:
            raise ValueError('shared_participation_qb_mismatch:' + team)
    field.entry_current = bool(entry_current)
    if entry_current and snaps is None:
        raise ValueError('shared_participation_entry_requires_snap_counts')
    update = None
    if snaps is not None:
        if snaps.season != season:
            raise ValueError('shared_participation_snap_season_mismatch')
        if any(w < week for _team, w in snaps.team_snaps):
            missing = [team for team in rosters if not snaps.weeks_before(team, week)]
            if missing:
                raise ValueError('shared_participation_snap_coverage_missing:' + ','.join(missing))
        update = snap_update.apply(field, snaps, week, rosters, snap_update.PLAYER_N0)
    return rosters, qbs, update


class Policy:
    def __init__(self, field, snapshot, snaps=None, entry_current=False):
        self.field = field
        self.rosters, self.qbs, self.update = configure(field, snapshot, snaps, entry_current)
        self.previous = {}
        self.provenance = {'version': VERSION, 'snapshot_sha256': snapshot['snapshot_sha256'],
                           'field_sha256': field.sha256, 'fit_seasons': list(field.seasons),
                           'entry_current': bool(entry_current), 'snap_update': self.update}

    def prepare(self, team, state, seed, group=None):
        previous = self.previous.get(team, {})
        draw = random.Random(str(seed) + ':lineup')
        if group is None:
            cell = self.field.supported_cell(pf.cell_of(state['down'], state['togo'], state['yl']))
            if cell is None:
                raise ValueError('shared_participation_no_cell')
            group = self.field.draw_group(team, previous.get('group', pf.START), cell, draw)
        else:
            cell = None
        if group is None or not any(g == group for _pos, g in self.field.position_prior):
            raise ValueError('shared_participation_group_not_in_fitted_table:' + str(group))
        lineup, record = self.field.advance(team, previous.get('lineup', {}), group,
                                            self.rosters[team], draw, prev_group=previous.get('group'),
                                            slots=previous.get('slots'))
        if lineup is None or record.get('status') != 'ok':
            raise ValueError('shared_participation_short:' + str(record))
        allowed = {p['gsis_id'] for p in self.rosters[team]}
        if not set(lineup).issubset(allowed) or self.qbs[team] in lineup:
            raise ValueError('shared_participation_invalid_selection')
        return {'team': team, 'group': group, 'lineup': lineup, 'slots': record['slots'],
                'qb1': self.qbs[team], 'selection': record, 'cell': cell,
                'source_sha256': self.field.sha256, 'policy_version': VERSION,
                'entry_current': self.provenance['entry_current'], 'snap_update': self.update,
                'scope': 'offensive_skill_players_only'}

    def commit(self, selected):
        self.previous[selected['team']] = selected
