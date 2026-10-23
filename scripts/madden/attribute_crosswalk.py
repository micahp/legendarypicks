#!/usr/bin/env python3
"""Attribute crosswalk: 60 Madden source columns -> 35 Gridiron ratings.

The mapping is authored here, one row per source column, and written to
docs/research/madden-attribute-crosswalk.csv. Presence counts and two internal
agreement checks are measured from the archive on every run.

Relations:
  exact      same concept under the same name (meaning per Gridiron docs/RATINGS.md)
  renamed    same concept, different spelling (SPEED -> SPD)
  partial    related but not the same measurement; use only with a stated caveat
  candidate  plausible match that is not used until the agreement check passes
  none       no Gridiron rating; kept as a source-only column

Nothing is combined. A source column that is split across several Gridiron ratings
(SRR/MRR/DRR into RTE, RBP/RBF into RBK) stays unmapped unless a combination is
written here explicitly.
"""

import argparse
import csv
import io
import os
import statistics
import sys
import zipfile

GRIDIRON_35 = ['ACC', 'AGI', 'AWR', 'BCV', 'BSH', 'BTK', 'CAR', 'CIT', 'CTH', 'ELU', 'FMV', 'IBL',
               'INJ', 'JMP', 'KAC', 'KPW', 'MCV', 'PBK', 'PMV', 'POW', 'PRC', 'PRS', 'PUR', 'RBK',
               'RET', 'RTE', 'SPC', 'SPD', 'STA', 'STR', 'TAK', 'THA', 'THP', 'TRK', 'ZCV']

