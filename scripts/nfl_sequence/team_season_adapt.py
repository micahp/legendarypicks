"""Current-season team tendencies for SLC V1.5 (research, off by default).

The V1 team layer (team_tendency.py) reads each team's situational event shares from seasons before the target. This
module blends 2026 evidence into those tendencies without changing the historical builder:

    P_V15 = (N0 * P_hist + n * P_season) / (N0 + n)

for each team, side, situation cell and event. P_hist is the V1 share (historical ratio times historical league share).
P_season is the current-season share, shrunk toward the historical league share with V1's prior strength. n is that
team's current-season play count in the cell, so a team with little 2026 evidence in a cell keeps most of its history.
With n = 0 the V1 ratio is returned unchanged.

Cutoff safety: a game is used only if its result was available at the target's cutoff. The result is available
AVAILABILITY_LAG_HOURS after kickoff, and the cutoff is CUTOFF_MINUTES before the target's own kickoff. The target game
is excluded by the same rule and by id. A game whose kickoff cannot be dated is excluded and listed in the manifest.
"""
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import pytz

import current_season_adapt as csa
import e1_drive as e1
import holdout
import team_tendency as tt

CUTOFF_MINUTES = 90
AVAILABILITY_LAG_HOURS = 10
EASTERN = pytz.timezone('America/New_York')
METHOD = 'team_tendency_v15_season_blend'


def kickoff_utc(gameday, gametime):
    """Kickoff in UTC from the schedule's local date and time. nfl_schedule publishes gametime in America/New_York."""
    local = EASTERN.localize(datetime.strptime(f'{gameday} {gametime}', '%Y-%m-%d %H:%M'))
    return local.astimezone(pytz.utc)


def cutoff_utc(kickoff):
    return kickoff - timedelta(minutes=CUTOFF_MINUTES)


def available_games(schedule_rows, season, cutoff, target_game_id):
    """(game ids whose result is available at `cutoff`, undated game ids). The target game never counts."""
    holdout.refuse_unless_cutoff(season, 'current-season team tendencies', cutoff)
    available, undated = [], []
    for row in schedule_rows:
        if int(row['season']) != season or row['game_id'] == target_game_id:
            continue
        if not row['gameday'] or not row['gametime']:
            undated.append(row['game_id'])
            continue
        available_at = kickoff_utc(row['gameday'], row['gametime']) + timedelta(hours=AVAILABILITY_LAG_HOURS)
        if available_at <= cutoff:
            available.append(row['game_id'])
    return sorted(available), sorted(undated)


def load_schedule(db, season):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        cursor = con.execute("SELECT game_id, season, week, gameday, gametime FROM nfl_schedule "
                             "WHERE season = ? AND game_type = 'REG'", (season,))
        return [dict(zip(('game_id', 'season', 'week', 'gameday', 'gametime'), r)) for r in cursor]
    finally:
        con.close()


def load_plays(db, season, game_ids, cutoff):
    """Play rows of the given games, in game order. Every read is cutoff-bounded, so the holdout check passes."""
    holdout.refuse_unless_cutoff(season, 'current-season plays', cutoff)
    if not game_ids:
        return []
    marks = ', '.join('?' for _ in game_ids)
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        query = (f"SELECT {', '.join(e1.COLUMNS)} FROM nfl_pbp WHERE season = ? AND game_id IN ({marks}) "
                 "ORDER BY game_id, play_id")
        return [dict(zip(e1.COLUMNS, r)) for r in con.execute(query, (season, *game_ids))]
    finally:
        con.close()


