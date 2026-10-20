"""Tournament surfaces for the shadow forecasts: the whole tracked set, not the served map.

The definitions below are copied verbatim from the dev branch (commit c4bd3c9f), so the shadow resolves an event to the
same canonical major and surface that dev uses. The served projection on this branch still uses its own two-event map,
and this module does not change it. When this branch is rebased on dev, these copies should be replaced by imports from
the shared definitions, so the two cannot drift.

Sources on dev:
- backend/espn_client/scoreboard.py: _ATP_MAJORS, _WTA_MAJORS, major_for_event
- backend/tennis_daily_projections.py: SURFACE_BY_EVENT, SURFACE_BY_MAJOR
"""
from __future__ import annotations


# Event id to surface (dev: SURFACE_BY_EVENT).
SHADOW_SURFACE_BY_EVENT = {"189": "Hard", "315": "Hard", "381": "Hard", "959": "Hard"}

# Canonical major name to surface (dev: SURFACE_BY_MAJOR).
SHADOW_SURFACE_BY_MAJOR = {
    "Australian Open": "Hard",
    "French Open": "Clay",
    "Wimbledon": "Grass",
    "US Open": "Hard",
    "Indian Wells": "Hard",
    "Miami Open": "Hard",
    "Monte-Carlo Masters": "Clay",
    "Madrid Open": "Clay",
    "Italian Open": "Clay",
    "Canadian Open": "Hard",
    "Cincinnati Open": "Hard",
    "Shanghai Masters": "Hard",
    "Paris Masters": "Hard",
    "China Open": "Hard",
    "Qatar Open": "Hard",
    "Dubai": "Hard",
    "Wuhan Open": "Hard",
    "ATP Finals": "Hard",
    "WTA Finals": "Hard",
    # ATP 500s, 2026. Surfaces from the tour listings (toomanyrackets.com, tennis-db.com).
    "Dallas Open": "Hard",
    "Rotterdam Open": "Hard",
    "Qatar ExxonMobil Open": "Hard",
    "Rio Open": "Clay",
    "Acapulco Open": "Hard",
    "Barcelona Open": "Clay",
    "Munich Open": "Clay",
    "Hamburg Open": "Clay",
    "Halle Open": "Grass",
    "Queen's Club": "Grass",
    "Washington": "Hard",
    "Tokyo Open": "Hard",
    "Vienna Open": "Hard",
    "Basel": "Hard",
    # WTA 500s, 2026. Linz is Hard: the 2025 WTA data lists it as Hard, and tennis-db says Clay.
    "Brisbane International": "Hard",
    "Adelaide International": "Hard",
    "Abu Dhabi Open": "Hard",
    "Mérida Open": "Hard",
    "Charleston Open": "Clay",
    "Linz Open": "Hard",
    "Stuttgart Open": "Clay",
    "Strasbourg Open": "Clay",
    "Berlin Open": "Grass",
    "Bad Homburg Open": "Grass",
    "Monterrey Open": "Hard",
    "Guadalajara Open": "Hard",
    "Singapore Tennis Open": "Hard",
    "Ningbo Open": "Hard",
    "Pan Pacific Open": "Hard",
}

# ESPN shortName aliases per tour (dev: scoreboard._ATP_MAJORS and _WTA_MAJORS).
_ATP_MAJORS = [
    # Grand Slams
    ("Australian Open",        ["Australian Open"]),
    ("French Open",            ["Roland Garros", "French Open"]),
    ("Wimbledon",              ["Wimbledon"]),
    ("US Open",                ["US Open"]),
    # Masters 1000
    ("Indian Wells",           ["BNP Paribas Open"]),
    ("Miami Open",             ["Miami Open"]),
    ("Monte-Carlo Masters",    ["Monte-Carlo Masters"]),
    ("Madrid Open",            ["Mutua Madrid Open"]),
    ("Italian Open",           ["Italian Open", "Internazionali BNL d'Italia"]),
    ("Canadian Open",          ["National Bank Open", "Omnium Banque Nationale",
                                "Rogers Cup", "Canadian Open"]),
    ("Cincinnati Open",        ["Cincinnati Open", "Western & Southern Open"]),
    ("Shanghai Masters",       ["Rolex Shanghai Masters", "Shanghai Masters"]),
    ("Paris Masters",          ["Rolex Paris Masters", "Paris Masters"]),
    # ATP 500s Kalshi lists and the competition trades. ATP China Open (Beijing) is a 500, so the
    # 1000-only list dropped it while WTA's China Open (a 1000) passed: added 2026-10-04.
    ("China Open",             ["China Open"]),
    # ATP 500 singles, 2026 (16 events). The tier comes from the ATP calendar as reported by
    # toomanyrackets.com/atp-500-tournaments; each alias is the ESPN shortName observed on the
    # scoreboard for that week on 2026-02-10 to 2026-10-27. Added 2026-10-18 with the multi-draw store.
    ("Dallas Open",            ["Nexo Dallas Open"]),
    ("Rotterdam Open",         ["ABN Amro Open"]),
    ("Qatar ExxonMobil Open",  ["Qatar ExxonMobil Open"]),
    ("Rio Open",               ["Rio Open"]),
    ("Acapulco Open",          ["Abierto Mexicano Telcel"]),
    ("Dubai",                  ["Dubai Duty Free Tennis Championships"]),
    ("Barcelona Open",         ["Barcelona Open"]),
    ("Munich Open",            ["BMW Open"]),
    ("Hamburg Open",           ["Hamburg Open"]),
    ("Halle Open",             ["Terra Wortmann Open"]),
    ("Queen's Club",           ["HSBC Championships"]),
    ("Washington",             ["Mubadala DC Open"]),
    ("Tokyo Open",             ["Kinoshita Group Japan Open"]),
    ("Vienna Open",            ["Erste Bank Open"]),
    ("Basel",                  ["Swiss Indoors Basel"]),
    # Finals
    ("ATP Finals",             ["ATP Finals", "Nitto ATP Finals", "ATP World Tour Finals"]),
]

