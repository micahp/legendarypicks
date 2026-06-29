"""routers/esports.py — live esports surfaces.

v0 = chess (Lichess), the "Live Now / moment that matters" proof. Stateless: each request
snapshots the current featured Lichess TV game plus a short window of its most recent moves,
and reads live *material momentum* off the FENs. This is the cheapest honest inflection signal
without an engine — Lichess `cloud-eval` does not cover live mid-game positions, so true win%
(engine eval) is a deliberate later upgrade. The same shape (players, live clocks, a "moment"
string) is what the Dota/CS2 adapters will return, so the frontend card is title-agnostic.
"""
import json
import math
import os
import shutil
import threading
import urllib.request as _u

import chess
import chess.engine
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


# --- Engine eval (Stockfish) → real win% --------------------------------------------------
# Lichess cloud-eval doesn't cover live positions, so we run our own engine at a shallow,
# bounded depth (fast enough for the request path) and convert to a White-POV win%.
_ENGINE_PATH = os.environ.get("STOCKFISH_PATH") or shutil.which("stockfish") or "/usr/games/stockfish"
_engine = None
_engine_lock = threading.Lock()


def _get_engine():
    global _engine
    if _engine is None:
        _engine = chess.engine.SimpleEngine.popen_uci(_ENGINE_PATH)
    return _engine


def _win_pct_from_cp(cp: int) -> float:
    """Centipawns (White POV) → White win%, using Lichess's logistic constant."""
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def _engine_eval(fen: str, depth: int = 11):
    """{cp, mate, win_pct} from White's POV, or None if the engine is unavailable."""
    try:
        board = chess.Board(fen)
    except Exception:
        return None
    if board.is_game_over():
        res = board.result()
        wp = 100.0 if res == "1-0" else 0.0 if res == "0-1" else 50.0
        return {"cp": None, "mate": None, "win_pct": round(wp, 1)}
    try:
        with _engine_lock:
            info = _get_engine().analyse(board, chess.engine.Limit(depth=depth))
        score = info["score"].white()
        if score.is_mate():
            m = score.mate()
            return {"cp": None, "mate": m, "win_pct": 100.0 if m > 0 else 0.0}
        cp = max(-1500, min(1500, score.score()))
        return {"cp": cp, "mate": None, "win_pct": round(_win_pct_from_cp(cp), 1)}
    except Exception:
        global _engine  # engine crashed → drop it so the next call respawns
        try:
            if _engine:
                _engine.quit()
        except Exception:
            pass
        _engine = None
        return None


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
    turn = "white" if (cur_fen.split(" ")[1:2] or ["w"])[0] == "w" else "black"

    # Real win% from the engine: evaluate the current position, and the window-start
    # position, so we can read a *win-probability swing* (the truest "moment that matters").
    eval_now = _engine_eval(cur_fen) if cur_fen else None
    start_fen = fens[0].get("fen") if len(fens) >= 2 else None
    eval_then = _engine_eval(start_fen) if start_fen else None
    win_now = eval_now["win_pct"] if eval_now else None
    win_swing = (round(win_now - eval_then["win_pct"], 1)
                 if (win_now is not None and eval_then) else None)

    # Moment priority: a big win% swing (someone blundered/converted) → time scramble →
    # decisive position → material fallback when the engine is unavailable.
    low = min([c for c in (wc, bc) if c is not None], default=None)
    moment = None
    if win_swing is not None and abs(win_swing) >= 12 and eval_then:
        who = "White" if win_swing > 0 else "Black"
        moment = f"{who} swung the game — win% {eval_then['win_pct']:.0f}→{win_now:.0f}"
    elif low is not None and low <= 20:
        moment = "Time scramble — under 20s on the clock"
    elif eval_now and eval_now.get("mate") is not None:
        who = "White" if eval_now["mate"] > 0 else "Black"
        moment = f"{who} has forced mate in {abs(eval_now['mate'])}"
    elif win_now is not None and (win_now >= 80 or win_now <= 20):
        who = "White" if win_now >= 80 else "Black"
        moment = f"{who} is winning ({max(win_now, 100 - win_now):.0f}% win)"
    elif abs(mat) >= 5:  # engine-less fallback
        moment = f"{'White' if mat > 0 else 'Black'} is winning (+{abs(mat)})"

    return {
        "live": True, "sport": "chess", "source": "lichess",
        "gameId": featured.get("id"),
        "url": f"https://lichess.org/{featured.get('id')}",
        "white": pl("white"), "black": pl("black"),
        "fen": cur_fen, "turn": turn,
        "clocks": {"white": wc, "black": bc},
        "material": mat,
        "eval": eval_now,          # {cp, mate, win_pct} White POV, or null
        "winPct": win_now,         # White win% (null if engine unavailable)
        "winSwing": win_swing,
        "moment": moment,
    }
