"""Entry point for `python -m audit_league_stats`.

The 2026-08-18 split turned `audit_league_stats.py` into this package, and the
`if __name__ == "__main__"` block in `__init__.py` does not fire for `-m` --
that form imports the package and then looks for `__main__`, which did not
exist. So every shell caller kept invoking `backend/audit_league_stats.py`, a
path that no longer resolves, and the two that matter both swallowed it:

  scripts/release.sh   guarded the whole audit behind `[ -f ...py ]`, so the
                       release preflight's stats audit was SKIPPED, silently.
  verify-gates.sh      read python's exit 2 ("can't open file") as 2 audit
                       failures against a known 21, which reads as progress.

A missing runner must not look like a clean audit. This file exists so the
runner is reachable again; the callers were moved to `-m` alongside it.
"""
import sys

from .cli import main

sys.exit(main())
