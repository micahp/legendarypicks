"""CEG player opportunity candidate: fitted counts only at runtime.

Fit the existing Phase 6 M3 formula on pregame-eligible weeks; candidates at
inference are the current skill lineup, not eventual opportunity recipients.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import math
import random
from pathlib import Path
from types import SimpleNamespace

import ceg_opportunity as op
import participation_field
import pregame_snapshot
import shared_participation
import snap_update
import nfl_team_codes

SCHEMA = 'ceg-opportunity-m3-v1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fit(args):
    season, week = args.season, args.week
    seasons = tuple(range(2022, season + 1))
    if len(seasons) < 2 or week < 1:
        raise ValueError('invalid opportunity cutoff')
    data = op.load(args.pbp_dir, seasons)
    # The target season contributes only prior weeks. Earlier seasons are eligible.
    data = data[(data.season < season) | ((data.season == season) & (data.week < week))]
    positions = op.positions(args.db)
    team, player = op.season_shares(data, season - 1)
    factors = op.situational_factors(data, tuple(range(2022, season)), positions)
    counts = data[data.season == season].groupby(['role', 'team', 'player']).size()
    payload = {'schema': SCHEMA, 'season': season, 'week': week, 'k': 160,
               'prior_team': [[*key, float(v)] for key, v in sorted(team.items())],
               'prior_player': [[*key, float(v[1])] for key, v in sorted(player.items())],
               'factors': [[*key, float(v)] for key, v in sorted(factors.items())],
               'counts': [[*key, int(v)] for key, v in sorted(counts.items())],
               'training_sources': {str(y): sha(Path(args.pbp_dir) / f'play_by_play_{y}.parquet')
                                    for y in seasons},
               'position_source_sha256': sha(args.db),
               'position_source_scope': 'fit-time DB position lookup; historical position provenance must be audited'}
    Path(args.out).write_text(json.dumps(payload, sort_keys=True, separators=(',', ':')) + '\n')
    print(sha(args.out))


class Opportunity:
    def __init__(self, payload, digest):
        if payload['schema'] != SCHEMA or payload['k'] != 160:
            raise ValueError('unexpected opportunity model')
        self.season, self.week = payload['season'], payload['week']
        self.digest = digest
        self.prior_team = {tuple(r[:-1]): r[-1] for r in payload['prior_team']}
        self.prior_player = {tuple(r[:-1]): r[-1] for r in payload['prior_player']}
        self.factors = {tuple(r[:-1]): r[-1] for r in payload['factors']}
        self.counts = {tuple(r[:-1]): r[-1] for r in payload['counts']}

    @classmethod
    def load(cls, path, digest):
        if sha(path) != digest:
            raise ValueError('opportunity artifact hash mismatch')
        return cls(json.loads(Path(path).read_text()), digest)

    def choose(self, role, team, selected, state, seed):
        # QB is present separately from the skill-player slots. Designed QB runs
        # are supported; dropback scrambles use the QB without an opportunity draw.
        team = nfl_team_codes.to_nflverse_team_code(team)
        candidates = dict(selected['slots'])
        candidates[selected['qb1']] = 'QB'
        candidates = {p: op.GROUPS[role][pos] for p, pos in candidates.items()
                      if pos in op.GROUPS[role]}
        if not candidates:
            raise ValueError('ceg_no_eligible_opportunity:' + role)
        sit = op.situation(SimpleNamespace(yardline_100=state['yl'], down=state['down'],
                                          score_differential=state.get('score_diff') or 0))
        ids = sorted(candidates)
        weights = []
        for pid in ids:
            prior = max(self.prior_team.get((role, team, pid),
                                           self.prior_player.get((role, pid), 0.0)), op.FLOOR)
            w = (self.counts.get((role, team, pid), 0) + 160 * prior) * self.factors.get(
                (role, sit, candidates[pid]), 1.0)
            if not math.isfinite(w) or w <= 0:
                raise ValueError('ceg_invalid_opportunity_weight')
            weights.append(w)
        return random.Random(str(seed) + ':opportunity:' + role).choices(ids, weights=weights, k=1)[0]


class GamePlayers:
    def __init__(self, inputs):
        snapshot, field_path, field_hash, snaps, opportunity, entry_current = inputs
        self.snapshot = snapshot
        self.opportunity = opportunity
        self.policy = shared_participation.Policy(participation_field.Field.load(field_path, field_hash),
                                                   snapshot, snaps, entry_current)
        self.teams = {'A': snapshot['schedule']['home_team'], 'B': snapshot['schedule']['away_team']}

    def prepare(self, side, state, seed):
        team = self.teams[side]
        lineup = self.policy.prepare(team, state, seed)
        def select(role):
            return self.opportunity.choose(role, team, lineup, state, seed)
        return lineup, select

    def commit(self, lineup):
        self.policy.commit(lineup)

    @property
    def provenance(self):
        return {**self.policy.provenance, 'opportunity_sha256': self.opportunity.digest,
                'scope': 'offensive_skill_snap_and_scrimmage_attribution',
                'player_outcome_conditioning': False, 'official_throwaway_targets': False}


def load_inputs(args, art):
    snapshot = pregame_snapshot.load_frozen_snapshot(str(args.player_snapshot))
    season, week = (int(snapshot['schedule'][k]) for k in ('season', 'week'))
    if (season, week) != (art['season'], art['week']):
        raise ValueError('CEG artifact/snapshot cutoff mismatch')
    opportunity = Opportunity.load(args.opportunity_artifact, args.opportunity_sha256)
    if (opportunity.season, opportunity.week) != (season, week):
        raise ValueError('CEG opportunity cutoff mismatch')
    snaps = snap_update.SnapCounts.load(args.player_snap_counts, args.player_snap_counts_sha256)
    if snaps.season != season:
        raise ValueError('CEG snap-count season mismatch')
    return snapshot, args.player_field, args.player_field_sha256, snaps, opportunity, getattr(args, 'entry_current', None) is not False


def tally(box, outcome):
    """Count only reducer-emitted accepted plays; no penalty no-play credits."""
    facts = outcome.get('ceg_player_facts')
    if not facts:
        return
    event = facts['event']
    qb, rusher, receiver = (facts.get(k) for k in ('passer', 'rusher', 'receiver'))
    yards = outcome['yards_gained'] or 0
    def stat(pid, name, value=1):
        if pid is not None:
            box[pid][name] += value
    for pid in [facts['qb1'], *facts['slots']]:
        stat(pid, 'offensive_snaps')
    if event in ('run', 'scramble', 'kneel'):
        stat(rusher, 'carries')
        stat(rusher, 'rushing_yards', yards)
        if outcome['touchdown']:
            stat(rusher, 'rushing_td')
    if event in ('pass_complete', 'pass_incomplete', 'interception', 'spike'):
        stat(qb, 'pass_attempts')
        stat(receiver, 'intended_targets')
        if event == 'pass_complete':
            stat(qb, 'completions')
            stat(qb, 'passing_yards', yards)
            stat(receiver, 'receptions')
            stat(receiver, 'receiving_yards', yards)
            if outcome['touchdown']:
                stat(qb, 'passing_td')
                stat(receiver, 'receiving_td')
        if event == 'interception':
            stat(qb, 'interceptions')
    if event == 'sack':
        stat(qb, 'sacks')
        stat(qb, 'sack_yards_lost', -yards)
    if facts['fumble']:
        stat(rusher or receiver or qb, 'fumbles')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pbp-dir', required=True)
    p.add_argument('--db', required=True)
    p.add_argument('--season', type=int, required=True)
    p.add_argument('--week', type=int, required=True)
    p.add_argument('--out', required=True)
    fit(p.parse_args())
