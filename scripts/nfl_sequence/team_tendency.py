"""Team tendencies for the E1 pool: each team's event mix by situation, shrunk toward the league.

Step 1 of the event integration. Tendencies come only from seasons before the target season, so a 2025 cutoff reads
2022 to 2024 and nothing later. Nothing here reads 2026. The sampler reweights events the pool already holds. S0 is
unchanged because the simulator uses a sampling policy only when one is passed.
"""
import hashlib
import json
from collections import Counter, defaultdict

import e0_single_play as e0
import e1_drive as e1
import holdout

PRIOR_STRENGTH = 25.0  # pseudo-plays of league mix added to each team-situation cell; fixed before any run, not tuned
METHOD = 'team_tendency_v1_log_odds_offense_defense'


def cell_key(row):
    return (int(row['down']), e0.ydstogo_bucket(row['ydstogo']), e0.yardline_bucket(row['yardline_100']))


def cell_name(cell):
    return '|'.join(str(part) for part in cell)


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class TeamTendencies:
    """Ratios of each team's event share to the league share, by situation cell. Frozen once built."""

    def __init__(self, ratios, manifest):
        self.ratios = ratios  # {'offense' | 'defense': {team: {cell_name: {event: ratio}}}}
        self.manifest = manifest

    def ratio(self, side, team, cell, event):
        by_team = self.ratios[side]
        if team not in by_team:
            raise ValueError(f'no {side} tendency for team {team!r} in the prior seasons')
        return by_team[team].get(cell_name(cell), {}).get(event, 1.0)


def build_from_pool(pool, target_season, prior_strength=PRIOR_STRENGTH):
    """Tendencies from a pool of prior-season samples, {cell: [(event, row, runoff, spot), ...]}."""
    holdout.refuse_if_holdout(target_season, 'team tendency')
    seasons = sorted({int(sample[1]['season']) for samples in pool.values() for sample in samples})
    if not seasons or seasons[-1] >= target_season:
        raise ValueError(f'team tendencies must come from seasons before {target_season}, got {seasons}')
    league = defaultdict(Counter)
    counts = {'offense': defaultdict(lambda: defaultdict(Counter)), 'defense': defaultdict(lambda: defaultdict(Counter))}
    plays = 0
    for cell, samples in pool.items():
        for event, row, _runoff, _spot in samples:
            plays += 1
            league[cell][event] += 1
            counts['offense'][row['posteam']][cell][event] += 1
            counts['defense'][row['defteam']][cell][event] += 1
    ratios = {}
    for side, by_team in counts.items():
        ratios[side] = {}
        for team, by_cell in by_team.items():
            ratios[side][team] = {}
            for cell, team_counts in by_cell.items():
                league_total = sum(league[cell].values())
                team_total = sum(team_counts.values())
                cell_ratios = {}
                for event, league_n in league[cell].items():
                    league_share = league_n / league_total
                    team_share = (team_counts[event] + prior_strength * league_share) / (team_total + prior_strength)
                    cell_ratios[event] = team_share / league_share
                ratios[side][team][cell_name(cell)] = cell_ratios
    values = [v for side in ratios.values() for team in side.values() for cell in team.values() for v in cell.values()]
    manifest = {
        'method': METHOD, 'target_season': target_season, 'tendency_seasons': seasons, 'tendency_plays': plays,
        'prior_strength': prior_strength, 'teams': sorted(counts['offense']),
        'ratio_range': [min(values), max(values)] if values else None,
        'tables_sha256': _sha(ratios),
    }
    manifest['sha256'] = _sha(manifest)
    return TeamTendencies(ratios, manifest)


def build_from_rows(rows, target_season, prior_strength=PRIOR_STRENGTH):
    """Tendencies from raw play rows (E1 columns) from seasons before the target season."""
    holdout.refuse_if_holdout(target_season, 'team tendency rows')
    pool, _excluded = e1.build_pool(rows)
    return build_from_pool(pool, target_season, prior_strength)


class TendencySampler:
    """Samples an observed pool play, weighting each event by both teams' situational tendencies."""

    def __init__(self, tendencies, side_teams=None):
        """`side_teams` maps the engine's side labels to team codes, e.g. {'A': home, 'B': away}. The engine passes
        sides, not team codes, so without the map a side label would be looked up as a team and fail closed."""
        self.tendencies = tendencies
        self.side_teams = dict(side_teams) if side_teams is not None else None
        self._cells = {}  # id(cell) -> (cell, entry); the cell is held so its id is not reused

    def _entry(self, cell):
        cached = self._cells.get(id(cell))
        if cached is not None:
            return cached[1]
        key = cell_key(cell[0][1])
        by_event = defaultdict(list)
        for sample in cell:
            if cell_key(sample[1]) != key:
                raise ValueError('a pool cell mixes situations; tendencies cannot be applied')
            by_event[sample[0]].append(sample)
        entry = {'key': key, 'base': Counter(sample[0] for sample in cell),
                 'by_event': {event: sorted(samples, key=lambda s: (s[1]['game_id'], s[1]['play_id']))
                              for event, samples in by_event.items()}}
        self._cells[id(cell)] = (cell, entry)
        return entry

    def _team(self, label):
        if self.side_teams is None:
            return label
        if label not in self.side_teams:
            raise ValueError(f'no team for side {label!r}; the side map is {sorted(self.side_teams)}')
        return self.side_teams[label]

    def sample(self, rng, cell, offense, defense):
        entry = self._entry(cell)
        offense, defense = self._team(offense), self._team(defense)
        events = [event for event in e1.EVENTS if entry['base'][event] > 0]
        weights = [entry['base'][event]
                   * self.tendencies.ratio('offense', offense, entry['key'], event)
                   * self.tendencies.ratio('defense', defense, entry['key'], event)
                   for event in events]
        if not events or sum(weights) <= 0:
            raise e1.SamplingUnavailable(f'team_tendency_no_supported_events:{offense}:{defense}')
        selected = rng.choices(events, weights=weights)[0]
        return rng.choice(entry['by_event'][selected])

    def describe(self):
        return {'method': METHOD, 'tendency_sha256': self.tendencies.manifest['sha256'],
                'side_teams': self.side_teams}
