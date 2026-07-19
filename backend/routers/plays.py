"""Read-only API for the published curated plays board.

The trading system validates and atomically publishes this snapshot.  The web
API owns the destination file and performs a defensive serving-boundary check
before returning it.  No Kalshi client, trading runner, or network request is
used here.

This is intentionally separate from ``/api/live/discounts``.  That endpoint
and its receipt/card contract remain the canonical live-signal surface.
"""

import copy
import datetime as dt
import json
import math
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse


router = APIRouter()

SCHEMA_VERSION = "plays-board-v1"
SURFACE = "curated_plays"
PAPER_MODE = "paper_research_only"
MAX_SNAPSHOT_BYTES = 256 * 1024
ACTIVE_MARKET_STATUSES = {"active", "open"}
TERMINAL_MARKET_STATUSES = {
    "amended",
    "closed",
    "determined",
    "disputed",
    "finalized",
    "resolved",
    "settled",
}

_DEFAULT_SNAPSHOT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "plays_board.json")
)


class SnapshotUnavailable(ValueError):
    """Safe, public classification for an unavailable published snapshot."""

    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


class SnapshotInvalid(ValueError):
    """Internal validation error; details are never returned to the browser."""


def snapshot_path() -> str:
    """Return the API-owned publication path (overridable for mounted data)."""

    return os.path.abspath(os.environ.get("LP_PLAYS_BOARD_PATH") or _DEFAULT_SNAPSHOT_PATH)