# source column -> (target, relation, basis, caveat)
MAP = {
    'OVR': ('', 'none', 'publisher overall; Gridiron OVR is its own league percentile',
            'comparison target only, never an input feature'),
    'SPEED': ('SPD', 'renamed', 'Gridiron SPD is the 40-yard-dash curve (RATINGS.md)',
              'EA speed rating, not measured velocity; do not treat as tracking data'),
    'ACC': ('ACC', 'exact', 'Gridiron ACC from 10-yard time (RATINGS.md)', ''),
    'AGI': ('AGI', 'exact', 'Gridiron AGI from 3-cone and shuttle (RATINGS.md)', ''),
    'COD': ('', 'candidate', 'change of direction is distinct from agility',
            'not mapped to AGI: would conflate two source measurements'),
    'STR': ('STR', 'exact', 'Gridiron STR from bench reps (RATINGS.md)', ''),
    'JMP': ('JMP', 'exact', 'Gridiron JMP from vertical (RATINGS.md)', ''),
    'STA': ('STA', 'exact', 'stamina, same name in Gridiron target list', 'meaning not checked against a glossary'),
    'INJ': ('INJ', 'exact', 'Madden INJ is an injury-resistance rating',
            'durability rating, NOT a current injury status; never use as an injury report'),
    'TGH': ('', 'none', 'toughness, no Gridiron rating', ''),
    'AWR': ('AWR', 'exact', 'Gridiron AWR from experience and playing-time share (RATINGS.md)', ''),
    'PRC': ('PRC', 'exact', 'same name in Gridiron target list', 'meaning not verified against a publisher glossary'),
    'THP': ('THP', 'exact', 'Gridiron THP from air yards and YPA (RATINGS.md)', ''),
    'TAC': ('THA', 'candidate', 'possible overall throw accuracy (QB)',
            'used only if the agreement check against TAS/TAM/TAD passes (see measured block)'),
    'TAS': ('', 'none', 'throw accuracy short', 'not combined into THA without an explicit mapping'),
    'TAM': ('', 'none', 'throw accuracy medium', 'not combined into THA without an explicit mapping'),
    'TAD': ('', 'none', 'throw accuracy deep', 'not combined into THA without an explicit mapping'),
    'PAC': ('', 'none', 'no Gridiron rating', ''),
    'TOR': ('', 'none', 'throw on the run, no Gridiron rating', ''),
    'TUP': ('', 'none', 'throw under pressure, no Gridiron rating', ''),
    'BSK': ('', 'none', 'break sack, no Gridiron rating', ''),
    'CAR': ('CAR', 'exact', 'Gridiron CAR from carries (RATINGS.md)', ''),
    'BTK': ('BTK', 'exact', 'Gridiron BTK from rushing EPA and YPC (RATINGS.md)', ''),
    'TRK': ('TRK', 'exact', 'same name in Gridiron target list', ''),
    'BCV': ('BCV', 'exact', 'Gridiron BCV from rushing EPA (RATINGS.md)', ''),
    'SFA': ('', 'none', 'stiff arm, no Gridiron rating', ''),
    'SPM': ('', 'none', 'spin move, no Gridiron rating', ''),
    'JKM': ('', 'none', 'juke move, no Gridiron rating', ''),
    'CTH': ('CTH', 'exact', 'Gridiron CTH from catches over expected (RATINGS.md)', ''),
    'SPC': ('SPC', 'exact', 'same name in Gridiron target list', ''),
    'CIT': ('CIT', 'exact', 'same name in Gridiron target list', ''),
    'SRR': ('', 'none', 'short route running; route split not combined',
            'RTE is target share in Gridiron; do not average SRR/MRR/DRR into it'),
    'MRR': ('', 'none', 'medium route running; route split not combined', 'see SRR'),
    'DRR': ('', 'none', 'deep route running; route split not combined', 'see SRR'),
    'RLS': ('', 'none', 'release, no Gridiron rating', ''),
    'RBK': ('RBK', 'exact', 'Gridiron RBK from strength and draft capital (RATINGS.md)', ''),
    'RBP': ('', 'none', 'run block power; not combined into RBK', ''),
    'RBF': ('', 'none', 'run block finesse; not combined into RBK', ''),
    'PBK': ('PBK', 'exact', 'Gridiron PBK from strength and draft capital (RATINGS.md)', ''),
    'PBP': ('', 'none', 'pass block power; not combined into PBK', ''),
    'PBF': ('', 'none', 'pass block finesse; not combined into PBK', ''),
    'IBL': ('IBL', 'exact', 'same name in Gridiron target list', ''),
    'LBK': ('', 'none', 'lead block, no Gridiron rating', ''),
    'TAK': ('TAK', 'exact', 'Gridiron TAK from tackles per game (RATINGS.md)', ''),
    'POW': ('POW', 'exact', 'same name in Gridiron target list', 'meaning not verified against a publisher glossary'),
    'PUR': ('PUR', 'exact', 'Gridiron PUR from tackles per game and speed (RATINGS.md)', ''),
    'BSH': ('BSH', 'exact', 'Gridiron BSH from TFL per game (RATINGS.md)', ''),
    'PMV': ('PMV', 'exact', 'Gridiron PMV from sacks and QB hits (RATINGS.md)', ''),
    'FMV': ('FMV', 'exact', 'Gridiron FMV from sacks and QB hits (RATINGS.md)', ''),
    'MCV': ('MCV', 'exact', 'Gridiron MCV from PD and INT per game (RATINGS.md)', ''),
    'ZCV': ('ZCV', 'exact', 'Gridiron ZCV from PD and INT per game (RATINGS.md)', ''),
    'PRS': ('PRS', 'exact', 'same name in Gridiron target list', ''),
    'KPW': ('KPW', 'exact', 'Gridiron KPW from 50+ yard FGs (RATINGS.md)', ''),
    'KAC': ('KAC', 'exact', 'Gridiron KAC from FG% and XP% (RATINGS.md)', ''),
    'KRN': ('RET', 'partial', 'kick return ability is one input to a returner rating',
            'Gridiron RET has no source column; KRN covers kickoff returns only'),
    'RUN': ('', 'none', 'team-page only, meaning not verified', ''),
    'ELU': ('ELU', 'exact', 'Gridiron ELU from rushing EPA and YAC (RATINGS.md)', ''),
    'RR': ('', 'none', 'team-page only, meaning not verified', ''),
    'RTE': ('RTE', 'exact', 'Gridiron RTE from target share (RATINGS.md)',
            'team-page dominated; check presence before use'),
    'THA': ('THA', 'exact', 'Gridiron THA from CPOE and INT rate (RATINGS.md)',
            'team-page only (165 cells in the archive)'),
}


