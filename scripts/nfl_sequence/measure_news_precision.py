#!/usr/bin/env python3
"""Measure news_evidence.classify against hand labels.

sample: freeze the parsed items of one raw RotoWire capture as JSON. Each item carries the other players' surnames that
        build() would have used for it (both teams of its next game, own surname removed), so scoring needs no database.
score:  run classify on the frozen sample and compare it with labels.csv. Prints precision and recall per class with
        Wilson 95% intervals, with borderline items excluded and included, and every disagreement.

The labels were written by hand from the text, following docs/research/news-evidence-precision-2026-11/RUBRIC.md,
before classify was run on the sample. One reviewer wrote them. A label without a sample item, or a sample item without
a label, stops the run.
"""
import argparse
import csv
import hashlib
import json
import math
import sqlite3
import sys
from pathlib import Path

import news_evidence as ne

RESEARCH = Path(__file__).resolve().parents[2] / 'docs' / 'research' / 'news-evidence-precision-2026-11'
SCHEMA = 'lp-news-evidence-precision-sample-1'
CODE_TO_CLASS = {'SN': 'starter_named', 'SE': 'starter_expected', 'CC': 'coach_confirmation_reported',
                 'ID': 'injury_designation', 'IO': 'injury_status_other'}
SEASON = 2026


def build_sample(capture_xml, db_path, out_path, season=SEASON):
    raw = Path(capture_xml).read_bytes()
    items = ne._parse_feed(raw)['items']
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    surnames = {}
    for row in con.execute("SELECT team, name FROM players WHERE league='nfl'"):
        tokens = ne.nfl_news.normalize_person_name(row['name']).split()
        if tokens:
            surnames.setdefault(row['team'], set()).add(tokens[-1])
    out, unresolved = [], 0
    for item in items:
        try:
            team = ne.nfl_news.normalize_team(item['team'])
        except ne.team_codes.UnknownTeamCode:
            unresolved += 1
            team = None
        teams, upcoming = set(), None
        if team:
            teams.add(team)
            published = ne._utc(item['published'], f"update {item['id']} DateTime")
            kickoffs = ne._game_kickoffs(con, team, season) or []
            upcoming = next((entry for entry in kickoffs if entry[0] > published), None)
            if upcoming:
                for code in upcoming[1].split('_')[2:4]:
                    teams.add(ne.nfl_news.normalize_team(code))
        out.append({'update_id': str(item['id']), 'first_name': item['first_name'], 'last_name': item['last_name'],
                    'team': item['team'], 'position': item['position'], 'injury_status': item['injury_status'],
                    'published': item['published'], 'headline': item['headline'], 'notes': item['notes'],
                    'analysis': item['analysis'], 'teams': sorted(teams),
                    'upcoming_game': upcoming[1] if upcoming else None})
    record = {'schema': SCHEMA, 'capture_sha256': hashlib.sha256(raw).hexdigest(), 'season': season,
              'db': str(db_path), 'teams_unresolved': unresolved,
              'surnames_by_team': {team_code: sorted(names) for team_code, names in surnames.items()
                                   if team_code is not None},
              'items': out}
    Path(out_path).write_text(json.dumps(record, indent=1, sort_keys=True) + '\n')
    print(f"sample: {len(out)} items; teams unresolved {unresolved}; "
          f"with an upcoming game {sum(1 for item in out if item['upcoming_game'])}; wrote {out_path}")
    return 0


def wilson(hits, n, z=1.96):
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def fmt(hits, n):
    if n == 0:
        return 'no denominator'
    lo, hi = wilson(hits, n)
    return f"{hits}/{n} = {100 * hits / n:.1f}% [95% CI {100 * lo:.1f}-{100 * hi:.1f}]"


