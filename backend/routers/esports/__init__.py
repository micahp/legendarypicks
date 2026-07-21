"""esports package — live esports surfaces: LoL/MSI, CS2/Dota (GRID), upcoming slate."""

from fastapi import APIRouter

from . import lol, picks, predict, slate

router = APIRouter()
router.include_router(lol.router)
router.include_router(slate.router)
router.include_router(picks.router)
router.include_router(predict.router)
