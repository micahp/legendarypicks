"""Measure field-goal, extra-point and two-point outcomes in the dev nfl_pbp table. Read-only.

Run: python3 scripts/nfl_sequence/measure_kick_outcomes.py [--db PATH]

The database is opened with mode=ro. The SQL printed here is the SQL recorded in
docs/SEQUENCE-E2-FIRST-PIECE-2026-10-24.md, and every number in that doc comes from this output.
"""
import argparse
import math
import sqlite3

DEFAULT_DB = '/root/legendarypicks/backend/data/picks.dev.db'
WINDOW = 'season BETWEEN 2022 AND 2025 AND week <= 18'
FG_MADE, FG_MISSED = 'Field goal', 'Missed field goal'
EP_SCORED = ('Touchdown', 'Opp touchdown')


def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes out of n."""
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


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
FROM nfl_pbp WHERE play_type = 'field_goal' GROUP BY season ORDER BY season"""
    section('2. field_goal per season, all seasons', sql)
    print(f'  {"season":>6s} {"made":>6s} {"missed":>6s} {"excl":>5s} {"rate":>6s}')
    for season, m, x, e in rows(con, sql):
        rate = m / (m + x) if m + x else float('nan')
        print(f'  {season:>6d} {m:6d} {x:6d} {e:5d} {rate:6.3f}')

    # 3. Field goals by yardline_100 (yards to the opponent's end zone at the snap; kick distance ~ yardline_100 + 17).
    bucket = """CASE WHEN yardline_100 < 10 THEN '1-9' WHEN yardline_100 < 20 THEN '10-19'
WHEN yardline_100 < 30 THEN '20-29' WHEN yardline_100 < 40 THEN '30-39' WHEN yardline_100 < 50 THEN '40-49'
ELSE '50+' END"""
    sql = f"""SELECT {bucket} AS bucket,
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

    # 5. Extra points by season, all seasons, and the primary window.
    sql = f"""SELECT season, SUM(success = 1) AS made, SUM(success = 0) AS missed
FROM nfl_pbp WHERE play_type = 'extra_point' AND series_result IN ('Touchdown', 'Opp touchdown')
GROUP BY season ORDER BY season"""
    section('5. extra_point per season, all seasons (made = success 1; series_result Touchdown or Opp touchdown)', sql)
    print(f'  {"season":>6s} {"made":>6s} {"missed":>6s} {"rate":>6s}')
    for season, m, x in rows(con, sql):
        rate = m / (m + x) if m + x else float('nan')
        print(f'  {season:>6d} {m:6d} {x:6d} {rate:6.3f}')
    excl = rows(con, """SELECT series_result, success, COUNT(*) FROM nfl_pbp
WHERE play_type = 'extra_point' AND series_result NOT IN ('Touchdown', 'Opp touchdown') GROUP BY 1, 2""")
    print(f'  excluded extra_point rows (series_result not Touchdown or Opp touchdown): {excl}')
    sql = f"""SELECT series_result, success, COUNT(*) FROM nfl_pbp
WHERE play_type = 'extra_point' AND {WINDOW} GROUP BY 1, 2 ORDER BY 1, 2"""
    section('5b. extra_point by series_result and success, 2022-2025 wk<=18', sql)
    ep = rows(con, sql)
    for lab, s, n in ep:
        print(f'  {str(lab):14s} success={s!s:4s} {n:6d}')
    m = sum(n for _, s, n in ep if s == 1)
    x = sum(n for _, s, n in ep if s == 0)
    print(f'  made={m} missed={x} rate {m / (m + x):.4f}  Wilson95 {wilson(m, m + x)}')

    # 6. Two-point attempts, primary window. success is the only outcome field; the TD flags never mark one.
    sql = f"""SELECT success, COUNT(*), ROUND(AVG(epa), 3),
  SUM(COALESCE(touchdown, 0) + COALESCE(pass_touchdown, 0) + COALESCE(rush_touchdown, 0) > 0)
FROM nfl_pbp WHERE two_point_attempt = 1 AND {WINDOW} GROUP BY success"""
    section('6. two_point_attempt=1 by success, 2022-2025 wk<=18 (count, mean epa, rows with any TD flag)', sql)
    tp = rows(con, sql)
    for s, n, e, td in tp:
        print(f'  success={s!s:4s} n={n:5d} mean_epa={e} any_td_flag={td}')
    k = sum(n for s, n, _, _ in tp if s == 1)
    t = sum(n for _, n, _, _ in tp)
    print(f'  converted={k} of {t} rate {k / t:.4f}  Wilson95 {wilson(k, t)}')


if __name__ == '__main__':
    main()
