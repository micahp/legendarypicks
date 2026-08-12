"""team_game_stats.stats — the JSON home for per-game team stats.

The migration is additive and two-sided (writers populate blob AND columns,
readers prefer the blob), so the tests that matter are the ones that pin which
source actually won. A test that only checks "the number is right" passes on a
database where the blob is ignored entirely.
"""
import json
import sqlite3

import pytest

from team_stats_json import stats_from_row, stats_to_json
from team_stats_schema import all_stat_keys, stat_keys_for


def _row(**cols):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    names = list(cols)
    con.execute(f"CREATE TABLE t({','.join(names)})")
    con.execute(
        f"INSERT INTO t({','.join(names)}) VALUES({','.join('?' * len(names))})",
        [cols[n] for n in names],
    )
    return con.execute("SELECT * FROM t").fetchone()


class TestSerialisation:
    def test_writes_only_keys_the_league_declares(self):
        # rebounds is an NBA key; a football row must not carry it even if the
        # caller hands one over. The registry is the claim, not the input.
        out = json.loads(stats_to_json("ncaaf", {"first_downs": 18, "rebounds": 40}))
        assert out == {"first_downs": 18}

    def test_real_zero_survives_and_absence_does_not(self):
        # A dash is not a zero. 0 turnovers is a measurement; a missing
        # rushing_yards is not, and must not serialise as null.
        out = json.loads(stats_to_json("ncaaf", {"turnovers": 0, "rushing_yards": None}))
        assert out == {"turnovers": 0}
        assert "rushing_yards" not in out

    def test_empty_string_is_absence_not_a_value(self):
        # sqlite happily stores '' in an INTEGER column, and the live dev DB has
        # them — they are empty cells, not data.
        assert json.loads(stats_to_json("ncaaf", {"first_downs": "", "total_yards": 341})) == {
            "total_yards": 341
        }

    def test_league_with_no_vocabulary_serialises_nothing(self):
        assert json.loads(stats_to_json("cricket", {"first_downs": 18})) == {}


class TestReadPrecedence:
    def test_blob_wins_over_columns(self):
        row = _row(stats=json.dumps({"first_downs": 18}), first_downs=99)
        assert stats_from_row(row)["first_downs"] == 18

    def test_columns_used_when_no_blob(self):
        assert stats_from_row(_row(stats=None, first_downs=99))["first_downs"] == 99

    def test_malformed_blob_falls_back_rather_than_raising(self):
        # A broken blob must not take a page down while the columns that predate
        # it are still populated.
        assert stats_from_row(_row(stats="{not json", first_downs=99))["first_downs"] == 99

    def test_missing_stats_column_is_absence_not_an_error(self):
        # Code newer than its database: the migration may not have run yet.
        assert stats_from_row(_row(first_downs=99))["first_downs"] == 99


class TestRegistryIsSingleSource:
    def test_schema_defers_to_the_contract(self):
        from team_stats_contract import STAT_FIELDS

        for league, keys in STAT_FIELDS.items():
            assert stat_keys_for(league) == tuple(keys), league

    def test_unknown_league_is_unverified_not_empty(self):
        # () means "nobody declared a vocabulary", which the migration reports as
        # SKIPPED. A league that silently serialised {} would look migrated.
        assert stat_keys_for("cricket") == ()

    def test_all_stat_keys_is_the_union(self):
        every = all_stat_keys()
        assert len(every) == len(set(every)), "duplicate key in the union"
        for league in ("nba", "nhl", "nfl", "ncaaf", "mls"):
            assert set(stat_keys_for(league)) <= set(every), league


class TestAgainstTheRealDatabase:
    """The blob must be what the aggregates actually read on dev."""

    DB = "data/picks.dev.db"

    @pytest.fixture
    def con(self):
        try:
            c = sqlite3.connect(f"file:{self.DB}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            pytest.skip("dev database not present")
        c.row_factory = sqlite3.Row
        cols = {r[1] for r in c.execute("PRAGMA table_info(team_game_stats)")}
        if "stats" not in cols:
            c.close()
            pytest.skip("dev database not migrated yet")
        yield c
        c.close()

    def test_every_migrated_row_holds_only_declared_keys(self, con):
        rows = con.execute(
            "SELECT league, stats FROM team_game_stats "
            "WHERE stats IS NOT NULL AND stats != '{}'"
        ).fetchall()
        assert rows, "no migrated rows to check"
        for r in rows:
            declared = set(stat_keys_for(r["league"]))
            got = set(json.loads(r["stats"]))
            assert got <= declared, f"{r['league']} blob has undeclared keys: {got - declared}"

    def test_no_blob_is_json_null_or_a_list(self, con):
        for r in con.execute(
            "SELECT stats FROM team_game_stats WHERE stats IS NOT NULL"
        ):
            assert isinstance(json.loads(r["stats"]), dict)
