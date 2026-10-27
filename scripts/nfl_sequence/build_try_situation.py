"""Went-for-two situations from the nflverse play-by-play parquet files, 2022-2025.

An eligible try is an extra-point or two-point attempt that follows a touchdown by the same team. Between the two, only
no-play rows may appear (a penalty nullifies a play and leaves a no-play row behind). A try that a penalty cancelled has no
attempt flag and is counted as canceled, not eligible. A second try row with no touchdown behind it is counted as a
duplicate. Every exclusion is counted in the manifest.

Writes the situation fixture (one row per eligible try), a sidecar manifest with the sources' SHA-256 and every count, and an
audit JSON with the decision tables. Margin is the scoring team's score minus the opponent's after the six points and before
the try.

Usage: /root/.venvs/nfl-parquet/bin/python scripts/nfl_sequence/build_try_situation.py [--source-dir DIR] [--out CSV]
"""
import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = Path('/root/nflverse-raw')
DEFAULT_OUT = REPO / 'docs' / 'fixtures' / 'e2' / 'try_situation_2022_2025.csv'
SEASONS = (2022, 2023, 2024, 2025)
TRY_LOOKBACK = 12  # plays searched back from a try for its touchdown; canceled penalty rows sit in between
COLUMNS = ['game_id', 'play_id', 'season', 'season_type', 'week', 'drive', 'qtr', 'quarter_seconds_remaining', 'posteam',
           'defteam', 'posteam_score', 'defteam_score', 'posteam_score_post', 'defteam_score_post', 'touchdown', 'td_team',
           'extra_point_attempt', 'extra_point_result', 'two_point_attempt', 'two_point_conv_result', 'play_type', 'penalty',
           'field_goal_result', 'safety', 'home_team', 'away_team', 'home_coach', 'away_coach']
OUT_COLUMNS = ['season', 'season_type', 'week', 'game_id', 'play_id', 'scorer', 'kind', 'result', 'made', 'qtr',
               'quarter_seconds_remaining', 'game_seconds_remaining', 'period', 'margin', 'opening_drive', 'first_td',
               'first_score', 'defensive_td', 'skipped_no_play_rows', 'scorer_coach']


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def wilson(k, n, z=1.96):
    if n == 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(100 * (c - h), 1), round(100 * (c + h), 1)


def cell(rows):
    n = len(rows)
    k = sum(1 for r in rows if r['kind'] == 'two_point')
    lo, hi = wilson(k, n)
    return {'two': k, 'n': n, 'pct': round(100 * k / n, 1) if n else None, 'ci95': [lo, hi]}


def period_of(qtr, qsec):
    if qtr in (1, 2):
        return 'H1'
    if qtr == 3:
        return 'Q3'
    if qtr == 4:
        return 'Q4_gt5' if qsec > 300 else 'Q4_le5'
    return 'OT'


def game_seconds(qtr, qsec):
    return (4 - qtr) * 900 + qsec if qtr <= 4 else qsec


def is_try(r):
    return r['extra_point_attempt'] == 1 or r['two_point_attempt'] == 1


def is_scoring(r):
    return r['touchdown'] == 1 or r['field_goal_result'] == 'made' or r['safety'] == 1


def score_of(r, team, when):
    if team == r['posteam']:
        return r['posteam_score'] if when == 'pre' else r['posteam_score_post']
    return r['defteam_score'] if when == 'pre' else r['defteam_score_post']


def load_games(source):
    games = defaultdict(list)
    files = []
    for season in SEASONS:
        path = Path(source) / f'play_by_play_{season}.parquet'
        names = pq.ParquetFile(path).schema_arrow.names
        missing = [c for c in COLUMNS if c not in names]
        if missing:
            raise SystemExit(f'{path} lacks {missing}')
        files.append(path)
        t = pq.read_table(path, columns=COLUMNS).to_pydict()
        for i in range(len(t['game_id'])):
            games[t['game_id'][i]].append({k: t[k][i] for k in COLUMNS})
    for plays in games.values():
        plays.sort(key=lambda r: r['play_id'])
    return games, files


