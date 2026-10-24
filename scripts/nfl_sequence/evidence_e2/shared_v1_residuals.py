#!/usr/bin/env python3
"""Blocker 7: the remaining shared-v1 contract violations of the successor seed-1 document, each traced to why the producer
cannot source it. The contract (shared_v1.py) is not changed, and no value is invented to clear a violation.

The check must report exactly the expected set, and nothing else. Any other violation, or a missing one, fails the build.
Writes docs/evidence/e2-successor/shared-v1-residuals.json. Usage: python3 shared_v1_residuals.py
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

# Each residual, and why this producer cannot source it from the data on the box.
EXPECTED = {
    'V-mode': 'the record is a sampled legal game state, not a pregame full-game snapshot; the contract mode is pregame_full_game',
    'V-unresolved-game_id': 'the record is a sampled game with no scheduled game key; no game identity is attached to a sampled play',
    'V-unresolved-scheduled_kickoff_utc': 'no scheduled kickoff time: the record is retrospective, not a pregame simulation',
    'V-unresolved-as_of_utc': 'no as-of time: the sampled plays are 2022-2025 outcomes with no pregame cutoff',
    'V-unresolved-snapshot_hash': 'no pregame snapshot exists for a sampled game, so there is nothing to hash',
    'V-unresolved-roster_snapshot_id': 'no roster or lineup snapshot: participants are the sampled observed plays\' players',
    'V-duration-seconds': ('the published play-by-play has no play duration; the tracking in-play time exists only for the '
                           '15,768 verified plays, not for the sampled plays the engine draws'),
}


def main():
    record = json.loads(RECORD.read_text())
    doc = sv.build_document(record)
    found = sv.check_document(doc)
    ids = {v['id'] for v in found}
    if ids != set(EXPECTED):
        raise SystemExit(f'violations differ from the expected residuals: unexpected {sorted(ids - set(EXPECTED))}, '
                         f'missing {sorted(set(EXPECTED) - ids)}')
    out = {
        'record': {'file': 'docs/evidence/e2-successor/seed1-game-successor.json',
                   'sha256': hashlib.sha256(RECORD.read_bytes()).hexdigest(),
                   'model_version': record['model_version'], 'rules_version': record['rules_version']},
        'contract': 'shared_v1.py, unchanged in this revision',
        'count': len(ids),
        'residuals': [{'id': v['id'], 'message': v.get('message', ''), 'why_not_sourced': EXPECTED[v['id']]}
                      for v in sorted(found, key=lambda v: v['id'])],
        'valid_full_game': record['valid_full_game'],
        'closed_as': ('documented residual: each violation is traced to its source and is not cleared by an invented value. '
                      'The document is not pregame_full_game conformant, and valid_full_game stays false.'),
    }
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    print(f"{len(ids)} residuals, exactly the expected set; valid_full_game {record['valid_full_game']}")


if __name__ == '__main__':
    main()
