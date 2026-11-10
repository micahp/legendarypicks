"""Research transition strengths for SLC.

The table models the joint event and gain bucket for a situation cell. Offensive
and defensive ratios are estimated separately, shrunk toward the league mix, then
multiplied at sampling time. It is an opt-in replacement for event-only team
tendencies; it is not part of the V2 default until walk-forward scoring supports it.

Penalty outcomes are not represented because the current SLC play pool does not
preserve reliable penalty labels. Kicks and turnovers are represented by event;
run, completion, and sack outcomes also carry a yardage bucket.
"""
import hashlib
import json
import math
from collections import Counter, defaultdict

import e1_drive as e1
import holdout

METHOD = 'slc_joint_team_transition_strength_v1'
PRIOR_STRENGTH = 50.0
YARDAGE_EVENTS = frozenset(('run', 'pass_complete', 'sack'))


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def cell_name(cell):
    return '|'.join(str(part) for part in cell)


def yardage_bucket(value):
    """Stable bins retaining negative plays, line-to-gain ranges, and explosive gains."""
    if value is None:
        return 'unknown'
    yards = int(value)
    if yards < 0:
        return 'loss'
    if yards == 0:
        return 'zero'
    if yards <= 2:
        return '1_2'
    if yards <= 5:
        return '3_5'
    if yards <= 9:
        return '6_9'
    if yards <= 19:
        return '10_19'
    return '20_plus'


def transition_key(event, row):
    if event in YARDAGE_EVENTS:
        pieces = [event, yardage_bucket(row.get('yards_gained'))]
        if event in ('run', 'pass_complete'):
            gained = int(row['yards_gained']) if row.get('yards_gained') is not None else 0
            converted = bool(row.get('touchdown') == 1 or
                             (row.get('ydstogo') is not None and gained >= int(row['ydstogo'])))
            pieces.extend(('converted' if converted else 'not_converted',
                           'touchdown' if row.get('touchdown') == 1 else 'no_touchdown'))
        return ':'.join(pieces)
    return f'{event}:event'


class TransitionStrength:
    """Smoothed offense and defense likelihood ratios for joint event/yardage transitions."""

    def __init__(self, ratios, league_shares, manifest):
        self.ratios = ratios
        self.league_shares = league_shares
        self.manifest = manifest
        self.fallbacks = Counter()
        self.fallback_count = 0

    def ratio(self, side, team, cell, event, row):
        return self.ratio_key(side, team, cell, transition_key(event, row))

    def ratio_key(self, side, team, cell, key):
        if team not in self.ratios[side]:
            raise ValueError(f'no {side} transition strength for team {team!r}')
        cname = cell_name(cell)
        ratio = self.ratios[side][team].get(cname, {}).get(key)
        if ratio is None:
            self.fallbacks[(side, team, cname, key)] += 1
            self.fallback_count += 1
            return 1.0
        return ratio

    def describe(self, side_teams=None):
        return {'method': METHOD, 'table_sha256': self.manifest['sha256'],
                'manifest': self.manifest, 'side_teams': side_teams,
                'fallbacks': [{'side': side, 'team': team, 'cell': cell, 'transition': key, 'count': count}
                              for (side, team, cell, key), count in sorted(self.fallbacks.items())]}


def _counts(pool):
    league = defaultdict(Counter)
    teams = {'offense': defaultdict(lambda: defaultdict(Counter)),
             'defense': defaultdict(lambda: defaultdict(Counter))}
    plays = 0
    seasons = set()
    for cell, samples in pool.items():
        cname = cell_name(cell)
        for event, row, _runoff, _spot in samples:
            key = transition_key(event, row)
            league[cname][key] += 1
            teams['offense'][row['posteam']][cname][key] += 1
            teams['defense'][row['defteam']][cname][key] += 1
            seasons.add(int(row['season']))
            plays += 1
    return league, teams, plays, sorted(seasons)


def _manifest(ratios, target_season, seasons, plays, prior_strength, parent=None):
    manifest = {'method': METHOD, 'target_season': int(target_season), 'fit_seasons': list(seasons),
                'plays': int(plays), 'prior_strength': float(prior_strength), 'parent_sha256': parent,
                'modeled_components': ['event_type', 'yardage_bucket', 'line_to_gain', 'offensive_touchdown'],
                'unmodeled_components': ['penalties', 'play_clock', 'special_team_kick_execution'],
                'ratio_sha256': _sha(ratios)}
    manifest['sha256'] = _sha(manifest)
    return manifest