def link_try(plays, i):
    """The touchdown behind the try at i: the nearest touchdown before it, when that touchdown is the same team's and no
    other try comes between. Returns (touchdown index or None, rows skipped, reason)."""
    skipped = 0
    for j in range(i - 1, max(-1, i - TRY_LOOKBACK - 1), -1):
        p = plays[j]
        if p['touchdown'] == 1:
            if p['td_team'] == plays[i]['posteam']:
                return j, skipped, 'linked'
            return None, skipped, 'nearest_touchdown_other_team'
        if is_try(p):
            return None, skipped, 'duplicate_try_row'
        skipped += 1
    return None, skipped, 'no_touchdown_within_lookback'


def build(games):
    rows, diag = [], Counter()
    unlinked = Counter()
    for gid, plays in games.items():
        first_drive = {}
        for r in plays:
            if r['posteam'] and r['drive'] is not None:
                first_drive[r['posteam']] = min(first_drive.get(r['posteam'], 10 ** 9), r['drive'])
        tds = [i for i, r in enumerate(plays) if r['touchdown'] == 1]
        scoring = [i for i, r in enumerate(plays) if is_scoring(r)]
        linked_td = set()
        for i, r in enumerate(plays):
            if not is_try(r):
                continue
            if r['season_type'] not in ('REG', 'POST'):
                diag['try_other_season_type'] += 1
                continue
            j, skipped, reason = link_try(plays, i)
            if j is None:
                unlinked[reason] += 1
                continue
            if j in linked_td:
                unlinked['second_try_for_one_touchdown'] += 1
                continue
            diag['max_rows_skipped_before_try'] = max(diag['max_rows_skipped_before_try'], skipped)
            if any(plays[k]['play_type'] == 'kickoff' for k in range(j + 1, i)):
                diag['try_linked_across_kickoff_row'] += 1
            linked_td.add(j)
            td = plays[j]
            scorer = td['td_team']
            if scorer is None:
                diag['touchdown_without_team'] += 1
                continue
            if td['touchdown'] != 1:
                raise SystemExit('touchdown index mismatch')
            td_post = score_of(td, scorer, 'post')
            td_pre = score_of(td, scorer, 'pre')
            if td_post - td_pre != 6:
                diag['td_did_not_add_six'] += 1
            pre_s, pre_o = score_of(r, scorer, 'pre'), score_of(r, r['defteam'] if scorer == r['posteam'] else r['posteam'], 'pre')
            if pre_s != td_post:
                diag['try_score_disagrees_with_td'] += 1
            if td['penalty'] == 1:
                diag['eligible_try_after_penalty_flagged_td'] += 1
            kind = 'two_point' if r['two_point_attempt'] == 1 else 'extra_point'
            result = r['two_point_conv_result'] if kind == 'two_point' else r['extra_point_result']
            made = None
            if result is not None:
                made = int(result in ('success', 'good'))
            else:
                diag['eligible_try_without_result'] += 1
            qtr, qsec = int(r['qtr']), int(r['quarter_seconds_remaining'])
            opening = scorer == td['posteam'] and td['drive'] == first_drive.get(scorer)
            coach = ''
            if scorer == r['home_team']:
                coach = r['home_coach'] or ''
            elif scorer == r['away_team']:
                coach = r['away_coach'] or ''
            if not coach:
                diag['eligible_try_without_coach'] += 1
            rows.append({
                'season': r['season'], 'season_type': r['season_type'], 'week': r['week'], 'game_id': gid,
                'play_id': int(r['play_id']), 'scorer': scorer, 'kind': kind, 'result': result or '',
                'made': '' if made is None else made, 'qtr': qtr, 'quarter_seconds_remaining': qsec,
                'game_seconds_remaining': game_seconds(qtr, qsec), 'period': period_of(qtr, qsec),
                'margin': int(pre_s - pre_o), 'opening_drive': int(bool(opening)), 'first_td': int(tds[0] == j),
                'first_score': int(bool(scoring) and scoring[0] == j), 'defensive_td': int(scorer != td['posteam']),
                'skipped_no_play_rows': skipped, 'scorer_coach': coach,
            })
        for j in tds:
            td = plays[j]
            if td['td_team'] is None:
                continue
            diag['touchdown_rows'] += 1
            if j not in linked_td:
                nxt = plays[j + 1] if j + 1 < len(plays) else None
                key = 'end' if nxt is None else (nxt['play_type'] or 'none')
                unlinked[f'touchdown_without_try:{td["season_type"]}:next={key}'] += 1
    rows.sort(key=lambda r: (r['season'], r['week'], r['game_id'], r['play_id']))
    return rows, diag, unlinked


