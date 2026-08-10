#!/usr/bin/env python3
"""Operator-run, published-first EWC 2026 per-title schedule fetcher.

Single writer for ``backend/data/esports_ewc_schedules/<slug>.json``. Source: Liquipedia
MediaWiki API (terms explicitly allow API access; NO HTML page scraping, NO request-path
fetching). One ``action=parse`` call per competition page (wikitext + revid), gzip
Accept-Encoding, descriptive LegendaryPicks User-Agent — the same approved channel as the
Club Championship standings fetcher.

Extraction contract (never invents data):
  - Finds ``{{Match}}`` / ``{{SingleMatch}}`` / ``{{Match2}}`` template blocks (balanced
    braces) in the published wikitext.
  - Per match: ``date`` (normalized ISO date + epoch ms when parseable; else None = the
    source has not published a date), ``opponent1/opponent2`` (named team -> name + Liquipedia
    slug; ``LiteralOpponent``/empty/``{{N Opponent}}`` -> PENDING participant, never a
    fabricated name), ``score1/score2`` (numeric, nonnegative when present), ``finished``,
    nearest ``{{Stage|...}}`` header as the stage label.
  - Qualifier rows (stage/section containing "qualifier"/"lcq") are excluded, mirroring the
    standings qualifier exclusion.
  - A page with ZERO match templates is recorded as schedule ``unavailable`` (no snapshot is
    published for it) — the honest "not machine-readable / not published" state, never an
    empty success.
  - Validation: revision present, every extracted block parses, dates parse or are null,
    scores numeric nonnegative, population = all blocks on the page. Atomic last-good
    publication per title (tmp + os.replace).

Usage (cwd=backend/, venv interpreter):
    venv/bin/python fetch_ewc_title_schedules.py              # fetch + publish all titles
    venv/bin/python fetch_ewc_title_schedules.py --slug dota-2 --dry-run
"""

import argparse
import datetime as _dt
import gzip
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

API_UA = ("LegendaryPicks/1.0 (EWC title schedule ingest; "
          "contact via github.com/legendarypicks)")
SOURCE_LABEL = "Liquipedia — EWC 2026"
PARSE_MIN_INTERVAL_S = 30.0  # MediaWiki API terms: action=parse <= 1 request / 30s.
SCHEDULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "data", "esports_ewc_schedules")
SCHEMA_VERSION = 1
MANIFEST_FILE = "manifest.json"
LIFECYCLES = ("upcoming", "active", "final")
UPCOMING_MAX_AGE_S = int(os.environ.get("LP_EWC_UPCOMING_MAX_AGE_S", "86400"))
ACTIVE_MAX_AGE_S = int(os.environ.get("LP_EWC_ACTIVE_MAX_AGE_S", "21600"))

