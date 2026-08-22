"""ingest_ufc_fight_stats — UFC fight stats + history ingest (package).

Split from the former single-file ingest_ufc_fight_stats.py (2026-08-18)
into modules by concern: schema, names, targets, card, fetch, plan,
apply, cli.

The package exposes the same external surface the module did. Callers
that did `import ingest_ufc_fight_stats as ingest` and used
`ingest.apply_plan`, `ingest.build_plan`, `ingest.load_targets`,
`ingest.resolve_from_card`, `ingest.fetch_fight_history`,
`ingest.ensure_table`, `ingest.FighterTarget`, `ingest.IngestPlan`,
`ingest.PreparedLog`, `ingest.DB`, `ingest.espn`, `ingest.time`, keep
working unchanged.
"""
import time

import espn_client as espn

from .schema import DB, ensure_table, _read_only_connection  # noqa: F401
from .names import _name_key, _name_parts, _parse_date, _opponent_for  # noqa: F401
from .targets import load_targets, _dedupe_games, FighterTarget  # noqa: F401
from .card import (  # noqa: F401
    _card_for_date, _fighters_from_card, resolve_from_card,
    _identity_for_existing_id, CardIdentity, card_source_payloads,
)
from .fetch import (  # noqa: F401
    fetch_fight_history, fetch_stats, fetch_fight_status, _error_kind,
    _retry_delay, _retryable, SourceUnavailable, StatsPayload,
)
from .plan import (  # noqa: F401
    _prepared_log, _resolve_target_for_plan, build_plan,
    build_current_card_plan, IngestPlan, PreparedLog, SourcePayload,
)
from .apply import apply_plan  # noqa: F401
from .cli import _positive_int, _fight_limit, _print_summary, main  # noqa: F401

if __name__ == "__main__":
    main()


# Names that were module-level on the pre-split file. Nothing re-exported them,
# so `<pkg>.<name>` raised AttributeError -- a surface the split promised to keep.
# None of these are ever REBOUND, only read or mutated in place, so importing them
# here yields the same objects the submodules use.
from .fetch import (  # noqa: E402,F401
    _STATS_URL,
    _STATUS_URL,
)
