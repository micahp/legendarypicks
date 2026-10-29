"""Cross-check the team playbook files against the decision labels built from the database (2025 regular season).

The playbook files (Gridiron Physics, research build) describe each team's observed plays. The decision layer's labels come from the
database and nflverse. Where both describe the same plays, the per-team counts of pass depth (D), pass location (E) and run gap (C)
must agree exactly. The check reports every team and category, and the counts that differ.

Usage: python3 playbook_crosscheck.py [--season 2025] [--out JSON]
"""
import argparse
import glob
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import decision_layer as dl  # noqa: E402
import e1_drive as e1  # noqa: E402

PLAYBOOKS = '/root/gridiron-playbooks-research/data/playbooks/research-2026-10-27'
CATS = {'D': 'pass_length', 'E': 'pass_location', 'C': 'run_gap'}
# the playbook files name two franchises differently from the database and nflverse: a join key, mapped before comparing
TEAM_CODE = {'LA': 'LAR', 'WAS': 'WSH'}


def playbook_counts(season):
    out = {}
    for path in glob.glob(f'{PLAYBOOKS}/*-{season}.json'):
        data = json.load(open(path))
        team = TEAM_CODE.get(data['team_id'], data['team_id'])
        counts = {c: Counter() for c in CATS}
        for play in data['offense']['observed_plays']:
            a = play['attributes']
            if a.get('play_type') == 'pass' and a.get('pass_length'):
                counts['D'][a['pass_length']] += 1
            if a.get('play_type') == 'pass' and a.get('pass_location'):
                counts['E'][a['pass_location']] += 1
            if a.get('play_type') == 'run' and a.get('run_gap'):
                counts['C'][a['run_gap']] += 1
        out[team] = counts
    return out


def run_gap_counts(season, con):
    """Run gap on every run, the playbook's own definition (the decision label C is restricted to backs and fullbacks)."""
    out = defaultdict(Counter)
    for team, gap, n in con.execute(
            "SELECT posteam, run_gap, COUNT(*) FROM nfl_pbp WHERE season = ? AND week <= 18 AND play_type = 'run' "
            "AND posteam IS NOT NULL AND run_gap IS NOT NULL GROUP BY posteam, run_gap", (season,)):
        out[team][gap] += n
    return out


def label_counts(season, rows):
    out = defaultdict(lambda: {c: Counter() for c in CATS})
    for row in rows:
        if row['season'] != season:
            continue
        for c in CATS:
            value = row['labels'].get(c)
            if value is not None:
                out[row['team']][c][value] += 1
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--season', type=int, default=2025)
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    import sqlite3
    rows = dl.load_rows(e1.DEFAULT_DB, [args.season])
    book = playbook_counts(args.season)
    labels = label_counts(args.season, rows)
    con = sqlite3.connect(f'file:{e1.DEFAULT_DB}?mode=ro', uri=True)
    gaps = run_gap_counts(args.season, con)
    con.close()
    report = {'season': args.season, 'teams': len(book), 'mismatches': [], 'agree': 0}
    for team in sorted(book):
        for c in CATS:
            a = dict(book[team][c])
            b = dict(gaps[team]) if c == 'C' else dict(labels[team][c])  # C: every run, the playbook's definition
            if a == b:
                report['agree'] += 1
            else:
                report['mismatches'].append({'team': team, 'category': c, 'playbook': a, 'labels': b})
    print(f"season {args.season}: {report['teams']} teams, {report['agree']} team-category pairs agree, "
          f"{len(report['mismatches'])} differ")
    for m in report['mismatches'][:12]:
        print(json.dumps(m, sort_keys=True))
    if args.out:
        args.out.write_text(json.dumps(report, indent=1, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