# Official EWC 2026 program page map: slug -> [(liquipedia subwiki, page)].  Mobile Legends
# spans two tournaments (MSC + MWI) so it has two pages merged into one snapshot.  These page
# names come from the EWC 2026 Club Championship page's own competition index (captured
# fixture, rev 15997) — the authoritative program reference.
TITLE_PAGES = {
    "apex-legends": [("apexlegends", "Apex Legends Global Series/2026/Split 1/Playoffs")],
    "call-of-duty-black-ops-7": [("callofduty", "Esports World Cup/2026/BO7")],
    "call-of-duty-warzone": [("callofduty", "Warzone Resurgence Series/2026")],
    "chess": [("chess", "Esports World Cup/2026")],
    "counter-strike-2": [("counterstrike", "Esports World Cup/2026")],
    "crossfire": [("crossfire", "Esports World Cup/2026")],
    "dota-2": [("dota2", "Esports World Cup/2026")],
    "ea-sports-fc-26": [("easportsfc", "FC Pro 26/World Championship")],
    "fatal-fury-city-of-the-wolves": [("fighters", "Esports World Cup/2026/CotW")],
    "fortnite-reload": [("fortnite", "Reload Elite Series/2026")],
    "free-fire": [("freefire", "Esports World Cup/2026")],
    "honor-of-kings": [("honorofkings", "Honor of Kings World Cup/2026")],
    "league-of-legends": [("leagueoflegends", "Esports World Cup/2026")],
    "mobile-legends-bang-bang": [("mobilelegends", "MSC/2026"),
                                 ("mobilelegends", "MLBB Women's Invitational/2026")],
    "overwatch-2": [("overwatch", "Overwatch Champions Series/2026/Midseason Championship")],
    "pubg-battlegrounds": [("pubg", "Esports World Cup/2026")],
    "pubg-mobile": [("pubgmobile", "PUBG Mobile World Cup/2026")],
    "rainbow-six-siege": [("rainbowsix", "Esports World Cup/2026")],
    "rocket-league": [("rocketleague", "Esports World Cup/2026")],
    "street-fighter-6": [("fighters", "Esports World Cup/2026/SF6")],
    "teamfight-tactics": [("tft", "Esports World Cup/2026")],
    "tekken-8": [("fighters", "Esports World Cup/2026/T8")],
    "trackmania": [("trackmania", "Esports World Cup/2026")],
    "valorant": [("valorant", "Esports World Cup/2026")],
}

_MATCH_OPEN = re.compile(r"\{\{(Match|SingleMatch|Match2)(?=[\s|}\n])")

_TZ_OFFSETS = {
    "CEST": 2 * 3600, "CET": 3600, "UTC": 0, "GMT": 0,
    "EDT": -4 * 3600, "EST": -5 * 3600, "PDT": -7 * 3600, "PST": -8 * 3600,
    "BST": 3600, "KST": 9 * 3600, "JST": 9 * 3600, "SGT": 8 * 3600, "CST": 8 * 3600,
}


class ScheduleSourceError(ValueError):
    """A source-parsing or population validation failure — no snapshot may be published."""


_API_OPENER = urllib.request.build_opener()
_LAST_PARSE_REQUEST = None


def _operator_log(message):
    """Emit source-attempt progress immediately for durable operator transcripts."""
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print("[%s] %s" % (stamp, message), flush=True)


# ---------------------------------------------------------------------------
# Wikitext parsing helpers (balanced-brace aware)
# ---------------------------------------------------------------------------
def _closing(text, i):
    """Index just past the '}}' closing the '{{' at position i (handles nesting)."""
    depth = 0
    j = i
    while j < len(text) - 1:
        if text[j:j + 2] == "{{":
            depth += 1
            j += 2
        elif text[j:j + 2] == "}}":
            depth -= 1
            j += 2
            if depth == 0:
                return j
        else:
            j += 1
    raise ScheduleSourceError("unbalanced template braces in source")


def _split_params(body):
    """Split a template body into (name, value) params on top-level '|' separators."""
    params = {}
    depth = 0
    cur = []
    name = None
    started = False
    for ch in body:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        if ch == "|" and depth == 0 and started:
            piece = "".join(cur).strip()
            if "=" in piece:
                k, v = piece.split("=", 1)
                params[k.strip().lower()] = v.strip()
            elif name is not None:
                params[name] = piece  # positional continuation for the last named param
            cur = []
            started = False
        else:
            cur.append(ch)
            started = True
    piece = "".join(cur).strip()
    if "=" in piece:
        k, v = piece.split("=", 1)
        params[k.strip().lower()] = v.strip()
    elif name is not None:
        params[name] = piece
    return params


def _inner(text, i):
    """Return the raw inner text of the template starting at i (between the braces)."""
    end = _closing(text, i)
    return text[i + 2:end - 2], end