def build_from_pool(pool, target_season, prior_strength=PRIOR_STRENGTH, cutoff=None):
    """Fit prior-season transition ratios from an E1 pool and enforce the season cutoff."""
    holdout.refuse_unless_cutoff(target_season, 'team transition strength', cutoff)
    if not math.isfinite(float(prior_strength)) or float(prior_strength) <= 0:
        raise ValueError('transition prior strength must be positive and finite')
    league_counts, team_counts, plays, seasons = _counts(pool)
    if not seasons or seasons[-1] >= int(target_season):
        raise ValueError(f'transition strengths must use seasons before {target_season}, got {seasons}')
    league_shares = {cell: {key: count / sum(counts.values()) for key, count in counts.items()}
                     for cell, counts in league_counts.items()}
    ratios = {side: {} for side in ('offense', 'defense')}
    for side, by_team in team_counts.items():
        for team, by_cell in by_team.items():
            ratios[side][team] = {}
            for cell, counts in by_cell.items():
                base = league_shares[cell]
                n = sum(counts.values())
                ratios[side][team][cell] = {
                    key: ((counts[key] + prior_strength * share) / (n + prior_strength)) / share
                    for key, share in base.items() if share > 0
                }
    manifest = _manifest(ratios, target_season, seasons, plays, prior_strength)
    manifest['teams'] = sorted(ratios['offense'])
    manifest['league_cells'] = len(league_shares)
    manifest['sha256'] = _sha({key: value for key, value in manifest.items() if key != 'sha256'})
    return TransitionStrength(ratios, league_shares, manifest)


def adapt(hist, rows, *, n0, team_games, prior_strength=PRIOR_STRENGTH):
    """Blend cutoff-safe current-season team transition shares into the frozen historical profile."""
    if not math.isfinite(float(n0)) or float(n0) <= 0:
        raise ValueError('transition season-adaptation n0 must be positive and finite')
    if not math.isfinite(float(prior_strength)) or float(prior_strength) <= 0:
        raise ValueError('transition prior strength must be positive and finite')
    known_penalty_rows = [row for row in rows if row.get('penalty') is not None]
    unknown_penalty_rows = len(rows) - len(known_penalty_rows)
    pool, excluded = e1.build_pool(known_penalty_rows)
    _league_counts, team_counts, plays, seasons = _counts(pool)
    if len(seasons) > 1:
        raise ValueError(f'current transition update contains multiple seasons: {seasons}')
    ratios = {side: {team: {cell: dict(values) for cell, values in by_cell.items()}
                     for team, by_cell in by_team.items()} for side, by_team in hist.ratios.items()}
    cells_blended = 0
    cells_without_history = 0
    for side, by_team in team_counts.items():
        for team, by_cell in by_team.items():
            team_table = ratios[side].setdefault(team, {})
            for cell, counts in by_cell.items():
                base = hist.league_shares.get(cell)
                if not base:
                    cells_without_history += 1
                    continue
                n = sum(counts.values())
                current_games = int(team_games.get(team, 0))
                history_weight = float(n0) / (float(n0) + current_games) if current_games else 1.0
                historical = team_table.get(cell, {})
                updated = dict(historical)
                for key, league_share in base.items():
                    hist_share = historical.get(key, 1.0) * league_share
                    season_share = (counts[key] + prior_strength * league_share) / (n + prior_strength)
                    share = history_weight * hist_share + (1.0 - history_weight) * season_share
                    updated[key] = share / league_share
                team_table[cell] = updated
                cells_blended += 1
    fit_seasons = sorted(set(hist.manifest['fit_seasons']) | set(seasons))
    manifest = _manifest(ratios, hist.manifest['target_season'], fit_seasons, plays,
                         prior_strength, parent=hist.manifest['sha256'])
    manifest.update({'season_update': True, 'n0': float(n0), 'team_games': dict(sorted(team_games.items())),
                     'cells_blended': cells_blended, 'cells_without_history': cells_without_history,
                     'rows_excluded_unknown_penalty_status': unknown_penalty_rows,
                     'excluded': dict(sorted(excluded.items()))})
    manifest['sha256'] = _sha({key: value for key, value in manifest.items() if key != 'sha256'})
    return TransitionStrength(ratios, hist.league_shares, manifest)


def build_from_rows(rows, target_season, prior_strength=PRIOR_STRENGTH, cutoff=None):
    holdout.refuse_unless_cutoff(target_season, 'team transition rows', cutoff)
    pool, _excluded = e1.build_pool(rows)
    return build_from_pool(pool, target_season, prior_strength, cutoff=cutoff)
