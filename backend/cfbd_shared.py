"""Shared CollegeFootballData transport, team, and season helpers.

Identity and game-log publishers are separate jobs, but they consume the same
CFBD endpoint contract and the same canonical NCAAF vocabulary.  Keeping those
boundary rules here prevents the two publishers from drifting.
"""
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request

import team_codes


LEAGUE = "ncaaf"
_API = "https://api.collegefootballdata.com"
_MIN_INTERVAL = float(os.environ.get("LP_CFBD_MIN_INTERVAL") or 1.0)
_HDRS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "Chrome/124 Safari/537.36"
    )
}


def _api_key():
    key = os.environ.get("CFBD_API_KEY")
    if key:
        return key
    env_path = os.path.join(os.path.expanduser("~"), ".hermes", ".env")
    try:
        with open(env_path) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("CFBD_API_KEY="):
                    return line.split("=", 1)[1]
    except OSError:
        pass
    raise RuntimeError("CFBD_API_KEY not found (env or ~/.hermes/.env)")


_last_request = [0.0]


class CfbdError(Exception):
    pass


def _get_json(url):
    """Make one paced CFBD request with a bounded 429/5xx retry ladder."""
    gap = _MIN_INTERVAL - (time.monotonic() - _last_request[0])
    if gap > 0:
        time.sleep(gap)
    attempts = 4
    last = None
    for i in range(attempts):
        req = urllib.request.Request(url, headers=_HDRS)
        req.add_header("Authorization", "Bearer " + _api_key())
        try:
            _last_request[0] = time.monotonic()
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = "HTTP %s" % exc.code
            if exc.code in (400, 401, 403):
                break
            time.sleep(min(30, 2.0 * (i + 1)))
        except OSError as exc:
            last = "%s: %s" % (type(exc).__name__, exc)
            time.sleep(min(30, 2.0 * (i + 1)))
    raise CfbdError("%s failed after %d attempts: %s" % (url, attempts, last))


_NAME_BY_CODE = {}
try:
    with open(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "docs",
        "espn-team-codes-2026-07-27.json",
    )) as _fh:
        _NAME_BY_CODE = {
            code: str(name or "").lower()
            for code, name in (json.load(_fh).get(LEAGUE) or {}).items()
        }
except OSError:
    _NAME_BY_CODE = {}


def _school_to_code(school, abbrev):
    """Return the canonical ESPN code for a CFBD team, or ``None``."""
    ab = (abbrev or "").strip().upper()
    if ab and team_codes.is_canonical(LEAGUE, ab):
        return ab
    school_name = (school or "").strip().lower()
    if school_name:
        for code, display in _NAME_BY_CODE.items():
            if display.startswith(school_name):
                return code
    return None


def _season_from_the_schedule(db_path):
    """Read the current NCAAF season key from the newest stored schedule game."""
    try:
        con = sqlite3.connect("file:{}?mode=ro".format(db_path), uri=True, timeout=20)
    except sqlite3.Error:
        return None
    try:
        row = con.execute(
            "SELECT max(date) FROM prop_games WHERE league='ncaaf'"
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if not row or not row[0]:
        return None
    year, month = int(str(row[0])[:4]), int(str(row[0])[5:7])
    return year - 1 if month <= 2 else year
