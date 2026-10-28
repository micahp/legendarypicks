"""Measure field-goal, extra-point and two-point outcomes in the dev nfl_pbp table. Read-only.

Run: python3 scripts/nfl_sequence/measure_kick_outcomes.py [--db PATH]

The database is opened with mode=ro. load_kick_table() is the table the E2 engine draws its kick outcomes from. The SQL
printed here is the SQL recorded in docs/SEQUENCE-E2-FIRST-PIECE-2026-10-24.md.
"""
import argparse
import math
import sqlite3
from pathlib import Path

DEFAULT_DB = '/root/legendarypicks/backend/data/picks.dev.db'
WINDOW = 'season BETWEEN 2022 AND 2025 AND week <= 18'


def before_cutoff(season, week, eligible_before):
    """True when (season, week) is strictly before the cutoff, or when there is no cutoff."""
    if eligible_before is None:
        return True
    cutoff_season, cutoff_week = int(eligible_before[0]), int(eligible_before[1])
    season, week = int(season), int(week)
    return season < cutoff_season or (season == cutoff_season and week < cutoff_week)
FG_MADE, FG_MISSED = 'Field goal', 'Missed field goal'
EP_SCORED = ('Touchdown', 'Opp touchdown')
BUCKET = """CASE WHEN yardline_100 < 10 THEN '1-9' WHEN yardline_100 < 20 THEN '10-19'
WHEN yardline_100 < 30 THEN '20-29' WHEN yardline_100 < 40 THEN '30-39' WHEN yardline_100 < 50 THEN '40-49'
ELSE '50+' END"""
FG_BY_BUCKET_SQL = f"""SELECT {BUCKET} AS bucket,
  SUM(series_result = '{FG_MADE}') AS made, SUM(series_result = '{FG_MISSED}') AS missed
FROM nfl_pbp WHERE play_type = 'field_goal' AND {WINDOW} AND series_result IN ('{FG_MADE}', '{FG_MISSED}')
GROUP BY bucket ORDER BY bucket"""