def measured_checks(rows, attrs):
    out = {}
    both = [r for r in rows if r['TAC'] and all(r[a] for a in ('TAS', 'TAM', 'TAD'))]
    if both:
        diffs = [abs(int(r['TAC']) - statistics.mean(int(r[a]) for a in ('TAS', 'TAM', 'TAD'))) for r in both]
        xs = [int(r['TAC']) for r in both]
        ys = [statistics.mean(int(r[a]) for a in ('TAS', 'TAM', 'TAD')) for r in both]
        out['TAC_vs_mean_TAS_TAM_TAD'] = {'rows': len(both),
                                           'mean_abs_diff': round(statistics.mean(diffs), 2),
                                           'pearson': round(statistics.correlation(xs, ys), 3)}
    rr = [r for r in rows if r['RTE'] and all(r[a] for a in ('SRR', 'MRR', 'DRR'))]
    if rr:
        xs = [int(r['RTE']) for r in rr]
        ys = [statistics.mean(int(r[a]) for a in ('SRR', 'MRR', 'DRR')) for r in rr]
        out['RTE_vs_mean_SRR_MRR_DRR'] = {'rows': len(rr), 'pearson': round(statistics.correlation(xs, ys), 3)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zip', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    zf = zipfile.ZipFile(args.zip)
    rows = list(csv.DictReader(io.StringIO(zf.read('out/madden_ratings_long.csv').decode('utf-8'))))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from audit_madden_ratings import IDENTITY  # noqa: E402
    attrs = list(rows[0].keys())[len(IDENTITY):]

    missing_src = [a for a in attrs if a not in MAP]
    extra_src = [a for a in MAP if a not in attrs]
    if missing_src or extra_src:
        print(f'FAIL: source columns unmapped {missing_src}; mapping keys not in archive {extra_src}')
        return 1

    covered = {t for (t, rel, _, _) in MAP.values() if t and rel in ('exact', 'renamed', 'partial')}
    uncovered = [t for t in GRIDIRON_35 if t not in covered]
    print(f'Gridiron targets covered: {len(covered & set(GRIDIRON_35))} of {len(GRIDIRON_35)}; uncovered: {uncovered}')
    if uncovered:
        print('FAIL: Gridiron ratings with no source column')
        return 1

    checks = measured_checks(rows, attrs)
    tac = checks.get('TAC_vs_mean_TAS_TAM_TAD')
    tac_pass = bool(tac and tac['pearson'] >= 0.8 and tac['mean_abs_diff'] <= 5)
    print('measured checks:', checks)
    print(f'TAC -> THA candidate passes agreement check: {tac_pass}')

    out_rows = []
    for a in attrs:
        target, rel, basis, caveat = MAP[a]
        if a == 'TAC':
            rel = 'exact' if tac_pass else 'candidate'
            if tac_pass:
                target = 'THA'
                caveat = (f'{caveat}; agreement check passed on {tac["rows"]} rows, '
                          f'pearson {tac["pearson"]}, mean abs diff {tac["mean_abs_diff"]}')
            else:
                caveat = f'{caveat}; agreement check did not pass'
        present = sum(1 for r in rows if r[a].strip())
        present_releases = sorted({int(r['madden_release']) for r in rows if r[a].strip()})
        out_rows.append({
            'source_column': a,
            'gridiron_rating': target,
            'relation': rel,
            'basis': basis,
            'caveat': caveat,
            'archive_nonblank_cells': present,
            'first_release_present': present_releases[0] if present_releases else '',
            'last_release_present': present_releases[-1] if present_releases else '',
        })
    with open(args.out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f'wrote {args.out} ({len(out_rows)} source columns)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