def _mapping(value: Any, field: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise SnapshotInvalid("{} must be an object".format(field))
    return value


def _list(value: Any, field: str) -> List[Any]:
    if not isinstance(value, list):
        raise SnapshotInvalid("{} must be an array".format(field))
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SnapshotInvalid("{} must be a non-empty string".format(field))
    return value


def _number(value: Any, field: str, *, allow_none: bool = False) -> Optional[float]:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SnapshotInvalid("{} must be a number".format(field))
    parsed = float(value)
    if not math.isfinite(parsed):
        raise SnapshotInvalid("{} must be finite".format(field))
    return parsed


def _probability(value: Any, field: str, *, allow_none: bool = False) -> Optional[float]:
    parsed = _number(value, field, allow_none=allow_none)
    if parsed is not None and not 0 <= parsed <= 1:
        raise SnapshotInvalid("{} must be a decimal probability between 0 and 1".format(field))
    return parsed


def _nonnegative(value: Any, field: str, *, allow_none: bool = False) -> Optional[float]:
    parsed = _number(value, field, allow_none=allow_none)
    if parsed is not None and parsed < 0:
        raise SnapshotInvalid("{} must be non-negative".format(field))
    return parsed


def _timestamp(value: Any, field: str) -> dt.datetime:
    raw = _text(value, field)
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SnapshotInvalid("{} must be an ISO-8601 timestamp".format(field)) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SnapshotInvalid("{} must include a timezone".format(field))
    return parsed.astimezone(dt.timezone.utc)


def _utc_iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _positive_integer(value: Any, field: str) -> int:
    parsed = _number(value, field)
    if parsed is None or parsed <= 0 or int(parsed) != parsed:
        raise SnapshotInvalid("{} must be a positive integer".format(field))
    return int(parsed)


def _validate_play(play: Any, index: int, generated_at: dt.datetime) -> None:
    prefix = "plays[{}]".format(index)
    play = _mapping(play, prefix)
    for field in (
        "category",
        "ticker",
        "title",
        "side",
        "thesis",
        "entry_condition",
        "invalidation",
        "exit_rule",
        "confidence",
        "resolves_at_note",
    ):
        _text(play.get(field), "{}.{}".format(prefix, field))
    if play["side"] not in ("YES", "NO"):
        raise SnapshotInvalid("{}.side must be YES or NO".format(prefix))
    for optional_field in ("market_status", "market_result", "quote_source"):
        if play.get(optional_field) is not None:
            _text(play[optional_field], "{}.{}".format(prefix, optional_field))

    entry = _probability(play.get("entry_price"), "{}.entry_price".format(prefix))
    if entry is None or entry <= 0:
        raise SnapshotInvalid("{}.entry_price must be greater than zero".format(prefix))
    _probability(play.get("target_price"), "{}.target_price".format(prefix))
    _probability(play.get("stop_price"), "{}.stop_price".format(prefix))
    _nonnegative(play.get("r_target"), "{}.r_target".format(prefix))

    bid = _probability(play.get("current_bid"), "{}.current_bid".format(prefix), allow_none=True)
    ask = _probability(play.get("current_ask"), "{}.current_ask".format(prefix), allow_none=True)
    _probability(play.get("current_price"), "{}.current_price".format(prefix), allow_none=True)
    _nonnegative(
        play.get("current_bid_depth"),
        "{}.current_bid_depth".format(prefix),
        allow_none=True,
    )
    _nonnegative(
        play.get("current_ask_depth"),
        "{}.current_ask_depth".format(prefix),
        allow_none=True,
    )
    _nonnegative(
        play.get("feed_book_age_ms"),
        "{}.feed_book_age_ms".format(prefix),
        allow_none=True,
    )
    if bid is not None and ask is not None and bid > ask:
        raise SnapshotInvalid("{}.current_bid cannot exceed current_ask".format(prefix))

    has_quote = any(
        play.get(field) is not None for field in ("current_price", "current_bid", "current_ask")
    )
    price_as_of = play.get("price_as_of")
    if has_quote and price_as_of is None:
        raise SnapshotInvalid("{}.price_as_of is required with a quote".format(prefix))
    if price_as_of is not None:
        quote_time = _timestamp(price_as_of, "{}.price_as_of".format(prefix))
        if quote_time > generated_at + dt.timedelta(minutes=5):
            raise SnapshotInvalid("{}.price_as_of cannot be materially in the future".format(prefix))
    _timestamp(play.get("resolves_at"), "{}.resolves_at".format(prefix))


def _validate_snapshot(snapshot: Any) -> Dict[str, Any]:
    snapshot = _mapping(snapshot, "snapshot")
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise SnapshotInvalid("unsupported schema_version")
    if snapshot.get("surface") != SURFACE:
        raise SnapshotInvalid("unsupported surface")
    if snapshot.get("mode") != PAPER_MODE:
        raise SnapshotInvalid("mode must be paper_research_only")

    generated_at = _timestamp(snapshot.get("generated_at"), "generated_at")
    as_of = _timestamp(snapshot.get("as_of"), "as_of")
    published_at = _timestamp(snapshot.get("published_at"), "published_at")
    if as_of > generated_at + dt.timedelta(minutes=5):
        raise SnapshotInvalid("as_of cannot be materially later than generated_at")
    if published_at + dt.timedelta(minutes=5) < generated_at:
        raise SnapshotInvalid("published_at cannot be materially earlier than generated_at")

    _text(snapshot.get("timezone"), "timezone")
    _text(snapshot.get("risk_definition"), "risk_definition")
    for index, limitation in enumerate(_list(snapshot.get("limitations"), "limitations")):
        _text(limitation, "limitations[{}]".format(index))

    policy = _mapping(snapshot.get("freshness_policy"), "freshness_policy")
    _positive_integer(
        policy.get("quote_stale_after_seconds"),
        "freshness_policy.quote_stale_after_seconds",
    )
    _positive_integer(
        policy.get("board_stale_after_seconds"),
        "freshness_policy.board_stale_after_seconds",
    )

    scope = _mapping(snapshot.get("scope"), "scope")
    scope_from = _timestamp(scope.get("from"), "scope.from")
    scope_through = _timestamp(scope.get("through"), "scope.through")
    if scope_from >= scope_through:
        raise SnapshotInvalid("scope.from must be before scope.through")
    _text(scope.get("label"), "scope.label")

    seen_categories = set()
    for index, row in enumerate(_list(snapshot.get("category_status"), "category_status")):
        row = _mapping(row, "category_status[{}]".format(index))
        category = _text(row.get("category"), "category_status[{}].category".format(index))
        if category in seen_categories:
            raise SnapshotInvalid("duplicate category_status category")
        seen_categories.add(category)
        _text(row.get("status"), "category_status[{}].status".format(index))
        _text(row.get("note"), "category_status[{}].note".format(index))

    seen_tickers = set()
    for index, play in enumerate(_list(snapshot.get("plays"), "plays")):
        _validate_play(play, index, generated_at)
        ticker = play["ticker"]
        if ticker in seen_tickers:
            raise SnapshotInvalid("duplicate play ticker")
        seen_tickers.add(ticker)
    return snapshot


def _derive_api_view(snapshot: Dict[str, Any], now: dt.datetime) -> Dict[str, Any]:
    result = copy.deepcopy(snapshot)
    policy = result["freshness_policy"]
    as_of = _timestamp(result["as_of"], "as_of")
    scope_through = _timestamp(result["scope"]["through"], "scope.through")
    board_age = max(0, int((now - as_of).total_seconds()))
    quote_counts = {"current": 0, "stale": 0, "unavailable": 0}
    event_counts = {"open_window": 0, "expired": 0}

    for play in result["plays"]:
        resolves_at = _timestamp(play["resolves_at"], "play.resolves_at")
        market_status = str(play.get("market_status") or "").strip().lower()
        market_result = str(play.get("market_result") or "").strip()
        if market_result or market_status in TERMINAL_MARKET_STATUSES:
            event_status = "expired"
        elif market_status in ACTIVE_MARKET_STATUSES:
            event_status = "open_window"
        else:
            event_status = "expired" if now >= resolves_at else "open_window"
        play["event_status"] = event_status
        event_counts[event_status] += 1

        has_quote = any(
            play.get(field) is not None for field in ("current_price", "current_bid", "current_ask")
        )
        if not has_quote or not play.get("price_as_of"):
            quote_status = "unavailable"
            quote_age = None
        else:
            quote_time = _timestamp(play["price_as_of"], "play.price_as_of")
            quote_age = max(0, int((now - quote_time).total_seconds()))
            quote_status = (
                "stale"
                if quote_age > policy["quote_stale_after_seconds"]
                else "current"
            )
        play["quote_status"] = quote_status
        play["quote_age_seconds"] = quote_age
        quote_counts[quote_status] += 1

    all_expired = bool(result["plays"]) and event_counts["open_window"] == 0
    if now >= scope_through or all_expired:
        board_status = "archived"
        status_reason = "The board's event window has ended."
    elif board_age > policy["board_stale_after_seconds"]:
        board_status = "stale"
        status_reason = "The published board is older than its freshness window."
    else:
        board_status = "current"
        status_reason = "The board is inside its publication freshness window."

    result["server_time"] = _utc_iso(now)
    result["board_status"] = board_status
    result["status_reason"] = status_reason
    result["board_age_seconds"] = board_age
    result["quote_status_counts"] = quote_counts
    result["event_status_counts"] = event_counts
    return result


def load_snapshot(path: str, *, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Read, validate, and derive a serving view without any external I/O."""

    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(dt.timezone.utc)

    try:
        size = os.path.getsize(path)
        if size > MAX_SNAPSHOT_BYTES:
            raise SnapshotUnavailable(
                "snapshot_too_large",
                "The published curated plays board is unavailable.",
            )
        with open(path, "r", encoding="utf-8") as handle:
            snapshot = json.load(handle)
    except FileNotFoundError as exc:
        raise SnapshotUnavailable(
            "snapshot_missing",
            "No curated plays board has been published.",
        ) from exc
    except SnapshotUnavailable:
        raise
    except (OSError, UnicodeError) as exc:
        raise SnapshotUnavailable(
            "snapshot_unreadable",
            "The published curated plays board could not be read.",
        ) from exc
    except json.JSONDecodeError as exc:
        raise SnapshotUnavailable(
            "snapshot_invalid",
            "The published curated plays board failed validation.",
        ) from exc

    try:
        return _derive_api_view(_validate_snapshot(snapshot), current)
    except SnapshotInvalid as exc:
        raise SnapshotUnavailable(
            "snapshot_invalid",
            "The published curated plays board failed validation.",
        ) from exc


def _unavailable_view(error: SnapshotUnavailable, now: dt.datetime) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "surface": SURFACE,
        "server_time": _utc_iso(now),
        "board_status": "unavailable",
        "status_reason": error.reason,
        "error_code": error.code,
        "mode": PAPER_MODE,
        "category_status": [],
        "plays": [],
    }


@router.get("/api/plays/today")
def today_plays():
    now = dt.datetime.now(dt.timezone.utc)
    try:
        payload = load_snapshot(snapshot_path(), now=now)
        status_code = 200
    except SnapshotUnavailable as error:
        payload = _unavailable_view(error, now)
        status_code = 503
    return JSONResponse(
        content=payload,
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )
