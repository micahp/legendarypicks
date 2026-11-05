#!/usr/bin/env python3
"""Matchup evidence report: every player the stored data can place in one matchup, as of a pregame cutoff.

Sections:
- A: players on the latest nfl_depth_chart snapshot at or before the cutoff, for either team. Current, but depth players only.
- B: players on the latest published ESPN roster for either team, not in A. That roster is about three months old.
- C: players with a projection for this game, or with stored news naming a matchup team, who are in neither A nor B.

Each player keeps its evidence in separate fields: roster (per source), injury (latest designation and any later clearing
update), official availability (player_game_availability), projections (each row checked, failures listed), and starter
(latest claim). Unknown stays unknown. Contradictions are listed first, not resolved.

The report says PREVIEW until the cutoff has passed, and it records an evidence digest so a frozen copy can be checked.

Usage: report_nfl_matchup_sample.py --db PATH --game GAME_ID --cutoff 2026-11-05T23:45:00Z --out FILE.md
"""
import argparse
import collections
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone

import nfl_matchup_reconciliation as recon
import nfl_news
import nfl_player_evidence as evidence


def parse_utc(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(timezone.utc)


def depth_text(cutoff):
    return cutoff.strftime('%Y-%m-%dT%H:%M:%SZ')


def num(value):
    return 'n/a' if value is None else f'{value:.2f}'


def cell(value):
    text = '' if value is None else str(value)
    return text.replace('|', '/').replace('\n', ' ').strip()


def game_row(con, game_id):
    row = con.execute('SELECT away_team, home_team, gameday, gametime FROM nfl_schedule WHERE game_id=?',
                      (game_id,)).fetchone()
    if row is None:
        raise SystemExit(f'no schedule row for {game_id}')
    return row


def depth_snapshot(con, team, cutoff):
    snapshot = con.execute('SELECT MAX(snapshot_at) FROM nfl_depth_chart WHERE team=? AND snapshot_at<=?',
                           (team, depth_text(cutoff))).fetchone()[0]
    if snapshot is None:
        raise SystemExit(f'no depth chart snapshot for {team} at or before {cutoff}')
    rows = con.execute(
        """SELECT player_id FROM nfl_depth_chart WHERE team=? AND snapshot_at=?
           ORDER BY pos_abb, pos_rank, player_name""", (team, snapshot)).fetchall()
    return snapshot, [int(r[0]) for r in rows if r[0] is not None]


def aug_roster(con, teams):
    """(captured_at, {LP player id: team}, ambiguous count) for the latest published ESPN roster. Joined by ESPN id only."""
    row = con.execute("SELECT captured_at, source_payload FROM roster_snapshots WHERE league='nfl' "
                      "AND status='published' ORDER BY captured_at DESC LIMIT 1").fetchone()
    if row is None:
        return None, {}, 0
    espn_to_lp = collections.defaultdict(set)
    for pid, espn in con.execute("SELECT id, espn_id FROM players WHERE league='nfl' AND COALESCE(espn_id,'') != ''"):
        espn_to_lp[str(espn)].add(int(pid))
    team_of, ambiguous = {}, 0
    for entry in json.loads(row[1]):
        if entry.get('team') not in teams:
            continue
        matches = espn_to_lp.get(str(entry.get('source_player_key') or ''), set())
        if len(matches) == 1:
            team_of[next(iter(matches))] = entry['team']
        elif len(matches) > 1:
            ambiguous += 1
    return row[0], team_of, ambiguous


def projected_ids(con, game_id):
    return {int(r[0]) for r in con.execute(
        'SELECT DISTINCT player_id FROM player_projections WHERE game_id=? AND player_id IS NOT NULL', (game_id,))}


def news_named_ids(con, teams, cutoff_iso):
    """Players whose latest stored update (known at the cutoff) names a matchup team: {player id: team}."""
    out = {}
    latest = {}
    for row in evidence._known_versions(con, cutoff_iso):
        if row['player_id'] is None:
            continue
        if row['player_id'] not in latest or row['published_utc'] > latest[row['player_id']]['published_utc']:
            latest[row['player_id']] = row
    for pid, row in latest.items():
        try:
            code = nfl_news.normalize_team(row['team'])
        except Exception:
            continue
        if code in teams:
            out[pid] = code
    return out


def build_record(con, pid, game_id, cutoff, teams, depth_team, roster_team, section):
    player = con.execute('SELECT id, name, team, position FROM players WHERE id=?', (pid,)).fetchone()
    ev = evidence.player_evidence(con, pid, cutoff, limit=500, game_id=game_id)
    own = [a for a in ev['news'] if a['player_id'] == pid]
    latest_own = max(own, key=lambda a: a['published_utc']) if own else None
    news_team = latest_own['team'] if latest_own else None
    injury = recon.injury_state([{
        'update_id': a['id'], 'published_utc': a['published_utc'], 'injury_status': a['injury_status'],
        'headline': a['headline'], 'notes': a['notes'], 'analysis': a['analysis']} for a in own])
    roster = recon.roster_state(teams, depth_team, roster_team, _team_code(news_team), player['team'])
    claims = [dict(c, published_utc=a['published_utc'], update_id=a['id'])
              for a in ev['news'] for c in a['claims'] if c['subject_player_id'] == pid]
    starter = recon.starter_state(claims)
    projections = [r for r in ev['projections']['rows'] if r['game_id'] == game_id]
    problems = []
    for r in projections:
        reason = recon.projection_problem(r)
        if reason:
            problems.append(f"{r['stat']} ({r['source']}/{r['model_version']}): {reason}")
    availability = [r for r in ev['availability'] if r['game_id'] == game_id]
    linked = bool(con.execute("SELECT 1 FROM player_source_ids WHERE source='rotowire' AND league='nfl' "
                              "AND player_id=? LIMIT 1", (pid,)).fetchone())
    record = {
        'player_id': pid, 'name': player['name'], 'team': player['team'], 'position': player['position'],
        'section': section, 'depth_team': depth_team, 'roster_team': roster_team,
        'injury': injury, 'roster': roster, 'starter': starter, 'availability': availability,
        'projections': projections, 'projection_problems': problems,
        'projected_but_not_rostered': section == 'C' and bool(projections),
        'news_count': len(own), 'latest_own': latest_own, 'claims': claims, 'linked': linked,
    }
    record['contradictions'] = recon.contradictions(record)
    return record


def _team_code(news_team):
    if not news_team:
        return None
    try:
        return nfl_news.normalize_team(news_team)
    except Exception:
        return None


def injury_text(injury):
    if injury['state'] == 'no_designation_recorded':
        return 'none recorded'
    text = f"{injury['designation']} ({injury['designation_published_utc']})"
    if injury['state'] == 'contradicted':
        text += ' CONTRADICTED by a later update: ' + '; '.join(c['text'] for c in injury['clears'])
    return text


def roster_text(roster):
    text = roster['state']
    if roster['conflicts']:
        text += ' CONFLICT: ' + '; '.join(roster['conflicts'])
    return text


def starter_text(starter):
    if starter['state'] == 'none_recorded':
        return 'none recorded'
    latest = starter['latest']
    return f"{starter['state']} ({latest['claim_class']}, article {latest['update_id']}, {latest['published_utc']})"


def projection_text(record):
    if not record['projections']:
        return 'none stored for this game'
    failing = len(record['projection_problems'])
    return f"{len(record['projections'])} rows; {len(record['projections']) - failing} pass; {failing} fail"


def contradiction_section(records):
    rows = [r for r in records if r['contradictions']]
    out = ['## Contradictions', '',
           'Listed, not resolved. Each line names the sources that disagree. Nothing here changes an evidence field.', '']
    if not rows:
        return out + ['No contradictions were found in the stored evidence.', '']
    for r in rows:
        out.append(f"- **{cell(r['name'])}** (LP {r['player_id']}, {cell(r['team'])}):")
        for line in r['contradictions']:
            out.append(f'  - {cell(line)}')
    return out + ['']


def player_table(title, records):
    out = [f'## {title}', '',
           '| section | pos | player | LP id | roster | injury | official availability | projections | starter | stored news | latest article (published / captured) |',
           '|---|---|---|---|---|---|---|---|---|---|---|']
    for r in records:
        latest = r['latest_own']
        latest_text = (f"{cell(latest['headline'])} ({cell(latest['published'])} / {cell(latest['captured_at_utc'])})"
                       if latest else '')
        availability = ('unknown (no row for this game)' if not r['availability'] else
                        cell('; '.join(str(a['report_status'] or a['played']) for a in r['availability'])))
        out.append(f"| {r['section']} | {cell(r['position'])} | {cell(r['name'])} | {r['player_id']} "
                   f"| {cell(roster_text(r['roster']))} | {cell(injury_text(r['injury']))} | {availability} "
                   f"| {cell(projection_text(r))} | {cell(starter_text(r['starter']))} | {r['news_count']} "
                   f"| {latest_text} |")
    return out + ['']


def projection_section(records):
    out = ['## Projections for this game (all stored rows, every source and model version)', '',
           'Each row is checked against range rules. A failed check is listed; the row is not corrected.', '',
           '| player | LP id | source | model | stat | mean | median | p10 | p90 | as of | check |',
           '|---|---|---|---|---|---|---|---|---|---|---|']
    any_rows = False
    for r in records:
        for p in r['projections']:
            any_rows = True
            problem = recon.projection_problem(p)
            out.append(f"| {cell(r['name'])} | {r['player_id']} | {cell(p['source'])} | {cell(p['model_version'])} "
                       f"| {cell(p['stat'])} | {num(p['mean'])} | {num(p['median'])} | {num(p['p10'])} | {num(p['p90'])} "
                       f"| {cell(p['as_of'])} | {cell(problem) or 'ok'} |")
    if not any_rows:
        out.append('| none | | | | | | | | | | |')
    return out + ['']


def coverage(records, aug_ambiguous):
    counts = collections.Counter()
    for r in records:
        counts[f"section {r['section']}"] += 1
        counts[f"roster {r['roster']['state']}"] += 1
        counts[f"injury {r['injury']['state']}"] += 1
        counts[f"starter {r['starter']['state']}"] += 1
        counts['official availability known'] += 1 if r['availability'] else 0
        counts['projection rows failing checks'] += len(r['projection_problems'])
        counts['players with a contradiction'] += 1 if r['contradictions'] else 0
        counts['linked to a RotoWire id'] += 1 if r['linked'] else 0
    lines = ['## Coverage and unknowns', '', '| item | count |', '|---|---|',
             f'| players in this report | {len(records)} |']
    lines += [f'| {key} | {counts[key]} |' for key in sorted(counts)]
    lines += [f'| ESPN roster rows matching more than one LP player (not used) | {aug_ambiguous} |', '']
    return lines


def samples_section(con, records):
    ids = [r['player_id'] for r in records if r['section'] in ('A', 'B', 'C')]
    out = ['## Sample raw rows (matchup players only)', '',
           'One row per source, restricted to players in this matchup, shown as stored.', '']
    if not ids:
        return out + ['No matchup player rows.', '']
    marks = ','.join('?' * len(ids))
    news = con.execute(
        f"""SELECT update_id, rotowire_player_id, player_id, match, team, first_name, last_name, position,
                  injury_status, headline, notes, analysis, link, published_raw, published_utc, first_seen_utc
           FROM nfl_player_news_updates WHERE player_id IN ({marks}) ORDER BY published_utc DESC LIMIT 1""",
        ids).fetchone()
    if news:
        out += ['**nfl_player_news_updates**', '', '```'] + [f'{k} = {news[k]!r}' for k in news.keys()] + ['```', '']
    claim = con.execute(
        f"""SELECT update_id, subject_player_id, update_player_id, attribution, claim_class, field, span, extractor
           FROM nfl_player_news_claims WHERE subject_player_id IN ({marks}) ORDER BY update_id LIMIT 1""", ids).fetchone()
    if claim:
        out += ['**nfl_player_news_claims**', '', '```'] + [f'{k} = {claim[k]!r}' for k in claim.keys()] + ['```', '']
    return out


def build(con, game_id, cutoff):
    game = game_row(con, game_id)
    teams = {game['away_team'], game['home_team']}
    snapshots, depth_team_of = {}, {}
    for team in sorted(teams):
        snapshots[team], depth_ids = depth_snapshot(con, team, cutoff)
        for pid in depth_ids:
            depth_team_of[pid] = team
    aug_at, aug_team, aug_ambiguous = aug_roster(con, teams)
    news_team_of = news_named_ids(con, teams, cutoff.isoformat())
    proj_ids = projected_ids(con, game_id)

    records, seen = [], set()
    for pid in sorted(depth_team_of):
        records.append(build_record(con, pid, game_id, cutoff, teams, depth_team_of[pid], aug_team.get(pid), 'A'))
        seen.add(pid)
    for pid in sorted(aug_team):
        if pid not in seen:
            records.append(build_record(con, pid, game_id, cutoff, teams, None, aug_team[pid], 'B'))
            seen.add(pid)
    for pid in sorted((proj_ids | set(news_team_of)) - seen):
        records.append(build_record(con, pid, game_id, cutoff, teams, None, None, 'C'))
        seen.add(pid)

    preview = datetime.now(timezone.utc) < cutoff
    status = ('PREVIEW: the cutoff has not passed, so these inputs can still change. Regenerate at the cutoff to freeze.'
              if preview else 'CUTOFF SNAPSHOT: generated after the cutoff.')
    digest_input = [{k: v for k, v in r.items() if k != 'latest_own'} for r in records]
    digest = hashlib.sha256(json.dumps(digest_input, sort_keys=True, default=str).encode()).hexdigest()
    header = [f'# Matchup evidence: {game["away_team"]} at {game["home_team"]} ({game_id})', '',
              f'Status: {status}', '',
              f'Cutoff: {cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")}. Kickoff {game["gameday"]} {game["gametime"]} '
              f'(nflverse Eastern), so the cutoff is kickoff minus 90 minutes. Generated '
              f'{datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}. Evidence digest (sha256 of the per-player '
              f'records): {digest}.', '',
              f'Depth snapshots: {", ".join(f"{t} {s}" for t, s in sorted(snapshots.items()))}. '
              f'ESPN roster snapshot: {aug_at}. Projections, availability and news are read as of the cutoff.', '']
    body = contradiction_section(records) + coverage(records, aug_ambiguous)
    body += player_table('Section A: current depth chart', [r for r in records if r['section'] == 'A'])
    body += player_table('Section B: rest of the ESPN roster (about three months old)',
                         [r for r in records if r['section'] == 'B'])
    body += player_table('Section C: projected or named in news, on neither roster',
                         [r for r in records if r['section'] == 'C'])
    body += projection_section(records)
    body += samples_section(con, records)
    return header + body


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
