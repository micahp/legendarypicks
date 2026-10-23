#!/usr/bin/env python3
"""Audit the Madden ratings archive (1992-2027) against its own oracles and the spec.

Reads out/madden_ratings_long.csv and out/madden_player_seasons.db straight from the
zip (nothing is extracted into the repo). Every check prints PASS, FAIL or INFO with
the measured number; any FAIL exits 1. A missing oracle is a FAIL, not a skip.

Writes:
  --derived-dir   row-level normalized table and review lists (raw ratings: keep out of git)
  --summary-json  aggregates only (no player names, no per-player ratings): commit-safe

Usage:
  python3 scripts/madden/audit_madden_ratings.py \
      --zip /root/nfl-ratings-data/madden_ratings_1992-2027.zip \
      --derived-dir /root/nfl-ratings-data/derived \
      --summary-json docs/research/data/madden-audit-summary.json
"""

import argparse
import csv
import io
import json
import os
import re
import sqlite3
import statistics
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict

EXPECTED_ROWS = 58743
EXPECTED_COLUMNS = 71  # README (bundle 2026-10-23 03:36): 11 identity + 60 attributes
EXPECTED_TEAM_PAGE_ROWS = 7387
EXPECTED_PLAYERS = 12570
IDENTITY = ['player_id', 'player_name', 'slug', 'madden_release', 'dupe_seq', 'nfl_season', 'team', 'POS',
            'source', 'site_calculated', 'value_flags']

# Madden POS (primary token before a slash) -> position group. Anything not listed is
# reported as OTHER and fails the check: an unmapped position is never silently grouped.
POS_GROUP = {
    'QB': 'QB',
    'RB': 'RB', 'HB': 'RB', 'FB': 'RB',
    'WR': 'WR',
    'TE': 'TE',
    'C': 'OL', 'G': 'OL', 'T': 'OL', 'LT': 'OL', 'RT': 'OL', 'LG': 'OL', 'RG': 'OL',
    'OG': 'OL', 'OT': 'OL', 'OL': 'OL', 'T-G': 'OL',
    'DE': 'DL', 'DT': 'DL', 'NT': 'DL', 'DL': 'DL', 'LE': 'DL', 'RE': 'DL',
    'LDE': 'DL', 'RDE': 'DL', 'LDT': 'DL', 'RDT': 'DL',
    'LB': 'LB', 'OLB': 'LB', 'ILB': 'LB', 'MLB': 'LB', 'LLB': 'LB', 'RLB': 'LB',
    'LOLB': 'LB', 'ROLB': 'LB', 'LILB': 'LB', 'RILB': 'LB',
    'CB': 'DB', 'LCB': 'DB', 'RCB': 'DB', 'S': 'DB', 'SS': 'DB', 'FS': 'DB', 'DB': 'DB',
    'K': 'K', 'P': 'P',
    'KR': 'ST', 'PR': 'ST', 'LS': 'ST',
}


def norm_name(s):
    """Lowercase, strip accents and punctuation, drop generational suffixes."""
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r"[.'`’-]", '', s.lower())
    s = re.sub(r'\s+(jr|sr|ii|iii|iv|v)$', '', s.strip())
    return re.sub(r'\s+', ' ', s).strip()


class Report:
    def __init__(self, waivers=None):
        self.checks = []
        self.fails = 0
        self.waived = 0
        self.waivers = waivers or {}

    def add(self, cid, status, detail, measured=None):
        # A waiver applies only to the exact measured values it was accepted for. Otherwise the
        # check stays a FAIL, and the detail says why the waiver no longer applies.
        measured = json.loads(json.dumps(measured, sort_keys=True)) if measured is not None else None
        waiver = self.waivers.get(cid)
        if status == 'FAIL' and waiver is not None:
            if measured == waiver['measured']:
                status = 'WAIVED'
                detail = f"{detail} [accepted exception: {waiver['reason']}]"
                self.waived += 1
            else:
                detail = f"{detail} [waiver does not match: measured {measured}, waived {waiver['measured']}]"
        self.checks.append({'id': cid, 'status': status, 'detail': detail, 'measured': measured})
        if status == 'FAIL':
            self.fails += 1
        print(f'[{status:6}] {cid}: {detail}')


