"""Reconcile the stadium capacity history against reported attendance and the 2026 venue snapshot.

Each dated row is split where SPLITS says, and every piece gets one status in the CSV's `reconciliation` column:

  ok              no reported attendance above the figure, and the 2026 snapshot agrees within TOLERANCE if it covers 2026
  flagged         used in lookups, with the reason in `reconciliation_note`: attendance above the figure in one covered
                  season, or the 2026 snapshot differs by more than TOLERANCE
  contradicted    reported attendance above the figure in two or more covered seasons. Not used in lookups.
  excluded_text   the page's own text says the figure does not hold for these seasons. Not used in lookups.
  undated         no year range. Kept for reference. Not used in lookups.
  no_figure       the page states no NFL capacity (LA Coliseum). Not used in lookups.

"Above" means the season's highest reported attendance is more than TOLERANCE over the figure. Reported attendance
(ESPN scoreboard, post-game; zero and suspect rows excluded) can exceed permanent seating, so it is evidence, not proof.
Notes are generated from the measured values. Only MANUAL and SPLITS carry typed facts, and each cites the CSV note.

Usage: python3 capacity_reconcile.py --evidence   # print the evidence table, change nothing
       python3 capacity_reconcile.py              # print the evidence table and rewrite the CSV
"""
import argparse
import collections
import csv
import os
import sqlite3

import team_splits_build as tb

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, 'data', 'stadium_capacity_history.csv')
DEV_DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
SNAPSHOT = '/root/lp-snapshots/nfl-game-info/2026/week08/2026-10-27T1900Z/venues.json'
COVERED = (2015, 2025)
SNAPSHOT_SEASON = 2026
TOLERANCE = 0.02
FIELDS = ['building', 'recorded_names', 'valid_from', 'valid_to', 'seating_capacity', 'basis', 'source_url', 'note',
          'capacity_definition', 'standing_room', 'confidence', 'reconciliation', 'reconciliation_note']

# (building, valid_from, valid_to, seating_capacity) -> season where a new piece starts. Each piece is then judged alone.
SPLITS = {
    ('State Farm Stadium', 2006, 2026, 63400): 2015,         # attendance starts in 2015, so 2006 to 2014 is untested
    ('SoFi Stadium', 2020, 2026, 70240): 2021,               # no nonzero reported attendance in 2020
    ('Raymond James Stadium', 2022, 2026, 69218): 2023,      # the 2022 figure, see MANUAL
}

# (building, piece valid_from) -> (status, reason). Used only where the page text settles the question.
MANUAL = {
    ('Raymond James Stadium', 2023): ('excluded_text',
        'CSV note: 69,218 is the 2022 figure, which included temporary south end-zone seats. The infobox label '
        '2022-present is not used for later seasons, and the 2026 snapshot lists 65,890.'),
    ('EverBank Stadium', 2026): ('excluded_text',
        'Event capacity for the 2026 renovation season: 42,507 including 1,260 standing-room tickets (Jaguars '
        'announcement, Feb 2026). Not permanent seating, so not used in lookups. The stadium website reports 42,465 '
        '(source conflict, not checked here). An Aug 2026 report of temporary seating is not yet checked.'),
}

# Undated figures the reconciliation needs for the venue comparison. Never used in a historical bin.
ADDED = [
    dict(building='Lumen Field', recorded_names='Lumen Field;CenturyLink Field;Qwest Field', valid_from='',
         valid_to='', seating_capacity='68740', basis='undated', source_url='https://en.wikipedia.org/wiki/Lumen_Field',
         note='infobox NFL 68,740 (undated; up to 72,000 for special events)'),
    dict(building='U.S. Bank Stadium', recorded_names='U.S. Bank Stadium', valid_from='', valid_to='',
         seating_capacity='66202', basis='undated', source_url='https://en.wikipedia.org/wiki/U.S._Bank_Stadium',
         note='infobox current 66,202 (undated; expandable to 73,000)'),
]


def observed_max(dev, names):
    """(building, season) -> highest clean reported attendance, and the stadium names that matched no building."""
    out, unmapped = collections.defaultdict(int), set()
    for stadium, season, att in dev.execute("""select s.stadium, c.season, c.attendance from nfl_game_context c
            join nfl_schedule s on s.game_id = c.game_id
            where c.season between ? and ? and c.attendance > 0 and coalesce(c.attendance_suspect, 0) = 0""", COVERED):
        building = names.get(stadium)
        if building is None:
            unmapped.add(stadium)
            continue
        out[(building, season)] = max(out[(building, season)], att)
    return out, unmapped


def load(path=CSV_PATH):
    with open(path, newline='') as handle:
        return list(csv.DictReader(handle))


def pieces_of(row):
    """The row's year span, split where SPLITS says: [(valid_from, valid_to), ...]."""
    vf, vt, cap = int(row['valid_from']), int(row['valid_to']), int(row['seating_capacity'])
    cut = SPLITS.get((row['building'], vf, vt, cap))
    if cut is None:
        return [(vf, vt)]
    return [(vf, cut - 1), (cut, vt)]