def _strip_wikilink(value):
    """'[[Name|Display]]' / '[[Name]]' -> display text; strips surrounding templates' noise."""
    v = value.strip()
    while v.startswith("{{") and "|" in v:
        v = v.split("|", 1)[1].rstrip("}").strip()
    m = re.fullmatch(r"\[\[([^\]|]*)(?:\|[^\]]*)?\]\]", v)
    if m:
        return m.group(1).strip()
    return v


# ---------------------------------------------------------------------------
# Date / opponent parsing
# ---------------------------------------------------------------------------
def parse_date(value):
    """Normalize a Liquipedia date param -> (iso_date, epoch_ms) or (None, None).

    Handles 'YYYY-MM-DD' and 'Month D, YYYY - HH:MM {{Abbr/TZ}}' forms. An empty
    value is (None, None) — the source has not published a date. A non-empty value
    that does not match the supported publisher formats rejects the candidate.
    """
    if not value or not isinstance(value, str) or not value.strip():
        return None, None
    v = " ".join(value.replace("{{Abbr/", "").replace("}}", "").replace(" - ", " ").split())
    tz = 0
    for abbr in _TZ_OFFSETS:
        if v.endswith(abbr):
            tz = _TZ_OFFSETS[abbr]
            v = v[: -len(abbr)].strip()
            break
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        try:
            d = _dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=_dt.timezone.utc)
        except ValueError as exc:
            raise ScheduleSourceError("malformed published date %r" % value) from exc
        return d.strftime("%Y-%m-%d"), int(d.timestamp() * 1000)
    m = re.fullmatch(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})(?: (\d{1,2}):(\d{2}))?", v)
    if m:
        try:
            d = _dt.datetime(int(m.group(3)), _dt.datetime.strptime(m.group(1), "%B").month,
                             int(m.group(2)), int(m.group(4) or 12), int(m.group(5) or 0),
                             tzinfo=_dt.timezone.utc) - _dt.timedelta(seconds=tz)
        except ValueError as exc:
            raise ScheduleSourceError("malformed published date %r" % value) from exc
        return d.strftime("%Y-%m-%d"), int(d.timestamp() * 1000)
    raise ScheduleSourceError("unsupported published date %r" % value)


def parse_opponent(value):
    """An opponent param -> (kind, name, slug, score).

    kind: 'named' (a real team), 'pending' (undecided bracket slot / literal placeholder —
    never fabricated). Empty TeamOpponent / {{N Opponent}} / empty value -> pending.
    """
    v = (value or "").strip()
    score = None
    m = re.fullmatch(r"\{\{(TeamOpponent|Team|LiteralOpponent)\|([^}]*)\}\}", v)
    if m:
        inner = m.group(2)
        parts = inner.split("|")
        body = parts[0].strip()
        if m.group(1) == "LiteralOpponent" or not body:
            return "pending", (body or None), None, score
        # {{TeamOpponent|[[Name]]|score=2}} etc.
        for p in parts[1:]:
            if p.strip().lower().startswith("score="):
                s = p.split("=", 1)[1].strip()
                if s:
                    try:
                        score = int(s)
                    except ValueError as exc:
                        raise ScheduleSourceError("malformed published score %r" % s) from exc
                    if score < 0:
                        raise ScheduleSourceError("negative published score %r" % score)
        name = _strip_wikilink(body)
        slug = re.sub(r"\s+", "_", name) if name else None
        return "named", name, slug, score
    m = re.fullmatch(r"\{\{\d+ ?Opponent\|([^}]*)\}\}", v)
    if m:
        label = m.group(1).strip() or None
        if label:
            name = _strip_wikilink(label)
            return "named", name, re.sub(r"\s+", "_", name), score
        return "pending", None, None, score
    if not v:
        return "pending", None, None, score
    if v.startswith("{{"):
        raise ScheduleSourceError("unsupported opponent template %r" % v[:80])
    return "named", _strip_wikilink(v), re.sub(r"\s+", "_", _strip_wikilink(v)), score


