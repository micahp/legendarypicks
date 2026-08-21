"""Published registry for free, official Watch sources.

This is intentionally source-first rather than league-first.  A registry row is
permission to *check* a named official publisher; it is not permission to show
every video on that publisher's channel.  The collector that consumes this
registry must still prove a concrete event is live/upcoming, matches the row's
title policy, and is embeddable before it can publish a Watch card.
"""

from __future__ import annotations

from typing import Any, Mapping


REGISTRY_VERSION = "watch-source-v1"

# `availability` is deliberately an enum, not a boolean.  A source that is
# free only for some events must never be rendered as generally free.
_AVAILABILITY = {"always_free", "event_specific", "research"}
_DELIVERY = {"youtube_embed", "external_free"}


WATCH_SOURCES: tuple[Mapping[str, Any], ...] = (
    {
        "id": "pwhl-youtube",
        "publisher": "Professional Women's Hockey League",
        "platform": "youtube",
        "delivery": "youtube_embed",
        "channel": "@thepwhlofficial",
        "official_url": "https://www.youtube.com/@thepwhlofficial",
        "availability": "always_free",
        "territory_note": "Unavailable in Canada, Czechia, and Slovakia under the 2025-26 schedule.",
        "title_policy": "A collector must require an opponent-style game title and reject shows, drafts, and press content.",
        "evidence_url": "https://www.thepwhl.com/en/news/2025/november/18/pwhl-announces-2025-26-broadcast-schedule",
        "enabled": True,
    },
    {
        "id": "fiba-youtube",
        "publisher": "FIBA Basketball",
        "platform": "youtube",
        "delivery": "youtube_embed",
        "channel": "@FIBA",
        "official_url": "https://www.youtube.com/@FIBA",
        "availability": "event_specific",
        "territory_note": "Free availability, memberships, and blackouts vary by competition and territory.",
        "title_policy": "Do not auto-publish until the event's official watch notice confirms free YouTube access; senior qualifiers and some youth events are restricted.",
        "evidence_url": "https://www.fiba.basketball/en/events/fiba-u18-eurobasket-2026/news/how-to-watch-fiba-u18-eurobasket-2026-and-fiba-u20-eurobasket-2026",
        "enabled": True,
    },
    {
        "id": "fifa-plus",
        "publisher": "FIFA+",
        "platform": "fifa_plus",
        "delivery": "external_free",
        "channel": None,
        "official_url": "https://www.plus.fifa.com/",
        "availability": "event_specific",
        "territory_note": "Availability and rights vary by match and territory; embed permission is not yet verified.",
        "title_policy": "Link out only after the exact event page says it is free in the viewer's territory. Never create an iframe from this row.",
        "evidence_url": "https://ipt.fifa.com/organisation/media-releases/fifa-plus-dazn-global-home-of-football",
        "enabled": True,
    },
)


def _public_source(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return only declared contract fields; callers cannot mutate the registry."""
    return {
        "id": row["id"],
        "publisher": row["publisher"],
        "platform": row["platform"],
        "delivery": row["delivery"],
        "officialUrl": row["official_url"],
        "availability": row["availability"],
        "territoryNote": row["territory_note"],
        "titlePolicy": row["title_policy"],
        "evidenceUrl": row["evidence_url"],
    }


def validate_registry(rows: tuple[Mapping[str, Any], ...] = WATCH_SOURCES) -> None:
    """Reject a bad source declaration before it can become product inventory."""
    seen = set()
    for row in rows:
        source_id = row.get("id")
        if not isinstance(source_id, str) or not source_id or source_id in seen:
            raise ValueError("watch registry requires unique non-empty source ids")
        seen.add(source_id)
        if row.get("delivery") not in _DELIVERY:
            raise ValueError(f"{source_id}: unsupported delivery")
        if row.get("availability") not in _AVAILABILITY:
            raise ValueError(f"{source_id}: unsupported availability")
        if not str(row.get("official_url") or "").startswith("https://"):
            raise ValueError(f"{source_id}: official_url must be https")
        if not str(row.get("evidence_url") or "").startswith("https://"):
            raise ValueError(f"{source_id}: evidence_url must be https")
        if not str(row.get("title_policy") or "").strip():
            raise ValueError(f"{source_id}: title_policy is required")
        if row.get("delivery") == "youtube_embed" and not str(row.get("channel") or "").startswith("@"):
            raise ValueError(f"{source_id}: YouTube embeds require an official channel handle")
        if row.get("delivery") == "external_free" and row.get("channel") is not None:
            raise ValueError(f"{source_id}: external links must not masquerade as a channel embed")


def public_sources() -> dict[str, Any]:
    """Stable read contract for the future Watch UI and offline collector."""
    validate_registry()
    return {
        "schemaVersion": REGISTRY_VERSION,
        "sources": [_public_source(row) for row in WATCH_SOURCES if row["enabled"]],
        "publicationRule": (
            "A source row is discovery metadata only. Publish a card only after an exact official "
            "event stream is confirmed live or upcoming, free for that event, and embeddable when "
            "delivery is youtube_embed."
        ),
    }
