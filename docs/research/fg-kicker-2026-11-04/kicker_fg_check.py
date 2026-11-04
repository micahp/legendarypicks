#!/usr/bin/env python3
"""Field goals by kicker: range and make curve, from published nflverse data (research).

Three measurements, all as of each game's week (only kicks before that week are used):

1. Reconciliation. Per kicker-week, the play-by-play field-goal attempts (play_type field_goal, field_goal_result made,
   missed or blocked) against the published player stats (stats_player_week and stats_player_post: fg_made, fg_missed,
   fg_blocked, fg_long), 2016 to 2025.
2. Range. Each attempt's distance against the kicker's career longest make before that week (the published fg_long,
   maximum over earlier weeks since 1999). Counted per season: attempts beyond it, how many of those come at the end of a
   half (Q2 or Q4, 60 seconds or less left in the half) or in desperation (Q4, 300 seconds or less, trailing by 8 or more:
   the engine's exceptions), how many by kickers with no earlier make, and how many beyond 60 yards outside both windows.
   Also the league median career longest make over kickers with a make in the season before.
3. Make curve, week over week. League: the engine's monotone logistic (measure_kick_outcomes._logit_fit, blocked kicks
   count as failures) on the four seasons before the target plus the target season's earlier weeks. Kicker: the league
   curve plus a logit offset for the kicker, the posterior mode under a normal prior with standard deviation SIGMA, from
   the kicker's earlier attempts since 1999 weighted RECENCY ** (seasons ago), each judged against its own week's league
   curve. Scored by the log loss of made versus not made.
   SIGMA in {0.1, 0.2, 0.3, 0.5, 0.8} and RECENCY in {0.5, 1.0} are chosen, before the 2022 to 2025 run, by the lowest
   pooled log loss on the 2016 to 2021 targets. Differences have game-clustered bootstrap intervals, by distance band.

Usage: python3 kicker_fg_check.py --raw <nflverse backfill raw dir> --out <json>
"""
import argparse
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / 'scripts' / 'nfl_sequence'))
import measure_kick_outcomes as mk  # noqa: E402

FIRST, LAST = 1999, 2025
TUNE = list(range(2016, 2022))
TARGETS = [2022, 2023, 2024, 2025]
LEAGUE_SEASONS = 4
SIGMAS = (0.1, 0.2, 0.3, 0.5, 0.8)
RECENCIES = (0.5, 1.0)
ORDINARY_CUTOFF = 60
BOOT = 2000
PBP_COLUMNS = ['play_type', 'field_goal_result', 'kick_distance', 'kicker_player_id', 'posteam', 'season', 'week',
               'season_type', 'game_id', 'play_id', 'qtr', 'half_seconds_remaining', 'game_seconds_remaining',
               'score_differential', 'yardline_100']


def load_attempts(raw):
    import pyarrow.parquet as pq
    out, skipped = [], Counter()
    for season in range(FIRST, LAST + 1):
        t = pq.read_table(Path(raw) / 'pbp' / f'play_by_play_{season}.parquet', columns=PBP_COLUMNS).to_pydict()
        for i in range(len(t['play_type'])):
            if t['play_type'][i] != 'field_goal':
                continue
            result, distance, kicker = t['field_goal_result'][i], t['kick_distance'][i], t['kicker_player_id'][i]
            if result not in ('made', 'missed', 'blocked') or distance is None or not kicker:
                skipped[f'{result}|{distance is None}|{bool(kicker)}'] += 1
                continue
            out.append({k: t[k][i] for k in PBP_COLUMNS})
    for row in out:
        row['season'], row['week'] = int(row['season']), int(row['week'])
        row['kick_distance'] = float(row['kick_distance'])
    out.sort(key=lambda r: (r['season'], r['week'], r['game_id'], r['play_id']))
    return out, dict(skipped)


def load_published(raw):
    """{(player_id, season, week): {'made', 'missed', 'blocked', 'long'}} from the published weekly player stats."""
    import pyarrow.parquet as pq
    out = {}
    for season in range(FIRST, LAST + 1):
        for kind in ('week', 'post'):
            path = Path(raw) / 'stats_player' / f'stats_player_{kind}_{season}.parquet'
            cols = ['player_id', 'season', 'week', 'fg_made', 'fg_missed', 'fg_blocked', 'fg_long', 'fg_att']
            t = pq.read_table(path, columns=cols).to_pydict()
            for i in range(len(t['player_id'])):
                if not t['fg_att'][i]:
                    continue
                key = (t['player_id'][i], int(t['season'][i]), int(t['week'][i]))
                if key in out:
                    raise ValueError(f'duplicate published kicker-week {key}')
                out[key] = {'made': t['fg_made'][i] or 0, 'missed': t['fg_missed'][i] or 0,
                            'blocked': t['fg_blocked'][i] or 0, 'long': t['fg_long'][i]}
    return out


