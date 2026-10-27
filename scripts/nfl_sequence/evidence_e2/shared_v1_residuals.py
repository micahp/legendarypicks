#!/usr/bin/env python3
"""Blocker 7: every remaining shared-v1 residual of the successor seed-1 document, each with its guard.

Nine residuals. Seven come from shared_v1.check_document (the LP contract check). Two come from Gridiron's adapter audit, which
reports them and LP's check does not: the team identities and the valid_full_game claim. Each residual is either fixed or
guarded. None is fixed here, because the data on the box cannot source it and the contract is not changed. Each guard is a test
(test_shared_v1_residuals.py) that fails if the guard stops firing. Writes docs/evidence/e2-successor/shared-v1-residuals.json.
Usage: python3 shared_v1_residuals.py
"""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import shared_v1 as sv  # noqa: E402

ROOT = HERE.parents[2]
RECORD = ROOT / 'docs' / 'evidence' / 'e2-successor' / 'seed1-game-successor.json'
OUT = ROOT / 'docs' / 'evidence' / 'e2-successor' / 'shared-v1-residuals.json'

LP_CHECK = {
    'V-mode': ('the record is a sampled legal game state, not a pregame full-game snapshot; the contract mode is pregame_full_game',
               'Gridiron: "mode is not pregame_full_game"'),
    'V-unresolved-game_id': ('a sampled game has no scheduled game key; no game identity is attached to a sampled play',
                             'Gridiron: "missing stable game_id"'),
    'V-unresolved-scheduled_kickoff_utc': ('no scheduled kickoff: the record is retrospective, not a pregame simulation',
                                           'Gridiron: "missing or invalid top-level as_of_utc before scheduled_kickoff_utc"'),
    'V-unresolved-as_of_utc': ('no as-of time: the sampled plays are 2022-2025 outcomes with no pregame cutoff',
                               'Gridiron: "missing or invalid top-level as_of_utc before scheduled_kickoff_utc"'),
    'V-unresolved-snapshot_hash': ('no pregame snapshot exists for a sampled game, so there is nothing to hash', None),
    'V-unresolved-roster_snapshot_id': ('no roster or lineup snapshot: participants are the sampled observed plays\' players',
                                        'Gridiron: "missing eligible roster snapshot"'),
    'V-duration-seconds': ('the published play-by-play has no play duration; tracking in-play time exists only for the 15,768 '
                           'verified plays, not for the sampled plays the engine draws', None),
}
GRIDIRON_ONLY = {
    'V-teams-unresolved': ('the home and away teams are authored labels A and B; no real identity is sampled',
                           'Gridiron: "missing real home/away team identities"'),
    'V-valid-full-game': ('valid_full_game is false: this legal_game_state_first_piece record is not a pregame_full_game; '
                          'unresolved contract inputs and unsupported transitions prevent certification',
                          'Gridiron: "record.valid_full_game is not true"'),
}
EXPECTED = {**{k: v[0] for k, v in LP_CHECK.items()}, **{k: v[0] for k, v in GRIDIRON_ONLY.items()}}
GUARD_TESTS = {
    'V-mode': 'test_shared_v1_residuals.Guards.test_mode_guard_fires',
    'V-unresolved-game_id': 'test_shared_v1_residuals.Guards.test_game_id_guard_fires',
    'V-unresolved-scheduled_kickoff_utc': 'test_shared_v1_residuals.Guards.test_kickoff_guard_fires',
    'V-unresolved-as_of_utc': 'test_shared_v1_residuals.Guards.test_as_of_guard_fires',
    'V-unresolved-snapshot_hash': 'test_shared_v1_residuals.Guards.test_snapshot_guard_fires',
    'V-unresolved-roster_snapshot_id': 'test_shared_v1_residuals.Guards.test_roster_guard_fires',
    'V-duration-seconds': 'test_shared_v1_residuals.Guards.test_duration_guard_fires',
    'V-teams-unresolved': 'test_shared_v1_residuals.Guards.test_teams_guard_fires',
    'V-valid-full-game': 'test_shared_v1_residuals.Guards.test_valid_guard_fires',
}


def residual_ids(doc, record):
    """The residual IDs this document shows: the LP contract violations, plus the two guards only Gridiron's audit reports."""
    ids = {v['id'] for v in sv.check_document(doc)}
    if record.get('team_identity_source') is None:  # a sampled record has no source for a real team identity
        ids.add('V-teams-unresolved')
    if record['valid_full_game'] is False:
        ids.add('V-valid-full-game')
    return ids


def main():
    record = json.loads(RECORD.read_text())
    doc = sv.build_document(record)
    ids = residual_ids(doc, record)
    if ids != set(EXPECTED):
        raise SystemExit(f'residuals differ from the expected nine: unexpected {sorted(ids - set(EXPECTED))}, '
                         f'missing {sorted(set(EXPECTED) - ids)}')
    out = {
        'record': {'file': 'docs/evidence/e2-successor/seed1-game-successor.json',
                   'sha256': hashlib.sha256(RECORD.read_bytes()).hexdigest(),
                   'model_version': record['model_version'], 'rules_version': record['rules_version']},
        'contract': 'shared_v1.py, unchanged in this revision',
        'count': len(ids),
        'residuals': [{'id': k, 'why_not_sourced': EXPECTED[k], 'source': 'shared_v1.check_document' if k in LP_CHECK else
                       'gridiron adapter audit (no LP check)',
                       'gridiron_text': (LP_CHECK.get(k) or GRIDIRON_ONLY.get(k))[1],
                       'guard_test': GUARD_TESTS[k], 'fixed': False} for k in sorted(EXPECTED)],
        'valid_full_game': record['valid_full_game'],
        'closed_as': ('documented residuals with guards. Each is traced to its source. None is cleared by an invented value or by a '
                      'change to the contract. The document is not pregame_full_game conformant, and valid_full_game stays false.'),
    }
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    print(f"{len(ids)} residuals, exactly the expected nine; valid_full_game {record['valid_full_game']}")


if __name__ == '__main__':
    main()