# ---------------------------------------------------------------------------
# Match extraction
# ---------------------------------------------------------------------------
def extract_matches(wikitext):
    """All Match-family blocks from the wikitext, with stage context and qualifier exclusion."""
    if not wikitext:
        return []
    unsupported = {name for name in re.findall(r"\{\{((?:Single)?Match\d+)\b", wikitext)
                   if name != "Match2"}
    if unsupported:
        raise ScheduleSourceError("unsupported match template(s): %s" %
                                  ", ".join(sorted(unsupported)))
    matches = []
    stage = None
    i = 0
    n = len(wikitext)
    while i < n:
        m = _MATCH_OPEN.search(wikitext, i)
        if not m:
            break
        block, end = _inner(wikitext, m.start())
        params = _split_params(block)
        # The nearest PRECEDING {{Stage|...}} header is this match's stage.
        stage_hdrs = re.findall(r"\{\{Stage\|([^}]*)\}\}",
                                wikitext[max(0, m.start() - 600):m.start()])
        if stage_hdrs:
            stage = stage_hdrs[-1].strip()
        label = " ".join(((stage or "") + " " + (params.get("section", ""))).lower().split())
        if "qualifier" in label or "lcq" in label:
            i = end
            continue
        matches.append({"stage": stage, "params": params})
        i = end
    return matches


def build_rows(wikitext, source_key="fixture"):
    """Normalize the page's match blocks into validated row dicts (no invented values)."""
    blocks = extract_matches(wikitext)
    rows = []
    for source_index, b in enumerate(blocks, start=1):
        p = b["params"]
        kind_a, name_a, slug_a, score_a = parse_opponent(p.get("opponent1", ""))
        kind_b, name_b, slug_b, score_b = parse_opponent(p.get("opponent2", ""))
        iso, ms = parse_date(p.get("date", ""))
        finished_raw = (p.get("finished", "") or "").strip().lower()
        if finished_raw and finished_raw not in ("true", "1", "yes", "y", "false", "0", "no", "n"):
            raise ScheduleSourceError("unsupported finished value %r" % finished_raw)
        finished = finished_raw in ("true", "1", "yes", "y")
        if not finished and ms and (score_a is not None or score_b is not None):
            finished = True  # a dated match with published scores is a result
        identity = "%s:%d" % (source_key, source_index)
        rows.append({
            "sourceMatchId": "liquipedia:%s" % hashlib.sha256(
                identity.encode("utf-8")).hexdigest()[:24],
            "stage": b["stage"] or None,
            "date": iso,
            "startTime": ms,
            "teamA": name_a,
            "teamASlug": slug_a,
            "teamAPending": kind_a == "pending",
            "teamB": name_b,
            "teamBSlug": slug_b,
            "teamBPending": kind_b == "pending",
            "scoreA": score_a,
            "scoreB": score_b,
            "finished": finished,
        })
    return rows


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _snapshot_checksum(snapshot):
    candidate = json.loads(json.dumps(snapshot))
    (candidate.get("source") or {}).pop("checksum", None)
    return hashlib.sha256(_canonical_json(candidate)).hexdigest()


def _source_urls(slug):
    return ["https://liquipedia.net/%s/%s" %
            (sub, urllib.parse.quote(page.replace(" ", "_")))
            for sub, page in TITLE_PAGES[slug]]


