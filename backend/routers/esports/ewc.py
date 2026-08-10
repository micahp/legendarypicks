"""ewc.py — EWC 2026 tournament-center contract: participant model, event identity, and the
published Club Championship snapshot store.

This module is the single owner of Club Championship publication. The refresh route invokes the
validated Liquipedia publisher at most once per cooldown window; the ordinary GET remains a fast
snapshot read. A failed refresh never replaces the last good snapshot or reconstructs standings
from match fragments.
"""

import json
import os
import threading
import time

_STANDINGS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                               "data", "esports_ewc_standings.json")
_DEFAULT_STALE_AFTER_S = int(os.environ.get("LP_EWC_STANDINGS_STALE_AFTER_S", "21600"))  # 6h publisher cadence
_REFRESH_COOLDOWN_S = 5 * 60
_refresh_lock = threading.Lock()
_refresh_last_attempt = 0.0
_UNAVAILABLE_LABEL = "Participant unavailable"

EVENT_ID = "ewc-2026"

# Official EWC 2026 program: 25 tournaments across 24 game titles.  This catalog is the
# completeness authority for the Games tab; the normalized match slate below is coverage,
# not the title directory.  Mobile Legends has two tournaments (MSC and MWI).
_PROGRAM_SOURCE = {
    "label": "EWC 2026 Media Guide",
    "url": "https://cdn.esportsworldcup.com/resources/uploads/EWC_26_Media_Guide_short_d6f73c0f8a.pdf",
}
_BRAND_SOURCE = {
    "label": "EWC Resource Center",
    "url": "https://resources.esportsworldcup.com/en/competitive-ops/rulebooks",
}
_PROGRAM_DATES = {
    "apex-legends": ("2026-07-07", "2026-07-11"),
    "call-of-duty-black-ops-7": ("2026-08-05", "2026-08-09"),
    "call-of-duty-warzone": ("2026-07-30", "2026-08-02"),
    "chess": ("2026-08-11", "2026-08-15"),
    "counter-strike-2": ("2026-08-12", "2026-08-23"),
    "crossfire": ("2026-08-18", "2026-08-22"),
    "dota-2": ("2026-07-07", "2026-07-19"),
    "ea-sports-fc-26": ("2026-07-22", "2026-07-26"),
    "fatal-fury-city-of-the-wolves": ("2026-07-08", "2026-07-11"),
    "fortnite-reload": ("2026-08-19", "2026-08-22"),
    "free-fire": ("2026-07-15", "2026-07-18"),
    "honor-of-kings": ("2026-07-30", "2026-08-08"),
    "league-of-legends": ("2026-07-15", "2026-07-19"),
    "mobile-legends-bang-bang": ("2026-07-14", "2026-08-01"),
    "overwatch-2": ("2026-07-29", "2026-08-02"),
    "pubg-battlegrounds": ("2026-07-21", "2026-07-26"),
    "pubg-mobile": ("2026-08-06", "2026-08-16"),
    "rainbow-six-siege": ("2026-08-04", "2026-08-15"),
    "rocket-league": ("2026-08-12", "2026-08-16"),
    "street-fighter-6": ("2026-07-29", "2026-08-01"),
    "teamfight-tactics": ("2026-07-21", "2026-07-25"),
    "tekken-8": ("2026-08-05", "2026-08-08"),
    "trackmania": ("2026-08-19", "2026-08-22"),
    "valorant": ("2026-07-02", "2026-07-12"),
}
_TITLE_BRAND_ASSETS = {
    "apex-legends": "https://cdn.esportsworldcup.com/resources/uploads/ALGS_Split_1_Playoff_Logo_Black_b705b1f3d8_b8523341f1.png",
    "call-of-duty-black-ops-7": "https://cdn.esportsworldcup.com/resources/uploads/COD_BO_7_Logo_Black_6b63bf75bc_1_eb18752f50.svg",
    "call-of-duty-warzone": "https://cdn.esportsworldcup.com/resources/uploads/CODWRS_Black_Launch_1_13f0a133a0_b4bdb97d8d.webp",
    "chess": "https://cdn.esportsworldcup.com/resources/uploads/Chess_Black_Final_a1c10fc918_697453b0ba.webp",
    "counter-strike-2": "https://cdn.esportsworldcup.com/resources/uploads/CS_2_Logo_Black_807905760f_bdedc62380.svg",
    "crossfire": "https://cdn.esportsworldcup.com/resources/uploads/cf_mfc_Logo_Black_f2c8fb7605_4b28815c3d.svg",
    "dota-2": "https://cdn.esportsworldcup.com/resources/uploads/dota2_c67f3d9478.svg",
    "ea-sports-fc-26": "https://cdn.esportsworldcup.com/resources/uploads/EA_FC_PRO_Horizontal_Lockup_Pitch_Black_RGB_545c0e3207_2501dbd4b6.webp",
    "fatal-fury-city-of-the-wolves": "https://cdn.esportsworldcup.com/resources/uploads/fatalfury_cotw_Logo_Black_f768ff3bae_9ce0cbfb95.webp",
    "fortnite-reload": "https://cdn.esportsworldcup.com/resources/uploads/Fortnite_dark_2_6c9812a8c1_0545a4cbe2.webp",
    "free-fire": "https://cdn.esportsworldcup.com/resources/uploads/FF_Logo_Black_05118535e6_4611ce292f.svg",
    "honor-of-kings": "https://cdn.esportsworldcup.com/resources/uploads/KWC_38dffebcbf_b7fd9c022f.webp",
    "league-of-legends": "https://cdn.esportsworldcup.com/resources/uploads/Logo_League_of_Legends_debae84876_074b09f1ef.webp",
    "mobile-legends-bang-bang": "https://cdn.esportsworldcup.com/resources/uploads/MSC_LOGO_SECONDARY_FULL_NAME_BLACK_RESIZED_03c08dadf8_a6b1e3a2d3.webp",
    "overwatch-2": "https://cdn.esportsworldcup.com/resources/uploads/OVERWATCH_CHAMPIONS_Logo_BLACK_HORIZONTAL_beb9deaf1d_bcc73ec957.svg",
    "pubg-battlegrounds": "https://cdn.esportsworldcup.com/resources/uploads/PUBG_BG_Full_Flat_Black_2048_b8d4567746_05ecfc8cc4.webp",
    "pubg-mobile": "https://cdn.esportsworldcup.com/resources/uploads/PMWC_upscale_137a127272_f1ad7d484a.webp",
    "rainbow-six-siege": "https://cdn.esportsworldcup.com/resources/uploads/R6_Siege_R6_Lockup_Horizontal_Black_f05af03efd_1fea4410ce.webp",
    "rocket-league": "https://cdn.esportsworldcup.com/resources/uploads/Rocket_League_dark_no_feature_0629c6b8eb_74c46dfbdc.webp",
    "street-fighter-6": "https://cdn.esportsworldcup.com/resources/uploads/SF_6_Logo_Black_24545f66e4_df8b7a3c92.svg",
    "teamfight-tactics": "https://cdn.esportsworldcup.com/resources/uploads/TFT_Logo_Black_c117699175_e19dc5e3be.svg",
    "tekken-8": "https://cdn.esportsworldcup.com/resources/uploads/T8_Logo_Black_a48fb5abec_c0134a15b1.svg",
    "trackmania": "https://cdn.esportsworldcup.com/resources/uploads/TM_Logo_BLACK_Text_HD_A_Ubisoft_Original_d4bc566fac_25e5fdf547.webp",
    "valorant": "https://cdn.esportsworldcup.com/resources/uploads/Valorant_Logo_Black_c849e41882_20a3d9711f.svg",
}
EWC_TITLES = [
    {"slug": "apex-legends", "name": "Apex Legends", "tournaments": ["ALGS Split 1"], "weeks": [1], "feedTitles": ["Apex Legends"]},
    {"slug": "call-of-duty-black-ops-7", "name": "Call of Duty: Black Ops 7", "tournaments": ["Call of Duty: Black Ops 7"], "weeks": [5], "feedTitles": ["Call of Duty"]},
    {"slug": "call-of-duty-warzone", "name": "Call of Duty: Warzone", "tournaments": ["Warzone Resurgence Series"], "weeks": [4], "feedTitles": ["Call of Duty: Warzone", "Warzone"]},
    {"slug": "chess", "name": "Chess", "tournaments": ["Chess"], "weeks": [6], "feedTitles": ["Chess"]},
    {"slug": "counter-strike-2", "name": "Counter-Strike 2", "tournaments": ["Counter-Strike 2"], "weeks": [7], "feedTitles": ["CS2"]},
    {"slug": "crossfire", "name": "Crossfire", "tournaments": ["Crossfire"], "weeks": [7], "feedTitles": ["Crossfire"]},
    {"slug": "dota-2", "name": "Dota 2", "tournaments": ["Dota 2"], "weeks": [1, 2], "feedTitles": ["Dota 2"]},
    {"slug": "ea-sports-fc-26", "name": "EA Sports FC 26", "tournaments": ["FC26"], "weeks": [3], "feedTitles": ["EA Sports FC 26", "EA FC"]},
    {"slug": "fatal-fury-city-of-the-wolves", "name": "Fatal Fury: City of the Wolves", "tournaments": ["Fatal Fury: City of the Wolves"], "weeks": [1], "feedTitles": ["Fatal Fury"]},
    {"slug": "fortnite-reload", "name": "Fortnite Reload", "tournaments": ["Fortnite Reload Elite Series"], "weeks": [7], "feedTitles": ["Fortnite"]},
    {"slug": "free-fire", "name": "Free Fire", "tournaments": ["Free Fire"], "weeks": [2], "feedTitles": ["Free Fire"]},
    {"slug": "honor-of-kings", "name": "Honor of Kings", "tournaments": ["KWC"], "weeks": [5], "feedTitles": ["King of Glory", "Honor of Kings"]},
    {"slug": "league-of-legends", "name": "League of Legends", "tournaments": ["League of Legends"], "weeks": [2], "feedTitles": ["LoL", "League of Legends"]},
    {"slug": "mobile-legends-bang-bang", "name": "Mobile Legends: Bang Bang", "tournaments": ["MSC", "MWI"], "weeks": [2, 3, 4], "feedTitles": ["Mobile Legends: Bang Bang", "MLBB"]},
    {"slug": "overwatch-2", "name": "Overwatch 2", "tournaments": ["Overwatch Champions Series"], "weeks": [4], "feedTitles": ["Overwatch", "Overwatch 2"]},
    {"slug": "pubg-battlegrounds", "name": "PUBG: Battlegrounds", "tournaments": ["PUBG: Battlegrounds"], "weeks": [3], "feedTitles": ["PUBG"]},
    {"slug": "pubg-mobile", "name": "PUBG Mobile", "tournaments": ["PUBG Mobile World Cup"], "weeks": [5, 6], "feedTitles": ["PUBG Mobile"]},
    {"slug": "rainbow-six-siege", "name": "Rainbow Six Siege", "tournaments": ["R6 Siege"], "weeks": [6], "feedTitles": ["Rainbow Six", "Rainbow Six Siege"]},
    {"slug": "rocket-league", "name": "Rocket League", "tournaments": ["Rocket League"], "weeks": [6], "feedTitles": ["Rocket League"]},
    {"slug": "street-fighter-6", "name": "Street Fighter 6", "tournaments": ["Street Fighter 6"], "weeks": [4], "feedTitles": ["Street Fighter 6"]},
    {"slug": "teamfight-tactics", "name": "Teamfight Tactics", "tournaments": ["Teamfight Tactics"], "weeks": [3], "feedTitles": ["Teamfight Tactics", "TFT"]},
    {"slug": "tekken-8", "name": "Tekken 8", "tournaments": ["Tekken 8"], "weeks": [5], "feedTitles": ["Tekken 8"]},
    {"slug": "trackmania", "name": "Trackmania", "tournaments": ["Trackmania"], "weeks": [7], "feedTitles": ["Trackmania"]},
    {"slug": "valorant", "name": "Valorant", "tournaments": ["Valorant"], "weeks": [1], "feedTitles": ["Valorant"]},
]
for _title in EWC_TITLES:
    _title["logo"] = _TITLE_BRAND_ASSETS[_title["slug"]]
    _title["programFirstDate"], _title["programLastDate"] = _PROGRAM_DATES[_title["slug"]]
