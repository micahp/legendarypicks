"""audit_league_stats — league stats audit (package).

Split from the former single-file audit_league_stats.py (2026-08-18)
into modules by concern: identity (name/position vocabulary), checks
(the per-league audit checks), cli (audit runner / main).

The package exposes the same external surface the module did. Callers
that did `import audit_league_stats as audit` and used `audit.audit`,
`audit.check_position_content`, `audit.main`, `audit.PASS` /
`audit.FAIL` / `audit.UNVERIFIED` / `audit.Result`, or imported
`_identity_name_key` directly, keep working unchanged.
"""
import sys

from .identity import (  # noqa: F401
    _IDENTITY_NAMES_PATH, _IDENTITY_NAMES_CACHE, _identity_name_key,
    _published_identity_names, _observed_positions,
    _declares_group_column, _position_vocabulary, _VOCABULARY_PATH,
    _VOCABULARY_CACHE, _columns,
)
from .checks import (  # noqa: F401
    _POSITION_CONTENT_FLOOR, check_required_stats, check_position_content,
    check_single_vocabulary, check_leaders_reach_logs, check_qualifier_unit,
    check_identity_crosswalk, check_published_identity,
    check_injury_population, Result, PASS, FAIL, UNVERIFIED,
)
from .cli import DB, MANIFEST, CHECKS, audit, main  # noqa: F401

if __name__ == "__main__":
    sys.exit(main())
