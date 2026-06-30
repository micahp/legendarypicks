"""esports package — live esports surfaces: LoL/MSI, CS2/Dota (GRID), upcoming slate."""

from fastapi import APIRouter

from . import lol, slate

router = APIRouter()
router.include_router(lol.router)
router.include_router(slate.router)