_EWC_TITLE_COUNT = len(EWC_TITLES)
_EWC_TOURNAMENT_COUNT = sum(len(title["tournaments"]) for title in EWC_TITLES)


# ---------------------------------------------------------------------------
# Participant model — structural pending participants, never a literal "TBD" name
# ---------------------------------------------------------------------------
def named_participant(club_id, club_name):
    """A decided side: the tournament has determined this club."""
    return {"state": "named", "clubId": club_id, "clubName": club_name}


def pending_participant(feeder_game_id, outcome, label):
    """A genuinely undecided bracket slot fed by another match."""
    return {"state": "pending", "feederGameId": feeder_game_id, "outcome": outcome, "label": label}


def unavailable_participant():
    """An unresolvable data fault — never a fabricated club, never a bare TBD."""
    return {"state": "unavailable", "label": _UNAVAILABLE_LABEL}


def participant_label(participant):
    """The display label for a participant: club name when decided, dependency label when
    pending, the honest unavailable phrase otherwise."""
    if not participant:
        return _UNAVAILABLE_LABEL
    state = participant.get("state")
    if state == "named":
        return participant.get("clubName") or _UNAVAILABLE_LABEL
    return participant.get("label") or _UNAVAILABLE_LABEL


def participant_is_resolved(participant):
    return bool(participant and participant.get("state") == "named")


