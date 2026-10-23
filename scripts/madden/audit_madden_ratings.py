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
EXPECTED_TEAM_PAGE_ROWS = 7387
EXPECTED_PLAYERS = 12570
IDENTITY = ['player_id', 'player_name', 'slug', 'madden_release', 'nfl_season', 'team', 'POS', 'source']

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
    def __init__(self):
        self.checks = []
        self.fails = 0

    def add(self, cid, status, detail):
        self.checks.append({'id': cid, 'status': status, 'detail': detail})
        if status == 'FAIL':
            self.fails += 1
        print(f'[{status:4}] {cid}: {detail}')


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
    args = ap.parse_args()
    os.makedirs(args.derived_dir, exist_ok=True)
    os.makedirs(os.path.dirname(args.summary_json), exist_ok=True)

    rep = Report()
    zf = zipfile.ZipFile(args.zip)
    bad_zip = zf.testzip()
    rep.add('zip.integrity', 'PASS' if bad_zip is None else 'FAIL', f'testzip={bad_zip}')

    header, rows = load_csv(zf)
    ATTR = header[len(IDENTITY):]
    coverage = json.loads(zf.read('out/coverage.json'))

    # 1. Shape
    rep.add('shape.header_identity', 'PASS' if header[:8] == IDENTITY else 'FAIL',
            f'first 8 columns = {header[:8]}')
    rep.add('shape.columns', 'INFO',
            f'{len(header)} columns total = {len(IDENTITY)} identity + {len(ATTR)} attributes '
            f'(spec says 73 columns and 5 identity: measured {len(header)} and {len(IDENTITY)})')
    rep.add('shape.rows', 'PASS' if len(rows) == EXPECTED_ROWS else 'FAIL',
            f'{len(rows)} rows vs expected {EXPECTED_ROWS}')

    # 2. Oracle: coverage.json (publisher-side counts are ours, so compare to the archive's own file)
    per_rel_csv = Counter(r['madden_release'] for r in rows)
    per_rel_cov = {str(k): v for k, v in coverage['seasons_per_release'].items()}
    mism = {y: (per_rel_cov.get(y), per_rel_csv.get(y)) for y in per_rel_cov if per_rel_cov.get(y) != per_rel_csv.get(y)}
    rep.add('coverage.per_release_rows', 'PASS' if not mism else 'FAIL',
            f'{len(per_rel_cov) - len(mism)} of {len(per_rel_cov)} releases match coverage.json' +
            (f'; mismatches {mism}' if mism else ''))

    # attribute_present_counts in coverage.json vs the CSV's non-blank cells
    cov_attr = coverage['attribute_present_counts']
    actual_attr = {a: sum(1 for r in rows if r[a].strip() != '') for a in ATTR}
    attr_mism = {a: (cov_attr.get(a), actual_attr[a]) for a in ATTR if cov_attr.get(a) != actual_attr[a]}
    rep.add('coverage.attribute_counts', 'PASS' if not attr_mism else 'FAIL',
            f'{len(ATTR) - len(attr_mism)} of {len(ATTR)} attribute counts match coverage.json; '
            f'e.g. OVR coverage.json={cov_attr["OVR"]} vs CSV={actual_attr["OVR"]}')

    # 3. OVR presence: README says 50,203
    ovr_nonblank = actual_attr['OVR']
    rep.add('ovr.README_claim_50203', 'PASS' if ovr_nonblank == 50203 else 'FAIL',
            f'rows with OVR = {ovr_nonblank} (README claims 50,203)')
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
            (f', e.g. player {range_bad[0][0]} {range_bad[0][1]} {range_bad[0][2]}={range_bad[0][3]}' if range_bad else ''))

    # 5. Keys and duplicates
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
    rep.add('keys.player_release_unique', 'PASS' if not dup_keys else 'FAIL',
            f'{len(dup_keys)} keys (player_id, madden_release) occur more than once, covering {dup_rows} rows; '
            f'{identical} identical, {team_differs} differ by team, {rating_differs} differ in at least one attribute')

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
            f'kept as team_missing, not filled')
    norm_teams = {t for t in low}
    rep.add('team.distinct_normalized', 'INFO',
            f'{len(norm_teams)} distinct non-blank team slugs after lowercasing (current NFL franchises: 32)')

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
            (', '.join(f'{y} ({c} vs {p}/{n})' for y, c, p, n in collapse) if collapse else 'none'))

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
    print(f'FAIL count: {rep.fails}')
    return 1 if rep.fails else 0


if __name__ == '__main__':
    sys.exit(main())
