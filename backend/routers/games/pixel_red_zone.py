"""Read-only archive endpoints for published ESPN Pixel Red Zone replays."""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException


router = APIRouter()
_REPLAY_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "pixel_red_zone"


@router.get("/api/nfl/pixel-red-zone/replays")
def list_pixel_red_zone_replays():
    """List explicitly archived game replays without contacting ESPN or a database."""
    replays = []
    for path in sorted(_REPLAY_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            game = payload.get("game") or {}
            replays.append({
                "game_id": game.get("game_id"),
                "date": game.get("date"),
                "teams": game.get("teams"),
                "score": game.get("score"),
                "events": len(payload.get("events") or []),
                "mode": payload.get("mode"),
                "path": path.stem,
            })
        except (OSError, json.JSONDecodeError, AttributeError, TypeError):
            continue
    return {"mode": "replay", "replays": replays}


@router.get("/api/nfl/pixel-red-zone/replay/{game_id}")
def get_pixel_red_zone_replay(game_id: str):
    """Serve one frozen ESPN replay; never fall through to a live source."""
    if not game_id.isdigit():
        raise HTTPException(status_code=404, detail="replay not found")
    path = _REPLAY_DIR / f"{game_id}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="replay not found")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="replay fixture is unreadable") from exc