# ---------------------------------------------------------------------------
# EWC event identity — data-driven detector, no hard-coded clubs or dates
# ---------------------------------------------------------------------------
def is_ewc_2026_serie(serie, league=None):
    """Whether a PandaScore serie belongs to the EWC 2026 main event (not open qualifiers).

    Uses the serie slug suffix + year published by PandaScore, plus the league name.  A serie whose
    slug ends ``-esports-world-cup-2026`` with year 2026 is EWC 2026; open-qualifier slugs do not
    end in that suffix and are excluded.  No club, date, or bracket is hard-coded.
    """
    serie = serie or {}
    slug = (serie.get("slug") or "").lower()
    year = serie.get("year")
    league_name = ((league or {}).get("name") or "").lower()
    serie_identity = " ".join(
        str(serie.get(field) or "").lower()
        for field in ("slug", "name", "full_name")
    )
    if "qualifier" in serie_identity or "qualifying" in serie_identity:
        return False
    if slug.endswith("-esports-world-cup-2026") and year == 2026:
        return True
    return league_name == "esports world cup" and year == 2026


_EWC_MAIN_LABEL_TOKENS = ("esports world cup",)


def is_ewc_2026_label(label):
    """Narrow label detector for slate rows without PandaScore identity (Bovada-only rows).

    Accepts normalized labels that start with the EWC main-event vocabulary and are NOT qualifiers.
    Qualifier labels ("open qualifier", "last chance qualifier") are explicitly excluded so the
    EWC tournament center does not absorb them.
    """
    norm = " ".join((label or "").lower().split())
    if not norm:
        return False
    if "qualifier" in norm:
        return False
    return any(norm.startswith(tok) for tok in _EWC_MAIN_LABEL_TOKENS)


