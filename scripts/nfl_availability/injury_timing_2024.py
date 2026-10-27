#!/usr/bin/env python3
"""2024 regular season: when were injury reports last modified, relative to each proposed forecast cutoff?

Read-only. Writes one markdown report to scratchpad/avail/inactives/injury_timing_2024_report.md.

Inputs
  nfl_hist_injuries (picks.db, read-only): one row per player-week, with report_status and date_modified.
  schedules.parquet (nflverse): gameday, weekday and gametime (Eastern), used for kickoff.

Definitions
  date_modified is the time the injury information was last updated. It is not a publication time.
  Each player-week is classed at each horizon by the latest stored version:
    timestamp-proxy   date_modified is before the cutoff. Publication timing is not established.
    post-cutoff       date_modified is after the cutoff. Whatever was shown before the cutoff is not stored.
    unverifiable      date_modified is null.
  verified point-in-time requires an archived or dated snapshot. None exists in this table, so that class is zero.

Cutoffs (proposed in the brief, not verified against published report times)
  Sunday games:   early = Wed 12:00 ET, practice = Fri 09:00 ET, final = Sat 09:00 ET
  Thursday games: early = Mon 12:00 ET, practice = Wed 09:00 ET, final = Thu 09:00 ET
  Monday games:   early = Thu 12:00 ET, practice = Sat 09:00 ET, final = Sun 09:00 ET
  pregame = kickoff minus 90 minutes (inactive deadline). Other weekdays are reported as unmapped.
"""
import os
import sqlite3

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(HERE, 'inactives', 'injury_timing_2024_report.md')
SCHEDULES = os.path.join(HERE, 'schedules.parquet')
DB = 'file:/root/legendarypicks/backend/data/picks.db?mode=ro'
ET_ZONE = 'America/New_York'
DB_TO_SCHED = {'LAR': 'LA', 'WSH': 'WAS'}
# (days before game date, hour ET) for each horizon, by weekday of the game
CUTOFF_RULES = {
    'Sunday': {'early': (4, 12), 'practice': (2, 9), 'final': (1, 9)},
    'Thursday': {'early': (3, 12), 'practice': (1, 9), 'final': (0, 9)},
    'Monday': {'early': (4, 12), 'practice': (2, 9), 'final': (1, 9)},
}
HORIZONS = ['early', 'practice', 'final', 'pregame']


def cutoffs_for(game_date, weekday, kickoff_utc):
    rule = CUTOFF_RULES.get(weekday)
    out = {'pregame': kickoff_utc - pd.Timedelta(minutes=90)}
    if rule is None:
        return out, False
    for name, (days, hour) in rule.items():
        local_day = pd.Timestamp(game_date) - pd.Timedelta(days=days)
        local = local_day.replace(hour=hour).tz_localize(ET_ZONE)
        out[name] = local.tz_convert('UTC')
    return out, True


