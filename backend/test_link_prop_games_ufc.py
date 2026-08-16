"""UFC linker regressions from the real ESPN cards and production oracle.

The 33 expected ids below were read from production with SQLite ``mode=ro`` on
2026-08-14.  The published fighter names and segment times were captured from
``espn_client.games('ufc', card_date)``.  The two surfaces deliberately disagree
on side ordering, accents, truncation, middle names, aliases, and bout times.
"""
from link_prop_games import link_prop_game


# date, prop start, prop away/home, ESPN segment start, ESPN away/home, fight id
ORACLE = [
    ("2026-07-25", "13:00", "Cody Gibson", "Abdul Hussein", "13:00", "Abdul Hussein", "Cody Gibson", "401898030"),
    ("2026-07-25", "13:20", "Mike Davis", "Nurullo Aliev", "13:00", "Mike Davis", "Nurullo Aliev", "401886737"),
    ("2026-07-25", "13:40", "Brendson Ribeiro", "Magomed Tuchalov", "13:00", "Brendson Ribeiro", "Magomed Tuchalov", "401874314"),
    ("2026-07-25", "14:00", "Muhammad Said", "Dustin Jacoby", "13:00", "Muhammad Said", "Dustin Jacoby", "401898040"),
    ("2026-07-25", "14:00", "Axel Sola", "Ismael Bonfim", "13:00", "Axel Sola", "Ismael Bonfim", "401874317"),
    ("2026-07-25", "14:20", "Sam Patterson", "Santiago Ponzinibbio", "13:00", "Sam Patterson", "Santiago Ponzinibbio", "401891531"),
    ("2026-07-25", "15:35", "Thomas Petersen", "Valter Walker", "13:00", "Thomas Petersen", "Valter Walker", "401874312"),
    ("2026-07-25", "16:00", "Saygid Izagakhmaev", "Abubakar Vagaev", "16:00", "Saygid Izagakhmaev", "Abubakar Vagaev", "401890156"),
    ("2026-07-25", "16:20", "Tyrell Fortune", "Rizvan Kuniev", "16:00", "Tyrell Fortune", "Rizvan Kuniev", "401874311"),
    ("2026-07-25", "17:15", "Damian Rzepecki", "Magomed Zaynukov", "16:00", "Damian Rzepecki", "Magomed Zaynukov", "401886732"),
    ("2026-07-25", "17:20", "Ramazan Temurov", "Steve Erceg", "16:00", "Ramazan Temirov", "Steve Erceg", "401874315"),
    ("2026-07-25", "17:40", "Bogdan Guskov", "Magomed Ankalaev", "16:00", "Bogdan Guskov", "Magomed Ankalaev", "401892276"),
    ("2026-08-01", "15:40", "Bogdan Grad", "Dennis Buzukja", "14:00", "Bogdan Grad", "Dennis Buzukja", "401875163"),
    ("2026-08-01", "16:00", "Michael Oliveira", "Oban Elliott", "14:00", "Michael Oliveira", "Oban Elliott", "401879329"),
    ("2026-08-01", "16:40", "Tofiq Musayev", "Ludovit Klein", "14:00", "Tofiq Musayev", "Ludovit Klein", "401875161"),
    ("2026-08-01", "17:00", "Noah Gugnon", "Milos Janicic", "17:00", "Noah Gugnon", "Milos Janicic", "401902574"),
    ("2026-08-01", "17:10", "Gilbert Urbina", "Vlasto Cepo", "17:00", "Gilbert Urbina", "Vlasto Čepo", "401874462"),
    ("2026-08-01", "18:10", "Marcin Tybura", "Aleksandr Rakic", "17:00", "Marcin Tybura", "Aleksandar Rakic", "401873865"),
    ("2026-08-01", "18:15", "Robert Valentin", "Dusko Todorovic", "17:00", "Robert Valentin", "Duško Todorović", "401873866"),
    ("2026-08-01", "18:40", "Navajo Stirling", "Jan Blachowicz", "17:00", "Navajo Stirling", "Jan Blachowicz", "401892191"),
    ("2026-08-01", "19:10", "Daniel Rodriguez", "Uros Medic", "17:00", "Daniel Rodriguez", "Uroš Medić", "401870843"),
    ("2026-08-15", "21:30", "Myktybek Orolbai", "Jeremiah Wells", "21:30", "Myktybek Orolbai", "Jeremiah Wells", "401881926"),
    ("2026-08-15", "21:50", "Ramiz Brahimaj", "Neil Magny", "21:30", "Ramiz Brahimaj", "Neil Magny", "401886763"),
    ("2026-08-15", "22:10", "Lucas Fernando", "Rafael Tobias", "21:30", "Lucas Fernando", "Rafael Tobias", "401905694"),
    ("2026-08-15", "23:00", "Tresean Gore", "Vicente Luque", "23:00", "Tresean Gore", "Vicente Luque", "401869338"),
    ("2026-08-15", "23:20", "Eric McConico", "Donte Johnson", "23:00", "Eric McConico", "Donte Johnson", "401902724"),
    ("2026-08-15", "23:40", "Eduardo Henrique", "Charles Johnson", "23:00", "Eduardo Chapolin", "Charles Johnson", "401909737"),
    ("2026-08-16", "00:00", "Joel Alvarez", "Chidi Njokuani", "23:00", "Joel Álvarez", "Chidi Njokuani", "401905373"),
    ("2026-08-16", "01:00", "Esteban Ribovics", "Edson Barboza", "01:00", "Esteban Ribovics", "Edson Barboza", "401879330"),
    ("2026-08-16", "01:20", "Dustin Stoltzfus", "Mansur Abdul-Malik", "01:00", "Dustin Stoltzfus", "Mansur Abdul-Malik", "401881928"),
    ("2026-08-16", "01:40", "Kaua Fernandes", "Jalin Turner", "01:00", "Kauê Fernandes", "Jalin Turner", "401886764"),
    ("2026-08-16", "02:45", "Gillian Robertson", "Mackenzie Dern", "01:00", "Gillian Robertson", "Mackenzie Dern", "401878072"),
    ("2026-08-16", "03:30", "Ian Machado Garry", "Islam Makhachev", "01:00", "Ian Machado Garry", "Islam Makhachev", "401869336"),
]


