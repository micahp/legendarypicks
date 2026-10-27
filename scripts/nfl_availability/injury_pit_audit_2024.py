#!/usr/bin/env python3
"""2024 point-in-time injury audit: what could have been known at each proposed horizon cutoff.

Read-only. Writes scratchpad/avail/inactives/injury_pit_audit_2024.md.

Input classes, per player-week and per horizon (latest stored version only; the table keeps one version per
player-week except two Week 15 keys, which are handled as explicit cases):
  verified           requires an archived or dated snapshot. None exists in nfl_hist_injuries: always zero here.
  timestamp-proxy    latest stored date_modified is before the cutoff. Publication timing is not established.
  retrospective      latest stored date_modified is after the cutoff. The state at the cutoff is not stored.
  unverifiable       date_modified is null.
  no-input           the official inactive identity has no injury row on the exact key at all. Missing input,
                     distinct from a 'none' designation (a healthy player with no report line).

Horizons (proposed in the brief, not verified report times): early, practice, final, pregame (kickoff minus 90 min).
Cutoffs are defined for Sunday, Thursday and Monday games. Other weekdays and playoff game days are reported
as unmapped and excluded from horizon rates.
"""
import json
import os
import sqlite3
from datetime import timedelta

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEDULES = os.path.join(HERE, 'schedules.parquet')
OFFICIAL = os.path.join(HERE, 'inactives', 'official_inactives_2024_full.jsonl')
REPORT = os.path.join(HERE, 'inactives', 'injury_pit_audit_2024.md')
DB = 'file:/root/legendarypicks/backend/data/picks.db?mode=ro'
ET = 'America/New_York'
DB_TO_SCHED = {'LAR': 'LA', 'WSH': 'WAS'}
RULES = {
    'Sunday': {'early': (4, 12), 'practice': (2, 9), 'final': (1, 9)},
    'Thursday': {'early': (3, 12), 'practice': (1, 9), 'final': (0, 9)},
    'Monday': {'early': (4, 12), 'practice': (2, 9), 'final': (1, 9)},
}
HORIZONS = ['early', 'practice', 'final', 'pregame']
CASES = {
    'Engram, 2024 week 2 (JAX, GSIS 00-0033881)': ('00-0033881', 2, 'JAX'),
    'Engram, 2024 week 3 (JAX, GSIS 00-0033881)': ('00-0033881', 3, 'JAX'),
    'Cade Stover, 2024 week 15 (HOU, GSIS 00-0039359)': ('00-0039359', 15, 'HOU'),
    'Tyler Conklin, 2024 week 15 (NYJ, GSIS 00-0034270)': ('00-0034270', 15, 'NYJ'),
    'Kyle Van Noy, 2024 week 1 (BAL, GSIS 00-0031360)': ('00-0031360', 1, 'BAL'),
}


def cutoffs(game_date, weekday, kickoff):
    out = {'pregame': kickoff - pd.Timedelta(minutes=90)}
    rule = RULES.get(weekday)
    if rule:
        for name, (days, hour) in rule.items():
            out[name] = (pd.Timestamp(game_date) - pd.Timedelta(days=days)).replace(hour=hour) \
                .tz_localize(ET).tz_convert('UTC')
    return out, rule is not None


def classify(modified, cut):
    if pd.isna(modified):
        return 'unverifiable'
    return 'timestamp-proxy' if modified <= cut else 'retrospective'


