"""Classify the pre-play score exceptions found by validate_pre_play_scores.py.

Research diagnostic, read-only. For each continuity mismatch (a play's pre-play score that differs from the previous play's
post-play score, after the possession swap) it records the size of each side's jump and the play type that came before it.
A jump of 1, 2, 3, 6, 7 or 8 points on one side with the other side unchanged is a scoring event that has no row in the
play-by-play (for example a missing point-after or a two-point try), so it is labelled as that. Anything else is unexplained.

For each final-score mismatch it records the difference between the schedule's final and the last play's post-play score,
per home and away team, and labels the common cases the same way.

Usage: python3 trace_score_exceptions.py --seasons 2010 ... 2025 --out JSON
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import holdout  # noqa: E402
import validate_pre_play_scores as v  # noqa: E402

SCORING_INCREMENTS = {1: 'point_after_or_safety', 2: 'two_point_or_safety', 3: 'field_goal', 6: 'touchdown',
                      7: 'touchdown_and_point_after', 8: 'touchdown_and_two_point'}
RAW_ROOTS = {'2010-2021': '/root/lp-snapshots/nfl-pbp-2010-2021', '2022-2025': v.DEFAULT_RAW}


def game_order(item):
    """Chronological order inside a game: quarter, then seconds remaining (descending), then play id.

    nflverse play ids are not always in game order: 37 games in 2022 and 16 in 2025 have consecutive ids that run
    backwards in the clock, so a check that follows play-id order compares states that never followed one another.
    """
    play_id, r = item
    quarter = int(float(r['qtr'])) if r['qtr'] else 99
    seconds = float(r['game_seconds_remaining']) if r['game_seconds_remaining'] else 0.0
    return (quarter, -seconds, play_id)


def raw_root(season):
    return RAW_ROOTS['2010-2021'] if season <= 2021 else RAW_ROOTS['2022-2025']


def jump_label(delta_off, delta_def):
    if delta_off == 0 and delta_def == 0:
        return 'no_change'
    if delta_off > 0 and delta_def == 0 and delta_off in SCORING_INCREMENTS:
        return f'offense_{delta_off}_{SCORING_INCREMENTS[delta_off]}'
    if delta_def > 0 and delta_off == 0 and delta_def in SCORING_INCREMENTS:
        return f'defense_{delta_def}_{SCORING_INCREMENTS[delta_def]}'
    if delta_off != 0 and delta_def != 0:
        return 'both_sides_changed'
    return 'unexplained_single_side'


def timed(raw):
    """Plays with a game clock. Untimed rows (blank clock, often a game-start row) cannot be placed in game order and are
    left out of the sequence checks; they are counted, not dropped silently."""
    untimed = [{'game_id': k[0], 'play_id': k[1], 'play_type': r['play_type'] or '', 'qtr': r['qtr'] or '',
                'pre_play_offense': r['posteam_score'] or '', 'pre_play_defense': r['defteam_score'] or ''}
               for k, r in raw.items() if not r['game_seconds_remaining']]
    return {k: r for k, r in raw.items() if r['game_seconds_remaining']}, untimed


def continuity_exceptions(raw):
    raw, untimed_rows = timed(raw)
    counts = Counter({'untimed_rows_excluded': len(untimed_rows)})
    by_prev_type = Counter()
    examples = []
    flagged = []
    by_game = defaultdict(list)
    for key, r in raw.items():
        by_game[key[0]].append((key[1], r))
    for game, plays in by_game.items():
        plays.sort(key=game_order)
        for index in range(len(plays) - 1):
            r, nxt = plays[index][1], plays[index + 1][1]
            if not (r['posteam_score_post'] and nxt['posteam_score'] and r['posteam'] and nxt['posteam']):
                continue
            post_off, post_def = v.number(r['posteam_score_post']), v.number(r['defteam_score_post'])
            act_off, act_def = v.number(nxt['posteam_score']), v.number(nxt['defteam_score'])
            if nxt['posteam'] == r['posteam']:
                exp_off, exp_def = post_off, post_def
            else:
                exp_off, exp_def = post_def, post_off
            if (exp_off, exp_def) == (act_off, act_def):
                continue
            label = jump_label(act_off - exp_off, act_def - exp_def)
            if label.startswith(('unexplained', 'both_sides')):
                pre_off, pre_def = v.number(r['posteam_score']), v.number(r['defteam_score'])
                if nxt['posteam'] == r['posteam']:
                    before = (pre_off, pre_def)
                else:
                    before = (pre_def, pre_off)
                if (act_off, act_def) == before:
                    label = 'stale_repeat_of_state_before_previous_play'
            counts[label] += 1
            by_prev_type[(r['play_type'] or 'null', label)] += 1
            flagged.append({'game_id': game, 'play_id': plays[index + 1][0], 'label': label,
                            'previous_play_id': plays[index][0], 'previous_play_type': r['play_type'] or '',
                            'expected_offense': exp_off, 'expected_defense': exp_def,
                            'actual_offense': act_off, 'actual_defense': act_def})
            if len(examples) < 3 and label.startswith('unexplained'):
                examples.append({'game_id': game, 'play_id': plays[index][0], 'prev_play_type': r['play_type'],
                                 'expected': [exp_off, exp_def], 'actual': [act_off, act_def]})
    return counts, by_prev_type, examples, flagged, untimed_rows


def final_exceptions(raw, finals):
    counts = Counter()
    rows = []
    by_game = defaultdict(list)
    for key, r in raw.items():
        by_game[key[0]].append((key[1], r))
    for game, plays in by_game.items():
        if game not in finals or not plays:
            continue
        plays.sort(key=game_order)
        last = plays[-1][1]
        home_score, away_score, home_team, away_team = finals[game]
        post_team, post_opp = v.number(last['posteam_score_post']), v.number(last['defteam_score_post'])
        if post_team is None or post_opp is None or not last['posteam']:
            counts['last_play_score_missing'] += 1
            continue
        home_post, away_post = (post_team, post_opp) if last['posteam'] == home_team else (post_opp, post_team)
        dh, da = home_score - home_post, away_score - away_post
        if dh == 0 and da == 0:
            counts['match'] += 1
        else:
            counts[f'home_{int(dh)}_away_{int(da)}_points_after_last_play'] += 1
            rows.append({'game_id': game, 'last_play_id': plays[-1][0], 'last_play_type': last['play_type'] or '',
                         'final_home': int(home_score), 'final_away': int(away_score),
                         'last_post_home': int(home_post), 'last_post_away': int(away_post)})
    return counts, rows


def trace(season, raw_dir, db):
    holdout.refuse_if_holdout(season, 'score exception trace')
    path = Path(raw_dir) / f'pbp_{season}.csv.gz'
    raw = v.raw_plays(path, season)
    finals = v.schedule_finals(db, season)
    cont, by_type, examples, flagged, untimed_rows = continuity_exceptions(raw)
    fin, final_rows = final_exceptions(raw, finals)
    return {'season': season, 'continuity_exceptions': dict(cont.most_common()),
            'continuity_by_previous_play_type': {f'{p}|{l}': n for (p, l), n in by_type.most_common(12)},
            'continuity_unexplained_examples': examples, 'final_score_outcomes': dict(fin.most_common()),
            'flagged_plays': [{**item, 'season': season} for item in flagged],
            'untimed_rows': [{**item, 'season': season} for item in untimed_rows],
            'final_mismatch_rows': [{**item, 'season': season} for item in final_rows]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', type=int, nargs='+', required=True)
    ap.add_argument('--db', default=v.DEFAULT_DB)
    ap.add_argument('--out', type=Path)
    ap.add_argument('--flags', type=Path, help='CSV of the play ids whose pre-play score disagrees with the previous play')
    ap.add_argument('--remaining', type=Path, help='CSV listing every remaining continuity, untimed and final-score row')
    args = ap.parse_args()
    report = []
    for season in args.seasons:
        report.append(trace(season, raw_root(season), args.db))
    flagged = [item for season in report for item in season['flagged_plays']]
    untimed = [item for season in report for item in season['untimed_rows']]
    final = [item for season in report for item in season['final_mismatch_rows']]
    for season in report:
        for key in ('flagged_plays', 'untimed_rows', 'final_mismatch_rows'):
            season.pop(key)
    text = json.dumps(report, indent=1, sort_keys=True)
    if args.out:
        args.out.write_text(text + '\n')
    import csv
    if args.flags:
        with open(args.flags, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['season', 'game_id', 'play_id', 'label'], extrasaction='ignore',
                                    lineterminator='\n')
            writer.writeheader()
            writer.writerows(flagged)
    if args.remaining:
        fields = ['category', 'season', 'game_id', 'play_id', 'label', 'previous_play_id', 'previous_play_type',
                  'expected_offense', 'expected_defense', 'actual_offense', 'actual_defense', 'qtr', 'pre_play_offense',
                  'pre_play_defense', 'final_home', 'final_away', 'last_post_home', 'last_post_away']
        rows = ([{**item, 'category': 'continuity_exception'} for item in flagged]
                + [{**item, 'category': 'untimed_row', 'label': 'no_game_clock'} for item in untimed]
                + [{**item, 'category': 'final_score_mismatch', 'label': 'final_vs_last_play_post_score',
                    'play_id': item['last_play_id']} for item in final])
        with open(args.remaining, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore', restval='', lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
    print(text)


if __name__ == '__main__':
    main()