def load_labels(path):
    labels = {}
    with open(path, newline='', encoding='utf-8') as fh:
        for row in csv.DictReader(fh):
            if row['update_id'] in labels:
                raise ValueError(f"duplicate label for update {row['update_id']}")
            codes = set() if row['gold_codes'] == 'none' else set(row['gold_codes'].split(';'))
            unknown = codes - set(CODE_TO_CLASS)
            if unknown:
                raise ValueError(f"unknown gold codes {sorted(unknown)} for update {row['update_id']}")
            labels[row['update_id']] = {'classes': {CODE_TO_CLASS[code] for code in codes},
                                        'borderline': row['borderline'] == 'yes', 'note': row['note']}
    return labels


def tally(rows, include_borderline):
    counts = {}
    for name in ne.CLASSES:
        tp = fp = fn = 0
        for item, label, emitted in rows.values():
            if label['borderline'] and not include_borderline:
                continue
            predicted = name in emitted
            gold = name in label['classes']
            tp += int(predicted and gold)
            fp += int(predicted and not gold)
            fn += int(gold and not predicted)
        counts[name] = (tp, fp, fn)
    return counts


def score(sample_path, labels_path, excluded):
    sample = json.loads(Path(sample_path).read_text())
    labels = load_labels(labels_path)
    sample_ids = [item['update_id'] for item in sample['items']]
    unlabelled = sorted(set(sample_ids) - set(labels))
    orphan = sorted(set(labels) - set(sample_ids))
    if unlabelled or orphan:
        raise SystemExit(f"label mismatch: {len(unlabelled)} sample items unlabelled {unlabelled[:5]}, "
                         f"{len(orphan)} labels with no sample item {orphan[:5]}")
    rows = {}
    for item in sample['items']:
        uid = item['update_id']
        if uid in excluded:
            continue
        own = ne._name_tokens(item['last_name'])
        other = frozenset(name for team_code in item['teams']
                          for name in sample['surnames_by_team'].get(team_code, [])) - own
        emitted = {hit['class']: hit['span'] for hit in ne.classify(item, other)}
        rows[uid] = (item, labels[uid], emitted)
    print(f"capture sha256 {sample['capture_sha256']}; sample items {len(sample_ids)}; "
          f"excluded {len(sample_ids) - len(rows)}; teams unresolved {sample['teams_unresolved']}")
    for include in (False, True):
        scored = sum(1 for _, label, _ in rows.values() if include or not label['borderline'])
        title = 'borderline included' if include else 'borderline excluded (main)'
        print(f"\n{title}: {scored} items scored")
        counts = tally(rows, include)
        for name in ne.CLASSES:
            tp, fp, fn = counts[name]
            print(f"  {name:28s} precision {fmt(tp, tp + fp):58s} recall {fmt(tp, tp + fn)}")
    print('\ndisagreements (borderline items marked):')
    for uid, (item, label, emitted) in rows.items():
        predicted, gold = set(emitted), label['classes']
        if predicted == gold:
            continue
        mark = ' [borderline]' if label['borderline'] else ''
        name = f"{item['first_name']} {item['last_name']} ({item['team']})"
        for cls in sorted(predicted - gold):
            print(f"  FP {cls:28s} update {uid} {name}{mark}: {emitted[cls]!r}; gold {sorted(gold)}; note: {label['note']}")
        for cls in sorted(gold - predicted):
            print(f"  FN {cls:28s} update {uid} {name}{mark}; gold {sorted(gold)}; note: {label['note']}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='command', required=True)
    make = sub.add_parser('sample', help='freeze the items of one capture with their other-player surnames')
    make.add_argument('--capture-xml', required=True)
    make.add_argument('--db', required=True)
    make.add_argument('--out', default=str(RESEARCH / 'sample.json'))
    check = sub.add_parser('score', help='classify the frozen sample and compare it with the labels')
    check.add_argument('--sample', default=str(RESEARCH / 'sample.json'))
    check.add_argument('--labels', default=str(RESEARCH / 'labels.csv'))
    check.add_argument('--exclude', action='append', default=[],
                       help='update id to leave out (repeatable), e.g. items whose output was seen earlier')
    a = ap.parse_args(argv)
    if a.command == 'sample':
        return build_sample(a.capture_xml, a.db, a.out)
    return score(a.sample, a.labels, set(a.exclude))


if __name__ == '__main__':
    sys.exit(main())
