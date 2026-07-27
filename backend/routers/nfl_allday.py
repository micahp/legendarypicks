#!/usr/bin/env python3
"""nfl_allday.py — NFL All Day collection viewer on Flow blockchain.

Read-only: queries the Flow Access API (REST, no FCL) for an address's AllDay
moments and resolves each to an NFL player in our `players` table.

Endpoint:
  GET /api/nfl/allday/collection?address=0x...&limit=200&offset=0

Why this is paged
-----------------
Real collections are far larger than the mint-halt headlines suggest — measured
on mainnet 2026-07-27, holders run to 66,387 moments. Resolving every moment's
metadata in one Cadence script exceeds Flow's per-script computation limit
somewhere between 572 and 1,254 moments, and the node answers 400. So we read
the id list first (cheap), then resolve one page of metadata at a time.

Hybrid Custody
--------------
Dapper wallets are Hybrid Custody parents: the address a user sees in the NFL
All Day UI often owns nothing itself, and the moments sit in a linked child
account. When the pasted address has no collection of its own we walk its
`HybridCustody.Manager` children and read theirs, reporting which accounts the
moments actually came from.

Cache: per (address, limit, offset) responses are cached in-process for 60s so a
re-render is not a re-query against mainnet.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from typing import Any, Optional

import requests
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/nfl/allday", tags=["nfl-allday"])
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FLOW_REST = "https://rest-mainnet.onflow.org"
FLOW_SCRIPTS_API = f"{FLOW_REST}/v1/scripts"
FLOW_ACCOUNTS_API = f"{FLOW_REST}/v1/accounts"
ALLDAY_ADDRESS = "0xe4cf4bdc1751c65d"
COLLECTION_PUBLIC_PATH = "/public/AllDayNFTCollection"

# Flow address: 0x + 16 hex chars
FLOW_ADDRESS_RE = r"^0x[0-9a-fA-F]{16}$"

# Metadata for this many moments per Cadence script. 572 was measured working
# and 1,254 measured failing, so stay well under the cliff.
FLOW_BATCH_SIZE = 200
DEFAULT_LIMIT = 200
MAX_LIMIT = 1000
MAX_CHILD_ACCOUNTS = 10

# Team full-name → abbreviation (for display; join is on name+position, not team)
TEAM_ABBREV: dict[str, str] = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}

# Position reconciliation: AllDay → our DB position
POSITION_MAP: dict[str, list[str]] = {
    "QB": ["QB"], "RB": ["RB", "FB"], "WR": ["WR"], "TE": ["TE"],
    "DB": ["CB", "S", "DB", "FS", "SS"], "CB": ["CB", "DB"], "S": ["S", "DB", "FS", "SS"],
    "LB": ["LB", "OLB", "ILB", "MLB"], "OLB": ["OLB", "LB"], "ILB": ["ILB", "LB"],
    "DE": ["DE", "DL"], "DT": ["DT", "DL"], "DL": ["DL", "DE", "DT", "NT"],
    "OT": ["OT", "OL", "T"], "OG": ["OG", "OL", "G"], "C": ["C", "OL"],
    "OL": ["OL", "OT", "OG", "C", "T", "G"],
    "K": ["K"], "P": ["P"], "LS": ["LS"],
}

# The metadata block is identical in both scripts; keep one copy.
_MOMENT_BODY = """
        var data: {String: AnyStruct} = {}
        data["id"] = id

        if let display = nft.resolveView(Type<MetadataViews.Display>()) {
            let d = display as! MetadataViews.Display
            data["name"] = d.name
            data["thumbnail"] = d.thumbnail.uri()
        }
        if let serialView = nft.resolveView(Type<MetadataViews.Serial>()) {
            let s = serialView as! MetadataViews.Serial
            data["serial"] = s.number
        }
        if let extView = nft.resolveView(Type<MetadataViews.ExternalURL>()) {
            let ext = extView as! MetadataViews.ExternalURL
            data["url"] = ext.url
        }
        if let allDayNFT = nft as? &AllDay.NFT {
            let edition = AllDay.getEditionData(id: allDayNFT.editionID)
            let play = AllDay.getPlayData(id: edition.playID)
            let series = AllDay.getSeriesData(id: edition.seriesID)
            let set = AllDay.getSetData(id: edition.setID)

            data["playerFirstName"] = play.metadata["playerFirstName"] ?? ""
            data["playerLastName"] = play.metadata["playerLastName"] ?? ""
            data["playerPosition"] = play.metadata["playerPosition"] ?? ""
            data["teamName"] = play.metadata["teamName"] ?? ""
            data["playerNumber"] = play.metadata["playerNumber"] ?? ""
            data["playType"] = play.metadata["playType"] ?? ""
            data["season"] = play.metadata["season"] ?? ""
            data["seriesName"] = series.name
            data["setDisplayName"] = set.name
            data["tier"] = edition.tier
            data["editionID"] = allDayNFT.editionID
        }