def judge(building, cap, span, observed, snapshot):
    """(status, note) for one piece of a dated row."""
    a, b = span
    lo, hi = max(a, COVERED[0]), min(b, COVERED[1])
    seen = {s: observed[(building, s)] for s in range(lo, hi + 1) if (building, s) in observed}
    above = sorted(s for s, v in seen.items() if v > cap * (1 + TOLERANCE))
    snap = snapshot.get(building) if a <= SNAPSHOT_SEASON <= b else None
    gap = (snap - cap) / cap if snap is not None else None
    parts = []
    if seen:
        peak = max(seen.values())
        parts.append(f"{len(seen)} covered seasons with reported attendance, peak {peak:,} ({peak / cap - 1:+.1%} vs figure)")
    else:
        parts.append('no reported attendance in covered seasons 2015 to 2025 for this piece')
    if above:
        parts.append(f"above the figure by more than {TOLERANCE:.0%} in {', '.join(map(str, above))}")
    if snap is not None:
        parts.append(f"2026 snapshot {snap:,} ({gap:+.1%} vs figure)")
    if (building, a) in MANUAL:
        status, why = MANUAL[(building, a)]
        return status, why + ' Evidence: ' + '; '.join(parts) + '.'
    if len(above) >= 2:
        return 'contradicted', '; '.join(parts) + '.'
    if above or (gap is not None and abs(gap) > TOLERANCE):
        return 'flagged', '; '.join(parts) + '.'
    return 'ok', '; '.join(parts) + '.'


def decide(rows, observed, snapshot):
    out = []
    present = {r['building'] for r in rows if r['basis'] == 'undated'}
    rows = rows + [dict(a) for a in ADDED if a['building'] not in present]
    for r in rows:
        r = dict(r, capacity_definition=r.get('capacity_definition') or 'seating_capacity',
                 standing_room=r.get('standing_room') or '', confidence=r.get('confidence') or 'provisional')
        if not r['seating_capacity']:
            if r['basis'] == 'unresolved':
                out.append(dict(r, confidence='unresolved', reconciliation='unresolved',
                                reconciliation_note=r['note']))
            else:
                out.append(dict(r, confidence='', reconciliation='no_figure',
                                reconciliation_note='The page states no NFL capacity.'))
            continue
        if r['basis'] == 'undated' or not r['valid_from']:
            out.append(dict(r, reconciliation='undated',
                            reconciliation_note='No year range. Kept for reference; never used in a historical bin.'))
            continue
        cap = int(r['seating_capacity'])
        for a, b in pieces_of(r):
            status, note = judge(r['building'], cap, (a, b), observed, snapshot)
            out.append(dict(r, valid_from=str(a), valid_to=str(b), reconciliation=status, reconciliation_note=note))
    return out


def venue_table(decided, observed, snapshot):
    """One line per 2026 snapshot venue: the figure in effect for 2026, the snapshot, and the attendance evidence."""
    lines = []
    for building, snap in sorted(snapshot.items()):
        covering = [r for r in decided if r['building'] == building and r['valid_from']
                    and int(r['valid_from']) <= SNAPSHOT_SEASON <= int(r['valid_to'])]
        dated = [r for r in covering if r['reconciliation'] not in ('unresolved', 'undated', 'no_figure')]
        undated = [r for r in decided if r['building'] == building and r['reconciliation'] == 'undated']
        if dated:
            row = dated[0]
            figure, kind, status = int(row['seating_capacity']), 'dated', row['reconciliation']
            lo, hi = int(row['valid_from']), int(row['valid_to'])
        elif covering and covering[0]['reconciliation'] == 'unresolved':
            figure, kind, status = None, 'unresolved', 'unresolved'
            lo, hi = COVERED
        elif undated:
            figure, kind, status = int(undated[0]['seating_capacity']), 'undated', 'undated'
            lo, hi = COVERED
        else:
            figure, kind, status = None, 'none', 'none'
            lo, hi = COVERED
        seen = {s: v for (b, s), v in observed.items() if b == building and lo <= s <= hi}
        peak = max(seen.values()) if seen else None
        over = sorted(s for s, v in seen.items() if figure and v > figure * (1 + TOLERANCE))
        gap = f"{(snap - figure) / figure:+.1%}" if figure else 'n/a'
        lines.append((building, snap, figure, kind, status, gap, len(seen), peak, over))
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--evidence', action='store_true')
    args = ap.parse_args()
    _, names = tb.load_capacity_history()
    dev = sqlite3.connect(DEV_DB, uri=True)
    observed, unmapped = observed_max(dev, names)
    if unmapped:
        raise SystemExit(f'stadium names with attendance but no capacity-history building: {sorted(unmapped)}')
    snapshot = tb.load_snapshot(SNAPSHOT, names)
    decided = decide(load(), observed, snapshot)
    counts = collections.Counter(r['reconciliation'] for r in decided)
    print('status counts:', dict(sorted(counts.items())))
    print('\ndated pieces with a status other than ok:')
    for r in decided:
        if r['reconciliation'] not in ('ok', 'undated', 'no_figure'):
            print(f"  {r['reconciliation']:13s} {r['building'][:40]:40s} {r['valid_from']}-{r['valid_to']} "
                  f"{r['seating_capacity']:>6s}  {r['reconciliation_note'][:150]}")
    print('\n2026 venues: snapshot against the figure in effect')
    print(f"{'building':40s} {'snapshot':>8s} {'figure':>7s} {'kind':8s} {'status':13s} {'vs fig':>7s} {'seasons':>7s} "
          f"{'peak':>6s} over")
    for building, snap, figure, kind, status, gap, n, peak, over in venue_table(decided, observed, snapshot):
        print(f"{building[:40]:40s} {snap:>8,d} {figure or 0:>7,d} {kind:8s} {status:13s} {gap:>7s} {n:>7d} "
              f"{peak or 0:>6,d} {over}")
    if args.evidence:
        return
    with open(CSV_PATH, 'w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(decided)
    print('\nwrote', CSV_PATH)


if __name__ == '__main__':
    main()