def reconcile(attempts, published, seasons):
    pbp = defaultdict(Counter)
    for r in attempts:
        if r['season'] in seasons:
            c = pbp[(r['kicker_player_id'], r['season'], r['week'])]
            c[r['field_goal_result']] += 1
            if r['field_goal_result'] == 'made':
                c['long'] = max(c['long'], int(r['kick_distance']))
    pub = {k: v for k, v in published.items() if k[1] in seasons}
    keys = set(pbp) | set(pub)
    out = Counter()
    for k in keys:
        a, b = pbp.get(k), pub.get(k)
        if a is None or b is None:
            out['only_pbp' if b is None else 'only_published'] += 1
            continue
        same = all(a[f] == b[f] for f in ('made', 'missed', 'blocked'))
        long_same = (a['long'] or None) == (b['long'] or None) if b['made'] else True
        out['counts_agree' if same else 'counts_differ'] += 1
        out['long_agree' if long_same else 'long_differ'] += 1
    out['kicker_weeks'] = len(keys)
    return dict(out)


def career_long(published):
    """{player_id: [(season, week, long)]} sorted, for the career longest make before a week."""
    out = defaultdict(list)
    for (pid, season, week), v in published.items():
        if v['made'] and v['long']:
            out[pid].append((season, week, int(v['long'])))
    for v in out.values():
        v.sort()
    return out


def long_before(history, pid, season, week):
    best = None
    for s, w, long in history.get(pid, ()):
        if (s, w) >= (season, week):
            break
        best = long if best is None else max(best, long)
    return best


def window(r):
    end_half = int(r['qtr']) in (2, 4) and (r['half_seconds_remaining'] or 0) <= 60
    desperation = int(r['qtr']) == 4 and (r['game_seconds_remaining'] or 0) <= 300 and (r['score_differential'] or 0) <= -8
    return end_half or desperation


def range_check(attempts, history, seasons):
    by_season = {}
    for season in seasons:
        rows = [r for r in attempts if r['season'] == season]
        c = Counter(attempts=len(rows))
        beyond_made = Counter()
        for r in rows:
            long = long_before(history, r['kicker_player_id'], r['season'], r['week'])
            d = r['kick_distance']
            if long is None:
                c['no_earlier_make'] += 1
                continue
            if d > long:
                c['beyond_career_long'] += 1
                c['beyond_career_long_in_window'] += int(window(r))
                c['beyond_career_long_by_5_or_more'] += int(d >= long + 5)
                beyond_made[r['field_goal_result']] += 1
            if d > ORDINARY_CUTOFF:
                c['over_60'] += 1
                c['over_60_outside_window'] += int(not window(r))
        c['beyond_career_long_results'] = dict(beyond_made)
        last = {pid for pid, v in history.items() if any(s == season - 1 for s, _w, _l in v)}
        prev = [long_before(history, pid, season, 1) for pid in last]
        prev = [x for x in prev if x is not None]
        c['league_median_career_long_of_last_season_kickers'] = statistics.median(prev) if prev else None
        c['last_season_kickers'] = len(prev)
        by_season[season] = dict(c)
    return by_season


def league_curve(attempts, season, week):
    rows = [r for r in attempts if season - LEAGUE_SEASONS <= r['season'] < season
            or (r['season'] == season and r['week'] < week)]
    return mk._logit_fit([{'kick_distance': r['kick_distance'], 'field_goal_result': r['field_goal_result']} for r in rows])


def p_league(curve, distance):
    z = curve['intercept'] + curve['distance_slope_per_10_yards'] * (distance - curve['distance_center_yards']) / 10.0
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def kicker_offset(history, sigma, recency, season):
    """Posterior mode of the kicker's logit offset. history: [(season, league logit at the kick, made)] before the week;
    each earlier kick is judged against the league curve of its own week."""
    delta = 0.0
    for _ in range(50):
        g, h = -delta / sigma ** 2, 1.0 / sigma ** 2
        for s, z0, made in history:
            w = recency ** (season - s)
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z0 + delta))))
            g += w * (made - p)
            h += w * p * (1 - p)
        step = g / h
        delta += step
        if abs(step) < 1e-8:
            break
    return delta


def logit(p):
    return math.log(p / (1 - p))