def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes out of n."""
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


KICK_RESULTS = Path(__file__).resolve().parents[2] / 'docs' / 'fixtures' / 'e2' / 'kick_results_2022_2025.csv'


def load_try_results(path=KICK_RESULTS, eligible_before=None):
    """Extra-point and two-point outcomes from the publisher's result fields, read from the rebuilt CSV.

    An extra point is made on `extra_point_result` == 'good' and missed on 'failed'. A blocked extra point and a row with no
    result are not in either count: they are returned under `excluded`, with their numbers. A two-point try is made on
    `two_point_conv_result` == 'success' and missed on 'failure'. Nothing is read from `success`.
    """
    import csv
    ep = {'good': 0, 'failed': 0, 'blocked': 0, 'missing': 0}
    tp = {'success': 0, 'failure': 0, 'missing': 0}
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            if not before_cutoff(r['season'], r['week'], eligible_before):
                continue
            if r['play_type'] == 'extra_point':
                key = r['extra_point_result'] or 'missing'
                ep[key] = ep.get(key, 0) + 1
            if r['two_point_attempt'] in ('1', '1.0'):
                key = r['two_point_conv_result'] or 'missing'
                tp[key] = tp.get(key, 0) + 1
    return {'extra_point': (ep['good'], ep['failed']), 'two_point': (tp['success'], tp['failure']),
            'excluded': {'extra_point': {'blocked': ep['blocked'], 'missing': ep['missing']},
                         'two_point': {'missing': tp['missing']}},
            'source': f'{path.name} (publisher fields extra_point_result, two_point_conv_result)'}


def fg_bucket_of(yardline_100):
    """The same bucket labels as the BUCKET SQL above."""
    for limit, label in ((10, '1-9'), (20, '10-19'), (30, '20-29'), (40, '30-39'), (50, '40-49')):
        if yardline_100 < limit:
            return label
    return '50+'


def load_field_goal_results(path=KICK_RESULTS, eligible_before=None):
    """Field-goal make and miss counts by yardline_100 bucket, from the publisher's field_goal_result.

    A kick is made on `field_goal_result` == 'made' and missed on 'missed', and only when its series label is a kick
    result ('Field goal' or 'Missed field goal'). A blocked kick is not a missed kick: its spot rule is different and the
    engine does not model it, so it is returned under `excluded`. So is any row whose series label is not a kick
    (a kneel, or a touchdown on the return).
    """
    import csv
    field_goal = {}
    outcomes = {}
    excluded = {'blocked': 0, 'series label is not a kick result': 0, 'missing yardline or result': 0}
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            if not before_cutoff(r['season'], r['week'], eligible_before):
                continue
            if r['play_type'] != 'field_goal':
                continue
            if r['field_goal_result'] in ('made', 'missed', 'blocked') and r['yardline_100']:
                bucket = fg_bucket_of(float(r['yardline_100']))
                counts = list(outcomes.get(bucket, (0, 0, 0)))
                counts[{'made': 0, 'missed': 1, 'blocked': 2}[r['field_goal_result']]] += 1
                outcomes[bucket] = tuple(counts)
            if r['field_goal_result'] == 'blocked':
                excluded['blocked'] += 1
                continue
            if r['series_result'] not in ('Field goal', 'Missed field goal'):
                excluded['series label is not a kick result'] += 1
                continue
            if r['field_goal_result'] not in ('made', 'missed') or not r['yardline_100']:
                excluded['missing yardline or result'] += 1
                continue
            bucket = fg_bucket_of(float(r['yardline_100']))
            made, missed = field_goal.get(bucket, (0, 0))
            if r['field_goal_result'] == 'made':
                made += 1
            else:
                missed += 1
            field_goal[bucket] = (made, missed)
    return {'field_goal': field_goal, 'field_goal_outcomes': outcomes, 'excluded': excluded}


def load_kick_table(db=DEFAULT_DB, results=KICK_RESULTS, eligible_before=None):
    """Published kick outcomes for the primary window, as (made, missed) pairs. Read-only.

    Field goals come from the dev table's `series_result`, as before. Extra points and two-point tries come from the
    publisher's result fields (load_try_results), not from `success`.
    {'field_goal': {bucket: (made, missed)}, 'extra_point': (made, missed), 'two_point': (made, missed),
     'excluded': {...}, 'source': str}
    """
    fg = load_field_goal_results(results, eligible_before=eligible_before)
    tries = load_try_results(results, eligible_before=eligible_before)
    return {'field_goal': fg['field_goal'], 'field_goal_outcomes': fg['field_goal_outcomes'],
            'extra_point': tries['extra_point'], 'two_point': tries['two_point'],
            'excluded': {'field_goal': fg['excluded'], **tries['excluded']},
            'source': f"{Path(results).name} (publisher fields field_goal_result, extra_point_result, "
                      f"two_point_conv_result; window {WINDOW})"}


def rows(con, sql):
    return con.execute(sql).fetchall()


def section(title, sql):
    print(f'\n=== {title}\n{sql.strip()}\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DEFAULT_DB)
    con = sqlite3.connect(f'file:{ap.parse_args().db}?mode=ro', uri=True)

    # 1. Field goals, the primary window (2022-2025, weeks <= 18: the E1 sampling window).
    sql = f"""SELECT series_result, COUNT(*) FROM nfl_pbp
WHERE play_type = 'field_goal' AND {WINDOW} GROUP BY series_result ORDER BY COUNT(*) DESC"""
    section('1. field_goal rows by series_result, 2022-2025 wk<=18', sql)
    census = rows(con, sql)
    made = sum(n for lab, n in census if lab == FG_MADE)
    missed = sum(n for lab, n in census if lab == FG_MISSED)
    total = sum(n for _, n in census)
    for lab, n in census:
        print(f'  {str(lab):20s} {n:6d}')
    print(f'  made={made} missed={missed} excluded={total - made - missed} (labels other than the two above)')
    print(f'  make rate {made / (made + missed):.4f}  Wilson95 {wilson(made, made + missed)}')
    epa = rows(con, f"""SELECT series_result, ROUND(AVG(epa), 3) FROM nfl_pbp
