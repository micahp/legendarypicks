"""Check that the context-managed playbook_prior.py loads the same table as its parent commit.

Loads the parent (adbb5b22^) and current versions of scripts/nfl_sequence/playbook_prior.py, calls load() for each
cutoff, and compares the pickled outputs. Reads only the playbook files that load() already reads (seasons before each
cutoff). Run from the repository root: python3 docs/research/playcall-m3-freeze-amendment-1-2026-11-02/check_playbook_prior_equivalence.py
"""
import hashlib
import importlib.util
import pickle
import subprocess
import sys
import tempfile

SEQ = 'scripts/nfl_sequence'
CHANGE = 'adbb5b22'
CUTOFFS = (2023, 2024, 2025)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parent = subprocess.run(['git', 'show', f'{CHANGE}^:{SEQ}/playbook_prior.py'], check=True, capture_output=True).stdout
    sys.path.insert(0, SEQ)
    with tempfile.NamedTemporaryFile('wb', suffix='.py', delete=False) as handle:
        handle.write(parent)
        parent_path = handle.name
    new = load_module('playbook_prior_current', f'{SEQ}/playbook_prior.py')
    old = load_module('playbook_prior_parent', parent_path)
    for cutoff in CUTOFFS:
        a = pickle.dumps(new.load(cutoff))
        b = pickle.dumps(old.load(cutoff))
        print(cutoff, 'identical' if a == b else 'DIFFERENT', hashlib.sha256(a).hexdigest()[:16], hashlib.sha256(b).hexdigest()[:16])


if __name__ == '__main__':
    main()
