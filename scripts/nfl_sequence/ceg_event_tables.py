#!/usr/bin/env python3
"""SLC-CEG Phase 1: canonical event tables from the published nflverse play-by-play (research). Read-only on its inputs.

Built from the full nflverse population, before any SLC pool filter: penalties, turnover touchdowns, the last snap of a
quarter, scrambles, kneels, spikes, tries, kickoffs and overtime are all kept. Only rows that are not snaps are set apart,
and they are kept too: timeout rows (play_type null, timeout == 1) and administrative rows (game start, quarter end).

One physical row per play, keyed by (game_id, play_id), in four tables, so a model cannot read a column from the wrong
side of the snap:

  decision   known before the snap: game, clock, down, distance, field, score, timeouts, weather, xpass.
  labels     what happened: play class, dropback outcome, turnover, penalty, scoring, and the offense's own choices at the
             snap (shotgun, no huddle, run location), which are model targets, never inputs.
  post       quantities the play produced and the transition to the next snap: yards, air yards, YAC, returns, kick
             distance, penalty yards, next snap, clock runoff, the clock-stop class.
  people     player ids on the play.

The opportunity datasets of the Phase 1 review (play_decisions, dropbacks, pass_attempts, ...) are views: a filter and
a denominator over these tables, defined once in VIEWS. Every table carries season, week and game_date; `cutoff()` cuts
any of them at a forecast instant.

Play classes (labels.play_class), lowest precedence first (a later rule overrides an earlier one):
  admin, timeout, other, designed_run (play_type run), dropback (qb_dropback), scramble (qb_scramble), spike, kneel,
  field_goal, punt, kickoff, extra_point, two_point (two_point_attempt), no_play (play_type no_play), and last timeout:
  nflverse files a timeout as a no_play row with timeout == 1, so a no_play row with a timeout and no penalty is a timeout,
  not a snap. A timeout flag on a real play (a few dozen a season) stays on that play.

Clock: the play-by-play has the game clock only at each snap. clock_runoff_seconds is this snap's game clock minus the
next snap's, in the same quarter. It is live-play time plus any dead-ball time while the clock runs. clock_stop_class
marks plays after which the clock is stopped until the next snap (incomplete pass, score, change of possession, a
timeout row before the next snap, out of bounds inside the last 2:00 of the first half or 5:00 of the second half);
for those, the runoff is live-play time alone. That split is how live duration and dead-ball runoff are separated.

Usage: python3 ceg_event_tables.py --raw DIR --out DIR --doc-dir DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

SEASONS = (2022, 2023, 2024, 2025, 2026)
KEY = ['game_id', 'play_id']
TIME = ['season', 'week', 'season_type', 'game_date']
SNAP_CLASSES = ('designed_run', 'dropback', 'scramble', 'spike', 'kneel', 'field_goal', 'punt', 'kickoff', 'extra_point',
                'two_point', 'no_play')
SCRIMMAGE = ('designed_run', 'dropback', 'scramble', 'spike', 'kneel')

# column -> timing class. pre_snap: known before the snap. offense_choice: chosen by the offense at the snap (a target).
# realized_event: what happened. intermediate: a quantity inside the play. transition: the state after the play.
DECISION = {c: 'pre_snap' for c in (
    'posteam', 'defteam', 'home_team', 'away_team', 'posteam_type', 'qtr', 'quarter_seconds_remaining',
    'half_seconds_remaining', 'game_seconds_remaining', 'down', 'ydstogo', 'yardline_100', 'goal_to_go',
    'score_differential', 'posteam_score', 'defteam_score', 'posteam_timeouts_remaining', 'defteam_timeouts_remaining',
    'roof', 'surface', 'temp', 'wind', 'xpass', 'fixed_drive')}
LABELS = {**{c: 'offense_choice' for c in ('shotgun', 'no_huddle', 'pass_location', 'run_location', 'run_gap')},
          **{c: 'realized_event' for c in (
              'play_type', 'play_type_nfl', 'qb_dropback', 'qb_scramble', 'qb_kneel', 'qb_spike', 'sack', 'pass_attempt',
              'rush_attempt', 'complete_pass', 'incomplete_pass', 'interception', 'fumble', 'fumble_lost',
              'fumble_recovery_1_team', 'touchdown', 'td_team', 'safety', 'penalty', 'penalty_type', 'penalty_team',
              'first_down_penalty', 'field_goal_result', 'extra_point_result', 'two_point_conv_result', 'two_point_attempt',
              'punt_blocked', 'touchback', 'own_kickoff_recovery', 'aborted_play', 'replay_or_challenge', 'timeout',
              'timeout_team', 'fixed_drive_result', 'first_down')}}
POST = {**{c: 'intermediate' for c in ('air_yards', 'yards_after_catch', 'return_yards', 'kick_distance')},
        **{c: 'realized_event' for c in ('yards_gained', 'penalty_yards', 'out_of_bounds')},
        'total_home_score': 'transition', 'total_away_score': 'transition'}
PEOPLE = ('passer_player_id', 'rusher_player_id', 'receiver_player_id', 'kicker_player_id', 'punter_player_id',
          'kickoff_returner_player_id', 'punt_returner_player_id', 'interception_player_id', 'fumbled_1_player_id')

# The opportunity datasets: (filter over labels.play_class and labels columns, denominator, targets).
VIEWS = {
    'play_decisions': ("play_class in ('designed_run','dropback','scramble','spike','kneel','punt','field_goal')",
                       'scrimmage snap with a play call (pre-snap penalties are in penalties)',
                       'intent: run, dropback (dropback or scramble), punt, field goal, kneel, spike'),
    'dropbacks': ("play_class in ('dropback','scramble')", 'dropback', 'pass attempt, sack, scramble, no attempt'),
    'pass_attempts': ("play_class == 'dropback' and pass_attempt == 1 and sack != 1", 'pass attempt (sacks excluded)',
                      'complete, incomplete, interception; receiver; air yards'),
    'pass_completions': ("complete_pass == 1", 'completion', 'yards after catch, fumble'),
    'designed_runs': ("play_class == 'designed_run'", 'designed carry (scrambles and kneels excluded)', 'yards, fumble'),
    'scrambles': ("play_class == 'scramble'", 'QB scramble', 'yards, fumble'),
    'turnovers': ("interception == 1 or fumble == 1", 'interception or fumble (lost or not)',
                  'recovering team, return yards, defensive touchdown'),
    'penalties': ("play_class in ('designed_run','dropback','scramble','spike','kneel','punt','field_goal','kickoff',"
                  "'extra_point','two_point','no_play')", 'snap (every play class, including no_play)',
                  'penalty, type, team, yards, first down by penalty'),
    'special_teams': ("play_class in ('kickoff','punt','field_goal','extra_point')", 'kick',
                      'result, distance, return, touchback, block, recovering team'),
    'clock_events': ("play_class in ('designed_run','dropback','scramble','spike','kneel','punt','field_goal','kickoff',"
                     "'extra_point','two_point','no_play')", 'snap followed by a snap in the same quarter',
                     'runoff to the next snap, clock-stop class, timeout before the next snap'),
    'strategic_decisions': ("(down == 4 and play_class in ('designed_run','dropback','scramble','punt','field_goal')) or "
                            "play_class in ('extra_point','two_point')", 'fourth-down snap with a call, or a post-TD try',
                            'go, punt or field goal; extra point or two-point'),
}

PERIODS = [
    {'name': 'development', 'seasons': [2022, 2023, 2024], 'use': 'fit and model selection'},
    {'name': 'confirmation', 'seasons': [2025], 'use': 'one pre-registered check of the selected models'},
    {'name': 'examined_2026', 'season': 2026, 'weeks': '1-11',
     'use': 'already read by earlier experiments (week 11 batch, opportunity step 1); not an untouched holdout'},
    {'name': 'prospective_2026', 'season': 2026, 'weeks': '12 and later',
     'use': 'games not yet played on 2026-11-24; forecasts frozen before kickoff'},
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def play_class(d):
    pt = d['play_type']
    out = pd.Series('admin', index=d.index)
    rules = [('timeout', pt.isna() & d['timeout'].eq(1)), ('other', pt.notna()), ('designed_run', pt.eq('run')),
             ('dropback', d['qb_dropback'].eq(1) & pt.isin(['pass', 'run', 'qb_spike'])),
             ('scramble', d['qb_scramble'].eq(1)), ('spike', d['qb_spike'].eq(1) | pt.eq('qb_spike')),
             ('kneel', d['qb_kneel'].eq(1) | pt.eq('qb_kneel')), ('field_goal', pt.eq('field_goal')),
             ('punt', pt.eq('punt')), ('kickoff', pt.eq('kickoff')), ('extra_point', pt.eq('extra_point')),
             ('two_point', d['two_point_attempt'].eq(1)), ('no_play', pt.eq('no_play')),
             ('timeout', pt.eq('no_play') & d['timeout'].eq(1) & d['penalty'].ne(1))]
    for name, mask in rules:
        out[mask.fillna(False)] = name
    return out


def dropback_outcome(d, cls):
    out = pd.Series(pd.NA, index=d.index, dtype='object')
    db = cls.eq('dropback')
    out[db] = 'no_attempt'
    out[db & d['pass_attempt'].eq(1) & d['incomplete_pass'].eq(1)] = 'incomplete'
    out[db & d['complete_pass'].eq(1)] = 'complete'
    out[db & d['interception'].eq(1)] = 'interception'
    out[db & d['sack'].eq(1)] = 'sack'
    out[cls.eq('scramble')] = 'scramble'
    return out


def transitions(d, cls):
    """Next snap (snap rows only) and the clock between them; whether a timeout row sits in between."""
    d = d.assign(play_class=cls).sort_values(KEY)
    snaps = d[d.play_class.isin(SNAP_CLASSES)]
    g = snaps.groupby('game_id', sort=False)
    nxt = pd.DataFrame({'next_play_id': g['play_id'].shift(-1), 'next_posteam': g['posteam'].shift(-1),
                        'next_yardline_100': g['yardline_100'].shift(-1), 'next_qtr': g['qtr'].shift(-1),
                        'next_down': g['down'].shift(-1), 'next_ydstogo': g['ydstogo'].shift(-1),
                        'next_game_seconds_remaining': g['game_seconds_remaining'].shift(-1)}, index=snaps.index)
    same_q = nxt['next_qtr'].eq(snaps['qtr'])
    nxt['clock_runoff_seconds'] = (snaps['game_seconds_remaining'] - nxt['next_game_seconds_remaining']).where(same_q)
    nxt['runoff_status'] = 'same_quarter'
    nxt.loc[nxt['next_qtr'].isna(), 'runoff_status'] = 'last_snap_of_game'
    nxt.loc[nxt['next_qtr'].notna() & ~same_q, 'runoff_status'] = 'last_snap_of_quarter'
    nxt.loc[nxt['clock_runoff_seconds'].lt(0), 'runoff_status'] = 'negative'
    nxt['possession_changed'] = nxt['next_posteam'].notna() & nxt['next_posteam'].ne(snaps['posteam'])
    # a timeout row between this snap and the next one
    timeouts = d[d.play_class.eq('timeout')][['game_id', 'play_id', 'timeout_team']]
    snap_ids = snaps[KEY].join(nxt['next_play_id'])
    merged = snap_ids.merge(timeouts, on='game_id', how='inner', suffixes=('', '_to'))
    between = merged[(merged.play_id_to > merged.play_id) & (merged.play_id_to < merged.next_play_id)]
    first = between.sort_values('play_id_to').drop_duplicates(KEY)[KEY + ['timeout_team']]
    out = snaps[KEY].join(nxt).merge(first.rename(columns={'timeout_team': 'timeout_before_next_snap_team'}), on=KEY,
                                     how='left')
    out['timeout_before_next_snap'] = out['timeout_before_next_snap_team'].notna()
    return out


def clock_stop_class(d, cls, trans):
    m = d[KEY + ['qtr', 'half_seconds_remaining', 'game_seconds_remaining', 'incomplete_pass', 'out_of_bounds',
                 'touchdown', 'field_goal_result', 'safety', 'interception', 'fumble_lost']].assign(play_class=cls).merge(
        trans[KEY + ['possession_changed', 'timeout_before_next_snap']], on=KEY, how='left')
    late_oob = m.out_of_bounds.eq(1) & ((m.qtr.eq(2) & m.half_seconds_remaining.le(120)) |
                                       (m.qtr.ge(4) & m.game_seconds_remaining.le(300)))
    stopped = (m.incomplete_pass.eq(1) | m.touchdown.eq(1) | m.field_goal_result.notna() | m.safety.eq(1) |
               m.possession_changed.fillna(False) | m.timeout_before_next_snap.fillna(False) | late_oob |
               m.play_class.isin(['spike', 'kickoff', 'punt', 'extra_point', 'two_point']))
    out = pd.Series('running', index=m.index)
    out[stopped] = 'stopped'
    out[~m.play_class.isin(SNAP_CLASSES)] = pd.NA
    return m[KEY].assign(clock_stop_class=out.values)


def build_season(path):
    cols = KEY + TIME + list(DECISION) + list(LABELS) + list(POST) + list(PEOPLE) + ['desc']
    d = pd.read_parquet(path, columns=cols)
    d = d[d.season_type.isin(['REG', 'POST'])].copy()
    d['play_id'] = d['play_id'].astype('int64')
    cls = play_class(d)
    labels = d[KEY + TIME + list(LABELS)].copy()
    labels['play_class'] = cls.values
    labels['dropback_outcome'] = dropback_outcome(d, cls).values
    labels['kickoff_onside'] = (cls.eq('kickoff') & d['desc'].str.contains('onside', case=False, na=False)).values
    labels['turnover'] = (d['interception'].eq(1) | d['fumble_lost'].eq(1)).values
    labels['defensive_touchdown'] = (d['touchdown'].eq(1) & d['td_team'].notna() & d['td_team'].ne(d['posteam'])).values
    trans = transitions(d, cls)
    post = d[KEY + TIME + list(POST)].copy()
    end = (d['yardline_100'] - d['yards_gained'])
    clean = cls.isin(SCRIMMAGE) & ~labels['turnover'].values & d['penalty'].ne(1)
    post['end_yardline_100'] = end.where(clean).values
    post['boundary'] = pd.Series(pd.NA, index=d.index, dtype='object')
    post.loc[clean & end.le(0), 'boundary'] = 'opponent_goal_line'
    post.loc[clean & end.ge(100), 'boundary'] = 'own_goal_line'
    post = post.merge(trans, on=KEY, how='left').merge(clock_stop_class(d, cls, trans), on=KEY, how='left')
    return d[KEY + TIME + list(DECISION)].copy(), labels, post, d[KEY + TIME + list(PEOPLE)].copy()


def team_week_counts(decision, labels, people):
    m = decision[KEY + ['season', 'week', 'season_type', 'posteam']].merge(
        labels[KEY + ['play_class', 'pass_attempt', 'sack', 'rush_attempt', 'two_point_attempt', 'play_type']], on=KEY).merge(
        people[KEY + ['receiver_player_id']], on=KEY)
    m = m[m.season_type.eq('REG') & m.two_point_attempt.ne(1) & m.posteam.notna()]
    m['pass_attempts'] = m.play_class.isin(['dropback', 'spike']) & m.pass_attempt.eq(1) & m.sack.ne(1)  # spikes count
    m['carries'] = m.play_class.isin(['designed_run', 'scramble', 'kneel']) & m.rush_attempt.eq(1)
    m['targets'] = m.receiver_player_id.notna() & m.play_type.eq('pass')
    return m.groupby(['season', 'week', 'posteam'])[['pass_attempts', 'carries', 'targets']].sum().astype(int)


def published_counts(stats_path):
    s = pd.read_parquet(stats_path, columns=['season', 'week', 'season_type', 'team', 'attempts', 'carries', 'targets'])
    s = s[s.season_type.eq('REG')]
    out = s.groupby(['season', 'week', 'team'])[['attempts', 'carries', 'targets']].sum().astype(int)
    out.index = out.index.set_names(['season', 'week', 'posteam'])
    return out.rename(columns={'attempts': 'pass_attempts'})


def reconcile_counts(ours, published):
    both = ours.join(published, lsuffix='_ours', rsuffix='_published', how='outer')
    rec = {}
    for col in ('pass_attempts', 'carries', 'targets'):
        a, b = both[f'{col}_ours'], both[f'{col}_published']
        diff = (a - b).dropna()
        rec[col] = {'team_weeks_ours': int(a.notna().sum()), 'team_weeks_published': int(b.notna().sum()),
                    'team_weeks_compared': int(len(diff)), 'exact': int((diff == 0).sum()),
                    'within_1': int((diff.abs() <= 1).sum()), 'total_ours': int(a.sum()), 'total_published': int(b.sum()),
                    'largest_differences': [[int(i[0]), int(i[1]), i[2], int(v)]
                                            for i, v in diff[diff != 0].sort_values(key=abs).tail(5).items()]}
    return rec


def reconcile_scores(post, games_csv, seasons):
    g = pd.read_csv(games_csv)
    g = g[g.season.isin(seasons) & g.game_type.eq('REG') & g.home_score.notna()]
    final = post.groupby('game_id')[['total_home_score', 'total_away_score']].max()
    m = g.set_index('game_id')[['home_score', 'away_score']].join(final, how='left')
    missing = m[m.total_home_score.isna()].index.tolist()
    m = m.dropna()
    bad = m[(m.home_score != m.total_home_score) | (m.away_score != m.total_away_score)]
    return {'games_with_final_score': int(len(g)), 'games_in_pbp': int(len(m)), 'games_missing_from_pbp': missing,
            'final_score_mismatches': bad.index.tolist()}


def audits(labels, post, decision):
    m = labels.merge(post.drop(columns=TIME), on=KEY).merge(decision[KEY + ['qtr', 'down', 'yardline_100']], on=KEY)
    out = {}
    # yardage support per class: no cap; report the full range and the tail counts
    sup = {}
    for cls, g in m[m.play_class.isin(SCRIMMAGE) & m.penalty.ne(1)].groupby('play_class'):
        y = g.yards_gained.dropna()
        sup[cls] = {'n': int(len(y)), 'min': float(y.min()), 'max': float(y.max()),
                    'q0001': float(y.quantile(0.001)), 'q9990': float(y.quantile(0.999)),
                    'le_minus_15': int((y <= -15).sum()), 'ge_60': int((y >= 60).sum()),
                    'reached_opponent_goal_line': int(g.boundary.eq('opponent_goal_line').sum()),
                    'reached_own_goal_line': int(g.boundary.eq('own_goal_line').sum())}
    out['yardage_support'] = sup
    # censoring: a touchdown run or catch is capped by the field; its yards equal yardline_100
    sc = m[m.play_class.isin(SCRIMMAGE) & m.penalty.ne(1) & m.turnover.eq(False)]
    td = sc[sc.touchdown.eq(1) & sc.td_team.eq(sc.merge(decision[KEY + ['posteam']], on=KEY).posteam.values)]
    out['boundary_censoring'] = {
        'offensive_touchdowns': int(len(td)),
        'touchdown_yards_equal_yardline_100': int((td.yards_gained == td.yardline_100).sum()),
        'note': 'a touchdown gain is right-censored at yardline_100: the gain distribution is observed only up to the goal line'}
    tov = m[m.interception.eq(1) | m.fumble.eq(1)]
    fum = m[m.fumble.eq(1)]
    out['turnovers'] = {
        'interceptions': int(m.interception.eq(1).sum()), 'pick_six': int((m.interception.eq(1) & m.defensive_touchdown).sum()),
        'fumbles': int(len(fum)), 'fumbles_lost': int(fum.fumble_lost.eq(1).sum()),
        'fumbles_recovered_by_offense': int(fum.fumble_lost.ne(1).sum()),
        'fumble_recovery_team_missing': int(fum.fumble_recovery_1_team.isna().sum()),
        'fumble_return_touchdowns': int((fum.fumble_lost.eq(1) & fum.defensive_touchdown).sum()),
        'turnover_return_yards_missing': int(tov[tov.turnover].return_yards.isna().sum()),
        'turnovers_with_next_snap_by_defense': int((tov.turnover & tov.possession_changed.fillna(False)).sum())}
    pen = m[m.penalty.eq(1)]
    out['penalties'] = {
        'snaps': int(m.play_class.isin(SNAP_CLASSES).sum()), 'penalty_rows': int(len(pen)),
        'on_no_play_rows': int(pen.play_class.eq('no_play').sum()), 'on_live_plays': int(pen.play_class.ne('no_play').sum()),
        'penalty_type_missing': int(pen.penalty_type.isna().sum()), 'penalty_yards_missing': int(pen.penalty_yards.isna().sum()),
        'first_down_by_penalty': int(pen.first_down_penalty.eq(1).sum()),
        'top_types': {k: int(v) for k, v in pen.penalty_type.value_counts().head(12).items()}}
    ck = m[m.play_class.isin(SNAP_CLASSES)]
    same = ck[ck.runoff_status.eq('same_quarter')]
    out['clock'] = {
        'runoff_status': {k: int(v) for k, v in ck.runoff_status.value_counts().items()},
        'runoff_by_stop_class': {k: {'n': int(len(g)), 'median': float(g.clock_runoff_seconds.median()),
                                     'p90': float(g.clock_runoff_seconds.quantile(0.9))}
                                 for k, g in same.groupby('clock_stop_class')},
        'timeout_rows': int(labels.play_class.eq('timeout').sum()),
        'snaps_followed_by_a_timeout_row': int(ck.timeout_before_next_snap.fillna(False).sum())}
    return out


def missingness(table, timing):
    out = {}
    for col in table.columns:
        if col in KEY + TIME:
            continue
        by = table.groupby('season')[col].apply(lambda s: round(float(s.isna().mean()), 4))
        out[col] = {'timing': timing.get(col, 'derived'), 'null_share_by_season': {int(k): v for k, v in by.items()}}
    return out


def cutoff(table, season, week):
    """Rows strictly before (season, week): what a forecast for a game in that week may read."""
    return table[(table.season < season) | ((table.season == season) & (table.week < week))]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--raw', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--doc-dir', required=True, type=Path)
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=False)
    args.doc_dir.mkdir(parents=True, exist_ok=True)
    inputs, recon, parts = {}, {}, {n: [] for n in ('decision', 'labels', 'post', 'people')}
    for season in SEASONS:
        pbp, stats = args.raw / f'play_by_play_{season}.parquet', args.raw / f'stats_player_week_{season}.parquet'
        inputs[pbp.name], inputs[stats.name] = sha256(pbp), sha256(stats)
        tables = build_season(pbp)
        assert set(tables[0].columns) - set(KEY + TIME) <= set(DECISION), 'decision table holds a non-pre-snap column'
        for name, table in zip(parts, tables):
            parts[name].append(table)
        recon[season] = reconcile_counts(team_week_counts(tables[0], tables[1], tables[3]), published_counts(stats))
        print(season, {k: f"{v['exact']}/{v['team_weeks_compared']}" for k, v in recon[season].items()}, flush=True)
    tables = {n: pd.concat(f, ignore_index=True) for n, f in parts.items()}
    for name in ('snap_counts', 'roster_weekly'):
        for season in SEASONS:
            inputs[f'{name}_{season}.parquet'] = sha256(args.raw / f'{name}_{season}.parquet')
    for season in (2022, 2023, 2024, 2025):
        inputs[f'pbp_participation_{season}.parquet'] = sha256(args.raw / f'pbp_participation_{season}.parquet')
    inputs['games.csv'] = sha256(args.raw / 'games.csv')

    manifest = {'inputs': inputs, 'tables': {}, 'periods': PERIODS}
    for name, table in tables.items():
        path = args.out / f'{name}.parquet'
        table.to_parquet(path, index=False)
        manifest['tables'][name] = {'rows': int(len(table)), 'duplicate_keys': int(table.duplicated(KEY).sum()),
                                    'sha256': sha256(path), 'path': str(path)}
    lab = tables['labels'].merge(tables['decision'][KEY + ['down']], on=KEY)
    manifest['play_class_by_season'] = {int(s): {k: int(v) for k, v in g.play_class.value_counts().items()}
                                        for s, g in lab.groupby('season')}
    views = {}
    for name, (query, denominator, targets) in VIEWS.items():
        v = lab.query(query, engine='python')
        views[name] = {'filter': query, 'denominator': denominator, 'targets': targets,
                       'rows_by_season': {int(s): int(n) for s, n in v.groupby('season').size().items()},
                       'rows_by_season_type': {k: int(n) for k, n in v.groupby('season_type').size().items()}}
    manifest['views'] = views
    manifest['reconciliation'] = {'team_week_counts_vs_stats_player_week': recon,
                                  'final_scores_vs_games_csv': reconcile_scores(tables['post'], args.raw / 'games.csv', SEASONS)}
    manifest['audits'] = audits(tables['labels'], tables['post'], tables['decision'])
    manifest['gaps'] = [
        'pbp_participation has no 2026 file (nflverse release, checked 2026-11-24): formation and personnel labels exist for '
        '2022-2025 only',
        'nflverse has no onside_kick column: kickoff_onside is read from the play description',
        'the play-by-play has the game clock only at snaps: live-play duration is observed directly only for plays after '
        'which the clock stops (clock_stop_class == stopped)']
    timing = {**DECISION, **LABELS, **POST, **{c: 'identity' for c in PEOPLE}}
    registry = {name: {'key': KEY, 'columns': {c: {'dtype': str(t[c].dtype), 'timing': timing.get(c, 'derived' if c not in
                                                                                                 KEY + TIME else 'key')}
                                                for c in t.columns}}
                for name, t in tables.items()}
    (args.doc_dir / 'schema_registry.json').write_text(json.dumps(registry, indent=1, sort_keys=True) + '\n')
    miss = {name: missingness(t, timing) for name, t in tables.items()}
    (args.doc_dir / 'missingness.json').write_text(json.dumps(miss, indent=1, sort_keys=True) + '\n')
    (args.doc_dir / 'phase1_manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True, default=str) + '\n')
    print(json.dumps({k: manifest[k] for k in ('tables', 'audits')}, indent=1, default=str)[:6000])
    print(json.dumps(manifest['reconciliation']['final_scores_vs_games_csv'], default=str)[:800])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
