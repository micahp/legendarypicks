"""routers/esports.py — live esports surfaces.

v0 = chess (Lichess), the "Live Now / moment that matters" proof. Stateless: each request
snapshots the current featured Lichess TV game plus a short window of its most recent moves,
and reads live *material momentum* off the FENs. This is the cheapest honest inflection signal
without an engine — Lichess `cloud-eval` does not cover live mid-game positions, so true win%
(engine eval) is a deliberate later upgrade. The same shape (players, live clocks, a "moment"
string) is what the Dota/CS2 adapters will return, so the frontend card is title-agnostic.
"""
import json
import urllib.request as _u
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

_PIECE = {"p": 1, "n": 3, "b": 3, "r": 5, "q": 9}  # king excluded


def _material(fen: str) -> int:
    """White-minus-black material from a FEN board field."""
    board = fen.split(" ", 1)[0]
    total = 0
    for ch in board:
        v = _PIECE.get(ch.lower())
        if v is None:
            continue
        total += v if ch.isupper() else -v
    return total


def _read_tv(window: int = 6, timeout: float = 3.0):
    """Read the global featured TV game: the 'featured' snapshot + up to `window` following
    fen updates (each carries the live clocks wc/bc). Returns (featured_dict, [fen_events])."""
    req = _u.Request("https://lichess.org/api/tv/feed",
                     headers={"Accept": "application/x-ndjson"})
    featured, fens = None, []
    with _u.urlopen(req, timeout=timeout) as r:
        for raw in r:
            try:
                ev = json.loads(raw.decode().strip())
            except Exception:
                continue
            t = ev.get("t")
            if t == "featured":
                featured = ev.get("d")
                fens = []  # reset: only collect updates for the current featured game
            elif t == "fen":
                fens.append(ev.get("d"))
            if featured and len(fens) >= window:
                break
    return featured, fens


@router.get("/api/esports/chess/live")
def chess_live():
    """The current top live chess game with a 'moment that matters' read."""
    try:
        featured, fens = _read_tv()
    except Exception:
        return JSONResponse({"live": False, "error": "feed unavailable"}, status_code=200)
    if not featured:
        return {"live": False}

    players = featured.get("players", []) or []

    def pl(color: str):
        p = next((x for x in players if x.get("color") == color), {}) or {}
        u = p.get("user") or {}
        return {"name": u.get("name") or "Anonymous",
                "rating": p.get("rating"),
                "clock": p.get("seconds")}

    cur = fens[-1] if fens else None
    cur_fen = (cur.get("fen") if cur else featured.get("fen")) or ""
    wc = cur.get("wc") if cur else pl("white")["clock"]
    bc = cur.get("bc") if cur else pl("black")["clock"]

    mat = _material(cur_fen) if cur_fen else 0
    series = [_material(f["fen"]) for f in fens if f.get("fen")]
    swing = (series[-1] - series[0]) if len(series) >= 2 else 0
    turn = "white" if (cur_fen.split(" ")[1:2] or ["w"])[0] == "w" else "black"

    # The "moment that matters": a material swing in-window (capture/blunder), a time
    # scramble, or a settled-but-decisive material edge — in priority order.
    low = min([c for c in (wc, bc) if c is not None], default=None)
    moment = None
    if abs(swing) >= 3:
        moment = f"{'White' if swing > 0 else 'Black'} just won material (+{abs(swing)})"
    elif low is not None and low <= 20:
        moment = "Time scramble — under 20s on the clock"
    elif abs(mat) >= 5:
        moment = f"{'White' if mat > 0 else 'Black'} is winning (+{abs(mat)})"

    return {
        "live": True, "sport": "chess", "source": "lichess",
        "gameId": featured.get("id"),
        "url": f"https://lichess.org/{featured.get('id')}",
        "white": pl("white"), "black": pl("black"),
        "fen": cur_fen, "turn": turn,
        "clocks": {"white": wc, "black": bc},
        "material": mat, "swing": swing, "moment": moment,
    }
