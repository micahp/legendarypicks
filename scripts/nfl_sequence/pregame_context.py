"""Build cutoff-filtered NFL matchup context for the statistical game simulator.

The first predictive inputs are the existing opponent-adjusted LP v1 offensive and
defensive point ratings. Recent form, tendencies, game identity, and verified roster
facts are included for diagnostics and later ablations, but do not alter S0 by default.

Historical schedule scores and play-by-play rows are filtered by season/week. The
current database does not retain row-level publication/ingestion times for those
results, so the manifest labels this reconstruction chronological-only unless an
external immutable input manifest proves availability at the cutoff.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1] / 'backend'
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))
import holdout  # noqa: E402

SCHEMA = 'lp-nfl-pregame-context-1'
RATING_CONFIG = {'half_life': 6.0, 'cap': 14.0, 'prior_games': 4.0, 'prior_shrink': 1.0 / 3.0}
RATING_VERSION = 'nfl-v1-opponent-adjusted-points'
PBP_FIELDS = ('game_id', 'play_id', 'posteam', 'play_type', 'pass_attempt', 'rush_attempt', 'yards_gained', 'epa')


def _canonical_sha(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError('context as_of must be an ISO-8601 timestamp with a timezone') from exc
    if parsed.tzinfo is None:
        raise ValueError('context as_of must include a timezone')
    return parsed.astimezone(timezone.utc)


def _require_matchup(matchup: dict, as_of: str) -> dict:
    required = ('game_id', 'season', 'week', 'game_type', 'home_team', 'away_team')
    missing = [key for key in required if matchup.get(key) is None]
    if missing:
        raise ValueError(f'matchup is missing required identity fields: {", ".join(missing)}')
    try:
        season, week = int(matchup['season']), int(matchup['week'])
    except (TypeError, ValueError) as exc:
        raise ValueError('matchup season and week must be integers') from exc
    holdout.refuse_if_holdout(season, 'pregame context')
    if season < 2010 or week < 1 or week > 18:
        raise ValueError('context v1 supports regular-season weeks 1 through 18 from 2010 onward')
    if matchup['game_type'] != 'REG':
        raise ValueError('context v1 currently supports regular-season games only')
    if not matchup['home_team'] or not matchup['away_team'] or matchup['home_team'] == matchup['away_team']:
        raise ValueError('matchup must have two distinct team codes')
    cutoff = _timestamp(as_of)
    kickoff = matchup.get('scheduled_kickoff_utc')
    if kickoff and cutoff >= _timestamp(kickoff):
        raise ValueError('pregame context cutoff must precede scheduled kickoff')
    return {'season': season, 'week': week, 'cutoff': cutoff}


def _eligible_schedule(con: sqlite3.Connection, season: int, week: int):
    rows = con.execute(
        """SELECT game_id, season, week, game_type, home_team, away_team,
                  home_score, away_score, location, gameday
             FROM nfl_schedule
            WHERE game_type='REG' AND (season < ? OR (season = ? AND week < ?))
            ORDER BY season, week, game_id""", (season, season, week)).fetchall()
    incomplete = [row[0] for row in rows if row[6] is None or row[7] is None]
    if incomplete:
        raise ValueError(f'{len(incomplete)} eligible regular-season schedule rows lack final scores: {incomplete[:5]}')
    return rows


def _pbp_team_games(con: sqlite3.Connection, season: int, week: int):
    query = """SELECT p.game_id, p.play_id, p.posteam, p.play_type, p.pass_attempt,
                      p.rush_attempt, p.yards_gained, p.epa
                 FROM nfl_pbp p JOIN nfl_schedule s ON s.game_id=p.game_id
                WHERE s.game_type='REG' AND (s.season < ? OR (s.season = ? AND s.week < ?))
                  AND p.posteam IS NOT NULL AND p.play_type IN ('pass','run')
                  AND COALESCE(p.penalty,0)=0 AND COALESCE(p.two_point_attempt,0)=0
                ORDER BY s.season, s.week, p.game_id, p.play_id"""
    rows = con.execute(query, (season, season, week)).fetchall()
    grouped = defaultdict(lambda: {'pass_attempts': 0, 'rush_attempts': 0, 'yards': 0.0,
                                   'scrimmage_plays': 0, 'epa_sum': 0.0, 'epa_plays': 0})
    for game_id, _play_id, team, play_type, pass_att, rush_att, yards, epa in rows:
        stat = grouped[(game_id, team)]
        stat['pass_attempts'] += int(pass_att or 0)
        stat['rush_attempts'] += int(rush_att or 0)
        if yards is not None:
            stat['yards'] += float(yards)
            stat['scrimmage_plays'] += 1
        if epa is not None:
            stat['epa_sum'] += float(epa)
            stat['epa_plays'] += 1
    digest_rows = [tuple(row) for row in rows]
    return grouped, {'rows': len(rows), 'sha256': _canonical_sha(digest_rows)}


def _rates(stats: dict | None) -> dict:
    stats = stats or {}
    passes = int(stats.get('pass_attempts', 0))
    runs = int(stats.get('rush_attempts', 0))
    attempts = passes + runs
    scrimmage = int(stats.get('scrimmage_plays', 0))
    epa_plays = int(stats.get('epa_plays', 0))
    return {
        'pass_attempts': passes,
        'rush_attempts': runs,
        'pass_attempt_share': passes / attempts if attempts else None,
        'yards_per_scrimmage_play': stats.get('yards', 0.0) / scrimmage if scrimmage else None,
        'epa_per_play': stats.get('epa_sum', 0.0) / epa_plays if epa_plays else None,
        'scrimmage_plays': scrimmage,
        'epa_plays': epa_plays,
    }


def _aggregate_games(games: list[dict]) -> dict:
    n = len(games)
    out = {'games': n}
    if not n:
        out.update({'points_for': None, 'points_against': None, 'pass_attempt_share': None,
                    'yards_per_scrimmage_play': None, 'epa_per_play': None})
        return out
    out['points_for'] = sum(g['points_for'] for g in games) / n
    out['points_against'] = sum(g['points_against'] for g in games) / n
    raw = [g['pbp'] for g in games if g['pbp'] is not None]
    combined = {key: sum(x.get(key, 0) for x in raw)
                for key in ('pass_attempts', 'rush_attempts', 'yards', 'scrimmage_plays', 'epa_sum', 'epa_plays')}
    out.update(_rates(combined))
    out['pbp_games'] = len(raw)
    return out


def _personnel(snapshot: dict | None, side: str) -> dict:
    if not snapshot:
        return {'status': 'unavailable'}
    roster = snapshot.get('rosters', {}).get(side)
    if not roster:
        return {'status': 'unavailable'}
    players = roster.get('players', [])
    full_pin = snapshot.get('roster_snapshot_source', {}).get('full_depth_roster_sha256')
    verified = bool(full_pin and all(isinstance(p.get('starter'), bool) and p.get('jersey_number') is not None
                                     for p in players))
    qbs = [p for p in players if p.get('pos_abb') == 'QB' and p.get('pos_rank') == 1
           and p.get('starter') is True]
    return {
        'status': 'verified_full_depth' if verified else 'present_unverified',
        'roster_snapshot_id': snapshot.get('roster_snapshot_id'),
        'player_rows': len(players),
        'starter_rows': sum(bool(p.get('starter')) for p in players),
        'starting_qb': ({'player_id': qbs[0].get('player_id'), 'gsis_id': qbs[0].get('gsis_id'),
                         'jersey_number': qbs[0].get('jersey_number')} if len(qbs) == 1 else None),
    }


def build_from_connection(con: sqlite3.Connection, matchup: dict, as_of: str,
                          snapshot: dict | None = None, ratings_backend=None) -> dict:
    """Build a context from the versioned matchup identity and a read-only DB connection.

    The caller must pass identity from a frozen pregame snapshot or immutable v1 lock.
    The schedule itself is not re-read from the latest row to infer historical identity.
    """
    timing = _require_matchup(matchup, as_of)
    season, week = timing['season'], timing['week']
    eligible = _eligible_schedule(con, season, week)
    cutoff_day = timing['cutoff'].date().isoformat()
    same_season_not_finished = [row[0] for row in eligible
                                if int(row[1]) == season and row[9] and str(row[9])[:10] >= cutoff_day]
    if same_season_not_finished:
        raise ValueError('prior-week schedule includes a game dated on/after the context cutoff: '
                         + ', '.join(same_season_not_finished[:5]))
    pbp, pbp_pin = _pbp_team_games(con, season, week)

    if ratings_backend is None:
        import nfl_ratings_data as ratings_backend  # noqa: E402
    rating_kwargs = {k: v for k, v in RATING_CONFIG.items() if k != 'prior_shrink'}
    prior = ratings_backend.prior_for_season(con, season, shrink=RATING_CONFIG['prior_shrink'], **rating_kwargs)
    if week == 1:
        teams = ratings_backend.teams_in_season(con, season)
        if not teams:
            raise ValueError(f'no regular-season teams for target season {season}')
        ratings = {team: prior.get(team, (0.0, 0.0)) for team in teams}
        rating_games = 0
    else:
        ratings_fit, rating_games = ratings_backend.fit_for_week(con, season, week, prior=prior, **rating_kwargs)
        ratings = {team: (ratings_fit.o[team], ratings_fit.d[team]) for team in ratings_fit.o}

    game_rows: dict[str, list[dict]] = defaultdict(list)
    current_record = {team: {'wins': 0, 'losses': 0, 'ties': 0} for team in
                      (matchup['home_team'], matchup['away_team'])}
    for row in eligible:
        gid, yr, wk, _game_type, home, away, hs, aws, _location, gameday = row
        for team, pf, pa in ((home, hs, aws), (away, aws, hs)):
            stat = pbp.get((gid, team))
            game_rows[team].append({'game_id': gid, 'season': int(yr), 'week': int(wk),
                                    'points_for': int(pf), 'points_against': int(pa),
                                    'gameday': gameday, 'pbp': stat})
            if int(yr) == season and team in current_record:
                if pf > pa:
                    current_record[team]['wins'] += 1
                elif pf < pa:
                    current_record[team]['losses'] += 1
                else:
                    current_record[team]['ties'] += 1

    sides = {'home': matchup['home_team'], 'away': matchup['away_team']}
    team_context = {}
    for side, team in sides.items():
        prior_games = sorted(game_rows.get(team, []), key=lambda g: (g['season'], g['week'], g['game_id']))
        recent = {}
        for count in (3, 5):
            selected = prior_games[-count:]
            recent[f'last_{count}'] = _aggregate_games(selected)
            recent[f'last_{count}']['game_ids'] = [g['game_id'] for g in selected]
        season_games = [g for g in prior_games if g['season'] == season]
        offense_rating, defense_rating = ratings.get(team, (None, None))
        team_context[side] = {
            'team': team,
            'record_before_game': {'season': season, 'games': sum(current_record[team].values()), **current_record[team]},
            'season_to_date': _aggregate_games(season_games),
            'recent_form': recent,
            'opponent_adjusted': {
                'offense_points_rating': offense_rating,
                'defense_strength_points_rating': defense_rating,
                'model': RATING_VERSION,
                'fit_games': rating_games,
            },
            'personnel': _personnel(snapshot, side),
        }

    schedule_projection = [tuple(row) for row in eligible]
    schedule_pin = {'rows': len(schedule_projection), 'sha256': _canonical_sha(schedule_projection)}
    location = (matchup.get('location') or '').strip().lower()
    context = {
        'schema': SCHEMA,
        'game': {
            'game_id': matchup['game_id'], 'season': season, 'week': week, 'game_type': matchup['game_type'],
            'as_of': _timestamp(as_of).isoformat().replace('+00:00', 'Z'),
            'home_team': matchup['home_team'], 'away_team': matchup['away_team'],
            'home_away': {'home': matchup['home_team'], 'away': matchup['away_team']},
            'neutral_site': location == 'neutral',
            'phase': 'regular_season',
        },
        'teams': team_context,
        'source_manifest': {
            'rating_model': {'version': RATING_VERSION, **RATING_CONFIG},
            'schedule_input': schedule_pin,
            'play_by_play_input': pbp_pin,
            'eligibility': {'prior_seasons': 'all completed regular-season games before target season',
                            'target_season': f'weeks 1 through {week - 1}',
                            'same_week_rows_excluded': True},
            'availability': {
                'classification': 'chronological_filter_only',
                'historical_replay_fairness': 'exploratory_until_row_level_input_availability_is_verified',
                'limitations': ['nfl_pbp has no row-level ingested_at/version timestamp',
                                'nfl_schedule score history is not versioned by this manifest'],
            },
            'snapshot_sha256': snapshot.get('snapshot_sha256') if snapshot else None,
        },
    }
    context['context_sha256'] = _canonical_sha(context)
    return context


def build(db: str, matchup: dict, as_of: str, snapshot: dict | None = None) -> dict:
    """Open the configured SQLite database read-only and build a context snapshot."""
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=30)
    try:
        return build_from_connection(con, matchup, as_of, snapshot=snapshot)
    finally:
        con.close()