def _game(row):
    date, _, _, _, source_time, source_away, source_home, fight_id = row
    return {
        "game_id": fight_id,
        "date": f"{date}T{source_time}:00Z",
        "away": {"name": source_away, "abbrev": source_away},
        "home": {"name": source_home, "abbrev": source_home},
    }


def _prop(row):
    date, prop_time, prop_away, prop_home, _, _, _, _ = row
    return {
        "league": "ufc", "date": date, "away": prop_away, "home": prop_home,
        "start_time": f"{date}T{prop_time}:00+00:00",
    }


def test_reproduces_all_33_production_fight_ids_exactly():
    slate = [_game(row) for row in ORACLE]
    actual = [link_prop_game(None, _prop(row), slate) for row in ORACLE]
    assert actual == [row[-1] for row in ORACLE]


def test_real_unpublished_matchup_refuses_to_guess():
    slate = [_game(row) for row in ORACLE if row[0] == "2026-07-25"]
    prop = {"league": "ufc", "date": "2026-07-25",
            "away": "Wellington Turman", "home": "Islam Dulatov",
            "start_time": "2026-07-25T17:00:00+00:00"}
    assert link_prop_game(None, prop, slate) == ""


def test_one_name_fallback_must_identify_one_fight_only():
    slate = [
        {"game_id": "1", "away": {"name": "Unknown Alias"},
         "home": {"name": "Repeated Fighter"}, "date": "2026-08-15T23:00Z"},
        {"game_id": "2", "away": {"name": "Other Alias"},
         "home": {"name": "Repeated Fighter"}, "date": "2026-08-15T23:00Z"},
    ]
    prop = {"league": "ufc", "date": "2026-08-15",
            "away": "Unpublished Name", "home": "Repeated Fighter",
            "start_time": "2026-08-15T23:00:00+00:00"}
    assert link_prop_game(None, prop, slate) == ""
