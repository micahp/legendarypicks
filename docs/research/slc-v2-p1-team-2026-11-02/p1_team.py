"""P1: team play-calling component (SLC v2 Milestone 3).

Three team-game metrics, each forecast the same way:
- pass_share: pass plays over run plus pass plays (regular season).
- plays: run plus pass plays in the game (tempo proxy).
- go_rate: fourth-down run or pass plays over fourth-down run, pass, punt and field-goal decisions (aggression).

The estimate shrinks the team's usable in-season values toward a prior with K = 4 pseudo-games. The prior, in order of
preference: (1) the head coach's prior-season mean of the metric across all team-games, if the coach has at least
MIN_COACH_GAMES prior-season team-games; (2) the team's prior-season mean; (3) the league prior-season mean.

Head-coach identity is carried from the team's latest usable earlier game. The target game's schedule row is never used
(owner ruling P1). Usable means the game's kickoff plus the 10-hour lag is at or before the final-horizon cutoff.

Baseline (frozen): the league prior-season mean, no team or coach information.
"""
import datetime as dt
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'slc-v2-p2-usage-2026-11-02'))
sys.path.insert(0, os.path.join(HERE, '..', 'slc-v2-depth-adapter-2026-11-02'))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'scripts'))
import p2_usage as p2  # noqa: E402
import depth_adapter as da  # noqa: E402
from nfl_team_codes import to_nflverse_team_code  # noqa: E402

RAW = '/root/gridiron-playbooks-research/data/raw'
DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
MIN_COACH_GAMES = 8
K = 4
METRICS = ('pass_share', 'plays', 'go_rate')


def usable(game, cutoff):
    return p2.usable(game, cutoff)


def carried_coach(history, cutoff, prior_season_last):
    rows = [g for g in history if usable(g, cutoff)]
    if rows:
        latest = max(rows, key=lambda g: g['kickoff'])
        return latest['coach'], 'usable_game'
    if prior_season_last:
        return prior_season_last, 'prior_season_last'
    return 'UNKNOWN', 'none'


def prior_for(coach, team, prior_by_coach, prior_by_team, league):
    if coach in prior_by_coach and prior_by_coach[coach][0] >= MIN_COACH_GAMES:
        return prior_by_coach[coach][1], 'coach_era'
    if team in prior_by_team:
        return prior_by_team[team][1], 'team_prior'
    return league, 'league_prior'


def team_feature(history, target, prior, prior_source, k=K, metric='pass_share'):
    cutoff = target['kickoff'] - dt.timedelta(hours=1)
    rows = [g for g in history if g['team'] == target['team'] and g['season'] == target['season'] and usable(g, cutoff)]
    observed = [g for g in rows if g[metric] is not None]
    values = [g[metric] for g in observed]
    return {
        'team': target['team'], 'season': target['season'], 'game_id': target['game_id'],
        'metric': metric, 'games_used': len(values), 'game_ids_used': [g['game_id'] for g in observed],
        'null_metric_games': len(rows) - len(observed),
        'prior': prior, 'prior_source': prior_source,
        'estimate': (sum(values) + k * prior) / (len(values) + k), 'cutoff': cutoff,
    }


def load_team_games(seasons):
    import pandas as pd
    con = sqlite3.connect(DB, uri=True)
    try:
        schedule = con.execute("select game_id, gameday, gametime, home_team, away_team, home_coach, away_coach "
                               "from nfl_schedule where game_type = 'REG'").fetchall()
    finally:
        con.close()
    kickoffs, schedule_rows = {}, {}
    for game_id, gameday, gametime, home, away, home_coach, away_coach in schedule:
        if not gametime:
            continue
        kickoffs[game_id] = da.game_horizons(gameday, gametime)[1] + dt.timedelta(hours=1)
        schedule_rows[game_id] = (to_nflverse_team_code(home), to_nflverse_team_code(away), home_coach, away_coach)
    records, unmatched = [], 0
    for season in seasons:
        pbp = pd.read_csv(os.path.join(RAW, f'pbp_{season}.csv.gz'), compression='gzip', low_memory=False,
                          usecols=['game_id', 'season_type', 'posteam', 'play_type', 'down'])
        pbp = pbp[(pbp['season_type'] == 'REG') & pbp['posteam'].notna()]
        scrimmage = pbp[pbp['play_type'].isin(['run', 'pass'])]
        totals = scrimmage.groupby(['game_id', 'posteam']).agg(
            plays=('play_type', 'size'), passes=('play_type', lambda s: int((s == 'pass').sum())))
        fourth = pbp[(pbp['down'] == 4) & pbp['play_type'].isin(['run', 'pass', 'punt', 'field_goal'])]
        decisions = fourth.groupby(['game_id', 'posteam']).agg(
            dec4=('play_type', 'size'), go4=('play_type', lambda s: int(s.isin(['run', 'pass']).sum())))
        merged = totals.join(decisions, how='left').reset_index()
        for row in merged.itertuples(index=False):
            info = schedule_rows.get(row.game_id)
            kickoff = kickoffs.get(row.game_id)
            if info is None or kickoff is None or row.posteam not in info[:2]:
                unmatched += 1
                continue
            home, away, home_coach, away_coach = info
            coach = home_coach if row.posteam == home else away_coach
            has_dec = row.dec4 == row.dec4 and row.dec4 > 0
            records.append({'team': row.posteam, 'season': season, 'game_id': row.game_id, 'game_type': 'REG',
                            'kickoff': kickoff, 'coach': coach,
                            'pass_share': row.passes / row.plays, 'plays': float(row.plays),
                            'go_rate': (row.go4 / row.dec4) if has_dec else None})
    return records, unmatched


def main():
    raise SystemExit('run p1_eval.py')


if __name__ == '__main__':
    main()