_WTA_MAJORS = [
    # Grand Slams (same as ATP)
    ("Australian Open",        ["Australian Open"]),
    ("French Open",            ["Roland Garros", "French Open"]),
    ("Wimbledon",              ["Wimbledon"]),
    ("US Open",                ["US Open"]),
    # WTA 1000
    ("Qatar Open",             ["Qatar TotalEnergies Open", "Qatar Open", "Qatar Total Open"]),
    ("Dubai",                  ["Dubai Duty Free Tennis Championships", "Dubai Tennis Championships"]),
    ("Indian Wells",           ["BNP Paribas Open"]),
    ("Miami Open",             ["Miami Open"]),
    ("Madrid Open",            ["Mutua Madrid Open"]),
    ("Italian Open",           ["Italian Open", "Internazionali BNL d'Italia"]),
    ("Canadian Open",          ["National Bank Open", "Omnium Banque Nationale", "Canadian Open"]),
    ("Cincinnati Open",        ["Cincinnati Open"]),
    ("China Open",             ["China Open"]),
    ("Wuhan Open",             ["Wuhan Open"]),
    # WTA 500 singles, 2026 (17 events). The tier comes from tennis-db.com/wta/tournaments.md and the WTA's
    # 2026 calendar announcement. Each alias is the ESPN shortName observed on the scoreboard for that week
    # (2026-01-05 to 2026-10-27). Washington shares ESPN's event id with the ATP 500, so its alias matches both.
    ("Brisbane International",  ["Brisbane International"]),
    ("Adelaide International",  ["Adelaide International"]),
    ("Abu Dhabi Open",          ["Abu Dhabi Open"]),
    ("Mérida Open",             ["Mérida Open"]),
    ("Charleston Open",         ["Charleston Open"]),
    ("Linz Open",               ["Upper Austria Ladies Linz"]),
    ("Stuttgart Open",          ["Porsche Tennis Grand Prix"]),
    ("Strasbourg Open",         ["Internationaux de Strasbourg"]),
    ("Queen's Club",            ["The HSBC Championships"]),
    ("Berlin Open",             ["Berlin Tennis Open"]),
    ("Bad Homburg Open",        ["Bad Homburg Open"]),
    ("Washington",              ["Mubadala DC Open"]),
    ("Monterrey Open",          ["Abierto GNP Seguros"]),
    ("Guadalajara Open",        ["Guadalajara Open"]),
    ("Singapore Tennis Open",   ["Singapore Tennis Open"]),
    ("Ningbo Open",             ["Ningbo Open"]),
    ("Pan Pacific Open",        ["Toray Pan Pacific Open"]),
    # Finals
    ("WTA Finals",             ["WTA Finals", "WTA Championships"]),
]

def major_for_event(league: str, event_short_name):
    """Canonical name of the tracked major this ESPN event is, or None.

    The single source of truth for what we cover. `_is_major` and the projection
    surface map both go through here, so the coverage list and the surface list
    cannot drift apart.
    """
    if league not in ("atp", "wta"):
        return None
    maj = _ATP_MAJORS if league == "atp" else _WTA_MAJORS
    name_lower = (event_short_name or "").lower()
    for canonical, aliases in maj:
        for alias in aliases:
            if alias.lower() in name_lower:
                return canonical
    return None


def surface_for(tour: str, tournament_id: str | None, event_name: str | None) -> tuple[str | None, str]:
    """Surface and its source, in dev's precedence: the event id, then the canonical major, else unmapped."""
    by_event = SHADOW_SURFACE_BY_EVENT.get(str(tournament_id or ""))
    if by_event:
        return by_event, "event_id"
    by_major = SHADOW_SURFACE_BY_MAJOR.get(major_for_event(tour, event_name) or "")
    if by_major:
        return by_major, "major_name"
    return None, "unmapped"