def _validate_match(row, seen):
    if not isinstance(row, dict):
        raise ScheduleSourceError("match row must be an object")
    source_id = row.get("sourceMatchId")
    if not isinstance(source_id, str) or not source_id.startswith("liquipedia:"):
        raise ScheduleSourceError("invalid sourceMatchId %r" % source_id)
    if source_id in seen:
        raise ScheduleSourceError("duplicate sourceMatchId %r" % source_id)
    seen.add(source_id)
    date = row.get("date")
    start = row.get("startTime")
    if (date is None) != (start is None):
        raise ScheduleSourceError("date/startTime must both be present or absent")
    if date is not None:
        try:
            _dt.date.fromisoformat(date)
        except (TypeError, ValueError) as exc:
            raise ScheduleSourceError("invalid normalized date %r" % date) from exc
        if not isinstance(start, int) or start < 0:
            raise ScheduleSourceError("invalid startTime %r" % start)
    for side in ("A", "B"):
        pending = row.get("team%sPending" % side)
        name = row.get("team%s" % side)
        if not isinstance(pending, bool):
            raise ScheduleSourceError("missing participant state for side %s" % side)
        if not pending and (not isinstance(name, str) or not name.strip()):
            raise ScheduleSourceError("named participant missing on side %s" % side)
        score = row.get("score%s" % side)
        if score is not None and (not isinstance(score, int) or score < 0):
            raise ScheduleSourceError("invalid score%s %r" % (side, score))
    if (row.get("scoreA") is None) != (row.get("scoreB") is None):
        raise ScheduleSourceError("partial published score")
    if not isinstance(row.get("finished"), bool):
        raise ScheduleSourceError("finished must be boolean")


def validate_snapshot(snapshot, expected_slug=None):
    if not isinstance(snapshot, dict) or snapshot.get("schemaVersion") != SCHEMA_VERSION:
        raise ScheduleSourceError("unsupported snapshot schema")
    if snapshot.get("event") != "ewc-2026":
        raise ScheduleSourceError("snapshot event must be ewc-2026")
    slug = snapshot.get("slug")
    if slug not in TITLE_PAGES or (expected_slug is not None and slug != expected_slug):
        raise ScheduleSourceError("snapshot title slug mismatch")
    lifecycle = snapshot.get("lifecycle")
    if lifecycle not in LIFECYCLES:
        raise ScheduleSourceError("invalid lifecycle %r" % lifecycle)
    source = snapshot.get("source") or {}
    urls = source.get("urls")
    revisions = source.get("revisions")
    if urls != _source_urls(slug):
        raise ScheduleSourceError("source URL identity mismatch")
    if not isinstance(revisions, list) or len(revisions) != len(urls) or not all(
            isinstance(rev, int) and rev > 0 for rev in revisions):
        raise ScheduleSourceError("source revision population mismatch")
    if (not source.get("fetchedAt") or not snapshot.get("publishedAt") or
            source.get("publishedAt") != snapshot.get("publishedAt")):
        raise ScheduleSourceError("missing source timestamps")
    rows = snapshot.get("matches")
    if not isinstance(rows, list) or not rows:
        raise ScheduleSourceError("published snapshot must contain matches")
    seen = set()
    for row in rows:
        _validate_match(row, seen)
    schedule = snapshot.get("schedule") or {}
    dated = [row for row in rows if row.get("startTime") is not None]
    if schedule.get("status") != "published" or schedule.get("count") != len(rows):
        raise ScheduleSourceError("schedule count/status mismatch")
    if schedule.get("datedCount") != len(dated):
        raise ScheduleSourceError("dated match count mismatch")
    expected_first = min((row["startTime"] for row in dated), default=None)
    expected_last = max((row["startTime"] for row in dated), default=None)
    if schedule.get("firstStart") != expected_first or schedule.get("lastStart") != expected_last:
        raise ScheduleSourceError("schedule bounds mismatch")
    expected_first_date = min((row["date"] for row in dated), default=None)
    expected_last_date = max((row["date"] for row in dated), default=None)
    if schedule.get("firstDate") != expected_first_date or schedule.get("lastDate") != expected_last_date:
        raise ScheduleSourceError("schedule date bounds mismatch")
    if lifecycle == "final":
        finality = snapshot.get("finality") or {}
        required = ("allMatchesResolved", "participantsComplete", "sourceRevisionRecorded")
        if not all(finality.get(key) is True for key in required):
            raise ScheduleSourceError("final lifecycle requires source-backed completion evidence")
        if not all(row.get("finished") for row in rows):
            raise ScheduleSourceError("final snapshot contains unresolved matches")
        if any(row.get("teamAPending") or row.get("teamBPending") for row in rows):
            raise ScheduleSourceError("final snapshot contains unpublished participants")
    checksum = source.get("checksum")
    if not isinstance(checksum, str) or checksum != _snapshot_checksum(snapshot):
        raise ScheduleSourceError("snapshot checksum mismatch")
    return snapshot


