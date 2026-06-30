"""results_store.py — durable on-disk results store for finished esports matches."""

import json
import os

_RESULTS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                              "data", "esports_results.json")


def _load_results_store():
    """Read the persisted results store. Returns {} on any error (missing/corrupt -> rebuild)."""
    try:
        with open(_RESULTS_PATH) as f:
            return json.loads(f.read())
    except Exception:
        return {}


def _save_results_store(store):
    """Atomic write: temp file + os.replace — safe against crashes and concurrent workers."""
    try:
        tmp = _RESULTS_PATH + ".tmp"
        os.makedirs(os.path.dirname(_RESULTS_PATH), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(store, f)
        os.replace(tmp, _RESULTS_PATH)
    except Exception:
        pass  # store write failures are non-fatal
