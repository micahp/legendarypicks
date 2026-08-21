"""Read-only Watch source registry endpoint.

No upstream request belongs here.  The endpoint returns the audited publisher
registry; a future scheduled collector owns network discovery and publication
of concrete streams.
"""

from fastapi import APIRouter

from .watch_registry import public_broadcasts, public_sources


router = APIRouter()


@router.get("/api/watch/sources")
def watch_sources():
    return public_sources()


@router.get("/api/watch/broadcasts")
def watch_broadcasts():
    return public_broadcasts()