WHERE play_type = 'field_goal' AND {WINDOW} AND series_result IN ('{FG_MADE}', '{FG_MISSED}') GROUP BY series_result""")
    print('  mean epa by label:', dict(epa))

    # 2. Field goals by season, all seasons: is the label stable?
    sql = f"""SELECT season,
  SUM(series_result = '{FG_MADE}') AS made,
  SUM(series_result = '{FG_MISSED}') AS missed,
  COUNT(*) - SUM(series_result IN ('{FG_MADE}', '{FG_MISSED}')) AS excluded
FROM nfl_pbp WHERE play_type = 'field_goal' AND {WINDOW} GROUP BY season ORDER BY season"""
    section('2. field_goal per season, 2022-2025 (2026 holdout excluded)', sql)
    print(f'  {"season":>6s} {"made":>6s} {"missed":>6s} {"excl":>5s} {"rate":>6s}')
    for season, m, x, e in rows(con, sql):
        rate = m / (m + x) if m + x else float('nan')
        print(f'  {season:>6d} {m:6d} {x:6d} {e:5d} {rate:6.3f}')

    # 3. Field goals by yardline_100 (yards to the opponent's end zone at the snap; kick distance ~ yardline_100 + 17).
    sql = f"""SELECT {BUCKET} AS bucket,
  SUM(series_result = '{FG_MADE}') AS made, SUM(series_result = '{FG_MISSED}') AS missed
FROM nfl_pbp WHERE play_type = 'field_goal' AND {WINDOW} AND series_result IN ('{FG_MADE}', '{FG_MISSED}')
GROUP BY bucket ORDER BY bucket"""
    section('3. make rate by yardline_100 bucket, 2022-2025 wk<=18 (made/missed labels only)', sql)
    print(f'  {"yl100":>6s} {"made":>6s} {"missed":>6s} {"rate":>6s}   wilson95')
    for b, m, x in rows(con, sql):
        print(f'  {b:>6s} {m:6d} {x:6d} {m / (m + x):6.3f}   {wilson(m, m + x)}')

    # 4. Field goals against the following play in the same game (independent of series_result).
    sql = f"""WITH n AS (
  SELECT play_type, posteam, defteam, series_result, season, week,
    LEAD(play_type) OVER w AS nxt_type, LEAD(posteam) OVER w AS nxt_pos
  FROM nfl_pbp WINDOW w AS (PARTITION BY game_id ORDER BY play_id))
SELECT series_result, nxt_type,
  CASE WHEN nxt_pos IS NULL THEN 'none' WHEN nxt_pos = defteam THEN 'other team'
       ELSE 'kicking team' END AS nxt_possession,
  COUNT(*) AS n
FROM n WHERE play_type = 'field_goal' AND {WINDOW}
GROUP BY 1, 2, 3 ORDER BY 1, 4 DESC"""
    section('4. field_goal rows vs the next play in the game, 2022-2025 wk<=18', sql)
    for lab, nt, pos, n in rows(con, sql):
        print(f'  {str(lab):20s} next={str(nt):10s} next_possession={pos:13s} {n:6d}')

    # 5. Extra points and two-point tries from the publisher's result fields in the kick table. success is never read.
    tries = load_try_results()
    good, failed = tries['extra_point']
    print('5. extra_point, publisher field extra_point_result (good / failed), 2022-2025 wk<=18')
    print(f'  good={good} failed={failed} rate {good / (good + failed):.4f}  Wilson95 {wilson(good, good + failed)}')
    print(f"  not counted: {tries['excluded']['extra_point']}")
    ok, miss = tries['two_point']
    print('6. two_point, publisher field two_point_conv_result (success / failure), 2022-2025 wk<=18')
    print(f'  success={ok} failure={miss} rate {ok / (ok + miss):.4f}  Wilson95 {wilson(ok, ok + miss)}')
    con.close()


if __name__ == '__main__':
    main()
