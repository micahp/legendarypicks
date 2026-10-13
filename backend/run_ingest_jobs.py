#!/usr/bin/env python3
"""run_ingest_jobs.py: run the ingest_registry jobs, DEV then PROD, through one engine.

This is a thin entry point on purpose. Everything hard (the durable `ingest_runs` ledger,
`ingest_provider_state.last_ok_at` per job and database, cadence skipping, per-host locks
and the per-database run lock) lives in `run_props_ingest.main`, and this passes
`ingest_registry.JOBS` through it rather than reimplementing any of it. Two registries, one
engine: a second engine would drift from the first, and the drift would be invisible.

Usage mirrors the props runner:

    LP_DB_PATH=.../picks.dev.db venv/bin/python run_ingest_jobs.py --list
    LP_DB_PATH=.../picks.dev.db venv/bin/python run_ingest_jobs.py --only soccer_logs --dry-run
    LP_DB_PATH=.../picks.db     venv/bin/python run_ingest_jobs.py

Exit codes are the engine's: 0 when a job succeeded or was skipped for cadence, 1 when a job
failed or a host lock was held by an unexpected caller, 2 on a bad LP_DB_PATH.
"""
import sys
from typing import Optional, Sequence

import ingest_registry
import run_props_ingest


def main(argv: Optional[Sequence[str]] = None) -> int:
    # Re-validated here as well as at import: this is the process that would otherwise run
    # work nobody can verify, so it should refuse to start rather than run half a registry.
    ingest_registry.validate()
    return run_props_ingest.main(argv, registry=ingest_registry.JOBS, label="ingest jobs")


if __name__ == "__main__":
    sys.exit(main())