def build_snapshot(slug, rows, revisions, fetched_at, lifecycle="upcoming", finality=None):
    if slug not in TITLE_PAGES:
        raise ScheduleSourceError("unknown EWC title slug %r" % slug)
    if not rows:
        raise ScheduleSourceError("published snapshot must contain matches")
    published_at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    dated = [r for r in rows if r["startTime"]]
    snapshot = {
        "schemaVersion": SCHEMA_VERSION,
        "event": "ewc-2026",
        "slug": slug,
        "lifecycle": lifecycle,
        "finality": finality,
        "publishedAt": published_at,
        "source": {
            "label": SOURCE_LABEL,
            "urls": _source_urls(slug),
            "revisions": revisions,
            "fetchedAt": fetched_at,
            "publishedAt": published_at,
            "checksum": None,
        },
        "schedule": {
            "status": "published",
            "count": len(rows),
            "datedCount": len(dated),
            "firstStart": min((r["startTime"] for r in dated), default=None),
            "lastStart": max((r["startTime"] for r in dated), default=None),
            "firstDate": min((r["date"] for r in dated), default=None),
            "lastDate": max((r["date"] for r in dated), default=None),
        },
        "matches": rows,
    }
    snapshot["source"]["checksum"] = _snapshot_checksum(snapshot)
    return validate_snapshot(snapshot, expected_slug=slug)


def build_manifest(published_at=None):
    published_at = published_at or time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    return {
        "schemaVersion": SCHEMA_VERSION,
        "event": "ewc-2026",
        "publishedAt": published_at,
        "titles": {slug: {"status": "unavailable"} for slug in TITLE_PAGES},
    }


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise ScheduleSourceError("unsupported manifest schema")
    if manifest.get("event") != "ewc-2026" or not manifest.get("publishedAt"):
        raise ScheduleSourceError("invalid manifest identity")
    titles = manifest.get("titles")
    if not isinstance(titles, dict) or set(titles) != set(TITLE_PAGES):
        raise ScheduleSourceError("manifest must contain the exact 24-title catalog")
    for slug, entry in titles.items():
        if not isinstance(entry, dict) or entry.get("status") not in ("unavailable", "published"):
            raise ScheduleSourceError("invalid manifest entry for %s" % slug)
        if entry.get("status") == "published":
            if entry.get("lifecycle") not in LIFECYCLES:
                raise ScheduleSourceError("invalid manifest lifecycle for %s" % slug)
            if not all(isinstance(entry.get(key), str) and entry.get(key)
                       for key in ("file", "checksum", "fetchedAt")):
                raise ScheduleSourceError("incomplete manifest entry for %s" % slug)
    return manifest


def read_manifest():
    try:
        with open(os.path.join(SCHEDULES_DIR, MANIFEST_FILE)) as f:
            return validate_manifest(json.load(f))
    except (OSError, ValueError, TypeError):
        return None


def publish(slug, snapshot):
    validate_snapshot(snapshot, expected_slug=slug)
    os.makedirs(SCHEDULES_DIR, exist_ok=True)
    checksum = snapshot["source"]["checksum"]
    filename = "%s.%s.json" % (slug, checksum[:16])
    path = os.path.join(SCHEDULES_DIR, filename)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(snapshot, f)
    os.replace(tmp, path)
    manifest = read_manifest() or build_manifest()
    manifest["publishedAt"] = snapshot["publishedAt"]
    manifest["titles"][slug] = {
        "status": "published",
        "file": filename,
        "checksum": checksum,
        "lifecycle": snapshot["lifecycle"],
        "fetchedAt": snapshot["source"]["fetchedAt"],
        "revisions": snapshot["source"]["revisions"],
    }
    validate_manifest(manifest)
    manifest_path = os.path.join(SCHEDULES_DIR, MANIFEST_FILE)
    manifest_tmp = manifest_path + ".tmp"
    with open(manifest_tmp, "w") as f:
        json.dump(manifest, f)
    os.replace(manifest_tmp, manifest_path)
    return path


