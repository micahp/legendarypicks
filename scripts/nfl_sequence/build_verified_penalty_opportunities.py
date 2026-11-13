#!/usr/bin/env python3
"""Build a conservative opportunity cohort aligned to official NFL gamebooks.

Only source descriptions that exactly match a unique official scrimmage block
are admitted. Unmatched, ambiguous, multiple and unsupported cases are counted,
not converted to negatives. Gamebook Last-Modified is retained as a conservative
source vintage, not a claim about original publication time.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import random
import re
import subprocess
import urllib.request
import pyarrow.parquet as pq
import pytz

MAPPING = {
    'False Start': ('pre_snap', 'offense', 'false_start'),
    'Delay of Game': ('pre_snap', 'offense', 'delay_of_game'),
    'Encroachment': ('pre_snap', 'defense', 'encroachment'),
    'Neutral Zone Infraction': ('pre_snap', 'defense', 'neutral_zone_infraction'),
    'Offensive Holding': ('live_ball', 'offense', 'offensive_holding'),
    'Offensive Pass Interference': ('live_ball', 'offense', 'offensive_pass_interference'),
    'Illegal Block Above the Waist': ('live_ball', 'offense', 'illegal_block'),
    'Intentional Grounding': ('live_ball', 'offense', 'intentional_grounding'),
    'Illegal Formation': ('live_ball', 'offense', 'illegal_formation'),
    'Illegal Shift': ('live_ball', 'offense', 'illegal_shift'),
    'Illegal Motion': ('live_ball', 'offense', 'illegal_motion'),
    'Defensive Holding': ('live_ball', 'defense', 'defensive_holding'),
    'Defensive Pass Interference': ('live_ball', 'defense', 'defensive_pass_interference'),
    'Illegal Contact': ('live_ball', 'defense', 'illegal_contact'),
    'Roughing the Passer': ('live_ball', 'defense', 'roughing_passer'),
    'Defensive Offside': ('live_ball', 'defense', 'offside'),
}
PLAY = re.compile(r'^\s*([1-4])-(\d+|[Gg]oal)-([A-Z]{2,3})\s+(\d+)\s+\(\d{1,2}:\d{2}\)')
QUARTER = re.compile(r'Play By Play\s+(First|Second|Third|Fourth|Overtime) Quarter', re.I)
FOUL = re.compile(r'\bpenalt(?:y|ies)\s+on\b', re.I)

def norm(text):
    text = re.sub(r'\b\d+-', '', text.lower())
    # Official gamebooks insert drive-first-down markers (P1/R2/X3) between
    # a play description and its foul continuation; nflverse omits them.
    text = re.sub(r'\b[prx]\d+\b', '', text)
    return re.sub(r'[^a-z0-9]+', '', text)

def file_sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def gamebook_blocks(text):
    blocks, current, quarter = [], None, None
    for line in text.splitlines():
        q = QUARTER.search(line)
        if q:
            quarter = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4, 'overtime': 5}[q.group(1).lower()]
        head = PLAY.match(line)
        if head:
            if current:
                blocks.append(current)
            current = {'qtr': quarter, 'text': line, 'clock': re.search(r'\((\d{1,2}:\d{2})\)', line).group(1),
                       'down': int(head.group(1)), 'to_go': head.group(2),
                       'field_team': head.group(3), 'field_number': int(head.group(4))}
        elif current:
            # PBP continuation lines are indented; unindented possessions,
            # scores, kicks and page headers end the scrimmage block.
            if not line.strip() or line.startswith('\f'):
                continue
            if len(line) - len(line.lstrip()) < 15 or 'Play By Play' in line or 'Timeout at' in line:
                blocks.append(current)
                current = None
            else:
                current['text'] += ' ' + line.strip()
    if current:
        blocks.append(current)
    return blocks

def fetch(game, directory):
    url = f"https://www.nflgsis.com/{game['season']}/REG/{game['week']:02d}/{game['gsis']}/Gamebook.pdf"
    path = directory / (game['game_id'] + '.pdf')
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 penalty research'})
    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read()
        modified = response.headers.get('Last-Modified')
    if not data.startswith(b'%PDF-') or not modified:
        raise ValueError(f'missing PDF or Last-Modified: {url}')
    path.write_bytes(data)
    text = subprocess.check_output(['pdftotext', '-layout', str(path), '-'], text=True)
    return game['game_id'], {'url': url, 'sha256': hashlib.sha256(data).hexdigest(),
          'source_published_utc': parsedate_to_datetime(modified).astimezone(timezone.utc).isoformat(),
          'last_modified_header': modified, 'blocks': gamebook_blocks(text)}

def selected_games(schedule, per_band):
    rng = random.Random(170612)
    groups = defaultdict(list)
    for g in schedule:
        if (2021 <= g['season'] <= 2025 and g['game_type'] == 'REG' and g['gsis']
                and g['gameday'] and g['gametime'] and 1 <= g['week'] <= 18):
            groups[(g['season'], min((g['week'] - 1) // 6, 2))].append(g)
    selected = []
    for key in sorted(groups):
        selected.extend(rng.sample(sorted(groups[key], key=lambda x: x['game_id']), per_band))
    return selected

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--archive', type=Path, required=True)
    ap.add_argument('--clauses', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--per-band', type=int, default=2)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    books_dir = args.out / 'gamebooks'; books_dir.mkdir()
    schedule = pq.read_table(args.archive / 'raw/schedules/games.parquet', columns=[
        'game_id','season','week','gameday','gametime','game_type','gsis']).to_pylist()
    games = selected_games(schedule, args.per_band)
    books, failed = {}, {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch, g, books_dir): g for g in games}
        for future, g in futures.items():
            try:
                key, book = future.result(); books[key] = book
            except Exception as exc:
                failed[g['game_id']] = str(exc)
    game_map = {g['game_id']: g for g in games if g['game_id'] in books}
    clauses = defaultdict(list)
    for row in pq.read_table(args.clauses, columns=['game_id','play_id','foul_type_text','foul_team_text','disposition']).to_pylist():
        if row['game_id'] in game_map:
            clauses[(row['game_id'], row['play_id'])].append(row)
    counts, audits, output = Counter(), Counter(), {'train': [], 'holdout': []}
    season_counts = defaultdict(Counter)
    fields = ['game_id','play_id','qtr','time','down','ydstogo','yardline_100','posteam','defteam',
              'play_type','desc','penalty','season_type','qb_dropback','qb_scramble']
    for year in range(2021, 2026):
        table = pq.read_table(args.archive / f'raw/pbp/play_by_play_{year}.parquet', columns=fields)
        for row in table.to_pylist():
            game = game_map.get(row['game_id'])
            if not game:
                continue
            count = season_counts[year]
            def exclude(reason):
                counts[reason] += 1; count[reason] += 1
            if (row['season_type'] != 'REG' or row['down'] not in (1,2,3,4) or not row['posteam']
                    or not row['defteam'] or not row['ydstogo'] or not row['yardline_100']
                    or row['play_type'] not in ('run','pass','no_play') or not row['desc'] or not row['time']):
                exclude('non_candidate'); continue
            rowclauses = clauses[(row['game_id'], row['play_id'])]
            stratum = ('no_clause' if not rowclauses else 'multiple' if len(rowclauses) > 1
                       else str(rowclauses[0]['foul_type_text']) + ':' + str(rowclauses[0]['disposition']))
            audits[f'{year}:{stratum}:candidate'] += 1
            desc = norm(row['desc'])
            matches = [b for b in books[row['game_id']]['blocks'] if b['qtr'] == row['qtr']
                       and b['clock'].lstrip('0') == row['time'].lstrip('0') and desc in norm(b['text'])]
            if len(matches) != 1:
                exclude('official_match_missing_or_ambiguous'); continue
            audits[f'{year}:{stratum}:official_text_match'] += 1
            block = matches[0]
            official = block['text']
            names = {'ARZ': 'ARI', 'BLT': 'BAL', 'CLV': 'CLE', 'HST': 'HOU', 'LA': 'LAR', 'JAC': 'JAX'}
            field_team = block['field_team']
            if field_team not in (row['posteam'], row['defteam']):
                field_team = names.get(field_team, field_team)
            if field_team not in (row['posteam'], row['defteam']):
                exclude('official_field_team_unknown'); continue
            field_pos = 100 - block['field_number'] if field_team == row['posteam'] else block['field_number']
            distance = field_pos if block['to_go'].lower() == 'goal' else int(block['to_go'])
            if (block['down'], distance, field_pos) != (row['down'], row['ydstogo'], row['yardline_100']):
                exclude('official_state_disagreement'); continue
            official_fouls = len(FOUL.findall(official))
            desc_fouls = len(FOUL.findall(row['desc']))
            if official_fouls != desc_fouls or official_fouls != len(rowclauses):
                exclude('foul_count_disagreement'); continue
            if official_fouls > 1:
                exclude('multiple_fouls'); continue
            if official_fouls == 0 and (row['penalty'] != 0 or row['play_type'] == 'no_play'):
                exclude('unknown_or_administrative'); continue
            if official_fouls:
                clause = rowclauses[0]; typ = clause['foul_type_text']; disposition = clause['disposition']
                audits[f"{year}:{typ}:{disposition}:official_matched"] += 1
                if typ not in MAPPING or disposition not in ('accepted','declined'):
                    exclude('unsupported_or_uncertain_foul'); continue
                phase, side, foul = MAPPING[typ]
                if clause['foul_team_text'] != row['posteam' if side == 'offense' else 'defteam']:
                    exclude('foul_team_mismatch'); continue
                if norm(typ) not in norm(official) or (disposition == 'declined' and 'declined' not in official.lower()) or (disposition == 'accepted' and 'enforced' not in official.lower()):
                    exclude('official_foul_label_disagreement'); continue
                if phase == 'pre_snap' and (row['play_type'] != 'no_play' or disposition != 'accepted'):
                    exclude('presnap_timing_ambiguous'); continue
            else:
                phase, side, foul, disposition = None, None, None, 'none'
            is_snap = row['play_type'] in ('run','pass')
            nullified_dropback = bool(phase == 'live_ball' and row['play_type'] == 'no_play'
                and re.search(r'\b(?:pass(?:es)?|sacked|scrambles?)\b', re.split(r'\bPENALTY\s+on\b', row['desc'], flags=re.I)[0], re.I))
            if phase == 'live_ball' and not is_snap and not nullified_dropback:
                exclude('nullified_live_play_class_unknown'); continue
            is_snap = is_snap or nullified_dropback
            if phase is None and not is_snap:
                exclude('unknown_snap'); continue
            if row['play_type'] == 'pass' or nullified_dropback or row['qb_dropback'] == 1 or row['qb_scramble'] == 1:
                play_class = 'dropback'
            else:
                play_class = 'run'
            kickoff = pytz.timezone('America/New_York').localize(
                datetime.fromisoformat(game['gameday'] + 'T' + game['gametime'])).astimezone(timezone.utc).isoformat()
            vintage = books[row['game_id']]['source_published_utc']
            for stage in ('pre_snap', 'live_ball'):
                if stage == 'live_ball' and not is_snap:
                    continue
                outcome = f'{side}:{foul}' if phase == stage else 'none'
                doc = {'context': {'phase': stage, 'rule_era': year, 'offense_team': row['posteam'],
                       'defense_team': row['defteam'], 'down': int(row['down']), 'to_go': int(row['ydstogo']),
                       'yardline_100': int(row['yardline_100']), 'play_class': 'pre_snap' if stage == 'pre_snap' else play_class},
                       'opportunity_id': f"{row['game_id']}:{int(row['play_id'])}:{stage}", 'game_kickoff_utc': kickoff,
                       'source_published_utc': vintage, 'outcome': outcome, 'label_verified': True,
                       'foul_count': int(outcome != 'none'), 'disposition': disposition if outcome != 'none' else 'none'}
                output['holdout' if year == 2025 else 'train'].append(doc)
                counts[f'{stage}:{outcome}'] += 1; count[f'{stage}:{outcome}'] += 1
            audits[f'{year}:{stratum}:included'] += 1
    for split, rows in output.items():
        with (args.out / (split + '.jsonl')).open('x') as f:
            for row in rows: f.write(json.dumps(row, sort_keys=True) + '\n')
    with (args.out / 'official-evidence.jsonl').open('x') as evidence:
        for rows in output.values():
            for row in rows:
                game_id, play_id, stage = row['opportunity_id'].split(':')
                book = books[game_id]
                evidence.write(json.dumps({
                    'opportunity_id': row['opportunity_id'], 'game_id': game_id,
                    'source_play_id': int(play_id), 'phase': stage,
                    'official_record_url': book['url'], 'official_record_sha256': book['sha256'],
                    'official_record_last_modified_utc': book['source_published_utc'],
                    'verification': 'unique_exact_text_match_with_state_and_foul_checks',
                }, sort_keys=True) + '\n')
    manifest = {'selection': f'seed 170612; uniform {args.per_band} games per season in weeks 1-6, 7-12, 13-18',
      'selected_games': games, 'unavailable_gamebooks': failed, 'gamebooks': {k:{x:y for x,y in v.items() if x != 'blocks'} for k,v in books.items()},
      'counts': dict(counts), 'by_season': {str(k):dict(v) for k,v in season_counts.items()},
      'source_sha256': {'clauses': file_sha(args.clauses),
         'schedule': file_sha(args.archive / 'raw/schedules/games.parquet'),
         **{f'pbp_{year}': file_sha(args.archive / f'raw/pbp/play_by_play_{year}.parquet') for year in range(2021, 2026)}},
      'matched_fouls_by_stratum':dict(audits), 'qualification':'Exact source-text alignment to an official block, not independent re-adjudication; selection and source vintage limitations apply.'}
    (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'games_selected':len(games),'games_downloaded':len(books),'failed':failed,'counts':dict(counts)},indent=2))
if __name__ == '__main__': main()
