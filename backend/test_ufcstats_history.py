import datetime as dt
import json
import sqlite3

from ingest_ufc_fight_stats.targets import FighterTarget
from ingest_ufc_fight_stats.ufcstats_pipeline import (
    UfcIdentityMerge,
    UfcStatsPlan,
    apply_ufcstats_plan,
    build_ufcstats_plan,
)
from ingest_ufc_fight_stats.ufcstats_source import (
    FighterProfile,
    SourceCardFight,
    SourceEvent,
    SourceFight,
    SourceFighter,
    parse_completed_events,
    parse_event_card,
    parse_fighter_profile,
)
import migrate_ufcstats_history as migration


EVENTS_HTML = """
<table><tr><td><a href="http://www.ufcstats.com/event-details/eeeeeeeeeeeeeeee">Test Card</a>
<span>August 29, 2026</span></td></tr></table>
"""

CARD_HTML = """
<table><tr data-link="http://www.ufcstats.com/fight-details/ffffffffffffffff"><td>
<a href="http://www.ufcstats.com/fighter-details/aaaaaaaaaaaaaaaa">Fighter Alpha</a>
<a href="http://www.ufcstats.com/fighter-details/bbbbbbbbbbbbbbbb">Fighter Beta</a>
</td></tr></table>
"""

PROFILE_HTML = """
<h2><span class="b-content__title-highlight">Fighter Alpha</span></h2>
<table><tr data-link="http://www.ufcstats.com/fight-details/ffffffffffffffff">
<td><p>win</p></td>
<td><p><a href="http://www.ufcstats.com/fighter-details/aaaaaaaaaaaaaaaa">Fighter Alpha</a></p>
    <p><a href="http://www.ufcstats.com/fighter-details/bbbbbbbbbbbbbbbb">Fighter Beta</a></p></td>
<td><p>0</p><p>0</p></td>
<td><p>34</p><p>8</p></td>
<td><p>2</p><p>0</p></td>
<td><p>0</p><p>0</p></td>
<td><p><a href="http://www.ufcstats.com/event-details/eeeeeeeeeeeeeeee">Test Card</a></p>
    <p>Aug. 29, 2026</p></td>
<td><p>U-DEC</p></td><td><p>3</p></td><td><p>5:00</p></td>
</tr></table>
"""


def test_parses_published_event_card_and_profile_fields():
    events = parse_completed_events(EVENTS_HTML)
    card = parse_event_card(CARD_HTML)
    profile = parse_fighter_profile(PROFILE_HTML, "aaaaaaaaaaaaaaaa", limit=5)

    assert [(event.source_event_key, event.date) for event in events] == [
        ("eeeeeeeeeeeeeeee", "2026-08-29")
    ]
    assert card == [
        SourceCardFight(
            "ffffffffffffffff",
            (SourceFighter("aaaaaaaaaaaaaaaa", "Fighter Alpha"),
             SourceFighter("bbbbbbbbbbbbbbbb", "Fighter Beta")),
        )
    ]
    assert profile.name == "Fighter Alpha"
    assert profile.fights[0].significant_strikes == 34
    assert profile.fights[0].fight_time_seconds == 900
    assert profile.fights[0].method == "DEC"


class FakeClient:
    def completed_events(self):
        return [SourceEvent("eventaa", "Test Card", "2026-08-29", "event-url")]

    def event_card(self, _event):
        return [
            SourceCardFight(
                "fightaa",
                (SourceFighter("fightera", "Fighter Alpha"),
                 SourceFighter("fighterb", "Fighter Beta")),
            )
        ]

    def fighter_profile(self, source_key, limit):
        opponent = "Fighter Beta" if source_key == "fightera" else "Fighter Alpha"
        opponent_key = "fighterb" if source_key == "fightera" else "fightera"
        strikes = 34 if source_key == "fightera" else 8
        result = "W" if source_key == "fightera" else "L"
        return FighterProfile(
            source_key,
            "Fighter Alpha" if source_key == "fightera" else "Fighter Beta",
            (SourceFight(
                "fightaa", "eventaa", "2026-08-29", opponent, opponent_key,
                result, "DEC", strikes, 3, "5:00", 900,
            ),)[:limit],
        )


class ReplacementClient(FakeClient):
    def published_events(self):
        return self.completed_events()

    def event_card(self, _event):
        return [
            SourceCardFight(
                "fightaa",
                (SourceFighter("replacement", "Replacement Fighter"),
                 SourceFighter("fighterb", "Fighter Beta")),
            )
        ]


class AliasClient(FakeClient):
    def event_card(self, _event):
        return [
            SourceCardFight(
                "fightaa",
                (SourceFighter("fightera", "Matthieu Duclos"),
                 SourceFighter("fighterb", "Fighter Beta")),
            )
        ]

    def fighter_profile(self, source_key, limit):
        if source_key == "fightera":
            return FighterProfile(source_key, "Matthieu Duclos", ())
        return super().fighter_profile(source_key, limit)


