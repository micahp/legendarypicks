#!/usr/bin/env python3
"""Write PROVENANCE-2026-10-24.json: the commits, versions, file hashes and output hashes behind the E2 successor packet.

Run it last, after every output it hashes is final. The seed record and envelope are checked against the exact research source
fingerprint; the model_version field is the last committed base for those engine files. The historical pins (the citation-heading fix, the
version-stamp commit, the previous survey's engine commit) are real commits, resolved by name. Writes
docs/evidence/e2-successor/PROVENANCE-2026-10-24.json. Usage: python3 provenance.py
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import versions  # noqa: E402

ROOT = HERE.parents[2]
EV = ROOT / 'docs' / 'evidence' / 'e2-successor'
OUT = EV / 'PROVENANCE-2026-10-24.json'
PREVIOUS_SURVEY_ENGINE = 'c131fda2'  # the engine commit of the survey before this one
CITATION_FIX = '9e830cc0'  # the citation-heading fix on this branch
STAMP_COMMIT = 'bd5f3383'  # the version stamps and traceability commit
GRIDIRON_CONTRACT_SHA = 'ae7b8a304dda480c3708b2543172f3fdc5064b156bf1b25816855acf31bc21b7'

EVIDENCE_SCRIPTS = [
    'legality_check.py', 'survey_legality_300.py', 'seed1_stats_check.py', 'toss_sampling_check.py', 'build_envelope.py',
    'make_seed1_record.py', 'kick_distance_offset.py', 'traceability.py', 'build_clock_baseline.py', 'test_legality.py',
    'test_traceability.py', 'unmodelled_enumeration.py', 'unmodelled_doc.py', 'overtime_rows_check.py', 'try_rates_check.py',
    'shared_v1_residuals.py', 'test_shared_v1_residuals.py', 'survey_doc.py', 'gridiron_adapter_proof.mjs',
    'drive_index_check.py', 'test_drive_index_corpus.py', 'gridiron_population.py', 'mismatch_explain.py',
    'gate_review_request.py', 'provenance.py']
OTHER_SCRIPTS = ['scripts/nfl_sequence/versions.py', 'scripts/nfl_sequence/test_versions.py', 'scripts/bdb/e3_tracking_join.py',
                 'scripts/bdb/tracking_coverage_doc.py']
FROZEN_FIXTURES = ['docs/fixtures/e2/e2-game-seed1.json', 'docs/fixtures/e2/e2-game-envelope-seed1.json',
                   'docs/fixtures/e2/e2-game-seed1.v1.json', 'docs/fixtures/e2/survey-per-seed-300.csv']
DATA_FIXTURES = ['docs/fixtures/e2/kick_results_2022_2025.csv', 'docs/fixtures/e2/play_extras_2022_2025.csv']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args):
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, capture_output=True, text=True).stdout.strip()


def main():
    source = versions.source_snapshot()
    engine_head = source['base_model_version']
    rec = json.loads((EV / 'seed1-game-successor.json').read_text())
    env = json.loads((EV / 'e2-game-envelope-seed1-successor.json').read_text())
    if (rec['model_version'] != engine_head or rec.get('research_source') != source or env['record'] != rec or
            env['source'].get('source_tree_sha256') != source['source_tree_sha256']):
        raise SystemExit('the seed-1 record or its envelope is not the record of the current engine: regenerate them first')
    if rec['valid_full_game'] is not False:
        raise SystemExit('valid_full_game must be false')
    lp_rules_path = 'docs/rules/NFL-2026-GAME-STATE-RULES.md'
    lp_rules_bytes = subprocess.run(['git', '-C', str(ROOT), 'show', f'origin/dev:{lp_rules_path}'],
                                    check=True, capture_output=True).stdout
    prov = {
        'branch': 'feat/nfl-sequence-e2-successor-2026-10-24',
        'frozen_reference_untouched': {'branch': 'feat/nfl-sequence-e2-kickoffs-2026-10-24',
                                       'commit': 'a442dcd72559cfaf2d04737fc2454cea486faf09'},
        'code_commits': {'engine_head': engine_head,
                         'version_stamps_and_matrix': git('rev-parse', STAMP_COMMIT),
                         'citation_heading_fix': git('rev-parse', CITATION_FIX)},
        'previous_survey_engine_commit': git('rev-parse', PREVIOUS_SURVEY_ENGINE),
        'engine_commits_after_previous_survey': git('log', '--oneline', f'{PREVIOUS_SURVEY_ENGINE}..HEAD', '--',
                                                    *versions.ENGINE_FILES),
        'model_version': {'value': rec['model_version'], 'meaning': 'most recent commit changing an ENGINE_FILES file'},
        'research_source': source,
        'rules_version': {'value': rec['rules_version'], 'meaning': 'SHA-256 of the RULE_FILES producer map (VERSION-DEFINITIONS)'},
        'valid_full_game': rec['valid_full_game'],
        'envelope': {'contract': env['contract'], 'base_commit': env['source']['base_commit'],
                     'producer_file_sha256': env['source']['producer_file_sha256']},
        'gridiron_contract': {'file': 'docs/GRIDIRON-CONTRACT-v1.md', 'sha256': sha(ROOT / 'docs' / 'GRIDIRON-CONTRACT-v1.md'),
                              'expected': GRIDIRON_CONTRACT_SHA},
        'gridiron_heads': {'de64ae12': 'de64ae12486171bbe5114323ba45db5fcc21d23a',
                           '13b18faa': '13b18faa9d9dbe78570df7d45636f2313f25d8ea',
                           'origin/main': '72c7a7471b266ffcf8d187c651758bb1719129de'},
        'gridiron_unmerged_followup': {'branch': 'origin/fix/week7-game-state-rules',
                                       'commit': 'c32e453d8637ac1350d0435a6255b65ccbfdd344',
                                       'base_common_commit_with_main': '967a40cffd21f83b0e9901c9d4fd9cf6891e7df5',
                                       'adapter_in_checkout': False,
                                       'merged_into_main': False},
        'lp_rules_reference': {'repository': 'micahp/legendarypicks', 'ref': 'origin/dev',
                               'origin_dev_head': git('rev-parse', 'origin/dev'), 'path': lp_rules_path,
                               'git_blob': git('rev-parse', f'origin/dev:{lp_rules_path}'),
                               'sha256': hashlib.sha256(lp_rules_bytes).hexdigest(),
                               'url': 'https://github.com/micahp/legendarypicks/blob/dev/docs/rules/NFL-2026-GAME-STATE-RULES.md'},
        'engine_and_rule_file_sha256': {f: sha(ROOT / f) for f in sorted(set(versions.ENGINE_FILES) | set(versions.RULE_FILES))},
        'evidence_script_sha256': {'scripts/nfl_sequence/evidence_e2/' + n: sha(HERE / n) for n in EVIDENCE_SCRIPTS}
        | {f: sha(ROOT / f) for f in OTHER_SCRIPTS},
        'frozen_fixture_sha256': {p: sha(ROOT / p) for p in FROZEN_FIXTURES},
        'data_fixture_sha256': {p: sha(ROOT / p) for p in DATA_FIXTURES},
        'outputs_sha256': {p.name: sha(p) for p in sorted(EV.iterdir()) if p.is_file() and p.name != OUT.name},
    }
    if prov['gridiron_contract']['sha256'] != GRIDIRON_CONTRACT_SHA:
        raise SystemExit('GRIDIRON-CONTRACT-v1.md is not byte-identical to the pinned contract')
    OUT.write_text(json.dumps(prov, indent=1, sort_keys=True) + '\n')
    print(f"provenance written: engine {engine_head[:12]}, rules {rec['rules_version'][:12]}, "
          f"{len(prov['outputs_sha256'])} outputs hashed")


if __name__ == '__main__':
    main()