"""

# Cheap: does this address have a collection, and what ids are in it?
CADENCE_IDS = """
import NonFungibleToken from 0x1d7e57aa55817448

access(all) fun main(address: Address): {String: AnyStruct} {
    let cap = getAccount(address).capabilities
        .get<&{NonFungibleToken.CollectionPublic}>(/public/AllDayNFTCollection)
    if !cap.check() {
        return {"hasCollection": false, "ids": [] as [UInt64]}
    }
    return {"hasCollection": true, "ids": cap.borrow()!.getIDs()}
}
"""

# Expensive: resolve metadata for an explicit page of ids.
CADENCE_MOMENTS = """
import NonFungibleToken from 0x1d7e57aa55817448
import MetadataViews from 0x1d7e57aa55817448
import AllDay from 0xe4cf4bdc1751c65d

access(all) fun main(address: Address, ids: [UInt64]): [{String: AnyStruct}] {
    let cap = getAccount(address).capabilities
        .get<&{NonFungibleToken.CollectionPublic}>(/public/AllDayNFTCollection)
    if !cap.check() { return [] }
    let collection = cap.borrow()!

    var moments: [{String: AnyStruct}] = []
    for id in ids {
        let nft = collection.borrowNFT(id)!
__BODY__
        moments.append(data)
    }
    return moments
}
""".replace("__BODY__", _MOMENT_BODY)

# Hybrid Custody: which child accounts does this address manage?
CADENCE_CHILDREN = """
import HybridCustody from 0xd8a7e05a7ac670c0