def adapt(hist, rows, n0=csa.DEFAULT_N0, prior_strength=tt.PRIOR_STRENGTH, focus_teams=(), team_games=None):
    """(TeamTendencies with current-season evidence blended in, diagnostics).

    `rows` are current-season play rows already filtered to games available at the cutoff. With no rows the historical
    object is returned unchanged. A cell with no historical league share cannot be blended; its plays are counted in the
    diagnostics and left at the historical value.

    `team_games` ({team: games available at the cutoff}, SLC V1.5 every-layer rule) sets the weight on history to
    N0 / (N0 + the team's games), the predeclared rule. Without it the weight uses the cell's play count n, as before."""
    league_shares = hist.league_shares  # {cell name: {event: historical league share}}; moves between shares and ratios
    diagnostics = {'method': METHOD, 'n0': float(n0), 'prior_strength': float(prior_strength), 'plays': len(rows),
                   'weight_unit': 'cell plays' if team_games is None else 'team games',
                   'cells_blended': 0, 'cells_without_history': 0, 'plays_without_history_cell': 0,
                   'focus': {}}
    if not rows:
        return hist, diagnostics
    pool, _excluded = e1.build_pool(rows)
    counts = {'offense': defaultdict(lambda: defaultdict(Counter)), 'defense': defaultdict(lambda: defaultdict(Counter))}
    for cell, samples in pool.items():
        cname = tt.cell_name(cell)
        for event, row, _runoff, _spot in samples:
            if cname not in league_shares:
                diagnostics['plays_without_history_cell'] += 1
                continue
            counts['offense'][row['posteam']][cname][event] += 1
            counts['defense'][row['defteam']][cname][event] += 1
    ratios = {side: {team: {cname: dict(events) for cname, events in by_cell.items()}
                     for team, by_cell in by_team.items()}
              for side, by_team in hist.ratios.items()}
    for side, by_team in counts.items():
        for team, by_cell in by_team.items():
            for cname, season_counts in by_cell.items():
                n = sum(season_counts.values())
                evidence = n if team_games is None else team_games.get(team, 0)
                shares = league_shares[cname]
                team_ratios = ratios[side].setdefault(team, {})
                historical = team_ratios.get(cname, {})
                blended = {}
                focus_rows = {}
                for event, league_share in shares.items():
                    hist_share = historical.get(event, 1.0) * league_share
                    season_share = (season_counts[event] + prior_strength * league_share) / (n + prior_strength)
                    share = csa.blend_probability(hist_share, season_share, evidence, n0)
                    blended[event] = share / league_share
                    if team in focus_teams:
                        focus_rows[event] = {'historical_share': hist_share, 'season_share': season_share,
                                             'blended_share': share}
                team_ratios[cname] = blended
                diagnostics['cells_blended'] += 1
                if team not in hist.ratios.get(side, {}):
                    diagnostics['cells_without_history'] += 1
                if team in focus_teams:
                    key = f'{side}:{team}:{cname}'
                    diagnostics['focus'][key] = {'n': n, 'weight_on_history': csa.effective_weight_on_history(evidence, n0),
                                                 'events': focus_rows}
    values = [v for side in ratios.values() for team in side.values() for cell in team.values() for v in cell.values()]
    manifest = {'method': METHOD, 'historical_sha256': hist.manifest['sha256'], 'n0': float(n0),
                'weight_unit': diagnostics['weight_unit'],
                'prior_strength': float(prior_strength), 'season_plays': len(rows),
                'ratio_range': [min(values), max(values)] if values else None,
                'tables_sha256': tt._sha(ratios)}
    manifest['sha256'] = tt._sha(manifest)
    adapted = tt.TeamTendencies(ratios, manifest, league_shares=league_shares)
    return adapted, diagnostics


def build_for_target(db, season, target_game_id, kickoff, hist, n0=csa.DEFAULT_N0, focus_teams=(), team_games=None):
    """The adapted tendencies for one target game: only games whose results were available at its cutoff are used."""
    cutoff = cutoff_utc(kickoff)
    schedule = load_schedule(db, season)
    game_ids, undated = available_games(schedule, season, cutoff, target_game_id)
    rows = load_plays(db, season, game_ids, cutoff)
    tendencies, diagnostics = adapt(hist, rows, n0=n0, focus_teams=focus_teams, team_games=team_games)
    diagnostics.update({'target_game_id': target_game_id, 'cutoff_utc': cutoff.isoformat(),
                        'season_games': game_ids, 'undated_games': undated})
    return tendencies, diagnostics
