#!/usr/bin/env python3
"""SLC-CEG Phase 1b: charting, participation and snap counts as separate source tables (research). Read-only on inputs.

Three sources stay distinct; nothing is inferred from one to another (a backfield count is not a personnel grouping):

  charting       FTN charting (nflverse ftn_charting), 2022-2026, keyed by (game_id, play_id).
  participation  nflverse pbp_participation, 2022-2025 (no 2026 file is published), keyed by (game_id, play_id).
  snap_counts    nflverse snap_counts, 2022-2026, one row per player and game (pfr_player_id; not joined to gsis here).

A play with no FTN row has every FTN field unknown, never False. Inside FTN, a boolean is a charted value.

Timing of each FTN field, in the generated event sequence (see FTN_TIMING): pre_snap_state, offense_pre_snap,
defense_pre_snap, play_design (chosen before the snap, revealed during the play), defense_execution, qb_execution,
outcome_label. A simulator can condition on a field only after it has generated it; outcome labels are never inputs.

Audits written to the doc folder (charting_audit.json): coverage by season, join cardinality, unmatched rows, label
values by season, throwaway against pass attempts / incompletions / targets / the no_attempt population, and shotgun and
no-huddle agreement with the play-by-play.

Usage: python3 ceg_charting.py --raw DIR --tables DIR --doc-dir DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

SEASONS = (2022, 2023, 2024, 2025, 2026)
KEY = ['game_id', 'play_id']
FTN_TIMING = {
    'starting_hash': 'pre_snap_state', 'qb_location': 'offense_pre_snap', 'n_offense_backfield': 'offense_pre_snap',
    'is_no_huddle': 'offense_pre_snap', 'is_motion': 'offense_pre_snap', 'n_defense_box': 'defense_pre_snap',
    'is_play_action': 'play_design', 'is_rpo': 'play_design', 'is_screen_pass': 'play_design',
    'is_trick_play': 'play_design', 'is_qb_sneak': 'play_design',
    'n_blitzers': 'defense_execution', 'n_pass_rushers': 'defense_execution',
    'is_qb_out_of_pocket': 'qb_execution', 'is_throw_away': 'qb_execution', 'read_thrown': 'qb_execution',
    'is_interception_worthy': 'outcome_label', 'is_catchable_ball': 'outcome_label', 'is_contested_ball': 'outcome_label',
    'is_drop': 'outcome_label', 'is_created_reception': 'outcome_label', 'is_qb_fault_sack': 'outcome_label',
}
SCRIMMAGE = ('designed_run', 'dropback', 'scramble', 'kneel', 'spike')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_ftn(raw):
    frames, inputs = [], {}
    for season in SEASONS:
        path = raw / f'ftn_charting_{season}.parquet'
        inputs[path.name] = sha256(path)
        f = pd.read_parquet(path).rename(columns={'nflverse_game_id': 'game_id', 'nflverse_play_id': 'play_id'})
        f['ftn_source_file'] = path.name
        frames.append(f)
    f = pd.concat(frames, ignore_index=True)
    f['play_id'] = f['play_id'].astype('int64')
    loc = f['qb_location'].astype('string').str.strip()
    f['qb_location_raw'] = f['qb_location']
    f['qb_location'] = loc.where(loc.isin(['S', 'U', 'P']))  # '0' (2023+) and null (2022) mean not charted as a snap
    return f, inputs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--raw', required=True, type=Path)
    ap.add_argument('--tables', required=True, type=Path)
    ap.add_argument('--doc-dir', required=True, type=Path)
    args = ap.parse_args(argv)
    ftn, inputs = load_ftn(args.raw)
    labels = pd.read_parquet(args.tables / 'labels.parquet',
                             columns=KEY + ['season', 'week', 'season_type', 'play_class', 'dropback_outcome', 'pass_attempt',
                                            'incomplete_pass', 'complete_pass', 'interception', 'sack', 'shotgun',
                                            'no_huddle', 'penalty'])
    people = pd.read_parquet(args.tables / 'people.parquet', columns=KEY + ['receiver_player_id'])
    lab = labels.merge(people, on=KEY)
    audit = {'coverage': {}, 'join': {}, 'labels_by_season': {}, 'throwaway': {}, 'agreement': {}}

    # join cardinality
    dup = ftn.duplicated(KEY, keep=False)
    keys = ftn.drop_duplicates(KEY)
    joined = lab.merge(keys[KEY].assign(_ftn=True), on=KEY, how='left')
    joined['_ftn'] = joined['_ftn'].fillna(False).astype(bool)
    unmatched_ftn = keys.merge(lab[KEY], on=KEY, how='left', indicator=True)
    audit['join'] = {'ftn_rows': int(len(ftn)), 'ftn_duplicate_key_rows': int(dup.sum()),
                     'ftn_keys_not_in_pbp': int(unmatched_ftn['_merge'].eq('left_only').sum())}
    for season in SEASONS:
        j = joined[joined.season.eq(season)]
        sc = j[j.play_class.isin(SCRIMMAGE)]
        weeks_missing = sorted(int(w) for w, g in sc.groupby('week') if not g._ftn.any())
        audit['coverage'][season] = {
            'scrimmage_snaps': int(len(sc)), 'scrimmage_snaps_with_ftn': int(sc._ftn.sum()),
            'share': round(float(sc._ftn.mean()), 4), 'weeks_with_no_ftn': weeks_missing,
            'by_class': {c: [int(g._ftn.sum()), int(len(g))] for c, g in sc.groupby('play_class')},
            'games_with_ftn': int(ftn[ftn.season.eq(season)].game_id.nunique()),
            'games_in_pbp': int(j.game_id.nunique())}
        f = ftn[ftn.season.eq(season)]
        audit['labels_by_season'][season] = {
            'qb_location_raw': {str(k): int(v) for k, v in f.qb_location_raw.value_counts(dropna=False).items()},
            **{c: {str(k): int(v) for k, v in f[c].value_counts(dropna=False).head(8).items()}
               for c in ('n_offense_backfield', 'n_defense_box', 'n_pass_rushers', 'n_blitzers', 'read_thrown')}}

    # throwaway reconciliation, on dropbacks with an FTN row
    m = lab.merge(ftn.drop_duplicates(KEY)[KEY + ['is_throw_away', 'qb_location', 'is_no_huddle']], on=KEY, how='inner')
    db = m[m.play_class.isin(['dropback', 'scramble'])]
    ta = db[db.is_throw_away.eq(True)]
    audit['throwaway'] = {
        'dropbacks_with_ftn': int(len(db)), 'throwaways': int(len(ta)),
        'throwaway_by_dropback_outcome': {str(k): int(v) for k, v in ta.dropback_outcome.value_counts(dropna=False).items()},
        'throwaway_with_pass_attempt': int(ta.pass_attempt.eq(1).sum()),
        'throwaway_incomplete': int(ta.incomplete_pass.eq(1).sum()),
        'throwaway_with_receiver_id': int(ta.receiver_player_id.notna().sum()),
        'throwaway_with_penalty': int(ta.penalty.eq(1).sum()),
        'incompletions_with_ftn': int(db.incomplete_pass.eq(1).sum()),
        'incompletions_that_are_throwaways': int((db.incomplete_pass.eq(1) & db.is_throw_away.eq(True)).sum()),
        'no_attempt_dropbacks_with_ftn': int(db.dropback_outcome.eq('no_attempt').sum()),
        'no_attempt_that_are_throwaways': int((db.dropback_outcome.eq('no_attempt') & db.is_throw_away.eq(True)).sum()),
        'by_season': {int(s): int(g.is_throw_away.eq(True).sum()) for s, g in db.groupby('season')}}

    # shotgun and no-huddle agreement with the play-by-play, on scrimmage snaps with both labels
    sc = m[m.play_class.isin(SCRIMMAGE) & m.qb_location.notna() & m.shotgun.notna()]
    xt = pd.crosstab(sc.qb_location, sc.shotgun)
    audit['agreement']['shotgun'] = {
        'plays': int(len(sc)), 'crosstab_ftn_qb_location_by_pbp_shotgun': {k: {str(int(c)): int(v) for c, v in row.items()}
                                                                          for k, row in xt.iterrows()},
        'agree_shotgun_equals_S': round(float(((sc.qb_location == 'S') == sc.shotgun.eq(1)).mean()), 4),
        'agree_shotgun_equals_S_or_P': round(float((sc.qb_location.isin(['S', 'P']) == sc.shotgun.eq(1)).mean()), 4)}
    nh = m[m.play_class.isin(SCRIMMAGE) & m.is_no_huddle.notna() & m.no_huddle.notna()]
    audit['agreement']['no_huddle'] = {
        'plays': int(len(nh)), 'agree': round(float((nh.is_no_huddle.astype(bool) == nh.no_huddle.eq(1)).mean()), 4),
        'ftn_true_pbp_false': int((nh.is_no_huddle.astype(bool) & nh.no_huddle.ne(1)).sum()),
        'ftn_false_pbp_true': int((~nh.is_no_huddle.astype(bool) & nh.no_huddle.eq(1)).sum())}

    # write the three source tables
    out = {}
    charting = ftn.drop_duplicates(KEY)
    path = args.tables / 'charting.parquet'
    charting.to_parquet(path, index=False)
    out['charting'] = (charting, path)
    parts = []
    for season in (2022, 2023, 2024, 2025):
        p = args.raw / f'pbp_participation_{season}.parquet'
        inputs[p.name] = sha256(p)
        d = pd.read_parquet(p).rename(columns={'nflverse_game_id': 'game_id'})
        d['season'] = season
        d['participation_source_file'] = p.name
        parts.append(d)
    part = pd.concat(parts, ignore_index=True)
    part['play_id'] = part['play_id'].astype('int64')
    path = args.tables / 'participation.parquet'
    part.to_parquet(path, index=False)
    out['participation'] = (part, path)
    snaps = []
    for season in SEASONS:
        p = args.raw / f'snap_counts_{season}.parquet'
        inputs[p.name] = sha256(p)
        snaps.append(pd.read_parquet(p).assign(snap_source_file=p.name))
    snap = pd.concat(snaps, ignore_index=True)
    path = args.tables / 'snap_counts.parquet'
    snap.to_parquet(path, index=False)
    out['snap_counts'] = (snap, path)
    pj = lab[lab.play_class.isin(SCRIMMAGE)].merge(part[KEY].drop_duplicates().assign(_p=True), on=KEY, how='left')
    audit['participation_coverage'] = {int(s): [int(g._p.notna().sum()), int(len(g))] for s, g in pj.groupby('season')}
    audit['snap_counts_coverage'] = {int(s): {'rows': int(len(g)), 'games': int(g.game_id.nunique()),
                                              'max_week': int(g.week.max())} for s, g in snap.groupby('season')}

    # manifest and schema registry updates
    man_path, reg_path = args.doc_dir / 'phase1_manifest.json', args.doc_dir / 'schema_registry.json'
    manifest, registry = json.loads(man_path.read_text()), json.loads(reg_path.read_text())
    manifest['inputs'].update(inputs)
    for name, (table, p) in out.items():
        key_cols = KEY if name != 'snap_counts' else ['game_id', 'pfr_player_id']
        manifest['tables'][name] = {'rows': int(len(table)), 'duplicate_keys': int(table.duplicated(key_cols).sum()),
                                    'sha256': sha256(p), 'path': str(p), 'key': key_cols}
        timing = FTN_TIMING if name == 'charting' else {}
        registry[name] = {'key': key_cols, 'source': {'charting': 'nflverse ftn_charting', 'participation':
                                                      'nflverse pbp_participation', 'snap_counts': 'nflverse snap_counts'}[name],
                          'columns': {c: {'dtype': str(table[c].dtype),
                                          'timing': timing.get(c, 'key' if c in key_cols else
                                                               ('provenance' if c.endswith(('source_file', 'date_pulled'))
                                                                else 'source_field'))}
                                      for c in table.columns}}
    manifest['gaps'] = [g for g in manifest['gaps'] if not g.startswith('pbp_participation has no 2026')] + [
        'personnel groupings, offense formation and coverage per play: nflverse pbp_participation and our '
        'nfl_hist_participation end at 2025; not published for 2026',
        f"FTN charting 2026: weeks with no FTN row {audit['coverage'][2026]['weeks_with_no_ftn']} (not pulled yet on "
        "2026-11-24); those plays have every FTN field unknown, never False"]
    (args.doc_dir / 'charting_audit.json').write_text(json.dumps(audit, indent=1, sort_keys=True) + '\n')
    man_path.write_text(json.dumps(manifest, indent=1, sort_keys=True, default=str) + '\n')
    reg_path.write_text(json.dumps(registry, indent=1, sort_keys=True) + '\n')
    print(json.dumps({k: audit[k] for k in ('join', 'throwaway', 'agreement')}, indent=1))
    print({s: (c['share'], c['weeks_with_no_ftn']) for s, c in audit['coverage'].items()})
    print('participation', audit['participation_coverage'], 'snaps', audit['snap_counts_coverage'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
