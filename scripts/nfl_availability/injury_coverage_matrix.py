#!/usr/bin/env python3
"""Coverage matrix: what can be evaluated at each horizon, historical versus verified prospective.

Read-only. Writes scratchpad/avail/inactives/injury_coverage_matrix.md.

Prospective (2026): a game's horizon input is VERIFIED only if a successful capture exists at or before the cutoff
and the most recent such capture is within MAX_GAP_HOURS of the cutoff. Otherwise the horizon is NOT VERIFIED.
Cutoffs in the future are PENDING. Games on unmapped weekdays are UNMAPPED.

Historical (2024, 2025): values come from injury_pit_audit_2024.md and the 2025 timestamp check (all null). No
historical input is verified: the database holds no archived snapshots.
"""
import os
import sqlite3
from datetime import datetime, timezone, timedelta

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, 'injury_snapshots.sqlite')
GAMES = os.path.join(HERE, 'snapshot_tmp', 'games.parquet')
REPORT = os.path.join(HERE, 'inactives', 'injury_coverage_matrix.md')
MAX_GAP_HOURS = 6
RULES = {
    'Sunday': {'early': (4, 12), 'practice': (2, 9), 'final': (1, 9)},
    'Thursday': {'early': (3, 12), 'practice': (1, 9), 'final': (0, 9)},
    'Monday': {'early': (4, 12), 'practice': (2, 9), 'final': (1, 9)},
}
HORIZONS = ['early', 'practice', 'final', 'pregame']


def cutoffs(gameday, weekday, kickoff):
    out = {'pregame': kickoff - pd.Timedelta(minutes=90)}
    rule = RULES.get(weekday)
    if rule:
        for name, (days, hour) in rule.items():
            out[name] = (pd.Timestamp(gameday) - pd.Timedelta(days=days)).replace(hour=hour) \
                .tz_localize('America/New_York').tz_convert('UTC')
    return out


def main():
    now = pd.Timestamp(datetime.now(timezone.utc))
    games = pd.read_parquet(GAMES, columns=['game_id', 'season', 'game_type', 'week', 'gameday', 'weekday', 'gametime'])
    games = games[games.season == 2026].copy()
    games['kickoff'] = [pd.Timestamp(f'{d} {t or "13:00"}').tz_localize('America/New_York').tz_convert('UTC')
                        for d, t in zip(games.gameday, games.gametime)]
    con = sqlite3.connect(STORE)
    runs = [(pd.Timestamp(o), s) for o, s in con.execute(
        "select observed_at_utc, status from snapshot_runs where status='ok' order by observed_at_utc")]
    runs = [(o, s) for o, s in runs]

    table = {h: {'verified': 0, 'not verified': 0, 'pending': 0, 'unmapped': 0} for h in HORIZONS}
    detail = []
    for g in games.itertuples(index=False):
        cuts = cutoffs(g.gameday, g.weekday, g.kickoff)
        for h in HORIZONS:
            if h not in cuts:
                table[h]['unmapped'] += 1
                continue
            cut = cuts[h]
            if cut > now:
                table[h]['pending'] += 1
                continue
            before = [o for o, _ in runs if o <= cut]
            ok = bool(before) and (cut - before[-1]) <= pd.Timedelta(hours=MAX_GAP_HOURS)
            table[h]['verified' if ok else 'not verified'] += 1
            if h == 'final' and len(detail) < 40:
                detail.append((g.week, g.game_type, g.weekday, str(cut), 'verified' if ok else 'not verified',
                               str(before[-1]) if before else 'none'))

    lines = []
    add = lines.append
    add('# Injury input coverage matrix')
    add('')
    add(f'Generated {now.isoformat()}. Cutoffs are the proposed rules in the brief, not verified publication times. '
        f'A horizon is verified only with a capture at or before its cutoff and within {MAX_GAP_HOURS} hours of it.')
    add('')
    add('## Historical inputs (not verified in any case)')
    add('| horizon | 2024 timestamp-proxy | 2024 retrospective | 2024 unverifiable | 2025 (nfl_hist_injuries) |')
    add('|---|---|---|---|---|')
    hist = {
        'early': ('0.0%', '100.0%', '0', 'unverifiable: 100% (date_modified null)'),
        'practice': ('5.1%', '94.9%', '0', 'unverifiable: 100%'),
        'final': ('98.7%', '1.3%', '0', 'unverifiable: 100%'),
        'pregame': ('100.0%', '0.0% (1 row, Van Noy)', '0', 'unverifiable: 100%'),
    }
    for h in HORIZONS:
        a, b, c, d = hist[h]
        add(f'| {h} | {a} | {b} | {c} | {d} |')
    add('')
    add('2024 figures: regular season, mapped weekdays (n = 5,736 latest rows), from injury_pit_audit_2024.md. '
        'Timestamp-proxy means the latest stored version was modified before the cutoff; publication timing is not '
        'established, so it is not leakage-free evidence.')
    add('')
    add('## Verified prospective inputs (2026 season, append-only capture store)')
    add('| horizon | verified | not verified | pending (cutoff in future) | unmapped weekday |')
    add('|---|---|---|---|---|')
    for h in HORIZONS:
        t = table[h]
        add(f"| {h} | {t['verified']} | {t['not verified']} | {t['pending']} | {t['unmapped']} |")
    add('')
    add(f'Capture runs in store: {len(runs)} successful, first at {runs[0][0] if runs else "none"}, '
        f'last at {runs[-1][0] if runs else "none"}.')
    add('')
    add('## Final-report horizon detail (first 40 games)')
    add('| week | game type | weekday | cutoff (UTC) | status | last capture before cutoff |')
    add('|---|---|---|---|---|---|')
    for row in detail:
        add('| ' + ' | '.join(str(x) for x in row) + ' |')
    add('')
    add('## Reading the matrix')
    add('- Verified prospective coverage is zero for every horizon until captures run on a schedule that brackets each '
        'cutoff. A single manual capture verifies nothing about earlier cutoffs.')
    add('- The historical columns cannot be verified. They can be used only as timestamp-proxy or retrospective inputs, '
        'and only with the caveats above.')
    add('- Models may not be fitted or promoted on these inputs until the verified column carries real coverage.')
    with open(REPORT, 'w') as handle:
        handle.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
