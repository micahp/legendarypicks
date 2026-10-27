"""The identity blockers the last published-rosters run recorded, for the API health check.

The roster job prints `identity_blockers=N` into its stored output on every applied run. Reading that line back means
the health check reports what the job already decided, and does not recompute identities on a polled endpoint.
"""
from __future__ import annotations

import re

_COUNT = re.compile(r"identity_blockers=(\d+)")


def last_run(con):
    """(blockers, checked_at) from the latest published-rosters run.

    (None, None) when no run is recorded. (None, checked_at) when the latest run printed no count.
    """
    row = con.execute(
        "SELECT finished_at, detail FROM ingest_runs WHERE provider='published_rosters' "
        "ORDER BY finished_at DESC LIMIT 1").fetchone()
    if row is None:
        return None, None
    match = _COUNT.search(row[1] or "")
    return (int(match.group(1)) if match else None), row[0]