def _targets():
    return [
        FighterTarget(1, "Fighter Alpha", "101", "2026-08-29", 10, "Fighter Beta"),
        FighterTarget(2, "Fighter Beta", "102", "2026-08-29", 10, "Fighter Alpha"),
    ]


def test_plan_resolves_exact_pair_and_builds_both_fighter_logs():
    plan = build_ufcstats_plan(
        _targets(),
        {1: {"fighteralpha"}, 2: {"fighterbeta"}},
        {}, {}, {}, FakeClient(), limit=5, emit=lambda _: None,
    )

    assert plan.resolved_count == 2
    assert plan.mappings == {1: "fightera", 2: "fighterb"}
    assert len(plan.inserts) == 2
    assert plan.unresolved == []
    assert plan.source_errors == []
    stats = {row.player_id: json.loads(row.stats_json) for row in plan.inserts}
    assert stats[1]["sigStrikesLanded"] == 34
    assert stats[2]["fight_time"] == 15.0
    assert stats[1]["win_by_decision"] == 1.0
    assert stats[1]["finishes"] == 0.0
    assert stats[2]["win_by_decision"] == 0.0


def test_replacement_is_not_mistaken_for_withdrawn_fighter_from_opponent_alone():
    target = FighterTarget(
        1, "Withdrawn Fighter", None, "2026-08-29", 10, "Fighter Beta"
    )
    plan = build_ufcstats_plan(
        [target],
        {1: {"withdrawnfighter"}},
        {},
        {},
        {},
        ReplacementClient(),
        include_upcoming_events=True,
        allow_pair_alias=True,
        emit=lambda _: None,
    )

    assert plan.active_target_count == 0
    assert len(plan.inactive) == 1
    assert plan.mappings == {}
    assert plan.unresolved == []


def test_middle_name_omission_requires_the_published_opponent_pair():
    targets = [
        FighterTarget(1, "Matthieu Letho Duclos", None, "2026-08-29", 10,
                      "Fighter Beta"),
    ]
    plan = build_ufcstats_plan(
        targets,
        {1: {"matthieulethoduclos"}},
        {},
        {},
        {},
        FakeClient(),
        allow_pair_alias=True,
        emit=lambda _: None,
    )

    # FakeClient publishes Fighter Alpha, which is not a compatible form.  The
    # exact opponent alone is deliberately insufficient identity evidence.
    assert plan.active_target_count == 0
    assert len(plan.inactive) == 1


def test_same_bout_compatible_names_collapse_to_one_published_fighter():
    targets = [
        FighterTarget(1, "Matthieu Letho Duclos", None, "2026-08-29", 10,
                      "Fighter Beta"),
        FighterTarget(3, "Matthieu Duclos", None, "2026-08-29", 10,
                      "Fighter Beta"),
    ]
    plan = build_ufcstats_plan(
        targets,
        {1: {"matthieulethoduclos"}, 3: {"matthieuduclos"}},
        {},
        {},
        {},
        AliasClient(),
        allow_pair_alias=True,
        emit=lambda _: None,
    )

    assert plan.active_target_count == 1
    assert plan.identity_merges == [
        UfcIdentityMerge(1, 3, "fightera", "Matthieu Duclos")
    ]
    assert plan.mappings == {1: "fightera"}
    assert plan.conflicts == []