# ---------------------------------------------------------------------------
# Published standings snapshot store — one writer, atomic replace, last good survives
# ---------------------------------------------------------------------------
def _validate_row(row, seen_ids):
    if not isinstance(row, dict):
        raise ValueError("standings row must be an object")
    rank = row.get("rank")
    if not isinstance(rank, int) or rank < 1:
        raise ValueError(f"invalid rank {rank!r}")
    club_id = row.get("clubId")
    if not club_id or not isinstance(club_id, str):
        raise ValueError(f"invalid clubId {club_id!r}")
    club_name = row.get("clubName")
    if not club_name or not isinstance(club_name, str):
        raise ValueError(f"invalid clubName {club_name!r}")
    points = row.get("points")
    if points is not None and (not isinstance(points, (int, float)) or points < 0):
        raise ValueError(f"negative or invalid points {points!r}")
    if club_id in seen_ids:
        raise ValueError(f"duplicate clubId {club_id!r}")
    seen_ids.add(club_id)


def _validate_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be an object")
    if snapshot.get("event") != EVENT_ID:
        raise ValueError("snapshot event must be ewc-2026")
    if not snapshot.get("publishedAt"):
        raise ValueError("snapshot missing publishedAt")
    src = snapshot.get("source") or {}
    expected = src.get("sourceReportedClubs")
    rows = snapshot.get("standings")
    if not isinstance(rows, list):
        raise ValueError("standings must be a list")
    if expected is not None and len(rows) != expected:
        raise ValueError(
            f"count disagreement: source reported {expected}, fetched {len(rows)}")
    seen_ids = set()
    for row in rows:
        _validate_row(row, seen_ids)
    # Rank/points ordering follows the publisher's official tiebreak. Real published rankings
    # contain TIED ranks (equal points share a rank — Liquipedia rev 15997 has tied 4th and
    # tied 6th), so duplicate ranks are legitimate. Contract:
    #   - ranks are non-decreasing;
    #   - points are non-increasing;
    #   - equal points -> equal rank (a tie);
    #   - strictly fewer points -> strictly greater rank.
    prev_rank = None
    prev_points = None
    for row in rows:
        rank = row.get("rank")
        points = row.get("points")
        if prev_rank is not None and rank < prev_rank:
            raise ValueError(f"rank regression: rank {rank} after rank {prev_rank}")
        if points is not None:
            if prev_points is not None:
                if points > prev_points:
                    raise ValueError(
                        f"point regression: rank {rank} has {points} > rank above with {prev_points}")
                if points == prev_points and rank != prev_rank:
                    raise ValueError(
                        f"tie mismatch: equal points {points} with ranks {prev_rank} and {rank}")
                if points < prev_points and rank <= prev_rank:
                    raise ValueError(
                        f"rank inversion: rank {rank} has {points} < rank above with {prev_points}")
            prev_points = points
        prev_rank = rank


