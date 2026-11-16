"""Ingest DWCS significant-strike actuals from UFCalendar's public pages.

The public UFC calendar feed supplies event URLs. Fight pages publish each
corner's significant strikes landed/attempted in the visible fight-stat table.
No UFCalendar API key is used.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import time
import unicodedata
import urllib.parse
import urllib.request
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from playwright.sync_api import sync_playwright


CALENDAR_URL = "https://www.ufcalendar.com/api/calendar/ufc.ics"
_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
_DWCS = re.compile(r"contender\s+series|\bdwcs\b", re.I)
_FIGHTER_NAME_ALIASES = {
    "gabriel lorenco": ("gabriel lourenco",),
    "gabriel lourenco": ("gabriel lorenco",),
    "reginaldo junior": ("reginaldo geraldo jr",),
    "mateus soares": ("matheus soares",),
}


def _key(value: str) -> str:
    folded = unicodedata.normalize("NFKD", str(value or ""))
    plain = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", plain.casefold()))


def _slug_key(value: str) -> str:
    return "-".join(_key(value).split())


def _name_matches_slug(name: str, slug: str) -> bool:
    slug_parts = _key(slug).split()
    normalized_name = _key(name)
    name_variants = [normalized_name]
    name_variants.extend(_FIGHTER_NAME_ALIASES.get(normalized_name, ()))
    for variant in name_variants:
        name_parts = variant.split()
        if name_parts == slug_parts:
            return True
        if len(name_parts) >= 2 and len(slug_parts) >= len(name_parts):
            if name_parts[-2:] == slug_parts[-2:]:
                first = name_parts[0]
                if len(first) == 1 and slug_parts[0].startswith(first):
                    return True
    return False


def _unescape_ical(value: str) -> str:
    return (value.replace("\\n", " ").replace("\\N", " ")
            .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\"))


def _calendar_events() -> List[dict]:
    request = urllib.request.Request(
        CALENDAR_URL, headers={"User-Agent": _USER_AGENT, "Accept": "text/calendar"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise RuntimeError("UFCalendar public calendar exceeded the 2 MB limit")

    unfolded = re.sub(br"\r?\n[ \t]", b"", body).decode("utf-8", "replace")
    events = []
    for block in unfolded.split("BEGIN:VEVENT")[1:]:
        fields = {}
        for line in block.splitlines():
            if line.strip() == "END:VEVENT":
                break
            name, separator, value = line.partition(":")
            if not separator:
                continue
            fields[name.split(";", 1)[0].upper()] = _unescape_ical(value.strip())
        title = fields.get("SUMMARY", "")
        raw_url = fields.get("URL", "")
        if not _DWCS.search(title) or not raw_url:
            continue
        parsed = urllib.parse.urlsplit(raw_url)
        date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", parsed.path)
        if not date_match:
            continue
        events.append({
            "title": title,
            "date": date_match.group(1),
            "url": urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")),
            "path": parsed.path.rstrip("/"),
        })
    return events


def _browser_executable() -> Optional[str]:
    configured = os.environ.get("BROWSER", "").strip()
    if configured and os.path.isfile(configured):
        return configured
    known = "/root/.cache/ms-playwright/chromium-1140/chrome-linux/chrome"
    return known if os.path.isfile(known) else None


def _event_fight_links(page, event: dict) -> Dict[Tuple[str, str], str]:
    page.goto(event["url"], wait_until="domcontentloaded", timeout=45_000)
    prefix = event["path"].rstrip("/") + "/"
    page.locator("a[href]").first.wait_for(timeout=15_000)
    found = {}
    for item in page.locator("a[href]").evaluate_all(
        "els => els.map(a => ({href:a.href, path:a.pathname}))"
    ):
        path = item["path"].rstrip("/")
        if not path.startswith(prefix):
            continue
        slug = path[len(prefix):]
        if "/" in slug or "-vs-" not in slug:
            continue
        left, right = slug.split("-vs-", 1)
        if left and right:
            found[(left, right)] = item["href"]
    if not found:
        raise RuntimeError("UFCalendar event page contained no bout links: " + event["url"])
    return found


def _pair_link(links: Dict[Tuple[str, str], str], home: str, away: str):
    home_key, away_key = _slug_key(home), _slug_key(away)
    candidates = []
    for pair, url in links.items():
        if pair == (home_key, away_key):
            return url, (home, away)
        if pair == (away_key, home_key):
            return url, (away, home)
        if _name_matches_slug(home, pair[0]) and _name_matches_slug(away, pair[1]):
            candidates.append((url, (home, away)))
        elif _name_matches_slug(home, pair[1]) and _name_matches_slug(away, pair[0]):
            candidates.append((url, (away, home)))
    return candidates[0] if len(candidates) == 1 else (None, None)


def _fight_actuals(page, url: str) -> Dict[str, int]:
    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    heading = page.locator("h2").filter(has_text="Fight stats: totals").first
    heading.wait_for(timeout=20_000)
    section_text = heading.evaluate(
        "e => e.closest('section').innerText"
    )
    lines = [line.strip() for line in section_text.splitlines() if line.strip()]
    label_index = lines.index("Significant strikes")
    landed_values = []
    for value in (lines[label_index - 1], lines[label_index + 1]):
        match = re.fullmatch(r"(\d+)\s*/\s*(\d+)", value)
        if not match:
            raise RuntimeError("UFCalendar significant-strike row was not landed/attempted")
        landed, attempted = map(int, match.groups())
        if landed > attempted:
            raise RuntimeError("UFCalendar significant strikes exceed attempts")
        landed_values.append(landed)
    slug = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
    left, separator, right = slug.partition("-vs-")
    if not separator:
        raise RuntimeError("UFCalendar bout URL has no fighter ordering")
    return {left: landed_values[0], right: landed_values[1]}


def ingest_ufcalendar_dwcs(
    con: sqlite3.Connection, game_ids: Optional[Sequence[int]] = None
) -> dict:
    """Store available DWCS totals for unsettled significant-strike props."""
    if game_ids is None:
        game_ids = [row[0] for row in con.execute(
            """SELECT DISTINCT pg.id FROM prop_games pg
                 JOIN props p ON p.game_id=pg.id
                 LEFT JOIN prop_results pr ON pr.prop_id=p.id
                WHERE lower(pg.league)='ufc' AND pr.prop_id IS NULL
                  AND pg.date <= date('now')
                  AND EXISTS (
                      SELECT 1 FROM scoreboard_snapshots ss
                       WHERE ss.league='ufc' AND ss.game_id=pg.espn_event_id
                         AND lower(ss.payload) LIKE '%contender series%'
                  )"""
        ).fetchall()]
    if not game_ids:
        return {"games": 0, "fighters": 0, "skipped": 0}

    from settlement.market_mapping import normalize_market, MARKET_ALIASES

    placeholders = ",".join("?" for _ in game_ids)
    rows = con.execute(
        f"""SELECT p.id AS prop_id,p.player_id,p.market,pl.name AS player_name,
                  pg.id AS game_id,pg.date,pg.home,pg.away,pg.espn_event_id
             FROM props p
             JOIN prop_games pg ON pg.id=p.game_id
             JOIN players pl ON pl.id=p.player_id
             LEFT JOIN prop_results pr ON pr.prop_id=p.id
            WHERE pg.id IN ({placeholders}) AND lower(pg.league)='ufc'
              AND pr.prop_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM player_game_logs pgl
                   WHERE pgl.league='ufc' AND pgl.source='ufcalendar'
                     AND pgl.player_id=p.player_id AND pgl.game_id=pg.espn_event_id
              )""",
        tuple(game_ids),
    ).fetchall()
    targets: Dict[int, dict] = {}
    for row in rows:
        market = normalize_market(row["market"])
        market = MARKET_ALIASES.get(market, market)
        if market != "significant_strikes":
            continue
        entry = targets.setdefault(int(row["game_id"]), {
            "date": str(row["date"] or "")[:10],
            "home": str(row["home"] or ""),
            "away": str(row["away"] or ""),
            "espn_event_id": str(row["espn_event_id"] or ""),
            "players": {},
        })
        entry["players"][int(row["player_id"])] = str(row["player_name"] or "")
    if not targets:
        return {"games": 0, "fighters": 0, "skipped": 0}

    events = _calendar_events()
    events_by_date: Dict[str, List[dict]] = {}
    for event in events:
        events_by_date.setdefault(event["date"], []).append(event)

    writes = []
    skipped = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=_browser_executable(), args=["--no-sandbox"]
        )
        page = browser.new_page(user_agent=_USER_AGENT)
        event_link_cache = {}
        actual_cache = {}
        try:
            for game_id, game in targets.items():
                candidate_events = []
                try:
                    game_date = dt.date.fromisoformat(game["date"])
                except ValueError:
                    skipped += len(game["players"])
                    continue
                for offset in (-1, 0, 1):
                    date_key = (game_date + dt.timedelta(days=offset)).isoformat()
                    candidate_events.extend(events_by_date.get(date_key, []))
                matched_event = None
                matched_url = None
                matched_order = None
                for event in candidate_events:
                    if event["url"] not in event_link_cache:
                        event_link_cache[event["url"]] = _event_fight_links(page, event)
                    matched_url, matched_order = _pair_link(
                        event_link_cache[event["url"]], game["home"], game["away"]
                    )
                    if matched_url:
                        matched_event = event
                        break
                if not matched_url:
                    skipped += len(game["players"])
                    continue

                if matched_url not in actual_cache:
                    actual_cache[matched_url] = _fight_actuals(page, matched_url)
                actuals = actual_cache[matched_url]
                route_slug = urllib.parse.urlsplit(matched_url).path.rsplit("/", 1)[-1]
                for player_id, name in game["players"].items():
                    matching_actuals = [
                        value for slug, value in actuals.items()
                        if _name_matches_slug(name, slug)
                    ]
                    if len(matching_actuals) != 1:
                        skipped += 1
                        continue
                    actual = matching_actuals[0]
                    player_slug = _slug_key(name)
                    opponent = game["away"] if _slug_key(game["home"]) == player_slug else game["home"]
                    stats = {
                        "sigStrikesLanded": actual,
                        "source": "ufcalendar",
                        "source_event_url": matched_event["url"],
                        "source_fight_url": matched_url,
                    }
                    source_key = "ufcalendar:{}:{}".format(
                        matched_event["path"].rsplit("/", 1)[-1], player_slug
                    )
                    writes.append((
                        player_id, int(game["date"][:4]), route_slug,
                        str(game["espn_event_id"]), game["date"], opponent,
                        json.dumps(stats, sort_keys=True, separators=(",", ":")),
                        source_key,
                    ))
                time.sleep(0.25)
        finally:
            browser.close()

    if writes:
        con.executemany(
            """INSERT INTO player_game_logs
               (player_id,league,season,game_no,game_id,game_date,opponent,
                stats,source,source_player_key)
               VALUES(?,'ufc',?,?,?,?,?,?,'ufcalendar',?)
               ON CONFLICT(league,source_player_key,season,game_no) DO UPDATE SET
                 player_id=excluded.player_id,game_id=excluded.game_id,
                 game_date=excluded.game_date,opponent=excluded.opponent,
                 stats=excluded.stats,source='ufcalendar',ingested_at=datetime('now')""",
            writes,
        )
        con.commit()
    return {"games": len({row[2] for row in writes}),
            "fighters": len(writes), "skipped": skipped}