def main():
    sched = pd.read_parquet(SCHEDULES, columns=['game_id', 'season', 'game_type', 'week', 'gameday', 'weekday',
                                                 'gametime', 'home_team', 'away_team'])
    sched = sched[(sched.season == 2024)].copy()
    sched['kickoff'] = [pd.Timestamp(f'{d} {t or "13:00"}').tz_localize(ET).tz_convert('UTC')
                        for d, t in zip(sched.gameday, sched.gametime)]
    teams = pd.concat([sched.rename(columns={'home_team': 'team'})[['game_id', 'game_type', 'week', 'team', 'weekday',
                                                                   'gameday', 'kickoff']],
                       sched.rename(columns={'away_team': 'team'})[['game_id', 'game_type', 'week', 'team', 'weekday',
                                                                    'gameday', 'kickoff']]])
    con = sqlite3.connect(DB, uri=True)
    inj = pd.read_sql("select season, game_type, week, team, gsis_id, full_name, report_status, practice_status, "
                      "report_primary_injury, date_modified from nfl_hist_injuries where season=2024", con)
    inj['team'] = inj.team.replace(DB_TO_SCHED)
    inj['modified'] = pd.to_datetime(inj.date_modified, utc=True, errors='coerce')
    total_all = len(inj)
    inj = inj.merge(teams, on=['game_type', 'week', 'team'], how='left')
    unmatched = inj[inj.game_id.isna()]
    inj = inj[inj.game_id.notna()].copy()
    inj['designation'] = inj.report_status.map(lambda v: 'NULL' if pd.isna(v) else v)
    stored = inj.groupby(['game_type', 'week', 'team', 'gsis_id']).size()
    multi = stored[stored > 1].index
    latest = inj.sort_values('modified', na_position='first').drop_duplicates(
        ['game_type', 'week', 'team', 'gsis_id'], keep='last').copy()

    rows = []
    for r in latest.itertuples(index=False):
        cuts, mapped = cutoffs(r.gameday, r.weekday, r.kickoff)
        rec = {'game_type': r.game_type, 'week': r.week, 'team': r.team, 'gsis_id': r.gsis_id, 'name': r.full_name,
               'weekday': r.weekday, 'designation': r.designation, 'modified': r.modified, 'kickoff': r.kickoff,
               'mapped': mapped, 'after_kickoff': bool(pd.notna(r.modified) and r.modified > r.kickoff)}
        for h in HORIZONS:
            if h in cuts:
                rec[h] = classify(r.modified, cuts[h])
            else:
                rec[h] = 'unmapped'
        rows.append(rec)
    df = pd.DataFrame(rows)

    # official inactive identities with no injury row on the exact key
    off = [json.loads(line) for line in open(OFFICIAL)]
    inj_keys = set(zip(inj.week, inj.team, inj.gsis_id))
    no_input = {'REG': 0, 'playoff': 0}
    for r in off:
        gt = 'REG' if int(r['week']) <= 18 else 'playoff'
        key_team = DB_TO_SCHED.get(r['team'], r['team'])
        if (int(r['week']), key_team, r['gsis_id']) not in inj_keys and r['label'] == 'inactive':
            no_input[gt] += 1

    lines = []
    add = lines.append
    add('# 2024 point-in-time injury audit')
    add('')
    add('Read-only. Horizons and cutoffs are the proposed rules in the brief, not verified report publication times. '
        'date_modified is an update time, not a publication time. No availability probability is fitted, and no model '
        'is promoted.')
    add('')
    add('## Coverage')
    add(f'- nfl_hist_injuries 2024 rows, all game types: {total_all}')
    add(f'- Rows with no matching schedule game: {len(unmatched)} '
        f'({sorted(set(zip(unmatched.game_type, unmatched.week)))[:6]}...)' if len(unmatched) else
        f'- Rows with no matching schedule game: 0')
    add(f'- Latest rows analysed: {len(df)} (regular season {int((df.game_type == "REG").sum())}, playoffs '
        f'{int((df.game_type != "REG").sum())})')
    add(f'- Player-weeks with more than one stored version: {len(multi)} (all Week 15 Conklin and Stover)')
    add(f'- Rows with null date_modified: {int(df.modified.isna().sum())}')
    add(f'- Official inactive identities with no injury row on the exact key (missing input): REG {no_input["REG"]}, '
        f'playoffs {no_input["playoff"]}')
    add('')
    add('## Verified point-in-time inputs')
    add('Zero. No archived or dated snapshot exists for 2024 in the database. Every class below is a timestamp-proxy, '
        'retrospective or unverifiable.')
    add('')
    m = df[(df.mapped) & (df.game_type == 'REG')]
    add(f'## Regular season, mapped weekdays (Sunday, Thursday, Monday): n = {len(m)}')
    add('| horizon | timestamp-proxy | retrospective | unverifiable | verified |')
    add('|---|---|---|---|---|')
    for h in HORIZONS:
        c = m[h].value_counts()
        n = len(m)
        add(f"| {h} | {c.get('timestamp-proxy', 0)} ({100*c.get('timestamp-proxy', 0)/n:.1f}%) | "
            f"{c.get('retrospective', 0)} ({100*c.get('retrospective', 0)/n:.1f}%) | "
            f"{c.get('unverifiable', 0)} | 0 |")
    add('')
    add('## By designation, regular season (mapped)')
    add('| designation | n | early retrospective | practice retrospective | final retrospective | pregame retrospective '
        '| after kickoff |')
    add('|---|---|---|---|---|---|---|')
    for d, g in m.groupby('designation'):
        add(f"| {d} | {len(g)} | " + ' | '.join(f"{100*(g[h] == 'retrospective').mean():.1f}%" for h in HORIZONS)
            + f" | {100*g.after_kickoff.mean():.1f}% |")
    add('')
    add('## By game day, regular season (mapped)')
    add('| weekday | n | early retrospective | practice retrospective | final retrospective | pregame retrospective '
        '| after kickoff |')
    add('|---|---|---|---|---|---|---|')
    for wd, g in m.groupby('weekday'):
        add(f"| {wd} | {len(g)} | " + ' | '.join(f"{100*(g[h] == 'retrospective').mean():.1f}%" for h in HORIZONS)
            + f" | {100*g.after_kickoff.mean():.1f}% |")
    add('')
    p = df[df.game_type != 'REG']
    add(f'## Playoffs: n = {len(p)}, all unmapped for horizon cutoffs (no published cutoff rule verified)')
    add(f"- Latest versions modified after kickoff: {int(p.after_kickoff.sum())} of {len(p)}")
    add('')
    add('## Explicit cases')
    for label, (gsis, week, team) in CASES.items():
        add(f'### {label}')
        if gsis is None:
            sub = df[(df.team == team) & (df.week == week) & (df.name.str.contains('Kyle Van Noy'))]
        else:
            sub = df[(df.gsis_id == gsis) & (df.week == week)]
        if gsis is None or not len(sub):
            pass
        raw = inj[(inj.gsis_id == gsis) & (inj.week == week)] if gsis else inj[(inj.team == team) & (inj.week == week)
                                                                              & inj.full_name.str.contains('Kyle')]
        if len(raw) == 0:
            add('- No injury row exists for this player-week in nfl_hist_injuries. The designation at every horizon '
                'is unverifiable, and the table cannot show the warm-up change described for this case.')
            add('')
            continue
        for r in raw.sort_values('modified', na_position='first').itertuples(index=False):
            add(f"- stored version: {r.designation}, date_modified {r.modified}, kickoff {r.kickoff}")
        last = latest[(latest.gsis_id == gsis) & (latest.week == week)] if gsis else \
            latest[(latest.team == team) & (latest.week == week) & latest.full_name.str.contains('Kyle')]
        if len(last):
            rr = last.iloc[0]
            cuts, mapped = cutoffs(rr.gameday, rr.weekday, rr.kickoff)
            for h in HORIZONS:
                if h in cuts:
                    add(f"- {h}: cutoff {cuts[h]}, class of latest version {classify(rr.modified, cuts[h])}")
                else:
                    add(f'- {h}: unmapped weekday {rr.weekday}')
        add('')
    add('## Method notes')
    add('- A retrospective class means the latest stored version was modified after the cutoff. Whatever the report '
        'said at the cutoff is not stored, so the forecast input cannot be reconstructed.')
    add('- Post-cutoff revisions are excluded from forecast inputs but kept in evaluation. Nothing here removes '
        'player-games.')
    with open(REPORT, 'w') as handle:
        handle.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