def _load_raw(path):
    try:
        with open(path) as f:
            return json.loads(f.read())
    except Exception:
        return None


def _read_valid(path):
    """Return the stored snapshot if it parses and validates, else None."""
    raw = _load_raw(path)
    if raw is None:
        return None
    try:
        _validate_snapshot(raw)
        return raw
    except ValueError:
        return None


def publish_standings(snapshot, path=None):
    """Validate and atomically publish a complete standings snapshot. Raises ValueError on any
    validation failure; a failed candidate never becomes readable. Regression of a club's points
    vs the previous published run is rejected unless the snapshot marks ``publisherCorrection``.
    """
    path = path or _STANDINGS_PATH
    _validate_snapshot(snapshot)
    prev = _read_valid(path)
    if prev is not None and not snapshot.get("publisherCorrection"):
        prev_by_id = {r.get("clubId"): r.get("points") for r in prev.get("standings", [])}
        for row in snapshot.get("standings", []):
            old = prev_by_id.get(row.get("clubId"))
            new = row.get("points")
            if old is not None and new is not None and new < old:
                raise ValueError(
                    f"point regression for {row.get('clubId')} ({old} -> {new}) without publisherCorrection")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(snapshot, f)
    os.replace(tmp, path)
    return snapshot


def read_standings(path=None, stale_after_s=None):
    """The request-path reader: exactly one published snapshot, with honest status.

    - valid snapshot fresh enough -> ``current``
    - valid snapshot older than the publisher cadence -> ``stale`` (last good survives)
    - no snapshot / corrupt / invalid -> ``unavailable`` (never an empty success)
    """
    path = path or _STANDINGS_PATH
    stale_after_s = _DEFAULT_STALE_AFTER_S if stale_after_s is None else stale_after_s
    snap = _read_valid(path)
    if snap is None:
        return {
            "event": EVENT_ID,
            "standings": [],
            "asOf": None,
            "source": None,
            "status": "unavailable",
            "reason": "no valid published Club Championship snapshot exists; "
                      "no permitted machine-readable publisher resolved (see "
                      "docs/ewc2026/PHASE0-SOURCE-AND-CONTRACTS.md)",
        }
    published_at = snap.get("publishedAt")
    try:
        import datetime as _dt
        parsed = _dt.datetime.fromisoformat(published_at).timestamp()
    except Exception:
        parsed = 0.0
    age = time.time() - parsed
    status = "stale" if age > stale_after_s else "current"
    src = snap.get("source") or {}
    return {
        "event": EVENT_ID,
        "standings": snap.get("standings", []),
        "asOf": published_at,
        "source": {"label": src.get("label"), "url": src.get("url")},
        "status": status,
    }


