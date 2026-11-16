"""Projection caches refresh when tennis-spine identities change."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tennis_daily_projections import needs_projection_refresh  # noqa: E402


def _match(home_id="100", away_id="200"):
    return {
        "gameId": "match-1",
        "identity": {
            "home": {"sackmann_player_id": home_id},
            "away": {"sackmann_player_id": away_id},
        },
    }


def _projection(home_id=None, away_id=None):
    return {
        "homeDoubleFaults": None,
        "awayDoubleFaults": None,
        "unavailableReason": "One or both player IDs are not mapped through the tennis spine.",
        "_sackmannPlayerIds": {"home": home_id, "away": away_id},
    }


def test_old_unmapped_cache_refreshes_after_players_resolve():
    stored = {"match-1": _projection()}
    assert needs_projection_refresh(stored, [_match("100", "200")])


def test_cache_refreshes_when_a_resolved_player_mapping_changes():
    stored = {"match-1": _projection("100", "200")}
    assert needs_projection_refresh(stored, [_match("100", "300")])


def test_current_unmapped_cache_does_not_refresh_repeatedly():
    stored = {"match-1": _projection()}
    assert not needs_projection_refresh(stored, [_match(None, None)])


def test_cache_without_double_fault_fields_refreshes():
    stored = {"match-1": {"_sackmannPlayerIds": {"home": "100", "away": "200"}}}
    assert needs_projection_refresh(stored, [_match()])


# --- coverage drives surfaces -------------------------------------------------
# The surface map used to be keyed only on ESPN tournament ids we had happened to
# see (Shanghai and Wuhan), so every other tracked event silently had no surface
# and therefore no surface-dependent output at all. These pin the invariant that
# keeps that from returning: every event the coverage rule tracks must resolve to
# a surface without needing an ESPN id.

from espn_client.scoreboard import _ATP_MAJORS, _WTA_MAJORS, major_for_event  # noqa: E402
import tennis_daily_projections as proj  # noqa: E402


def test_every_tracked_major_has_a_surface():
    missing = [
        (tour, canonical)
        for tour, majors in (("atp", _ATP_MAJORS), ("wta", _WTA_MAJORS))
        for canonical, _aliases in majors
        if canonical not in proj.SURFACE_BY_MAJOR
    ]
    assert missing == []


def test_event_name_resolves_a_surface_without_an_espn_id():
    for tour, event_name, expected in (
        ("atp", "Rolex Paris Masters", "Hard"),
        ("atp", "Wimbledon", "Grass"),
        ("atp", "Roland Garros", "Clay"),
        ("atp", "Rolex Shanghai Masters", "Hard"),
        ("wta", "Qatar TotalEnergies Open", "Hard"),
        ("wta", "Dongfeng Voyah Wuhan Open", "Hard"),
        ("wta", "Mutua Madrid Open", "Clay"),
    ):
        major = major_for_event(tour, event_name)
        assert major is not None, f"{event_name} is tracked but has no canonical major"
        assert proj.SURFACE_BY_MAJOR[major] == expected, f"{event_name} -> {expected}"


def test_mens_grand_slams_are_best_of_five_and_everything_else_three():
    for tour, event_name in (
        ("atp", "Wimbledon"), ("atp", "Roland Garros"),
        ("atp", "US Open"), ("atp", "Australian Open"),
    ):
        assert major_for_event(tour, event_name) in proj.FIVE_SET_MAJORS
    for tour, event_name in (
        ("wta", "Wimbledon"), ("wta", "Roland Garros"),
        ("atp", "Rolex Paris Masters"), ("atp", "ATP Finals"),
        ("wta", "WTA Finals"), ("atp", "China Open"),
    ):
        major = major_for_event(tour, event_name)
        assert not (tour == "atp" and major in proj.FIVE_SET_MAJORS)


def test_untracked_event_is_not_given_a_surface():
    assert major_for_event("atp", "Vienna Open") is None
    assert major_for_event("atp", "Some Challenger") is None


# ---------------------------------------------------------------------------
# 500 coverage (2026). The names are ESPN shortNames observed on the scoreboard for each event's week,
# not guesses. The tiers come from the tours' 2026 calendars. See docs/TENNIS-COVERAGE.md section 2b.
# ---------------------------------------------------------------------------

ATP_500_OBSERVED = (
    ("Nexo Dallas Open", "Dallas Open", "Hard"),
    ("ABN Amro Open", "Rotterdam Open", "Hard"),
    ("Qatar ExxonMobil Open", "Qatar ExxonMobil Open", "Hard"),
    ("Rio Open presented by Claro", "Rio Open", "Clay"),
    ("Abierto Mexicano Telcel presentado por HSBC", "Acapulco Open", "Hard"),
    ("Dubai Duty Free Tennis Championships", "Dubai", "Hard"),
    ("BMW Open by Bitpanda", "Munich Open", "Clay"),
    ("Barcelona Open Banc Sabadell", "Barcelona Open", "Clay"),
    ("Bitpanda Hamburg Open", "Hamburg Open", "Clay"),
    ("Terra Wortmann Open", "Halle Open", "Grass"),
    ("HSBC Championships", "Queen's Club", "Grass"),
    ("Mubadala DC Open", "Washington", "Hard"),
    ("Kinoshita Group Japan Open Tennis Championships", "Tokyo Open", "Hard"),
    ("Erste Bank Open", "Vienna Open", "Hard"),
    ("Swiss Indoors Basel", "Basel", "Hard"),
)

WTA_500_OBSERVED = (
    ("Brisbane International presented by ANZ", "Brisbane International", "Hard"),
    ("Adelaide International", "Adelaide International", "Hard"),
    ("Mubadala Abu Dhabi Open presented by Abu Dhabi Sports Council", "Abu Dhabi Open", "Hard"),
    ("Mérida Open Akron", "Mérida Open", "Hard"),
    ("Credit One Charleston Open", "Charleston Open", "Clay"),
    ("Upper Austria Ladies Linz", "Linz Open", "Hard"),
    ("Porsche Tennis Grand Prix", "Stuttgart Open", "Clay"),
    ("Internationaux de Strasbourg presented by Mammotion", "Strasbourg Open", "Clay"),
    ("The HSBC Championships", "Queen's Club", "Grass"),
    ("VANDA Pharmaceuticals Berlin Tennis Open", "Berlin Open", "Grass"),
    ("Bad Homburg Open powered by Solarwatt", "Bad Homburg Open", "Grass"),
    ("Mubadala DC Open", "Washington", "Hard"),
    ("Abierto GNP Seguros", "Monterrey Open", "Hard"),
    ("Guadalajara Open presentado por Santander", "Guadalajara Open", "Hard"),
    ("Singapore Tennis Open presented by BNP Paribas", "Singapore Tennis Open", "Hard"),
    ("BNB Ningbo Open", "Ningbo Open", "Hard"),
    ("Toray Pan Pacific Open Tennis", "Pan Pacific Open", "Hard"),
)

# ---------------------------------------------------------------------------
# 250 coverage (2026). Names are ESPN shortNames from the 2026 season lists on the ATP and WTA scoreboards
# (ESPN year-wide query 2026-10-21, plus a 4-day WTA sweep and a weekly ATP cross-check to 2026-12-31).
# Tiers: the ATP's 2026 calendar for the ATP; Wikipedia's 2026 WTA Tour and tennis-db for the WTA, which agree.
# See docs/TENNIS-COVERAGE.md section 2c.
# ---------------------------------------------------------------------------

ATP_250_OBSERVED = (
    ("Brisbane International presented by ANZ", "Brisbane International", "Hard"),
    ("Bank of China Hong Kong Tennis Open", "Hong Kong Tennis Open", "Hard"),
    ("Adelaide International", "Adelaide International", "Hard"),
    ("ASB Classic", "ASB Classic", "Hard"),
    ("Open Occitanie", "Open Occitanie", "Hard"),
    ("IEB+ Argentina Open", "Argentina Open", "Clay"),
    ("Delray Beach Open", "Delray Beach Open", "Hard"),
    ("BCI Seguros Chile Open", "Chile Open", "Clay"),
    ("Tiriac Open presented by UniCredit Bank", "Tiriac Open", "Clay"),
    ("Fayez Sarofim & Co. U.S. Men's Clay Court Championship", "US Men's Clay Court Championship", "Clay"),
    ("Grand Prix Hassan II", "Grand Prix Hassan II", "Clay"),
    ("Gonet Geneva Open", "Geneva Open", "Clay"),
    ("Boss Open", "Boss Open", "Grass"),
    ("Libéma Open", "Libéma Open", "Grass"),
    ("Vanda Pharmaceuticals Mallorca Championships", "Mallorca Championships", "Grass"),
    ("Lexus Eastbourne Open", "Eastbourne Open", "Grass"),
    ("Nordea Open", "Nordea Open", "Clay"),
    ("EFG Swiss Open Gstaad", "Gstaad Open", "Clay"),
    ("Plava Laguna Croatia Open Umag", "Umag Open", "Clay"),
    ("Generali Open", "Generali Open", "Clay"),
    ("Millennium Estoril Open", "Estoril Open", "Clay"),
    ("Mifel Tennis Open by Telcel Oppo", "Mifel Tennis Open", "Hard"),
    ("Winston-Salem Open", "Winston-Salem Open", "Hard"),
    ("Chengdu Open", "Chengdu Open", "Hard"),
    ("AITO Hangzhou Open", "Hangzhou Open", "Hard"),
    ("Almaty Open", "Almaty Open", "Hard"),
    ("BNP Paribas Fortis European Open", "Brussels Open", "Hard"),
    ("Grand Prix Auvergne-Rhône-Alpes", "Lyon Open", "Hard"),
    ("Bybit Stockholm Open", "Stockholm Open", "Hard"),
)

WTA_250_OBSERVED = (
    ("ASB Classic", "ASB Classic", "Hard"),
    ("Hobart International", "Hobart International", "Hard"),
    ("Ostrava Open", "Ostrava Open", "Hard"),
    ("Transylvania Open powered by Kaufland", "Transylvania Open", "Hard"),
    ("ATX Open", "ATX Open", "Hard"),
    ("Copa Colsanitas Colsubsidio", "Bogotá Open", "Clay"),
    ("Open Capfinances Rouen Métropole", "Rouen Open", "Clay"),
    ("Grand Prix Son Altesse Royale", "Morocco Open", "Clay"),
    ("Libéma Open", "Libéma Open", "Grass"),
    ("Lexus Nottingham Open", "Nottingham Open", "Grass"),
    ("Lexus Eastbourne Open", "Eastbourne Open", "Grass"),
    ("Unicredit Iasi Open", "Iași Open", "Clay"),
    ("Vanda Pharmaceuticals Athens Open", "Athens Open", "Hard"),
    ("MSC Hamburg Ladies Open", "Hamburg Ladies Open", "Clay"),
    ("Livesport Prague Open", "Prague Open", "Hard"),
    ("The Memphis Classic", "Memphis Classic", "Hard"),
    ("SP Open", "São Paulo Open", "Hard"),
    ("Korea Open", "Korea Open", "Hard"),
    ("Kinoshita Group Japan Open", "Japan Women's Open", "Hard"),
    ("Guangzhou Open", "Guangzhou Open", "Hard"),
    ("Prudential Hong Kong Tennis Open", "Hong Kong Open", "Hard"),
    ("Chennai Open", "Chennai Open", "Hard"),
)

# Events on the same scoreboards that neither the ATP 2026 calendar nor the WTA 250 lists (Wikipedia, tennis-db)
# list as a 250. These are 125s or unlisted. None may be tracked. Jiangxi Open is on tennis-db only, and ESPN
# publishes no November Jiangxi event in 2026, so the only Jiangxi on ESPN (a May event) stays out too.
UNTRACKED_OBSERVED = {
    "wta": ("Jiangxi Open", "Workday Canberra International", "Queretaro Open", "Lexus Ilkley Open",
            "Memorial Eugenio Fontana", "Odlum Brown VanOpen", "Axeria Open 2026 powered by Intaro Sport",
            "Ennoble Care Philly Open", "Abierto de Curitiba", "Turk Telekom Ankara Open", "Eupago Porto Open",
            "Delta Motors Tolentino Open", "BBVA Open Internacional De Valencia",
            "Zavarovalnica Triglav Ljubljana", "L&T Mumbai Open", "Megasaray Hotels Open 1",
            "Trophée Clarins", "Istanbul Open", "Parma Ladies Open presented by Iren",
            "Lexus Birmingham Open", "Warsaw T-Mobile Polish Open", "Dubrovnik Open"),
}


def test_every_observed_250_name_resolves_to_its_canonical_event():
    for tour, rows in (("atp", ATP_250_OBSERVED), ("wta", WTA_250_OBSERVED)):
        for espn_name, canonical, _surface in rows:
            assert major_for_event(tour, espn_name) == canonical, f"{tour}: {espn_name}"


def test_every_added_250_has_its_surface_and_is_never_best_of_five():
    for tour, rows in (("atp", ATP_250_OBSERVED), ("wta", WTA_250_OBSERVED)):
        for espn_name, canonical, surface in rows:
            assert proj.SURFACE_BY_MAJOR[canonical] == surface, f"{espn_name} -> {surface}"
            assert canonical not in proj.FIVE_SET_MAJORS, f"{espn_name} must be best of three"


def test_the_2026_250_lists_are_complete_and_distinct():
    # 29 ATP 250s on the ATP 2026 calendar; 22 WTA 250s on both Wikipedia and tennis-db.
    assert len(ATP_250_OBSERVED) == 29 and len({c for _n, c, _s in ATP_250_OBSERVED}) == 29
    assert len(WTA_250_OBSERVED) == 22 and len({c for _n, c, _s in WTA_250_OBSERVED}) == 22


def test_every_observed_500_name_resolves_to_its_canonical_event():
    for tour, rows in (("atp", ATP_500_OBSERVED), ("wta", WTA_500_OBSERVED)):
        for espn_name, canonical, _surface in rows:
            assert major_for_event(tour, espn_name) == canonical, f"{tour}: {espn_name}"


def test_every_added_500_has_its_surface_and_is_never_best_of_five():
    for tour, rows in (("atp", ATP_500_OBSERVED), ("wta", WTA_500_OBSERVED)):
        for espn_name, canonical, surface in rows:
            assert proj.SURFACE_BY_MAJOR[canonical] == surface, f"{espn_name} -> {surface}"
            assert canonical not in proj.FIVE_SET_MAJORS, f"{espn_name} must be best of three"


def test_non_250_events_on_the_same_scoreboards_stay_untracked():
    for tour, names in UNTRACKED_OBSERVED.items():
        for name in names:
            assert major_for_event(tour, name) is None, f"{tour}: {name} must not be tracked"


def test_added_500_canonicals_are_distinct_from_the_250s_they_sit_beside():
    tracked = {canonical for _n, canonical, _s in ATP_500_OBSERVED + WTA_500_OBSERVED}
    assert "Kinoshita Group Japan Open" not in tracked
    assert len(ATP_500_OBSERVED) == 15 and len(WTA_500_OBSERVED) == 17
