"""Paired rules-only check: run the pinned validity cohort with the reference fingerprint pinned to a saved one.

The saved fingerprint comes from an earlier commit (docs/evidence/e2-overtime/teamfix-model-inputs.json for 1260efd8).
Only the engine rules differ from that run, so any seed that changes is attributable to the rule change.

Extra arguments are passed to run_pinned_validity.py, for example --overtime-choice receive for a paired decision control.

Usage: python3 run_paired_rules_check.py REPO_ROOT SAVED_MODEL_INPUTS.json OUT.csv OUT.json [extra run_pinned_validity args]
"""
import json, sys
from pathlib import Path
REPO = Path(sys.argv[1])
sys.path.insert(0, str(REPO / 'scripts/nfl_sequence'))
import e2_reference as er
import run_pinned_validity as rpv
SAVED = json.load(open(sys.argv[2]))
orig_load = er.load
def pinned_load(*a, **k):
    ref, excluded = orig_load(*a, **k)
    ref.model_inputs = SAVED  # the team-label-fix fingerprint: only the rules differ from that run
    return ref, excluded
er.load = pinned_load
sys.argv = ['run_pinned_validity.py', '--policy', 'unconditional', '--out', sys.argv[3], '--summary', sys.argv[4]] + sys.argv[5:]
rpv.main()