def count_canceled(games):
    canceled = Counter()
    for plays in games.values():
        for r in plays:
            if r['play_type'] == 'extra_point' and not is_try(r):
                canceled[r['season_type']] += 1
    return canceled


def tables(rows):
    reg = [r for r in rows if r['season_type'] == 'REG']
    post = [r for r in rows if r['season_type'] == 'POST']
    out = {'regular_season': {}, 'postseason': {}}
    out['regular_season']['all'] = cell(reg)
    out['regular_season']['by_season'] = {s: cell([r for r in reg if r['season'] == s]) for s in SEASONS}
    out['regular_season']['by_quarter'] = {q: cell([r for r in reg if r['qtr'] == q]) for q in (1, 2, 3, 4, 5)}
    out['regular_season']['opening_drive'] = {str(v): cell([r for r in reg if r['opening_drive'] == v]) for v in (1, 0)}
    out['regular_season']['first_td'] = {str(v): cell([r for r in reg if r['first_td'] == v]) for v in (1, 0)}
    out['regular_season']['first_score'] = {str(v): cell([r for r in reg if r['first_score'] == v]) for v in (1, 0)}
    out['regular_season']['defensive_td'] = {str(v): cell([r for r in reg if r['defensive_td'] == v]) for v in (1, 0)}
    out['regular_season']['q1_to_q3'] = cell([r for r in reg if r['qtr'] <= 3])
    out['regular_season']['margin'] = {}
    for m in sorted({r['margin'] for r in reg}):
        block = {'all': cell([r for r in reg if r['margin'] == m])}
        for p in ('H1', 'Q3', 'Q4_gt5', 'Q4_le5'):
            block[p] = cell([r for r in reg if r['margin'] == m and r['period'] == p])
        out['regular_season']['margin'][str(m)] = block
    out['postseason']['all'] = cell(post)
    out['postseason']['by_season'] = {s: cell([r for r in post if r['season'] == s]) for s in SEASONS}
    out['regular_season']['two_point_success'] = _success(reg)
    out['postseason']['two_point_success'] = _success(post)
    return out


def _success(rows):
    two = [r for r in rows if r['kind'] == 'two_point' and r['made'] != '']
    xp = [r for r in rows if r['kind'] == 'extra_point' and r['made'] != '']
    return {'two_point_made': sum(r['made'] for r in two), 'two_point_attempts': len(two),
            'extra_point_made': sum(r['made'] for r in xp), 'extra_point_attempts': len(xp)}


def fmt(c):
    if not c['n']:
        return '-'
    return f"{c['two']}/{c['n']} {c['pct']}% [{c['ci95'][0]}-{c['ci95'][1]}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source-dir', default=str(DEFAULT_SOURCE))
    ap.add_argument('--out', default=str(DEFAULT_OUT))
    args = ap.parse_args()
    out = Path(args.out)
    games, files = load_games(args.source_dir)
    rows, diag, unlinked = build(games)
    canceled = count_canceled(games)
    tab = tables(rows)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        'generator': 'scripts/nfl_sequence/build_try_situation.py',
        'generator_sha256': sha256(__file__),
        'columns': OUT_COLUMNS,
        'window': 'season 2022-2025, season_type REG and POST (week <= 18 for REG)',
        'sources': {p.name: sha256(p) for p in files},
        'exclusions': {
            'canceled_extra_point_rows (penalty nullified the kick; no attempt flag)': dict(canceled),
            'unlinked_try_rows': dict(sorted(unlinked.items())),
            'diagnostics': dict(sorted(diag.items())),
        },
        'output': {'path': str(out.relative_to(REPO)) if out.is_relative_to(REPO) else str(out), 'sha256': sha256(out),
                   'rows': len(rows), 'regular_season_rows': sum(1 for r in rows if r['season_type'] == 'REG'),
                   'postseason_rows': sum(1 for r in rows if r['season_type'] == 'POST')},
    }
    Path(str(out) + '.manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    audit = out.with_name(out.stem + '.audit.json')
    audit.write_text(json.dumps(tab, indent=1, sort_keys=True, default=str) + '\n')
    print(f'wrote {out} ({len(rows)} rows), manifest, and {audit.name}')
    reg = tab['regular_season']
    print('REG all', fmt(reg['all']), '| POST all', fmt(tab['postseason']['all']))
    print('canceled XP rows', dict(canceled), '| unlinked', dict(unlinked), '| diagnostics', dict(diag))


if __name__ == '__main__':
    main()
