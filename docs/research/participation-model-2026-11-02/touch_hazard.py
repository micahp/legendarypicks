#!/usr/bin/env python3
"""Does a recent touch change when a skill player leaves the field? (SLC v2 steps 3 and 4, research).

For each consecutive pair of offensive snaps in a team-game, a skill player on the field at the earlier snap is counted
as leaving if he is off the field at the next snap. Every on-field skill player is used, and nothing about the next
snap's grouping is conditioned on. So the leave rate is the probability a forecast would need, not a rate that depends
on the outcome. The features are all from the earlier snap: his class, his stint, and whether he touched the ball on
that play (the rusher or receiver, from the nflverse play-by-play by game_id and play_id) and that play's type.

Because forced substitutions are included, these rates mix rotation with count changes. A grouping model would
separate them, but that requires the next snap's grouping, which a forecast does not have.

Rates are tabulated by class, stint bucket (1 to 6, 6 meaning 6 or more) and whether he touched the ball on the earlier
snap. Estimation uses 2022 to 2024, and the 2025 holdout is scored out of sample.

Usage: python3 touch_hazard.py --tables <scrimmage_participation.csv.gz> --raw-dir <pinned nflverse dir> --out <json>
"""
import argparse
import csv
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import candidate_substitution as cs  # noqa: E402
import diagnose_substitution_gap as dg  # noqa: E402
import lineup_fit as lf  # noqa: E402
import participation_labels as pl  # noqa: E402
import participation_model as pm  # noqa: E402
import participation_field as pf  # noqa: E402

CLASSES = pf.SKILL_CLASSES
CAP = 6


def load_touches(raw_dir, seasons):
    """{(game_id, play_id): (play_type, frozenset of rusher and receiver ids)} for regular-season plays."""
    out = {}
    for season in seasons:
        with gzip.open(raw_dir / f'pbp_{season}.csv.gz', 'rt', encoding='utf-8', newline='') as handle:
            for row in csv.DictReader(handle):
                if row['season_type'] != 'REG' or not row['play_id']:
                    continue
                ids = frozenset(x for x in (row['rusher_player_id'], row['receiver_player_id']) if x)
                play = 'run' if row['rush_attempt'] == '1' else 'pass' if row['pass_attempt'] == '1' else 'other'
                out[(row['game_id'], int(float(row['play_id'])))] = (play, ids)
    return out


