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
import urllib.parse
import urllib.request

API_UA = ("LegendaryPicks/1.0 (EWC title schedule ingest; "
          "contact via github.com/legendarypicks)")
SOURCE_LABEL = "Liquipedia — EWC 2026"
SCHEDULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "data", "esports_ewc_schedules")

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

    Handles 'YYYY-MM-DD' and 'Month D, YYYY - HH:MM {{Abbr/TZ}}' forms. An empty or
    unparseable value is (None, None) — the source has not published a date (never guessed).
    """
    if not value or not isinstance(value, str):
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
        except ValueError:
            return None, None
        return d.strftime("%Y-%m-%d"), int(d.timestamp() * 1000)
    m = re.fullmatch(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})(?: (\d{1,2}):(\d{2}))?", v)
    if m:
        try:
            d = _dt.datetime(int(m.group(3)), _dt.datetime.strptime(m.group(1), "%B").month,
                             int(m.group(2)), int(m.group(4) or 12), int(m.group(5) or 0),
                             tzinfo=_dt.timezone.utc) - _dt.timedelta(seconds=tz)
        except ValueError:
            return None, None
        return d.strftime("%Y-%m-%d"), int(d.timestamp() * 1000)
    return None, None


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
                    except ValueError:
                        score = None
        name = _strip_wikilink(body)
        slug = re.sub(r"\s+", "_", name) if name else None
        return "named", name, slug, score
    m = re.fullmatch(r"\{\{\d+ ?Opponent\|([^}]*)\}\}", v)
    if m:
        label = m.group(1).strip() or None
        return "pending", label, None, score
    if not v:
        return "pending", None, None, score
    if v.startswith("{{"):
        # Unknown nested template — treat as pending with a label, never a fabricated team.
        return "pending", re.sub(r"[\{\}]", "", v)[:60] or None, None, score
    return "named", _strip_wikilink(v), re.sub(r"\s+", "_", _strip_wikilink(v)), score


# ---------------------------------------------------------------------------
# Match extraction
# ---------------------------------------------------------------------------
def extract_matches(wikitext):
    """All Match-family blocks from the wikitext, with stage context and qualifier exclusion."""
    if not wikitext:
        return []
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


def build_rows(wikitext):
    """Normalize the page's match blocks into validated row dicts (no invented values)."""
    blocks = extract_matches(wikitext)
    rows = []
    for b in blocks:
        p = b["params"]
        kind_a, name_a, slug_a, score_a = parse_opponent(p.get("opponent1", ""))
        kind_b, name_b, slug_b, score_b = parse_opponent(p.get("opponent2", ""))
        iso, ms = parse_date(p.get("date", ""))
        finished_raw = (p.get("finished", "") or "").strip().lower()
        finished = finished_raw in ("true", "1", "yes", "y")
        if not finished and ms and (score_a is not None or score_b is not None):
            finished = True  # a dated match with published scores is a result
        rows.append({
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


def build_snapshot(slug, rows, revisions, fetched_at):
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    published_at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    weeks = sorted({_dt.date.fromtimestamp(r["startTime"] / 1000).isocalendar()[1]
                    for r in rows if r["startTime"]})
    dated = [r for r in rows if r["startTime"]]
    return {
        "event": "ewc-2026",
        "slug": slug,
        "publishedAt": published_at,
        "source": {
            "label": SOURCE_LABEL,
            "urls": ["https://liquipedia.net/%s/%s" % (sub, urllib.parse.quote(page.replace(" ", "_")))
                     for sub, page in TITLE_PAGES[slug]],
            "revisions": revisions,
            "fetchedAt": fetched_at,
            "publishedAt": published_at,
            "checksum": hashlib.sha256(payload).hexdigest(),
        },
        "schedule": {
            "status": "published" if rows else "unavailable",
            "count": len(rows),
            "datedCount": len(dated),
            "firstStart": min((r["startTime"] for r in dated), default=None),
            "lastStart": max((r["startTime"] for r in dated), default=None),
            "weeks": weeks,
        },
        "matches": rows,
    }


def publish(slug, snapshot):
    os.makedirs(SCHEDULES_DIR, exist_ok=True)
    path = os.path.join(SCHEDULES_DIR, "%s.json" % slug)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(snapshot, f)
    os.replace(tmp, path)
    return path


def read_snapshot(slug):
    try:
        with open(os.path.join(SCHEDULES_DIR, "%s.json" % slug)) as f:
            return json.load(f)
    except Exception:
        return None


def _api_get(sub, page, retries=8):
    """One polite MediaWiki parse call with Retry-After-aware rate-limit backoff and retries."""
    url = ("https://liquipedia.net/%s/api.php?action=parse&page=%s"
           "&prop=wikitext%%7Crevid&format=json" % (sub, urllib.parse.quote(page)))
    for attempt in range(retries):
        try:
            time.sleep(2.0)  # sustained politeness — never burst the API
            req = urllib.request.Request(url, headers={
                "Accept-Encoding": "gzip", "User-Agent": API_UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After")
                try:
                    wait = max(int(retry_after), 30)
                except (TypeError, ValueError):
                    wait = 30 * (2 ** attempt)
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(15)
            continue
    raise ScheduleSourceError("rate-limited after retries: %s:%s" % (sub, page))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slug", help="only fetch this title slug")
    ap.add_argument("--dry-run", action="store_true", help="fetch + validate, print summary, no writes")
    args = ap.parse_args(argv)

    slugs = [args.slug] if args.slug else list(TITLE_PAGES)
    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    summary = {}
    for slug in slugs:
        revisions = []
        wikitexts = []
        rows = []
        try:
            for sub, page in TITLE_PAGES[slug]:
                doc = _api_get(sub, page)
                parse = doc.get("parse") or {}
                revid = parse.get("revid")
                wikitext = (parse.get("wikitext") or {}).get("*")
                if not revid or wikitext is None:
                    raise ScheduleSourceError("missing revid/wikitext for %s:%s" % (sub, page))
                revisions.append(revid)
                wikitexts.append(wikitext)
                rows.extend(build_rows(wikitext))
                time.sleep(1.0)  # polite pacing between pages
            if not revisions:
                raise ScheduleSourceError("no pages fetched")
            if not rows and not any("{{Match" in w for w in wikitexts):
                # No Match templates at all on any page -> schedule not machine-readable here.
                raise ScheduleSourceError("no Match templates found on the published page")
            snapshot = build_snapshot(slug, rows, revisions, fetched_at)
            summary[slug] = {"revisions": revisions, "matches": len(rows),
                             "dated": snapshot["schedule"]["datedCount"],
                             "status": snapshot["schedule"]["status"]}
            if args.dry_run:
                print("[dry-run] %-32s rev=%s rows=%d dated=%d" % (
                    slug, revisions, len(rows), snapshot["schedule"]["datedCount"]))
                continue
            path = publish(slug, snapshot)
            print("published %-32s -> %s (rev=%s rows=%d dated=%d weeks=%s)" % (
                slug, path, revisions, len(rows), snapshot["schedule"]["datedCount"],
                snapshot["schedule"]["weeks"]))
        except Exception as exc:  # noqa: BLE001 — operator-facing
            summary[slug] = {"error": str(exc)[:160]}
            print("FAILED    %-32s %s" % (slug, exc))
    if args.dry_run:
        print("[dry-run] %d titles processed — nothing written" % len(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