DEFAULT_EXCEPTIONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'docs', 'research',
                                  'madden-audit-exceptions.json')


def load_waivers(path):
    """Read accepted exceptions keyed by check id. A missing file means no waivers, not an error."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    return {e['check']: e for e in data['exceptions']}


def load_csv(zf):
    raw = zf.read('out/madden_ratings_long.csv').decode('utf-8')
    reader = csv.DictReader(io.StringIO(raw))
    rows = list(reader)
    return list(reader.fieldnames), rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zip', required=True)
    ap.add_argument('--derived-dir', required=True)
    ap.add_argument('--summary-json', required=True)
    ap.add_argument('--exceptions', default=DEFAULT_EXCEPTIONS)
    args = ap.parse_args()
    os.makedirs(args.derived_dir, exist_ok=True)
    os.makedirs(os.path.dirname(args.summary_json), exist_ok=True)

    rep = Report(load_waivers(args.exceptions))
    zf = zipfile.ZipFile(args.zip)
    bad_zip = zf.testzip()
    rep.add('zip.integrity', 'PASS' if bad_zip is None else 'FAIL', f'testzip={bad_zip}')

    header, rows = load_csv(zf)
    ATTR = header[len(IDENTITY):]
    coverage = json.loads(zf.read('out/coverage.json'))

    # 1. Shape
    rep.add('shape.header_identity', 'PASS' if header[:len(IDENTITY)] == IDENTITY else 'FAIL',
            f'first {len(IDENTITY)} columns = {header[:len(IDENTITY)]}')
    rep.add('shape.columns', 'PASS' if len(header) == EXPECTED_COLUMNS else 'FAIL',
            f'{len(header)} columns = {len(IDENTITY)} identity + {len(ATTR)} attributes '
            f'(expected {EXPECTED_COLUMNS}: {len(IDENTITY)} identity + 60 attributes)')
    rep.add('shape.rows', 'PASS' if len(rows) == EXPECTED_ROWS else 'FAIL',
            f'{len(rows)} rows vs expected {EXPECTED_ROWS}')
    readme = zf.read('README.md').decode('utf-8')
    rep.add('readme.column_count', 'FAIL' if '× 73 columns' in readme else 'PASS',
            f'README contents table says "× 73 columns"; the file has {len(header)} and the README numbers say 70')
    spec_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'docs',
                             'MADDEN-RATINGS-DATASET-1992-2027.md')
    spec_text = open(spec_path, encoding='utf-8').read() if os.path.exists(spec_path) else ''
    # Every column count the spec states must equal the file's count.
    stated = sorted({int(n) for n in re.findall(r'(\d+) columns', spec_text)} |
                    {int(n) for n in re.findall(r'identity columns = (\d+)', spec_text)})
    stale = [n for n in stated if n != len(header)]
    rep.add('spec.column_count', 'PASS' if spec_text and stated and not stale else 'FAIL',
            f'repo spec doc states column counts {stated}; the file has {len(header)}'
            + (f'; stale: {stale}' if stale else ''))

    # 2. Oracle: coverage.json (publisher-side counts are ours, so compare to the archive's own file)
    per_rel_csv = Counter(r['madden_release'] for r in rows)
    per_rel_cov = {str(k): v for k, v in coverage['seasons_per_release'].items()}
    mism = {y: (per_rel_cov.get(y), per_rel_csv.get(y)) for y in per_rel_cov if per_rel_cov.get(y) != per_rel_csv.get(y)}
    rep.add('coverage.per_release_rows', 'PASS' if not mism else 'FAIL',
            f'{len(per_rel_cov) - len(mism)} of {len(per_rel_cov)} releases match coverage.json' +
            (f'; mismatches {mism}' if mism else ''))

    # The archive ships its own register of known limits. Each count it publishes must match the rows.
    if 'out/source_limits.json' not in zf.namelist():
        rep.add('register.present', 'FAIL', 'out/source_limits.json is missing from the bundle')
    else:
        register = json.loads(zf.read('out/source_limits.json'))
        limits = {it['check']: it for it in register['known_limits']}
        blank_n = sum(1 for r in rows if not r['team'].strip())
        fa_n = sum(1 for r in rows if r['team'].strip().lower() == 'fa')
        oor_n = sum(1 for r in rows for a in ATTR
                    if r[a].strip() and re.fullmatch(r'-?\d+', r[a].strip()) and not 0 <= int(r[a]) <= 99)
        dup_groups = defaultdict(int)
        for r in rows:
            dup_groups[(r['player_id'], r['madden_release'])] += 1
        dup_n = sum(1 for n in dup_groups.values() if n > 1)
        r27 = [r for r in rows if r['madden_release'] == '2027']
        teams27 = {r['team'].strip().lower() for r in r27 if r['team'].strip() and r['team'].strip().lower() != 'fa'}
        teamless27 = sum(1 for r in r27 if not r['team'].strip())
        expected = [
            ('blank_team.count', limits['blank_team']['count'], blank_n),
            ('blank_team.free_agent_rows_total', limits['blank_team']['free_agent_rows_total'], fa_n),
            ('out_of_range_values.count', limits['out_of_range_values']['count'], oor_n),
            ('duplicate_player_release.count', limits['duplicate_player_release']['count'], dup_n),
            ('release_incomplete.teams_present', limits['release_incomplete']['teams_present'], len(teams27)),
            ('release_incomplete.teamless_rows_2027', limits['release_incomplete']['teamless_rows_2027'], teamless27),
        ]
        mism = [f'{name}: register {reg} vs rows {got}' for name, reg, got in expected if reg != got]
        rep.add('register.counts_match_rows', 'PASS' if not mism else 'FAIL',
                f'{len(expected)} published register counts checked' +
                (f'; mismatches: {mism}' if mism else ''))

    # Every out/by_year/madden_<year>.csv must be the same multiset of rows as the long CSV slice.
    def row_key(d):
        return tuple(d.get(c, '').strip() for c in header)

    stale = []
    for y in sorted(per_rel_csv, key=int):
        name = f'out/by_year/madden_{y}.csv'
        if name not in zf.namelist():
            stale.append((y, 'missing file'))
            continue
        by = list(csv.DictReader(io.StringIO(zf.read(name).decode('utf-8'))))
        if set(by[0].keys()) != set(header):
            stale.append((y, 'columns differ'))
            continue
        long_keys = sorted(row_key(r) for r in rows if r['madden_release'] == y)
        by_keys = sorted(row_key(r) for r in by)
        if long_keys != by_keys:
            stale.append((y, len(by), len(long_keys)))
    rep.add('zip.by_year_matches_long', 'PASS' if not stale else 'FAIL',
            f'{len(per_rel_csv) - len(stale)} of {len(per_rel_csv)} by_year files equal the long CSV slice' +
            (f'; stale: {stale}' if stale else ''))

    # attribute_present_counts in coverage.json vs the CSV's non-blank cells
    cov_attr = coverage['attribute_present_counts']
    actual_attr = {a: sum(1 for r in rows if r[a].strip() != '') for a in ATTR}
    attr_mism = {a: (cov_attr.get(a), actual_attr[a]) for a in ATTR if cov_attr.get(a) != actual_attr[a]}
    rep.add('coverage.attribute_counts', 'PASS' if not attr_mism else 'FAIL',
            f'{len(ATTR) - len(attr_mism)} of {len(ATTR)} attribute counts match coverage.json; '
            f'e.g. OVR coverage.json={cov_attr["OVR"]} vs CSV={actual_attr["OVR"]}')

    # 3. OVR: the README splits presence into EA-published and site-calculated values
    ovr_nonblank = actual_attr['OVR']
    ea_pub = sum(1 for r in rows if r['OVR'].strip() and not r['site_calculated'].strip())
    calc_n = sum(1 for r in rows if r['site_calculated'].strip())
    rep.add('ovr.README_counts', 'PASS' if (ovr_nonblank, ea_pub, calc_n) == (58345, 50203, 8142) else 'FAIL',
            f'OVR present {ovr_nonblank} (README 58,345), EA-published {ea_pub} (README 50,203), '
            f'site-calculated {calc_n} (README 8,142)')
    calc_flags = {r['site_calculated'].strip() for r in rows}
    rep.add('ovr.calculated_flag_values', 'PASS' if calc_flags <= {'', 'OVR'} else 'FAIL',
            f'site_calculated values: {sorted(calc_flags)}')
    calc_rel = {r['madden_release'] for r in rows if r['site_calculated'].strip()}
    expected_calc = {str(y) for y in list(range(1992, 1997)) + list(range(1998, 2001))}
    rep.add('ovr.calculated_only_1992_2000', 'PASS' if calc_rel == expected_calc else 'FAIL',
            f'releases with site-calculated OVR: {sorted(calc_rel, key=int)}')
    all_empty = sum(1 for r in rows if not any(r[c].strip() for c in ('OVR', 'SPEED', 'AWR')))
    rep.add('ovr.no_empty_core_rows', 'PASS' if all_empty == 0 else 'FAIL',
            f'rows where OVR, SPEED and AWR are all blank = {all_empty}')

    # 4. Attribute values: integers in 0-99, blank = absent
    tokens_bad = Counter()
    range_bad = []
    for i, r in enumerate(rows):
        for a in ATTR:
            v = r[a].strip()
            if v == '':
                continue
            if not re.fullmatch(r'-?\d+', v):
                tokens_bad[a] += 1
                continue
            n = int(v)
            if n < 0 or n > 99:
                range_bad.append((r['player_id'], r['madden_release'], a, v))
    rep.add('attr.integer_tokens', 'PASS' if not tokens_bad else 'FAIL',
            f'non-integer tokens: {dict(tokens_bad) or "none"}')
    rep.add('attr.range_0_99', 'PASS' if not range_bad else 'FAIL',
            f'{len(range_bad)} cells outside 0-99' +
            (f', e.g. player {range_bad[0][0]} {range_bad[0][1]} {range_bad[0][2]}={range_bad[0][3]}' if range_bad else ''),
            measured={'cells': len(range_bad), 'values': sorted({v[3] for v in range_bad}),
                      'releases': sorted({v[1] for v in range_bad})})

    # 5. Keys and duplicates
    doc_key = defaultdict(list)
    for i, r in enumerate(rows):
        doc_key[(r['player_id'], r['madden_release'], r['dupe_seq'])].append(i)
    doc_key_dups = sum(1 for v in doc_key.values() if len(v) > 1)
    rep.add('keys.documented_key_unique', 'PASS' if doc_key_dups == 0 else 'FAIL',
            f'(player_id, madden_release, dupe_seq) is duplicated for {doc_key_dups} keys; the README documents this key')
    key_groups = defaultdict(list)
    for i, r in enumerate(rows):
        key_groups[(r['player_id'], r['madden_release'])].append(i)
    dup_keys = {k: v for k, v in key_groups.items() if len(v) > 1}
    dup_rows = sum(len(v) for v in dup_keys.values())
    identical = sum(1 for v in dup_keys.values()
                    if all(rows[v[0]][c] == rows[j][c] for j in v[1:] for c in header))
    team_differs = sum(1 for v in dup_keys.values() if len({rows[j]['team'].strip().lower() for j in v}) > 1)
    rating_differs = sum(1 for v in dup_keys.values()
                         if any(len({rows[j][c] for j in v}) > 1 for c in ATTR))
    seq_bad = [k for k, v in dup_keys.items() if sorted(int(rows[i]['dupe_seq']) for i in v) != list(range(len(v)))]
    rep.add('keys.stint_sequence_contiguous', 'PASS' if not seq_bad else 'FAIL',
            f'{len(dup_keys)} player-releases have more than one row ({dup_rows} rows); '
            f'dupe_seq is not 0..n-1 for {len(seq_bad)}')
    same_team = [k for k, v in dup_keys.items() if len({rows[i]['team'].strip().lower() for i in v}) == 1]
    rep.add('keys.stints_differ_by_team', 'PASS' if not same_team else 'FAIL',
            f'{len(same_team)} multi-row player-releases have one team on every row; '
            f'the README says these rows are team changes')
    rep.add('keys.stint_ratings_differ', 'INFO',
            f'{identical} identical, {team_differs} differ by team, {rating_differs} of {len(dup_keys)} differ in at '
            f'least one attribute; a value that changes within one release is a leakage question')

    # 6. Team: casing, blanks, normalized count
    raw_team = Counter(r['team'] for r in rows)
    low = defaultdict(set)
    for t in raw_team:
        if t.strip():
            low[t.strip().lower()].add(t)
    case_pairs = {k: sorted(v) for k, v in low.items() if len(v) > 1}
    rep.add('team.case_consistent', 'PASS' if not case_pairs else 'FAIL',
            f'{len(case_pairs)} team slugs appear in more than one casing, e.g. {next(iter(case_pairs.values()), [])}')
    blank_team = [r for r in rows if not r['team'].strip()]
    rep.add('team.no_blank', 'PASS' if not blank_team else 'FAIL',
            f'{len(blank_team)} rows with blank team (all source={set(r["source"] for r in blank_team)}); '
            f'kept as team_missing, not filled',
            measured={'rows': len(blank_team), 'sources': sorted({r['source'] for r in blank_team})})
    norm_teams = {t for t in low}
    rep.add('team.distinct_normalized', 'INFO',
            f'{len(norm_teams)} distinct non-blank team slugs after lowercasing (current NFL franchises: 32)')
    teams_by_rel = defaultdict(set)
    for r in rows:
        # 'fa' is the free-agent marker (see register.counts_match_rows), not a franchise.
        if r['team'].strip() and r['team'].strip().lower() != 'fa':
            teams_by_rel[int(r['madden_release'])].add(r['team'].strip().lower())
    short = {y: len(teams_by_rel[y]) for y in range(2003, 2028) if len(teams_by_rel[y]) != 32}
    rep.add('team.32_franchises_2003_2027', 'PASS' if not short else 'FAIL',
            'releases 2003-2027 whose team count is not 32: ' + (str(short) if short else 'none'),
            measured={'short': {str(k): v for k, v in short.items()}})

    # 7. nfl_season: text in player pages, blank in team pages
    season_bad = []
    season_src = Counter()
    for r in rows:
        s = r['nfl_season'].strip()
        if s == '':
            season_src['derived_from_release'] += 1
            continue
        m = re.fullmatch(r'(\d{4})( NFL season)?', s)
        if not m:
            season_bad.append(s)
            continue
        season_src['source_text'] += 1
        if int(m.group(1)) != int(r['madden_release']) - 1:
            season_bad.append((r['madden_release'], s))
    rep.add('season.consistent_with_release_minus_1', 'PASS' if not season_bad else 'FAIL',
            f'{season_src["source_text"]} non-blank nfl_season values agree with release-1 '
            f'({len(season_bad)} disagree); {season_src["derived_from_release"]} blank values are derived from release-1')

    # 8. Team-page supplement and POS
    tp = sum(1 for r in rows if r['source'] == 'team_page')
    rep.add('source.team_page_rows', 'PASS' if tp == EXPECTED_TEAM_PAGE_ROWS else 'FAIL',
            f'{tp} team_page rows vs spec {EXPECTED_TEAM_PAGE_ROWS}')
    pos_prim = Counter()
    unmapped = Counter()
    for r in rows:
        p = r['POS'].strip().split('/')[0]
        pos_prim[p] += 1
        if p not in POS_GROUP:
            unmapped[p] += 1
    rep.add('pos.all_mapped', 'PASS' if not unmapped else 'FAIL',
            f'{len(pos_prim)} distinct primary POS tokens; unmapped: {dict(unmapped) or "none"}')

    # 9. Identity consistency inside the archive
    names_per_id = defaultdict(set)
    ids_per_name = defaultdict(set)
    for r in rows:
        names_per_id[r['player_id']].add(r['player_name'])
        ids_per_name[norm_name(r['player_name'])].add(r['player_id'])
    multi_name_ids = {k: v for k, v in names_per_id.items() if len(v) > 1}
    rep.add('identity.one_name_per_player_id', 'PASS' if not multi_name_ids else 'FAIL',
            f'{len(multi_name_ids)} player_ids carry more than one player_name')
    rep.add('identity.player_count', 'PASS' if len(names_per_id) == EXPECTED_PLAYERS else 'FAIL',
            f'{len(names_per_id)} distinct player_id vs spec {EXPECTED_PLAYERS}')
    malformed_re = re.compile(r'\s-\s|\s\(|\||\s(?:HB|WR|QB|RB|TE|OL|DL|LB|DB|CB|SS|FS|S|K|P|OT|OG|DE|DT|LT|RT|LG|RG|FB|LS|KR|PR|C|G|T)$')
    malformed_rows = [r for r in rows if malformed_re.search(r['player_name'])]
    malformed_ids = {r['player_id'] for r in malformed_rows}
    malformed_examples = sorted({r['player_name'] for r in malformed_rows})[:2]
    rep.add('identity.name_is_person_only', 'PASS' if not malformed_rows else 'FAIL',
            f'{len(malformed_ids)} player_ids ({len(malformed_rows)} rows) carry position or team text in '
            f'player_name, e.g. {malformed_examples}')
    homonyms = {k: v for k, v in ids_per_name.items() if len(v) > 1}
    rep.add('identity.homonym_names', 'INFO',
            f'{len(homonyms)} normalized names map to more than one player_id (review queue, not merged)')

    # 10. Compare every row with the SQLite copy (cell by cell, same order)
    tmpdb = os.path.join(args.derived_dir, 'madden_player_seasons.db')
    with open(tmpdb, 'wb') as f:
        f.write(zf.read('out/madden_player_seasons.db'))
    con = sqlite3.connect('file:' + tmpdb + '?mode=ro', uri=True)
    cur = con.execute('select * from ratings order by rowid')
    dbcols = [d[0] for d in cur.description]
    dbrows = cur.fetchall()

    def cell(v):
        if v is None:
            return ''
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)

    db_diff = 0
    if dbcols != header or len(dbrows) != len(rows):
        db_diff = -1
    else:
        for a, b in zip(rows, dbrows):
            for j, c in enumerate(header):
                if cell(b[j]).strip() != a[c].strip():
                    db_diff += 1
    rep.add('db.matches_csv_cellwise', 'PASS' if db_diff == 0 else 'FAIL',
            f'{len(dbrows)} DB rows vs {len(rows)} CSV rows; {db_diff} cell differences' if db_diff >= 0 else
            'DB shape differs from CSV')
    db_players = con.execute('select count(*) from players').fetchone()[0]
    rep.add('db.players_table_rows', 'PASS' if db_players == EXPECTED_PLAYERS else 'FAIL',
            f'players table rows = {db_players} vs {EXPECTED_PLAYERS}')
    con.close()

    # 11. Diagnostics: per release and per release x position group
    by_rel = defaultdict(list)
    for r in rows:
        by_rel[r['madden_release']].append(r)
    rel_summary = []
    for y in sorted(by_rel, key=int):
        rs = by_rel[y]
        attrs_any = sum(1 for a in ATTR if any(r[a].strip() for r in rs))
        cells = statistics.mean(sum(1 for a in ATTR if r[a].strip()) for r in rs)
        teams = {r['team'].strip().lower() for r in rs if r['team'].strip()}

        def med(col):
            vals = [int(r[col]) for r in rs if r[col].strip()]
            return (round(statistics.median(vals), 1), len(vals)) if vals else (None, 0)
        rel_summary.append({
            'release': int(y),
            'nfl_season': int(y) - 1,
            'rows': len(rs),
            'players': len({r['player_id'] for r in rs}),
            'team_page_rows': sum(1 for r in rs if r['source'] == 'team_page'),
            'blank_team_rows': sum(1 for r in rs if not r['team'].strip()),
            'teams_normalized': len(teams),
            'players_per_team_mean': round(len(rs) / max(len(teams), 1), 1),
            'attributes_with_any_value': attrs_any,
            'mean_nonblank_attribute_cells_per_row': round(cells, 1),
            'ovr_nonblank': sum(1 for r in rs if r['OVR'].strip()),
            'median_OVR': med('OVR')[0],
            'median_SPEED': med('SPEED')[0],
            'median_AWR': med('AWR')[0],
        })

    # Definition shifts: attribute presence jumps or appears/disappears between releases
    years = [s['release'] for s in rel_summary]
    shifts = []
    presence = {}
    for a in ATTR:
        presence[a] = {}
        for y in years:
            rs = by_rel[str(y)]
            presence[a][y] = sum(1 for r in rs if r[a].strip()) / len(rs)
    for a in ATTR:
        for prev, cur_y in zip(years, years[1:]):
            p0, p1 = presence[a][prev], presence[a][cur_y]
            if (p0 == 0) != (p1 == 0) or abs(p1 - p0) >= 0.25:
                shifts.append({'attribute': a, 'from_release': prev, 'to_release': cur_y,
                               'presence_from': round(p0, 3), 'presence_to': round(p1, 3)})
    shift_years = Counter(s['to_release'] for s in shifts)
    rep.add('shift.attribute_presence', 'INFO',
            f'{len(shifts)} attribute presence steps (>=25 pts or appear/disappear); '
            f'largest in releases {dict(shift_years.most_common(6))}')

    # A release whose player pages show under half the attribute cells of both neighbours is a
    # source template gap until shown otherwise, not a rating-definition change.
    cells_by_rel = {s['release']: s['mean_nonblank_attribute_cells_per_row'] for s in rel_summary}
    collapse = []
    for prev, y, nxt in zip(years, years[1:], years[2:]):
        if cells_by_rel[y] < 0.5 * min(cells_by_rel[prev], cells_by_rel[nxt]):
            collapse.append((y, cells_by_rel[y], cells_by_rel[prev], cells_by_rel[nxt]))
    rep.add('presence.no_collapse_vs_neighbours', 'PASS' if not collapse else 'FAIL',
            'releases with attribute cells per row under half of both neighbours: ' +
            (', '.join(f'{y} ({c} vs {p}/{n})' for y, c, p, n in collapse) if collapse else 'none'),
            measured={'releases': sorted(y for y, _, _, _ in collapse)})

    # Position x release aggregates (commit-safe: counts and medians only)
    grp_rows = []
    rel_pos = defaultdict(list)
    for r in rows:
        g = POS_GROUP.get(r['POS'].strip().split('/')[0], 'OTHER')
        rel_pos[(r['madden_release'], g)].append(r)
    for (y, g) in sorted(rel_pos, key=lambda k: (int(k[0]), k[1])):
        rs = rel_pos[(y, g)]

        def gm(col):
            vals = [int(r[col]) for r in rs if r[col].strip()]
            return round(statistics.median(vals), 1) if vals else None
        grp_rows.append({'release': int(y), 'pos_group': g, 'rows': len(rs),
                         'median_OVR': gm('OVR'), 'median_SPEED': gm('SPEED'), 'median_AWR': gm('AWR'),
                         'median_THP': gm('THP'), 'median_CTH': gm('CTH')})

    # 12. Write derived row-level normalized table (raw ratings: derived dir only)
    out_path = os.path.join(args.derived_dir, 'normalized_ratings.csv')
    out_cols = ['row_id', 'player_id', 'player_name', 'slug', 'madden_release', 'nfl_season', 'season_source',
                'team_raw', 'team_norm', 'team_missing', 'POS', 'pos_primary', 'pos_group', 'source',
                'dupe_seq', 'site_calculated',
                'key_duplicate', 'ovr_present', 'attr_present_count'] + ATTR
    dup_row_ids = {i for v in dup_keys.values() for i in v}
    with open(out_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(out_cols)
        for i, r in enumerate(rows):
            s = r['nfl_season'].strip()
            season = (int(re.match(r'\d{4}', s).group(0)) if s else int(r['madden_release']) - 1)
            team_norm = r['team'].strip().lower()
            prim = r['POS'].strip().split('/')[0]
            w.writerow([i + 1, r['player_id'], r['player_name'], r['slug'], int(r['madden_release']), season,
                        'source_text' if s else 'derived_release_minus_1',
                        r['team'], team_norm, 1 if not team_norm else 0,
                        r['POS'], prim, POS_GROUP.get(prim, 'OTHER'), r['source'],
                        r['dupe_seq'], r['site_calculated'],
                        1 if i in dup_row_ids else 0,
                        1 if r['OVR'].strip() else 0,
                        sum(1 for a in ATTR if r[a].strip())] + [r[a].strip() for a in ATTR])
    review_path = os.path.join(args.derived_dir, 'duplicate_keys_review.csv')
    with open(review_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['player_id', 'player_name', 'madden_release', 'row_id', 'team_raw', 'source', 'OVR', 'SPEED', 'AWR'])
        for k in sorted(dup_keys, key=lambda k: (int(k[1]), k[0])):
            for i in dup_keys[k]:
                r = rows[i]
                w.writerow([k[0], r['player_name'], k[1], i + 1, r['team'], r['source'], r['OVR'], r['SPEED'], r['AWR']])
    print(f'wrote {out_path}')
    print(f'wrote {review_path}')

    summary = {
        'archive': os.path.basename(args.zip),
        'rows': len(rows),
        'columns': len(header),
        'identity_columns': len(IDENTITY),
        'attribute_columns': len(ATTR),
        'checks': rep.checks,
        'fail_count': rep.fails,
        'waived_count': rep.waived,
        'releases': rel_summary,
        'position_group_by_release': grp_rows,
        'attribute_presence_shifts': shifts,
        'duplicate_keys': len(dup_keys),
        'duplicate_rows': dup_rows,
        'blank_team_rows': len(blank_team),
        'team_case_pairs': len(case_pairs),
        'team_distinct_normalized': len(norm_teams),
        'coverage_json_attribute_mismatches': len(attr_mism),
        'coverage_json_attribute_examples': {a: {'coverage_json': cov_attr.get(a), 'csv': actual_attr[a]}
                                              for a in ['OVR', 'SPEED', 'ACC', 'AWR', 'STR']},
    }
    with open(args.summary_json, 'w') as f:
        json.dump(summary, f, indent=2)
        f.write('\n')
    print(f'wrote {args.summary_json}')
    print(f'WAIVED count: {rep.waived}')
    print(f'FAIL count: {rep.fails}')
    return 1 if rep.fails else 0


if __name__ == '__main__':
    sys.exit(main())