def read_snapshot(slug):
    if slug not in TITLE_PAGES:
        return None
    manifest = read_manifest()
    if manifest is None:
        return None
    entry = manifest["titles"].get(slug) or {}
    if entry.get("status") != "published":
        return None
    try:
        filename = entry.get("file")
        if os.path.basename(filename or "") != filename:
            return None
        with open(os.path.join(SCHEDULES_DIR, filename)) as f:
            snapshot = json.load(f)
        validate_snapshot(snapshot, expected_slug=slug)
        if snapshot["source"]["checksum"] != entry.get("checksum"):
            return None
        lifecycle = snapshot.get("lifecycle")
        max_age = ACTIVE_MAX_AGE_S if lifecycle == "active" else UPCOMING_MAX_AGE_S
        if lifecycle != "final":
            published = _dt.datetime.fromisoformat(snapshot["publishedAt"])
            now = _dt.datetime.now(tz=published.tzinfo or _dt.timezone.utc)
            if (now - published).total_seconds() > max_age:
                return None
        return snapshot
    except (OSError, ValueError, TypeError):
        return None


def _wait_for_parse_slot():
    global _LAST_PARSE_REQUEST
    now = time.monotonic()
    if _LAST_PARSE_REQUEST is not None:
        remaining = PARSE_MIN_INTERVAL_S - (now - _LAST_PARSE_REQUEST)
        if remaining > 0:
            time.sleep(remaining)
    _LAST_PARSE_REQUEST = time.monotonic()


