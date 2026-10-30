"""The two version fields every E2 game record carries, defined once here. The definitions are in
docs/evidence/e2-successor/VERSION-DEFINITIONS-2026-10-24.md.

model_version is the commit of the engine that produced the record: the most recent commit that changed an ENGINE_FILES
file. The producing tree must be clean for those files, so the value names code that exists and was run. Evidence-only
commits do not change it.

rules_version is the SHA-256 of the canonical JSON of the rule-bearing producer files' SHA-256 map (RULE_FILES). It is the
scoped id the Gridiron envelope already pins under source.producer_file_sha256. It hashes files, not the envelope, because
the envelope contains the record.

The engine itself does not stamp its records: a commit cannot contain its own SHA. The producer calls stamp() on a clean tree.

Research evidence can be generated from an uncommitted tree only through research_stamp(). Its model_version remains the base
engine commit, while research_source records the exact hashes of the current engine and rule files. Release stamping remains
fail-closed and requires a clean source tree.
"""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULE_FILES = ('scripts/nfl_sequence/game_state.py', 'scripts/nfl_sequence/rules_matrix.py',
              'scripts/nfl_sequence/e1_drive.py', 'scripts/nfl_sequence/shared_v1.py')
ENGINE_FILES = ('scripts/nfl_sequence/game_state.py', 'scripts/nfl_sequence/e1_drive.py',
                'scripts/nfl_sequence/e2_reference.py', 'scripts/nfl_sequence/e0_single_play.py',
                'scripts/nfl_sequence/clock_d.py',
                'scripts/nfl_sequence/paired_random_streams.py')


def _git(*args):
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, capture_output=True, text=True).stdout.strip()


def file_hashes(paths=RULE_FILES):
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}


def rules_version(hashes=None):
    hashes = file_hashes() if hashes is None else hashes
    return hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def assert_clean(paths):
    dirty = _git('status', '--porcelain', '--', *paths)
    if dirty:
        raise RuntimeError(f'uncommitted changes to producing files, so no version can be stamped: {dirty}')


def model_version():
    assert_clean(ENGINE_FILES)
    return _git('log', '-1', '--format=%H', '--', *ENGINE_FILES)


def source_snapshot():
    """The exact research source tree, including dirty engine/rule files, plus its last committed engine base."""
    paths = tuple(sorted(set(ENGINE_FILES) | set(RULE_FILES)))
    hashes = file_hashes(paths)
    return {
        'base_model_version': _git('log', '-1', '--format=%H', '--', *ENGINE_FILES),
        'source_file_sha256': hashes,
        'source_tree_sha256': hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        'producer_file_sha256': file_hashes(RULE_FILES),
        'producer_worktree_dirty': bool(_git('status', '--porcelain', '--', *paths)),
    }


def research_stamp(record, source=None):
    """Stamp a research record with its base commit and exact source-tree fingerprint, even when source files are dirty."""
    source = source_snapshot() if source is None else source
    return {
        **record,
        'model_version': source['base_model_version'],
        'rules_version': rules_version(source['producer_file_sha256']),
        'research_source': source,
    }


def stamp(record):
    """The record with model_version and rules_version set. Refuses when the producing tree is dirty."""
    assert_clean(ENGINE_FILES + RULE_FILES)
    return {**record, 'model_version': model_version(), 'rules_version': rules_version()}