def refresh_standings(path=None, cooldown_s=None):
    """Attempt one upstream publication while preserving the last good snapshot."""
    global _refresh_last_attempt
    cooldown_s = _REFRESH_COOLDOWN_S if cooldown_s is None else cooldown_s
    if not _refresh_lock.acquire(blocking=False):
        return {"attempted": False, "succeeded": False, "reason": "refresh_in_progress"}
    try:
        now = time.monotonic()
        retry_after = cooldown_s - (now - _refresh_last_attempt)
        if _refresh_last_attempt and retry_after > 0:
            return {
                "attempted": False,
                "succeeded": False,
                "reason": "refresh_cooldown",
                "retryAfterSeconds": int(retry_after) + 1,
            }
        _refresh_last_attempt = now
        try:
            import fetch_ewc_standings as fetcher
            snapshot = fetcher.fetch_validated_snapshot()
            publish_standings(snapshot, path=path or _STANDINGS_PATH)
            return {
                "attempted": True,
                "succeeded": True,
                "publishedAt": snapshot["publishedAt"],
                "sourceRevision": snapshot["source"].get("revision"),
            }
        except Exception as exc:
            return {
                "attempted": True,
                "succeeded": False,
                "reason": "upstream_refresh_failed",
                "error": str(exc),
            }
    finally:
        _refresh_lock.release()

# ---------------------------------------------------------------------------
# EWC router — event payload + published Club Championship reader
# ---------------------------------------------------------------------------
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

_EVENT_NAME = "Esports World Cup 2026"
# A completed EWC match keeps the module active for this long after it ends; the module then
# expires automatically and the page falls back to the generic board. No hard-coded dates.
_ACTIVE_RESULT_TAIL_S = 24 * 3600


# ---------------------------------------------------------------------------
# Data-derived title coverage — published schedule snapshots + slate feed counts
# ---------------------------------------------------------------------------
def _title_coverage():
    """Per-title schedule coverage from the published per-title schedule snapshots.

    Reads ONLY local published snapshot files (``backend/data/esports_ewc_schedules/``) —
    no request-path network calls. A title with no snapshot is honestly ``unavailable``.
    """
    from fetch_ewc_title_schedules import read_snapshot

    out = {}
    for title in EWC_TITLES:
        slug = title["slug"]
        snap = read_snapshot(slug)
        if not snap or not isinstance(snap, dict):
            out[slug] = {
                "status": "program", "count": 0, "datedCount": 0,
                "firstStart": None, "lastStart": None,
                "firstDate": title["programFirstDate"],
                "lastDate": title["programLastDate"], "lifecycle": None,
                "reason": "match-level schedule not published",
                "source": _PROGRAM_SOURCE,
            }
            continue
        sched = snap.get("schedule") or {}
        src = snap.get("source") or {}
        out[slug] = {
            "status": sched.get("status", "published"),
            "count": sched.get("count", 0),
            "datedCount": sched.get("datedCount", 0),
            "firstStart": sched.get("firstStart"),
            "lastStart": sched.get("lastStart"),
            "firstDate": sched.get("firstDate"),
            "lastDate": sched.get("lastDate"),
            "lifecycle": snap.get("lifecycle"),
            "reason": None,
            "source": {"label": src.get("label"), "urls": src.get("urls"),
                        "revisions": src.get("revisions"),
                        "publishedAt": src.get("publishedAt")},
        }
    return out


def _titles_payload(ewc_matches, coverage):
    """The Games-tab title list: catalog identity + data-derived schedule + feed counts.

    The hardcoded program ``weeks`` are NOT exposed here — tile labels must reflect data
    coverage (published schedule window / feed rows), never program branding claims.
    """
    titles = []
    for title in EWC_TITLES:
        slug = title["slug"]
        cov = coverage.get(slug, {})
        feed_count = sum(1 for m in ewc_matches if m.get("title") in title["feedTitles"])
        titles.append({
            "slug": slug,
            "name": title["name"],
            "tournaments": title["tournaments"],
            "feedTitles": title["feedTitles"],
            "logo": title["logo"],
            "schedule": {
                "status": cov.get("status", "unavailable"),
                "count": cov.get("count", 0),
                "datedCount": cov.get("datedCount", 0),
                "firstStart": cov.get("firstStart"),
                "lastStart": cov.get("lastStart"),
                "firstDate": cov.get("firstDate"),
                "lastDate": cov.get("lastDate"),
                "lifecycle": cov.get("lifecycle"),
                "reason": cov.get("reason"),
                "source": cov.get("source"),
            },
            "feedCount": feed_count,
        })
    return titles