def score(attempts, seasons, sigma, recency, curves):
    """Per attempt in the target seasons: (game_id, band, log loss league, log loss kicker). Walks every week from 1999,
    so each kicker's history holds his kicks before the week."""
    out = []
    by_kicker = defaultdict(list)
    rows_by_week = defaultdict(list)
    for r in attempts:
        rows_by_week[(r['season'], r['week'])].append(r)
    for sw in sorted(rows_by_week):
        rows = rows_by_week[sw]
        curve = curves[sw]
        if sw[0] in seasons:
            deltas = {}
            for r in rows:
                pid = r['kicker_player_id']
                if pid not in deltas:
                    deltas[pid] = kicker_offset(by_kicker[pid], sigma, recency, sw[0])
                d, made = r['kick_distance'], r['field_goal_result'] == 'made'
                pl = p_league(curve, d)
                pk = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, logit(pl) + deltas[pid]))))
                band = '<40' if d < 40 else '40-49' if d < 50 else '50+'
                out.append((r['game_id'], band, -math.log(pl if made else 1 - pl), -math.log(pk if made else 1 - pk)))
        for r in rows:
            by_kicker[r['kicker_player_id']].append(
                (r['season'], logit(p_league(curve, r['kick_distance'])), r['field_goal_result'] == 'made'))
    return out


def summarize(rows, rng):
    out = {}
    for band in ('<40', '40-49', '50+', 'all'):
        sel = [r for r in rows if band == 'all' or r[1] == band]
        by_game = defaultdict(lambda: [0.0, 0.0, 0])
        for game, _b, ll, lk in sel:
            by_game[game][0] += ll
            by_game[game][1] += lk
            by_game[game][2] += 1
        games = list(by_game.values())
        n = sum(g[2] for g in games)
        league, kicker = sum(g[0] for g in games) / n, sum(g[1] for g in games) / n
        draws = []
        for _ in range(BOOT):
            pick = [games[rng.randrange(len(games))] for _ in games]
            draws.append(sum(g[1] - g[0] for g in pick) / sum(g[2] for g in pick))
        draws.sort()
        out[band] = {'attempts': n, 'league_log_loss': round(league, 5), 'kicker_log_loss': round(kicker, 5),
                     'kicker_minus_league': round(kicker - league, 5),
                     'ci95': [round(draws[int(0.025 * BOOT)], 5), round(draws[int(0.975 * BOOT) - 1], 5)]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    attempts, skipped = load_attempts(args.raw)
    published = load_published(args.raw)
    report = {'attempts_1999_2025': len(attempts), 'skipped_pbp_rows': skipped,
              'reconciliation_2016_2025': reconcile(attempts, published, set(range(2016, 2026)))}
    print('reconciliation', report['reconciliation_2016_2025'], flush=True)
    offsets = Counter(int(r['kick_distance'] - r['yardline_100']) for r in attempts if r['season'] >= 2016)
    report['kick_distance_minus_yardline_2016_2025'] = dict(sorted(offsets.items()))
    history = career_long(published)
    report['range_by_season'] = range_check(attempts, history, list(range(2016, 2026)))
    for s, v in report['range_by_season'].items():
        print(s, v, flush=True)
    curves = {}  # the league curve each week; 1999's weeks use 1999 itself, as history only (never scored)
    first = league_curve(attempts, FIRST + 1, 1)
    for season, week in sorted({(r['season'], r['week']) for r in attempts}):
        curves[(season, week)] = first if season == FIRST else league_curve(attempts, season, week)
    print('league curves', len(curves), flush=True)
    grid = {}
    for sigma in SIGMAS:
        for recency in RECENCIES:
            rows = score(attempts, set(TUNE), sigma, recency, curves)
            grid[(sigma, recency)] = sum(r[3] for r in rows) / len(rows)
            league = sum(r[2] for r in rows) / len(rows)
            print(f'tune sigma={sigma} recency={recency} kicker {grid[(sigma, recency)]:.5f} league {league:.5f}', flush=True)
    sigma, recency = min(grid, key=lambda k: (grid[k], k))
    report['tune'] = {f'sigma={s},recency={r}': round(v, 5) for (s, r), v in sorted(grid.items())}
    report['selected'] = {'sigma': sigma, 'recency': recency}
    rows = score(attempts, set(TARGETS), sigma, recency, curves)
    report['targets_2022_2025'] = summarize(rows, random.Random(20261104))
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True, default=str))
    print(json.dumps(report['targets_2022_2025'], indent=1))


if __name__ == '__main__':
    main()