def _database(path):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE players(id INTEGER PRIMARY KEY,name TEXT,league TEXT,espn_id TEXT);
        CREATE TABLE player_source_ids(
          id INTEGER PRIMARY KEY AUTOINCREMENT,source TEXT,league TEXT,
          source_player_key TEXT,player_id INTEGER,first_seen TEXT,last_seen TEXT,
          UNIQUE(source,league,source_player_key));
        CREATE TABLE app_schema_migrations(
          migration_id TEXT PRIMARY KEY,checksum TEXT NOT NULL,
          applied_at TEXT NOT NULL DEFAULT(datetime('now')),
          status TEXT NOT NULL DEFAULT 'applied',note TEXT);
    """)
    con.executemany(
        "INSERT INTO players VALUES(?,?,'ufc',?)",
        [(1, "Fighter Alpha", "101"), (2, "Fighter Beta", "102")],
    )
    con.commit()
    return con


def test_explicit_migration_and_apply_are_idempotent(tmp_path):
    db_path = tmp_path / "clone.db"
    backup_path = tmp_path / "clone.backup.db"
    con = _database(db_path)
    backup = sqlite3.connect(backup_path)
    con.backup(backup)
    backup.close()
    con.close()

    assert migration.inspect(str(db_path))["state"] == "pending"
    assert migration.apply(str(db_path), str(backup_path))["state"] == "applied"

    plan = build_ufcstats_plan(
        _targets(),
        {1: {"fighteralpha"}, 2: {"fighterbeta"}},
        {}, {}, {}, FakeClient(), limit=5, emit=lambda _: None,
    )
    result = apply_ufcstats_plan(str(db_path), plan)
    assert result["mappings_inserted"] == 2
    assert result["inserted_logs"] == 2

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    stored = {
        (row["source_player_key"], row["game_id"]): row
        for row in con.execute("SELECT * FROM player_game_logs_ufcstats")
    }
    existing = {}
    for row in stored.values():
        from ingest_ufc_fight_stats.ufcstats_pipeline import PreparedUfcStatsLog
        prepared = PreparedUfcStatsLog(
            row["player_id"], row["source_player_key"], row["game_id"],
            row["source_event_key"], row["season"], row["game_date"],
            row["opponent"], row["stats"],
        )
        existing[prepared.natural_key] = prepared
    con.close()

    second = build_ufcstats_plan(
        _targets(),
        {1: {"fighteralpha"}, 2: {"fighterbeta"}},
        {1: "fightera", 2: "fighterb"},
        {"fightera": 1, "fighterb": 2},
        existing, FakeClient(), limit=5, emit=lambda _: None,
    )
    assert second.existing_count == 2
    assert second.inserts == []
    assert second.updates == []
    assert second.mappings == {}
    assert sqlite3.connect(db_path).execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_source_proven_duplicate_merge_reparents_every_discovered_reference(tmp_path):
    db_path = tmp_path / "merge.db"
    backup_path = tmp_path / "merge.backup.db"
    con = _database(db_path)
    con.executescript("""
        CREATE TABLE name_alias(
          id INTEGER PRIMARY KEY AUTOINCREMENT,player_id INTEGER,alias_norm TEXT,
          UNIQUE(player_id,alias_norm));
        CREATE TABLE props(
          id INTEGER PRIMARY KEY,game_id INTEGER,player_id INTEGER,market TEXT,
          line REAL,side TEXT,source TEXT,captured_at TEXT);
        INSERT INTO players VALUES(3,'Fighter A. Alpha','ufc',NULL);
        INSERT INTO props VALUES(1,10,3,'win_by_decision',0.5,'over','bovada','now');
    """)
    con.commit()
    backup = sqlite3.connect(backup_path)
    con.backup(backup)
    backup.close()
    con.close()
    migration.apply(str(db_path), str(backup_path))

    plan = UfcStatsPlan(
        target_count=2,
        active_target_count=2,
        mappings={1: "fightera"},
        identity_merges=[UfcIdentityMerge(1, 3, "fightera", "Fighter A. Alpha")],
    )
    result = apply_ufcstats_plan(str(db_path), plan)

    con = sqlite3.connect(db_path)
    assert result["identities_merged"] == 1
    assert con.execute("SELECT player_id FROM props").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM players WHERE id=3").fetchone()[0] == 0
    assert con.execute(
        "SELECT player_id FROM player_source_ids WHERE source_player_key='fightera'"
    ).fetchone()[0] == 1
    con.close()


def test_fighter_form_is_database_only_and_reports_ufcstats(monkeypatch, tmp_path):
    import routers.games as games

    db_path = tmp_path / "form.db"
    con = sqlite3.connect(db_path)
    con.executescript("""
        CREATE TABLE players(
          id INTEGER PRIMARY KEY,name TEXT,league TEXT,espn_id TEXT
        );
        CREATE TABLE player_game_logs_ufcstats(
          player_id INTEGER,league TEXT,game_id TEXT,source_event_key TEXT,
          game_date TEXT,opponent TEXT,stats TEXT
        );
    """)
    con.execute("INSERT INTO players VALUES(1,'Fighter Alpha','ufc','101')")
    con.execute(
        "INSERT INTO player_game_logs_ufcstats VALUES(?,?,?,?,?,?,?)",
        (1, "ufc", "fight-aa", "event-aa", "2026-08-01", "Fighter Beta",
         json.dumps({"result": "W", "method": "DEC", "round": 3,
                     "clock_display": "5:00"})),
    )
    con.commit()
    con.close()

    def connection():
        opened = sqlite3.connect(db_path)
        opened.row_factory = sqlite3.Row
        return opened

    monkeypatch.setattr(games, "_db", connection)
    result = games.ufc_fighter_form(1)

    assert result["source"] == "ufcstats"
    assert result["fights"] == [{
        "result": "W", "method": "DEC", "round": 3, "time": "5:00",
        "opponent": "Fighter Beta",
        "date": "2026-08-01", "event_id": "event-aa", "fight_id": "fight-aa",
    }]