def pairs(rows, touches, recon=None):
    """Yield (season, class, stint bucket, touched the earlier snap, earlier play type, left before the next snap)."""
    seqs = defaultdict(list)
    for row in rows:
        key = (int(row['season']), row['game_id'], row['posteam'])
        skill = {pid: label for pid, label, _source in pl.aligned_labels(row, recon) if label in lf.SKILL}
        seqs[key].append((int(row['play_id']), frozenset(skill), {p: lf.SKILL[lab] for p, lab in skill.items()}))
    for key, items in seqs.items():
        items.sort(key=lambda it: it[0])
        ids = [it[1] for it in items]
        cls = [it[2] for it in items]
        stints = dg.stint_track(ids)
        for i in range(1, len(items)):
            prev_play = items[i - 1][0]
            play_type, touched = touches.get((key[1], prev_play), ('other', frozenset()))
            for pid in ids[i - 1]:
                c = cls[i - 1].get(pid)
                if c is None:
                    continue
                yield key[0], c, min(stints[i - 1][pid], CAP), pid in touched, play_type, pid not in ids[i]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables', type=Path, required=True)
    ap.add_argument('--raw-dir', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--positions', type=Path, default=None, help='reconstructed 2022 positions (reconstruct_positions.py)')
    args = ap.parse_args()

    seasons = {2022, 2023, 2024, 2025}
    rows = [r for r in pm.load_scrimmage(args.tables, seasons) if r['season_type'] == 'REG']
    touches = load_touches(args.raw_dir, seasons)
    recon = pl.load_reconstruction(args.positions) if args.positions else None
    events = list(pairs(rows, touches, recon))

    def tabulate(season_set):
        cells = defaultdict(lambda: [0, 0])
        for season, c, bucket, touched, _pt, left in events:
            if season in season_set:
                cells[(c, bucket, 'touched' if touched else 'untouched')][0] += 1
                cells[(c, bucket, 'touched' if touched else 'untouched')][1] += int(left)
        return cells

    fit, hold = tabulate(cs.FIT_SEASONS), tabulate(cs.HOLDOUT)

    def rate(cells, c, bucket, state):
        n, left = cells.get((c, bucket, state), (0, 0))
        return (left / n if n else None), n

    table = {}
    for c in CLASSES:
        for bucket in range(1, CAP + 1):
            row = {}
            for state in ('untouched', 'touched'):
                r_fit, n_fit = rate(fit, c, bucket, state)
                r_hold, n_hold = rate(hold, c, bucket, state)
                row[state] = {'fit_rate': None if r_fit is None else round(r_fit, 4), 'fit_n': n_fit,
                              'holdout_rate': None if r_hold is None else round(r_hold, 4), 'holdout_n': n_hold}
            table[f'{c}|stint{bucket}'] = row

    play_type = defaultdict(lambda: [0, 0])
    for season, _c, _bucket, touched, pt, left in events:
        if not touched and season in cs.FIT_SEASONS:
            play_type[pt][0] += 1
            play_type[pt][1] += int(left)
    untouched_by_play = {pt: {'n': n, 'leave_rate': round(l / n, 4)} for pt, (n, l) in sorted(play_type.items()) if n}

    def logloss_with(key_fn):
        """Leave probability from the fit cells, scored on the holdout pairs. A cell with no fit data falls back to
        the class-by-stint rate, so a spec is never scored on an empty cell."""
        fit_cells, fit_totals = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
        for season, c, bucket, touched, pt, left in events:
            if season in cs.FIT_SEASONS:
                k = key_fn(c, bucket, touched, pt)
                fit_cells[k][0] += 1
                fit_cells[k][1] += int(left)
                fit_totals[(c, bucket)][0] += 1
                fit_totals[(c, bucket)][1] += int(left)
        total, n = 0.0, 0
        for season, c, bucket, touched, pt, left in events:
            if season not in cs.HOLDOUT:
                continue
            k = key_fn(c, bucket, touched, pt)
            if fit_cells[k][0]:
                pr = fit_cells[k][1] / fit_cells[k][0]
            else:
                tn, tl = fit_totals[(c, bucket)]
                pr = tl / tn if tn else 0.5
            pr = min(max(pr, 1e-6), 1 - 1e-6)
            total += -(math.log(pr) if left else math.log(1 - pr))
            n += 1
        return round(total / max(n, 1), 6), n

    holdout_logloss = {
        'class_stint': logloss_with(lambda c, b, t, pt: (c, b)),
        'class_stint_touch': logloss_with(lambda c, b, t, pt: (c, b, t)),
        'class_stint_touch_playtype': logloss_with(lambda c, b, t, pt: (c, b, t, pt)),
    }
    out = {'source': args.tables.name, 'cap': CAP, 'fit_seasons': sorted(cs.FIT_SEASONS),
           'holdout': sorted(cs.HOLDOUT), 'holdout_logloss_per_pair': holdout_logloss,
           'leakage_check': 'every feature (class, stint, touch, play type) comes from the earlier snap; the next '
                            'snap is used only for the leave outcome, and nothing about its grouping is conditioned on',
           'pairs': len(events), 'rates_by_class_stint_touch': table,
           'untouched_leave_rate_by_earlier_play_type_fit': untouched_by_play}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'pairs': len(events), 'holdout_logloss_per_pair': holdout_logloss}, sort_keys=True))


if __name__ == '__main__':
    main()