def _api_get(sub, page, retries=4):
    """One polite MediaWiki parse call with Retry-After-aware rate-limit backoff and retries."""
    url = ("https://liquipedia.net/%s/api.php?action=parse&page=%s"
           "&prop=wikitext%%7Crevid&format=json" % (sub, urllib.parse.quote(page)))
    for attempt in range(retries):
        try:
            _wait_for_parse_slot()
            _operator_log("source request attempt=%d/%d wiki=%s page=%s" % (
                attempt + 1, retries, sub, page))
            req = urllib.request.Request(url, headers={
                "Accept-Encoding": "gzip", "User-Agent": API_UA})
            with _API_OPENER.open(req, timeout=45) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            _operator_log("source response status=success wiki=%s page=%s bytes=%d" % (
                sub, page, len(raw)))
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After")
                _operator_log("source response status=rate-limited wiki=%s page=%s "
                              "retry-after=%s" % (
                                  sub, page, retry_after or "not-supplied"))
                if attempt + 1 >= retries:
                    raise ScheduleSourceError(
                        "rate limited by Liquipedia (Retry-After=%s) for %s:%s" %
                        (retry_after or "not supplied", sub, page)) from exc
                try:
                    wait = max(int(retry_after), 30)
                except (TypeError, ValueError):
                    wait = 30 * (2 ** attempt)
                time.sleep(wait)
                continue
            _operator_log("source response status=http-error code=%s wiki=%s page=%s" % (
                exc.code, sub, page))
            raise
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            _operator_log("source response status=transport-error wiki=%s page=%s error=%s" % (
                sub, page, type(exc).__name__))
            if attempt + 1 >= retries:
                raise ScheduleSourceError("source request failed after retries: %s:%s" %
                                          (sub, page))
            time.sleep(15)
            continue
    raise ScheduleSourceError("rate-limited after retries: %s:%s" % (sub, page))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slug", help="only fetch this title slug")
    ap.add_argument("--dry-run", action="store_true", help="fetch + validate, print summary, no writes")
    ap.add_argument("--lifecycle", choices=LIFECYCLES,
                    help="publication lifecycle; defaults to the prior value or upcoming")
    ap.add_argument("--refresh-final", action="store_true",
                    help="explicitly allow a frozen final title to be fetched again")
    ap.add_argument("--final-all-resolved", action="store_true")
    ap.add_argument("--final-participants-complete", action="store_true")
    args = ap.parse_args(argv)

    if args.slug and args.slug not in TITLE_PAGES:
        ap.error("unknown EWC title slug: %s" % args.slug)
    if args.lifecycle == "final" and not (
            args.final_all_resolved and args.final_participants_complete):
        ap.error("--lifecycle final requires both finality evidence flags")
    slugs = [args.slug] if args.slug else list(TITLE_PAGES)
    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    summary = {}
    failures = 0
    for slug in slugs:
        revisions = []
        wikitexts = []
        rows = []
        try:
            manifest = read_manifest()
            prior = ((manifest or {}).get("titles") or {}).get(slug) or {}
            if prior.get("lifecycle") == "final" and not args.refresh_final:
                summary[slug] = {"status": "skipped-final"}
                print("SKIPPED   %-32s frozen final snapshot" % slug)
                continue
            for sub, page in TITLE_PAGES[slug]:
                doc = _api_get(sub, page)
                parse = doc.get("parse") or {}
                revid = parse.get("revid")
                wikitext = (parse.get("wikitext") or {}).get("*")
                if not revid or wikitext is None:
                    raise ScheduleSourceError("missing revid/wikitext for %s:%s" % (sub, page))
                revisions.append(revid)
                wikitexts.append(wikitext)
                rows.extend(build_rows(wikitext, source_key="%s:%s" % (sub, page)))
            if not revisions:
                raise ScheduleSourceError("no pages fetched")
            if not rows and not any("{{Match" in w for w in wikitexts):
                # No Match templates at all on any page -> schedule not machine-readable here.
                raise ScheduleSourceError("no Match templates found on the published page")
            lifecycle = args.lifecycle or prior.get("lifecycle") or "upcoming"
            finality = None
            if lifecycle == "final":
                finality = {
                    "allMatchesResolved": args.final_all_resolved,
                    "participantsComplete": args.final_participants_complete,
                    "sourceRevisionRecorded": bool(revisions),
                }
            snapshot = build_snapshot(slug, rows, revisions, fetched_at,
                                      lifecycle=lifecycle, finality=finality)
            summary[slug] = {"revisions": revisions, "matches": len(rows),
                             "dated": snapshot["schedule"]["datedCount"],
                             "status": snapshot["schedule"]["status"]}
            if args.dry_run:
                print("[dry-run] %-32s rev=%s rows=%d dated=%d" % (
                    slug, revisions, len(rows), snapshot["schedule"]["datedCount"]))
                continue
            path = publish(slug, snapshot)
            print("published %-32s -> %s (rev=%s rows=%d dated=%d dates=%s..%s lifecycle=%s)" % (
                slug, path, revisions, len(rows), snapshot["schedule"]["datedCount"],
                snapshot["schedule"]["firstDate"], snapshot["schedule"]["lastDate"],
                snapshot["lifecycle"]))
        except Exception as exc:  # noqa: BLE001 — operator-facing
            failures += 1
            summary[slug] = {"error": str(exc)[:160]}
            print("FAILED    %-32s %s" % (slug, exc))
    if args.dry_run:
        print("[dry-run] %d titles processed — nothing written" % len(summary))
    succeeded = sum(1 for item in summary.values() if "error" not in item)
    print("summary: requested=%d succeeded-or-skipped=%d failed=%d" % (
        len(slugs), succeeded, failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