access(all) fun main(address: Address): [Address] {
    let acct = getAuthAccount<auth(Storage) &Account>(address)
    if let m = acct.storage.borrow<&HybridCustody.Manager>(
        from: HybridCustody.ManagerStoragePath
    ) {
        return m.getChildAddresses()
    }
    return []
}
"""

# ---------------------------------------------------------------------------
# In-process cache
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, Any]] = {}  # cache key → (expires_at, response)
CACHE_TTL_S = 60
CACHE_MAX_SIZE = 64


def _cache_get(key: str) -> Optional[dict]:
    if key not in _cache:
        return None
    expires, data = _cache[key]
    if time.time() > expires:
        del _cache[key]
        return None
    return data


def _cache_set(key: str, data: dict) -> None:
    # Evict oldest if at capacity
    while len(_cache) >= CACHE_MAX_SIZE:
        oldest = min(_cache.keys(), key=lambda k: _cache[k][0])
        del _cache[oldest]
    _cache[key] = (time.time() + CACHE_TTL_S, data)


# ---------------------------------------------------------------------------
# JSON-Cadence decoder
# ---------------------------------------------------------------------------

def _decode_json_cadence(v):
    """Recursively decode JSON-Cadence values to plain Python."""
    if isinstance(v, dict):
        t = v.get("type", "")
        val = v.get("value")
        if t == "Dictionary":
            result = {}
            for entry in val:
                k = _decode_json_cadence(entry["key"])
                result[k] = _decode_json_cadence(entry["value"])
            return result
        elif t == "Array":
            return [_decode_json_cadence(x) for x in val]
        elif t == "Optional":
            return _decode_json_cadence(val) if val is not None else None
        elif t in ("String", "UInt64", "Int", "UFix64", "Fix64", "Bool",
                   "Address", "Word64", "Word32", "Word16", "Word8"):
            return val
        elif t == "Path":
            return val.get("value", str(val)) if isinstance(val, dict) else str(val)
        else:
            return _decode_json_cadence(val) if isinstance(val, (dict, list)) else val
    elif isinstance(v, list):
        return [_decode_json_cadence(x) for x in v]
    return v


# ---------------------------------------------------------------------------
# Flow query helpers
# ---------------------------------------------------------------------------

class FlowError(Exception):
    """A Flow read failed. Carries an operator-facing detail we do NOT return."""


def _cadence_arg(type_name: str, value) -> str:
    return base64.b64encode(
        json.dumps({"type": type_name, "value": value}).encode()
    ).decode()


def _flow_script(script: str, args: list[str]) -> Any:
    """Execute a Cadence script and return the decoded value.

    Raises FlowError with the upstream detail attached for logging. The caller
    must never surface that detail to the client — it contains our request URL
    and the raw node error.
    """
    try:
        resp = requests.post(
            FLOW_SCRIPTS_API,
            json={"script": base64.b64encode(script.encode()).decode(), "arguments": args},
            timeout=30,
        )
    except requests.RequestException as e:
        raise FlowError(f"transport: {e}") from e

    if resp.status_code != 200:
        raise FlowError(f"HTTP {resp.status_code}: {resp.text[:500]}")

    try:
        body = resp.json()
        decoded = base64.b64decode(body).decode("utf-8") if isinstance(body, str) else body
        return _decode_json_cadence(json.loads(decoded)
                                    if isinstance(decoded, str) else decoded)
    except (ValueError, KeyError, TypeError) as e:
        raise FlowError(f"decode: {e}") from e


def _account_exists(address: str) -> bool:
    """Flow returns 400 for an address that was never created on mainnet."""
    try:
        r = requests.get(f"{FLOW_ACCOUNTS_API}/{address}", timeout=15)
        return r.status_code == 200
    except requests.RequestException as e:
        raise FlowError(f"account lookup: {e}") from e


def _get_ids(address: str) -> tuple[bool, list[int]]:
    """Return (has_collection, sorted ids) for an address."""
    res = _flow_script(CADENCE_IDS, [_cadence_arg("Address", address)]) or {}
    has = bool(res.get("hasCollection"))
    ids = sorted(int(i) for i in (res.get("ids") or []))
    return has, ids


def _get_children(address: str) -> list[str]:
    """Hybrid Custody child accounts, or [] if the address manages none."""
    try:
        return [str(a) for a in (_flow_script(
            CADENCE_CHILDREN, [_cadence_arg("Address", address)]) or [])]
    except FlowError as e:
        # An address with no Manager resource is the common case, not an error.
        log.info("allday: no hybrid-custody manager for %s (%s)", address, e)
        return []


def _get_moments(address: str, ids: list[int]) -> list[dict]:
    """Resolve metadata for an explicit list of ids, batched under the limit."""
    out: list[dict] = []
    for i in range(0, len(ids), FLOW_BATCH_SIZE):
        batch = ids[i:i + FLOW_BATCH_SIZE]
        res = _flow_script(CADENCE_MOMENTS, [
            _cadence_arg("Address", address),
            _cadence_arg("Array", [{"type": "UInt64", "value": str(x)} for x in batch]),
        ])
        out.extend(res or [])
    return out


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_db():
    """Return a sqlite3 connection to the picks DB."""
    import sqlite3
    db_path = os.environ.get("LP_DB_PATH", "data/picks.dev.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


_SUFFIX_RE = re.compile(r"\s+(?:jr|sr|ii|iii|iv|v)\.?$", re.I)


def _norm_name(name: str) -> str:
    """Lowercase, strip generational suffix and punctuation that varies by source."""
    n = _SUFFIX_RE.sub("", name.strip().lower())
    return re.sub(r"[.\'`-]", "", n).replace("  ", " ").strip()


class PlayerResolver:
    """Resolves AllDay player names against `players` using one connection.

    The previous implementation opened a fresh sqlite connection and ran up to
    two queries per moment. At 200 moments a page that is 200 connections and
    400 queries for a table small enough to hold in memory once.
    """

    def __init__(self) -> None:
        self._by_name: dict[str, list[dict]] = {}
        conn = _get_db()
        try:
            for row in conn.execute(
                "SELECT id, name, position, team, nfl_gsis_id, active "
                "FROM players WHERE league='nfl'"
            ):
                r = dict(row)
                self._by_name.setdefault(_norm_name(r["name"]), []).append(r)
        finally:
            conn.close()

    def resolve(self, first: str, last: str, position: str) -> Optional[dict]:
        full_key = _norm_name(f"{first} {last}")

        # Step 1 — exact normalised full-name match (existing behaviour, unchanged)
        rows = self._by_name.get(full_key)
        if rows:
            return self._disambiguate(rows, position)

        # Step 2 — FULL_NAME_ALIASES lookup (legal name changes)
        from .nfl_name_aliases import FULL_NAME_ALIASES
        aliased = FULL_NAME_ALIASES.get(full_key)
        if aliased:
            rows = self._by_name.get(aliased)
            if rows:
                return self._disambiguate(rows, position)

        # Step 3 — first-name expansion with exact surname match
        from .nfl_name_aliases import expand_first_names
        norm_first = _norm_name(first)
        norm_last = _norm_name(last)
        candidates: list[dict] = []
        for variant in expand_first_names(norm_first):
            key = f"{variant} {norm_last}"
            rows = self._by_name.get(key)
            if rows:
                candidates.extend(rows)

        if not candidates:
            return None

        # Deduplicate by id
        seen: dict[int, dict] = {}
        for c in candidates:
            seen.setdefault(c["id"], c)
        unique = list(seen.values())

        if len(unique) == 1:
            # One candidate — accept even when position disagrees (AllDay says DL
            # where our spine says LB for Gregory Rousseau — vocabulary difference).
            return unique[0]

        # Multiple candidates — position disambiguates; it does not reject
        allowed = POSITION_MAP.get(position, [position])
        pos_matches = [c for c in unique if c["position"] in allowed]
        if len(pos_matches) == 1:
            return pos_matches[0]

        # Either zero or >1 position matches — ambiguous.  Return None rather
        # than guessing (Scotty Miller must stay unmatched — there are two
        # Scott Millers and picking either is a wrong join).
        return None

    def _disambiguate(self, rows: list[dict], position: str) -> Optional[dict]:
        """Pick the right row when multiple players share a name."""
        if len(rows) == 1:
            return rows[0]
        allowed = POSITION_MAP.get(position, [position])
        for row in rows:
            if row["position"] in allowed:
                return row
        # Ambiguous across eras and position did not separate them; prefer
        # an active player over a retired one rather than an arbitrary row.
        for row in rows:
            if row.get("active"):
                return row
        return rows[0]

# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

def _empty(address: str, status: str, sources: list[str] | None = None) -> dict:
    return {
        "address": address, "moments": [], "total": 0, "returned": 0,
        "matched": 0, "unmatched": 0, "nonPlayer": 0, "offset": 0, "limit": 0,
        "status": status, "sources": sources or [],
    }


@router.get("/collection")
def get_collection(
    address: str = Query(..., description="Flow wallet address (0x...)"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    nocache: bool = Query(False, description="Bypass cache for debugging"),
):
    """Return NFL All Day moments for a Flow wallet, resolved against our players DB.

    `status` tells the caller *why* a collection is empty, which the UI needs in
    order to say something true:
      ok             — moments returned
      no_account     — that address does not exist on Flow mainnet
      no_collection  — the account exists but holds no AllDay collection
      empty          — it has a collection with nothing in it
    """
    if not re.match(FLOW_ADDRESS_RE, address):
        raise HTTPException(
            status_code=400,
            detail="Invalid Flow address format. Expected 0x + 16 hex chars.",
        )

    cache_key = f"{address}:{limit}:{offset}"
    if not nocache:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    try:
        has_collection, ids = _get_ids(address)

        # Dapper wallets own nothing directly — the moments are in linked child
        # accounts. Only pay for that lookup when the address itself is empty.
        sources: list[tuple[str, list[int]]] = []
        if has_collection and ids:
            sources.append((address, ids))
        else:
            for child in _get_children(address)[:MAX_CHILD_ACCOUNTS]:
                c_has, c_ids = _get_ids(child)
                if c_has and c_ids:
                    sources.append((child, c_ids))

        if not sources:
            if not has_collection and not _account_exists(address):
                return _empty(address, "no_account")
            return _empty(address, "no_collection" if not has_collection else "empty")

        # Page across the concatenated id space so offset/limit are stable.
        flat = [(acct, i) for acct, acct_ids in sources for i in acct_ids]
        total = len(flat)
        page = flat[offset:offset + limit]

        by_account: dict[str, list[int]] = {}
        for acct, i in page:
            by_account.setdefault(acct, []).append(i)

        raw_moments: list[dict] = []
        for acct, acct_ids in by_account.items():
            raw_moments.extend(_get_moments(acct, acct_ids))

    except FlowError as e:
        # Log the upstream detail; never return it. It contains our request URL.
        log.warning("allday: Flow read failed for %s — %s", address, e)
        raise HTTPException(
            status_code=502,
            detail="Could not read that wallet from the Flow network. Try again shortly.",
        ) from e

    resolver = PlayerResolver()
    resolved: list[dict] = []
    matched = 0
    unmatched = 0
    non_player = 0

    for m in raw_moments:
        first = str(m.get("playerFirstName", "")).strip()
        last = str(m.get("playerLastName", "")).strip()
        pos = str(m.get("playerPosition", "")).strip()
        team_full = str(m.get("teamName", "")).strip()

        moment_out = {
            "momentId": int(m.get("id", 0)),
            "displayName": str(m.get("name", "")),
            "thumbnail": str(m.get("thumbnail", "")),
            "url": str(m.get("url", "")),
            "firstName": first,
            "lastName": last,
            "position": pos,
            "teamName": team_full,
            "teamAbbrev": TEAM_ABBREV.get(team_full, team_full),
            "playerNumber": str(m.get("playerNumber", "")),
            "playType": str(m.get("playType", "")),
            "tier": str(m.get("tier", "")),
            "serial": int(m.get("serial", 0) or 0),
            "seriesName": str(m.get("seriesName", "")),
            "setName": str(m.get("setDisplayName", "")),
            "season": str(m.get("season", "")),
        }

        # Not every moment is a player moment. AllDay ships team highlights -- e.g. playType
        # "Team Melt" in the "What a Drive" set -- with playerFirstName/playerLastName empty on
        # chain. Counting those as a failed join blames our players table for data AllDay never
        # published, and drags an otherwise ~100% player-moment match rate down to ~94%.
        is_player_moment = bool(first and last)
        moment_out["isPlayerMoment"] = is_player_moment

        if not is_player_moment:
            moment_out["player"] = None
            non_player += 1
            resolved.append(moment_out)
            continue

        player = resolver.resolve(first, last, pos)
        if player:
            moment_out["player"] = {
                "id": player["id"],
                "name": player["name"],
                "position": player["position"],
                "team": player["team"],
                "gsisId": player.get("nfl_gsis_id", ""),
                "active": bool(player.get("active", False)),
            }
            matched += 1
        else:
            moment_out["player"] = None
            unmatched += 1

        resolved.append(moment_out)

    result = {
        "address": address,
        "moments": resolved,
        "total": total,
        "returned": len(resolved),
        "matched": matched,
        "unmatched": unmatched,
        "nonPlayer": non_player,
        "offset": offset,
        "limit": limit,
        "status": "ok",
        "sources": [acct for acct, _ in sources],
    }

    _cache_set(cache_key, result)
    return result
