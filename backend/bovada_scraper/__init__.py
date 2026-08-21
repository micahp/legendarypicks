"""bovada_scraper — scrape player props from Bovada's open API (package).

Split from the former single-file bovada_scraper.py (2026-08-18) into
modules by concern: config, backoff, client, parsers, direct, ingest,
cli.

The package exposes the same external surface the module did. Callers
that did `import bovada_scraper as bs` and used `bs.LEAGUES`,
`bs._parse_mls_props`, `bs.fetch_events`, `bs.main`, etc. keep working
unchanged. The module-level accumulators (_UNMAPPED_PLAYER_MARKETS,
_STALE_TEAM_TAGS, _MINTED_PLAYERS, _RESTED_LEAGUES) are the SAME
objects imported from .config, so tests that clear them and parsers
that append to them share state exactly as before.
"""
from .config import (  # noqa: F401
    API_BASE, BOVADA, LEAGUES, SCHEDULED_LEAGUES, HDR, _SOCCER_MARKET_RULES, _WC_SKIP_KW,
    MARKET_MAP, _BACKOFF_PATH, _EMPTY_RUNS_BEFORE_BACKOFF, _BACKOFF_HOURS,
    _MLS_PLAYER_MARKETS, _MLS_PLAYER_GROUPS, _MLS_CLUB_CODES,
    _MLS_NON_PLAYER_OUTCOMES, _UNMAPPED_PLAYER_MARKETS, _STALE_TEAM_TAGS,
    _MINTED_PLAYERS, _RESTED_LEAGUES, _UFC_METHOD,
)
from .backoff import (  # noqa: F401
    _load_backoff, _save_backoff, _should_fetch, _record_result,
)
from .client import fetch_events, parse_player_props  # noqa: F401
from .parsers import (  # noqa: F401
    _parse_ufc_props, _parse_tennis_props, _report_unmapped_market,
    _looks_player_attributed, _parse_mls_props, _parse_wc_props,
    _split_market_and_player, _parse_standard_props,
)
from .direct import (  # noqa: F401
    _wc_event_date, _event_start_iso, _wc_direct_ingest,
    _normalize_identity_name, _resolve_ufc_player_for_bovada,
    _find_existing_ufc_game_for_players, _ufc_direct_ingest,
)
from .ingest import ingest_batch, capture_snapshots  # noqa: F401
from .cli import main, _run_report, targets_for_request  # noqa: F401

if __name__ == "__main__":
    main()
