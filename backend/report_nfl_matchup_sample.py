#!/usr/bin/env python3
"""Sample report: every rostered player for one NFL matchup, as stored at a pregame cutoff.

The roster is the latest nfl_depth_chart snapshot at or before the cutoff, for each team. Each depth row is joined to
players by player_id, and the GSIS id is checked against players.nfl_gsis_id. A mismatch is reported, not repaired. Each
player's stored evidence comes from nfl_player_evidence.player_evidence, which reads the database only.

Usage: report_nfl_matchup_sample.py --db PATH --game GAME_ID --cutoff 2026-11-05T23:45:00Z --out FILE.md
"""
import argparse
import collections
import json
import sqlite3
import sys
from datetime import datetime, timezone

import nfl_player_evidence as evidence


def parse_utc(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(timezone.utc)


def cutoff_snapshot_text(cutoff):
    return cutoff.strftime('%Y-%m-%dT%H:%M:%SZ')


def game_teams(con, game_id):
    row = con.execute('SELECT away_team, home_team, gameday, gametime FROM nfl_schedule WHERE game_id=?',
                      (game_id,)).fetchone()
    if row is None:
        raise SystemExit(f'no schedule row for {game_id}')
    return row


def depth_rows(con, team, cutoff):
    stamp = cutoff_snapshot_text(cutoff)
    snapshot = con.execute('SELECT MAX(snapshot_at) FROM nfl_depth_chart WHERE team=? AND snapshot_at<=?',
                           (team, stamp)).fetchone()[0]
    if snapshot is None:
        return None, []
    rows = con.execute(
        """SELECT player_id, gsis_id, player_name, pos_abb, pos_rank, snapshot_at
           FROM nfl_depth_chart WHERE team=? AND snapshot_at=? ORDER BY pos_abb, pos_rank, player_name""",
        (team, snapshot)).fetchall()
    return snapshot, [dict(row) for row in rows]


def num(value):
    return 'n/a' if value is None else f'{value:.1f}'


def cell(value):
    text = '' if value is None else str(value)
    return text.replace('|', '/').replace('\n', ' ').strip()


def player_line(con, row, game_id, cutoff, linked_ids):
    player = con.execute('SELECT id, name, nfl_gsis_id, position FROM players WHERE id=?', (row['player_id'],)).fetchone()
    if player is None:
        return None, {'depth': row, 'player': None, 'gsis_match': False, 'linked': False}
    gsis_match = None if row['gsis_id'] is None else (player['nfl_gsis_id'] or '') == (row['gsis_id'] or '')
    ev = evidence.player_evidence(con, player['id'], cutoff)
    news = ev['news']
    latest_news = news[0] if news else None
    injury = next((a['injury_status'] for a in news if a['injury_status']), None)
    game_projections = [r for r in ev['projections']['rows'] if r['game_id'] == game_id]
    game_availability = [r for r in ev['availability'] if r['game_id'] == game_id]
    claims = [c['claim_class'] for a in news for c in a['claims'] if c['subject_player_id'] == player['id']]
    line = {
        'depth': row,
        'player': dict(player),
        'gsis_match': gsis_match,
        'linked': player['id'] in linked_ids,
        'news_count': len(news),
        'latest_news': latest_news,
        'claims': claims,
        'injury': injury,
        'projections': game_projections,
        'availability': game_availability,
    }
    return line, None


def render_team(team_label, team, lines, unresolved):
    out = [f'## {team_label} ({team})', '',
           '| depth | pos | player | LP id | GSIS match | RotoWire link | stored news | starter claims | '
           'latest injury status | latest article (published / captured) | projection for this game | availability for this game |',
           '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for line in lines:
        depth = line['depth']
        player = line['player']
        if player is None:
            out.append(f"| {depth['pos_rank']} | {depth['pos_abb']} | {cell(depth['player_name'])} | {depth['player_id']} "
                       f"| no players row | no | 0 | | | | | |")
            continue
        latest = line['latest_news']
        latest_text = (f"{cell(latest['headline'])} ({cell(latest['published'])} / {cell(latest['captured_at_utc'])})"
                       if latest else '')
        projection = '; '.join(f"{cell(p['stat'])} {num(p['mean'])} (p10 {num(p['p10'])}, p90 {num(p['p90'])})"
                               for p in line['projections'][:3]) if line['projections'] else 'none'
        availability = '; '.join(cell(a['report_status'] or a['played']) for a in line['availability']) \
            if line['availability'] else 'none'
        out.append(
            f"| {cell(depth['pos_rank'])} | {cell(depth['pos_abb'])} | {cell(player['name'])} | {player['id']} "
            f"| {'n/a' if line['gsis_match'] is None else ('yes' if line['gsis_match'] else 'NO')} | {'yes' if line['linked'] else 'no'} | {line['news_count']} "
            f"| {cell(', '.join(sorted(set(line['claims']))) or '')} | {cell(line['injury'] or '')} | {latest_text} "
            f"| {projection} | {availability} |")
    out.append('')
    if unresolved:
        out.append(f'Depth rows with no players row: {len(unresolved)}.')
        out.append('')
    return out


def sample_rows(con, game_id, cutoff, lines):
    out = ['## Sample raw rows', '',
           'One row from each source, as stored. Each is shown exactly as the database holds it.', '']
    news_row = con.execute(
        """SELECT update_id, rotowire_player_id, player_id, match, team, first_name, last_name, position,
                  injury_status, headline, notes, analysis, link, published_raw, published_utc, first_seen_utc
           FROM nfl_player_news_updates WHERE player_id IS NOT NULL ORDER BY published_utc DESC LIMIT 1""").fetchone()
    if news_row:
        out += ['**nfl_player_news_updates** (publisher time and capture time kept separately)', '', '```']
        out += [f'{key} = {news_row[key]!r}' for key in news_row.keys()]
        out += ['```', '']
    claim_row = con.execute(
        """SELECT update_id, subject_player_id, update_player_id, attribution, claim_class, field, span, extractor
           FROM nfl_player_news_claims ORDER BY update_id LIMIT 1""").fetchone()
    if claim_row:
        out += ['**nfl_player_news_claims**', '', '```']
        out += [f'{key} = {claim_row[key]!r}' for key in claim_row.keys()]
        out += ['```', '']
    proj_row = con.execute(
        """SELECT player_id, team, game_id, stat, mean, median, p10, p90, scenario, model_version, source, as_of
           FROM player_projections WHERE game_id=? ORDER BY as_of DESC, stat LIMIT 1""", (game_id,)).fetchone()
    if proj_row:
        out += ['**player_projections** (read only; this report never writes it)', '', '```']
        out += [f'{key} = {proj_row[key]!r}' for key in proj_row.keys()]
        out += ['```', '']
    depth_row = con.execute(
        """SELECT player_id, gsis_id, team, player_name, pos_abb, pos_rank, snapshot_at, source
           FROM nfl_depth_chart ORDER BY snapshot_at DESC LIMIT 1""").fetchone()
    if depth_row:
        out += ['**nfl_depth_chart**', '', '```']
        out += [f'{key} = {depth_row[key]!r}' for key in depth_row.keys()]
        out += ['```', '']
    return out


def roster_snapshot(con):
    """The latest published NFL roster snapshot (ESPN). Returns (captured_at, players) or (None, [])."""
    row = con.execute(
        """SELECT captured_at, source_payload FROM roster_snapshots
           WHERE league='nfl' AND status='published' ORDER BY captured_at DESC LIMIT 1""").fetchone()
    if row is None:
        return None, []
    return row[0], json.loads(row[1])


def roster_rows(con, team, captured_at, payload):
    espn_to_lp = collections.defaultdict(set)
    for pid, espn in con.execute("SELECT id, espn_id FROM players WHERE league='nfl' AND COALESCE(espn_id,'') != ''"):
        espn_to_lp[str(espn)].add(int(pid))
    out, unmapped, ambiguous = [], 0, 0
    for entry in payload:
        if entry.get('team') != team:
            continue
        key = str(entry.get('source_player_key') or '')
        matches = espn_to_lp.get(key, set())
        if len(matches) == 1:
            pid = next(iter(matches))
        else:
            pid = None
            if matches:
                ambiguous += 1
            else:
                unmapped += 1
        out.append({'player_id': pid, 'gsis_id': None, 'player_name': entry.get('name'), 'pos_abb': entry.get('position'),
                    'pos_rank': None, 'snapshot_at': captured_at, 'espn_id': key})
    return out, unmapped, ambiguous


def build(con, game_id, cutoff):
    away, home, gameday, gametime = game_teams(con, game_id)
    linked_ids = {int(r[0]) for r in con.execute(
        "SELECT player_id FROM player_source_ids WHERE source='rotowire' AND league='nfl' AND player_id IS NOT NULL")}
    roster_at, roster_payload = roster_snapshot(con)
    header = [f'# Matchup sample: {away} at {home} ({game_id})', '',
              f'Cutoff: {cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")}. Kickoff: {gameday} {gametime} (nflverse Eastern time), so the '
              f'pregame cutoff is kickoff minus 90 minutes. Evidence is what was stored when this report was generated; every '
              f'capture in the store is before the cutoff, so no later news is included.', '',
              'Two rosters are shown, because no single complete roster is current. Section A is the latest nfl_depth_chart '
              'snapshot at or before the cutoff: it is current, but it lists only the depth players. Section B is every other '
              f'player on the latest published ESPN roster snapshot ({roster_at}), which is complete but about three months old, '
              'so a player shown there may have moved or been released since.', '']
    totals = collections.Counter()
    lines_a, lines_b = {}, {}
    body = ['## Section A: current depth chart', '']
    seen_ids = set()
    for team, label in ((away, 'Away'), (home, 'Home')):
        snapshot, rows = depth_rows(con, team, cutoff)
        if snapshot is None:
            raise SystemExit(f'no depth chart snapshot for {team} at or before {cutoff}')
        lines, unresolved = [], []
        for row in rows:
            line, missing = player_line(con, row, game_id, cutoff, linked_ids)
            if missing:
                unresolved.append(row)
                lines.append(missing)
                continue
            lines.append(line)
            seen_ids.add(line['player']['id'])
            totals['A_players'] += 1
            totals['A_gsis_mismatch'] += 0 if line['gsis_match'] else 1
            totals['A_linked'] += 1 if line['linked'] else 0
            totals['A_news'] += 1 if line['news_count'] else 0
            totals['A_projection'] += 1 if line['projections'] else 0
            totals['A_availability'] += 1 if line['availability'] else 0
        lines_a[team] = lines
        body += [f'Depth snapshot for {team}: {snapshot}', '']
        body += render_team(label, team, lines, unresolved)
    body += ['## Section B: rest of the ESPN roster (not in the current depth chart)', '',
             f'Roster snapshot captured {roster_at}. Players are joined to players by their ESPN id. A player with no '
             'matching ESPN id is counted and not shown.', '']
    for team, label in ((away, 'Away'), (home, 'Home')):
        rows, unmapped, ambiguous = roster_rows(con, team, roster_at, roster_payload)
        lines = []
        for row in rows:
            if row['player_id'] is None or row['player_id'] in seen_ids:
                continue
            line, missing = player_line(con, row, game_id, cutoff, linked_ids)
            if missing:
                continue
            lines.append(line)
            seen_ids.add(line['player']['id'])
            totals['B_players'] += 1
            totals['B_linked'] += 1 if line['linked'] else 0
            totals['B_news'] += 1 if line['news_count'] else 0
            totals['B_projection'] += 1 if line['projections'] else 0
        totals[f'B_unmapped_{team}'] = unmapped
        totals[f'B_ambiguous_{team}'] = ambiguous
        lines_b[team] = lines
        body += render_team(label + ' (roster)', team, lines, [])
        body += [f'ESPN roster rows for {team} with no LP player: {unmapped}; with more than one LP player: {ambiguous}.', '']
    extra_ids = [int(r[0]) for r in con.execute(
        "SELECT DISTINCT player_id FROM player_projections WHERE game_id=? AND player_id IS NOT NULL ORDER BY player_id",
        (game_id,)) if int(r[0]) not in seen_ids]
    lines_c = []
    for pid in extra_ids:
        player = con.execute('SELECT id, name, position FROM players WHERE id=?', (pid,)).fetchone()
        row = {'player_id': pid, 'gsis_id': None, 'player_name': player['name'] if player else None,
               'pos_abb': player['position'] if player else None, 'pos_rank': None, 'snapshot_at': None}
        line, missing = player_line(con, row, game_id, cutoff, linked_ids)
        if missing:
            continue
        lines_c.append(line)
        seen_ids.add(pid)
    totals['C_players'] = len(lines_c)
    body += ['## Section C: other players with a projection for this game', '',
             'Projected for this game but on neither roster above (for example, a later signing). Team is the players row.', '']
    body += render_team('Section C', f'{away}/{home}', lines_c, [])
    coverage = ['## Coverage', '',
                '| | Section A (depth chart, current) | Section B (rest of ESPN roster, Aug snapshot) |',
                '|---|---|---|',
                f"| players | {totals['A_players']} | {totals['B_players']} |",
                f"| GSIS id mismatches with players | {totals['A_gsis_mismatch']} | not checked (roster has no GSIS id) |",
                f"| linked to a RotoWire id | {totals['A_linked']} | {totals['B_linked']} |",
                f"| with stored news | {totals['A_news']} | {totals['B_news']} |",
                f"| with a projection for this game | {totals['A_projection']} | {totals['B_projection']} |",
                f"| with an availability row for this game | {totals['A_availability']} | 0 (no availability rows exist for this game) |",
                f"| Section C (projected for this game, on neither roster) | {totals['C_players']} | |",
                '']
    return header + coverage + body + sample_rows(con, game_id, cutoff, [l for v in lines_a.values() for l in v]
                                                  + [l for v in lines_b.values() for l in v] + lines_c)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', required=True)
    ap.add_argument('--game', required=True)
    ap.add_argument('--cutoff', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    cutoff = parse_utc(a.cutoff)
    con = sqlite3.connect(f'file:{a.db}?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        text = '\n'.join(build(con, a.game, cutoff)) + '\n'
    finally:
        con.close()
    with open(a.out, 'w') as handle:
        handle.write(text)
    print(f'wrote {a.out} ({len(text.splitlines())} lines)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