def main():
    sched = pd.read_parquet(SCHEDULES, columns=['game_id', 'season', 'game_type', 'week', 'gameday', 'weekday',
                                                 'gametime', 'home_team', 'away_team'])
    sched = sched[(sched.season == 2024) & (sched.game_type == 'REG')].copy()
    sched['game_date'] = pd.to_datetime(sched.gameday).dt.date
    sched['kickoff_utc'] = [pd.Timestamp(f'{d} {t or "13:00"}').tz_localize(ET_ZONE).tz_convert('UTC')
                            for d, t in zip(sched.gameday, sched.gametime)]
    teams = pd.concat([
        sched[['game_id', 'week', 'home_team', 'weekday', 'game_date', 'kickoff_utc']].rename(
            columns={'home_team': 'team'}),
        sched[['game_id', 'week', 'away_team', 'weekday', 'game_date', 'kickoff_utc']].rename(
            columns={'away_team': 'team'})])

    con = sqlite3.connect(DB, uri=True)
    inj = pd.read_sql("select week, team, gsis_id, full_name, report_status, practice_status, report_primary_injury, "
                      "date_modified from nfl_hist_injuries where season=2024 and game_type='REG' and week between 1 and 18",
                      con)
    inj['sched_team'] = inj.team.replace(DB_TO_SCHED)
    inj['modified'] = pd.to_datetime(inj.date_modified, utc=True, errors='coerce')
    total_rows = len(inj)
    null_modified = int(inj.modified.isna().sum())
    dup_keys = inj[inj.duplicated(['week', 'team', 'gsis_id'], keep=False)]

    merged = inj.merge(teams, left_on=['week', 'sched_team'], right_on=['week', 'team'], how='left',
                       suffixes=('', '_sched'))
    unmatched = int(merged.game_id.isna().sum())
    merged = merged[merged.game_id.notna()].copy()

    # latest stored version per player-week; null dates sort last and are only kept when nothing else exists
    merged['_sort'] = merged.modified.fillna(pd.Timestamp('1900-01-01', tz='UTC'))
    latest = merged.sort_values('_sort').drop_duplicates(['week', 'team', 'gsis_id'], keep='last').copy()

    rows = []
    unmapped_weekdays = {}
    for r in latest.itertuples(index=False):
        cuts, mapped = cutoffs_for(r.game_date, r.weekday, r.kickoff_utc)
        if not mapped:
            unmapped_weekdays[r.weekday] = unmapped_weekdays.get(r.weekday, 0) + 1
        rec = {'week': r.week, 'team': r.team, 'gsis_id': r.gsis_id, 'name': r.full_name, 'weekday': r.weekday,
               'designation': r.report_status if isinstance(r.report_status, str) else 'NULL',
               'modified': r.modified, 'kickoff_utc': r.kickoff_utc, 'mapped': mapped}
        rec['hours_before_kickoff'] = (r.kickoff_utc - r.modified).total_seconds() / 3600 if pd.notna(r.modified) else None
        for h in HORIZONS:
            if h not in cuts:
                rec[f'{h}_class'] = 'unmapped'
                rec[f'{h}_cutoff_utc'] = None
                continue
            cut = cuts[h]
            if pd.isna(r.modified):
                cls = 'unverifiable'
            elif r.modified <= cut:
                cls = 'timestamp-proxy'
            else:
                cls = 'post-cutoff'
            rec[f'{h}_class'] = cls
            rec[f'{h}_cutoff_utc'] = cut
        rec['after_kickoff'] = bool(pd.notna(r.modified) and r.modified > r.kickoff_utc)
        rows.append(rec)
    df = pd.DataFrame(rows)

    lines = []
    add = lines.append
    add('# 2024 regular season: injury report timing against proposed forecast cutoffs')
    add('')
    add('Read-only measurement from nfl_hist_injuries and nflverse schedules. Cutoffs are the proposed rules in the brief, '
        'not verified report publication times. date_modified is an update time, not a publication time.')
    add('')
    add('## Coverage')
    add(f'- Injury rows, 2024 REG weeks 1-18: {total_rows}')
    add(f'- Unique player-weeks (latest version): {len(df)}')
    add(f'- Rows with null date_modified: {null_modified}')
    add(f'- Rows not matched to a scheduled game: {unmatched}')
    add(f'- Keys with more than one stored version: {int(dup_keys.groupby(["week", "team", "gsis_id"]).ngroups)}')
    add(f'- Games on weekdays without a cutoff rule (unmapped): {unmapped_weekdays or "none"}')
    add('')
    add('## Stored versions')
    if len(dup_keys):
        add('| week | team | player | designation | date_modified |')
        add('|---|---|---|---|---|')
        for r in dup_keys.sort_values(['week', 'gsis_id', 'date_modified']).itertuples(index=False):
            add(f'| {r.week} | {r.team} | {r.full_name} | {r.report_status} | {r.date_modified} |')
    add('')
    add('## Share of latest versions by class, per horizon (mapped games only)')
    m = df[df.mapped]
    add('| horizon | timestamp-proxy | post-cutoff | unverifiable | verified point-in-time |')
    add('|---|---|---|---|---|')
    for h in HORIZONS:
        c = m[f'{h}_class'].value_counts()
        n = len(m)
        add(f"| {h} | {c.get('timestamp-proxy', 0)} ({100*c.get('timestamp-proxy', 0)/n:.1f}%) | "
            f"{c.get('post-cutoff', 0)} ({100*c.get('post-cutoff', 0)/n:.1f}%) | "
            f"{c.get('unverifiable', 0)} ({100*c.get('unverifiable', 0)/n:.1f}%) | 0 (no archived snapshots) |")
    add('')
    add('## Modified after kickoff')
    add(f"- Latest versions modified after kickoff: {int(m.after_kickoff.sum())} of {len(m)} "
        f"({100*m.after_kickoff.mean():.1f}%)")
    add('')
    add('## By weekday, share modified after each cutoff')
    add('| weekday | n | early | practice | final | pregame | after kickoff |')
    add('|---|---|---|---|---|---|---|')
    for wd, g in m.groupby('weekday'):
        def share(h):
            return f"{100*(g[f'{h}_class'] == 'post-cutoff').mean():.1f}%"
        add(f'| {wd} | {len(g)} | {share("early")} | {share("practice")} | {share("final")} | {share("pregame")} | '
            f'{100*g.after_kickoff.mean():.1f}% |')
    add('')
    add('## By designation, share modified after the final cutoff and after kickoff')
    add('| designation | n | after final cutoff | after kickoff |')
    add('|---|---|---|---|')
    for d, g in m.groupby('designation'):
        add(f"| {d} | {len(g)} | {100*(g.final_class == 'post-cutoff').mean():.1f}% | {100*g.after_kickoff.mean():.1f}% |")
    add('')
    add('## By week, share modified after the final cutoff')
    add('| week | n | after final cutoff |')
    add('|---|---|---|')
    for w, g in m.groupby('week'):
        add(f"| {w} | {len(g)} | {100*(g.final_class == 'post-cutoff').mean():.1f}% |")
    add('')
    add('## Rows modified after kickoff')
    late = m[m.after_kickoff]
    if len(late):
        add('| week | team | player | designation | date_modified | kickoff (UTC) |')
        add('|---|---|---|---|---|---|')
        for r in late.itertuples(index=False):
            add(f'| {r.week} | {r.team} | {r.name} | {r.designation} | {r.modified} | {r.kickoff_utc} |')
    else:
        add('- None.')
    add('')
    add('## Engram, 2024 week 2 (regression case)')
    eg = df[(df.gsis_id == '00-0033881') & (df.week == 2)]
    if len(eg):
        r = eg.iloc[0]
        add(f"- Designation: {r.designation}; kickoff (UTC): {r.kickoff_utc}; date_modified: {r.modified}")
        add(f"- Hours before kickoff of the stored version: {r.hours_before_kickoff:.2f}" if r.hours_before_kickoff is not None
            else '- date_modified is null')
        for h in HORIZONS:
            add(f"- {h}: cutoff {r[f'{h}_cutoff_utc']}, class {r[f'{h}_class']}")
    else:
        add('- No row found for Engram in week 2 with this key.')
    add('')
    add('## Verdict for the rule')
    add('- No verified point-in-time inputs exist in this table for 2024. Every class above is timestamp-proxy, '
        'post-cutoff or unverifiable.')
    add('- Designation rates in the rate report use the latest version and are retrospective. The table above shows '
        'how many of them could have changed after the final cutoff.')
    add('- Prospective timestamped snapshots are needed for verified multi-horizon evaluation.')
    with open(REPORT, 'w') as handle:
        handle.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