@router.get("/api/esports/events/ewc-2026")
def ewc_event_data():
    """The EWC 2026 event payload over the existing normalized esports slate.

    Filters the shared board by the normalized event identity (``ewcEventId``) stamped at the
    backend boundary — never a UI substring search. Returns live / upcoming / completed buckets
    plus ``active`` so the page can fall back to the generic board when the event expires, and
    per-title data coverage (published schedule snapshots + feed counts) for the Games tab.
    """
    from .slate import esports_upcoming

    board = esports_upcoming()
    matches = board.get("matches") or []
    ewc_matches = [m for m in matches if m.get("ewcEventId") == EVENT_ID]
    coverage = _title_coverage()
    titles = _titles_payload(ewc_matches, coverage)
    if board.get("building") and not matches:
        return {"eventId": EVENT_ID, "eventName": _EVENT_NAME, "active": False,
                "building": True, "matches": {"live": [], "upcoming": [], "completed": []},
                "titles": titles, "titleCount": _EWC_TITLE_COUNT,
                "tournamentCount": _EWC_TOURNAMENT_COUNT,
                "programSource": _PROGRAM_SOURCE, "brandSource": _BRAND_SOURCE, "asOf": None}
    now_ms = time.time() * 1000
    live, upcoming, completed = [], [], []
    for m in ewc_matches:
        if m.get("live"):
            live.append(m)
        elif m.get("finished"):
            completed.append(m)
        else:
            upcoming.append(m)
    def _sort(bucket, desc=False):
        return sorted(bucket, key=lambda x: (x.get("startTime") or 0), reverse=desc)
    completed = _sort(completed, desc=True)
    upcoming = _sort(upcoming)
    active = bool(live or upcoming) or any(
        (m.get("endTime") or 0) >= now_ms - _ACTIVE_RESULT_TAIL_S * 1000 for m in completed)
    return {
        "eventId": EVENT_ID,
        "eventName": _EVENT_NAME,
        "active": active,
        "titles": titles,
        "titleCount": _EWC_TITLE_COUNT,
        "tournamentCount": _EWC_TOURNAMENT_COUNT,
        "programSource": _PROGRAM_SOURCE,
        "brandSource": _BRAND_SOURCE,
        "matches": {"live": live, "upcoming": upcoming, "completed": completed},
        "asOf": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _title_by_slug(slug):
    return next((title for title in EWC_TITLES if title["slug"] == slug), None)


def _snapshot_match(row, title):
    """Map a validated local snapshot row onto the shared frontend match contract."""
    score_a = row.get("scoreA")
    score_b = row.get("scoreB")
    finished = bool(row.get("finished"))
    canceled = bool(row.get("canceled"))
    winner = None
    if finished and score_a is not None and score_b is not None and score_a != score_b:
        winner = "a" if score_a > score_b else "b"
    stage = row.get("stage")
    source_match_id = row.get("sourceMatchId") or ""
    if source_match_id.startswith("pandascore:"):
        source_label = "pandascore-snapshot"
    elif source_match_id.startswith("lichess:"):
        source_label = "lichess-snapshot"
    else:
        source_label = "liquipedia-snapshot"
    return {
        "startTime": row.get("startTime"),
        "endTime": row.get("startTime") if finished else None,
        "live": False,
        "finished": finished,
        "canceled": canceled,
        "title": title["name"],
        "league": "%s%s" % (_EVENT_NAME, " — %s" % stage if stage else ""),
        "teamA": row.get("teamA") or "Participant pending",
        "teamB": row.get("teamB") or "Participant pending",
        "favorite": None,
        "watch": None,
        "score": {"a": score_a, "b": score_b} if score_a is not None else None,
        "winner": winner,
        "ewcEventId": EVENT_ID,
        "eventId": source_match_id,
        "sourceMatchId": source_match_id,
        "source": source_label,
    }


def _norm_name(value):
    return " ".join((value or "").casefold().split())


def _same_published_match(left, right):
    """Cross-source duplicate evidence; a timestamp by itself is never sufficient."""
    left_id = left.get("sourceMatchId")
    right_id = right.get("sourceMatchId")
    if left_id and right_id and left_id == right_id:
        return True
    left_teams = (_norm_name(left.get("teamA")), _norm_name(left.get("teamB")))
    right_teams = (_norm_name(right.get("teamA")), _norm_name(right.get("teamB")))
    if not all(left_teams + right_teams) or left_teams != right_teams:
        return False
    left_start = left.get("startTime")
    right_start = right.get("startTime")
    if isinstance(left_start, (int, float)) and isinstance(right_start, (int, float)):
        if abs(left_start - right_start) <= 6 * 3600 * 1000:
            return True
    if left.get("finished") and right.get("finished"):
        return left.get("score") is not None and left.get("score") == right.get("score")
    return False


def _merge_title_matches(snapshot_rows, slate_rows):
    """Prefer actively changing slate rows over frozen duplicates, retaining distinct rows."""
    merged = list(snapshot_rows)
    for slate_row in slate_rows:
        duplicate = next((i for i, row in enumerate(merged)
                          if _same_published_match(row, slate_row)), None)
        if duplicate is None:
            merged.append(slate_row)
        else:
            merged[duplicate] = slate_row
    return merged


@router.get("/api/esports/events/ewc-2026/titles/{slug}/matches")
def ewc_title_matches(slug: str):
    """Bounded selected-title rows from a local snapshot plus the current normalized slate."""
    from fetch_ewc_title_schedules import read_snapshot
    from .slate import esports_upcoming

    title = _title_by_slug(slug)
    if title is None:
        raise HTTPException(status_code=404, detail="unknown EWC title")
    snapshot = read_snapshot(slug)
    snapshot_rows = [_snapshot_match(row, title) for row in (snapshot or {}).get("matches", [])]
    board = esports_upcoming()
    slate_rows = [
        row for row in (board.get("matches") or [])
        if row.get("ewcEventId") == EVENT_ID and row.get("title") in title["feedTitles"]
    ]
    rows = _merge_title_matches(snapshot_rows, slate_rows)
    live = sorted((row for row in rows if row.get("live")),
                  key=lambda row: row.get("startTime") or 0)
    # Canceled matches are resolved terminal facts: they belong with completed rows, not
    # with upcoming (they will never be played) and not in a fake result state.
    completed = sorted((row for row in rows
                        if not row.get("live") and (row.get("finished") or row.get("canceled"))),
                       key=lambda row: row.get("startTime") or 0, reverse=True)
    upcoming = sorted((row for row in rows
                       if not row.get("live") and not row.get("finished") and not row.get("canceled")),
                      key=lambda row: row.get("startTime") or 0)
    source = (snapshot or {}).get("source") or {}
    return {
        "eventId": EVENT_ID,
        "title": {"slug": slug, "name": title["name"]},
        "status": "published" if snapshot else "unavailable",
        "lifecycle": (snapshot or {}).get("lifecycle"),
        "source": {"label": source.get("label"), "urls": source.get("urls"),
                   "revisions": source.get("revisions")} if snapshot else None,
        "matches": {"live": live, "upcoming": upcoming, "completed": completed},
    }


@router.get("/api/esports/events/ewc-2026/club-standings")
def ewc_club_standings(limit: int = Query(10, ge=1, le=100)):
    """The published Club Championship reader: exactly one published snapshot, bounded limit.

    Desktop requests ten; mobile requests five and expands to ten. The complete published
    population is never served in full by the landing page. With no valid publication the route
    serves the honest unavailable state (never a self-certified empty success, never zero points).
    """
    out = read_standings()
    if out["status"] != "unavailable":
        out["standings"] = out["standings"][:limit]
    return out


@router.post("/api/esports/events/ewc-2026/club-standings/refresh")
def ewc_club_standings_refresh(limit: int = Query(10, ge=1, le=100)):
    """Refresh from the publisher, then return the refreshed or last-good snapshot."""
    refresh = refresh_standings()
    out = read_standings()
    if out["status"] != "unavailable":
        out["standings"] = out["standings"][:limit]
    out["refresh"] = refresh
    return out
