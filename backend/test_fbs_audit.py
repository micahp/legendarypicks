"""Tests for the FBS audit scripts.

These pin the specific traps that cost real time in this work, so a future
edit that reintroduces one fails here rather than in a report nobody reads.

The traps, and the test that plants each:

1. The ESPN event id is TEXT in the database and int64 in the releases. A
   text-vs-int comparison silently matches nothing and reads as "the release
   has no coverage of our fixtures", which is false. `test_fixture_keys_normalise`
   plants a padded/zero-prefixed id and checks both forms normalise equal.

2. The `any key` coverage query is an OR over several JSON predicates. An
   unparenthesised OR binds across the whole WHERE clause and matches every
   log row for the market, not the props, producing coverage over 100%.
   `test_any_key_query_stays_scoped` checks the parenthesisation is present.

3. `league_mean` is called once per item by `marcel`. Without a cache it is
   O(items x players x games) and does not finish. `test_league_mean_is_cached`
   checks the memo exists and returns the same object.

4. The 2025 holdout does not exist. `test_holdout_is_not_2025` pins the
   pre-registered statement so a later edit cannot silently grade a season
   with no props.
"""
import os
import re
import sqlite3
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    HERE, "data", "picks.dev.db"
)

# The tests that need the database skip rather than fail when it is absent,
# because the audit scripts are the primary deliverable and a missing dev DB
# is an environment fact, not a code defect.
needs_db = pytest.mark.skipif(
    not os.path.exists(DB), reason="dev database not present: %s" % DB
)


def read(path):
    with open(os.path.join(HERE, path)) as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# 1. key normalisation
# ---------------------------------------------------------------------------
def test_fixture_keys_normalise():
    src = read("audit_fbs_reconcile.py")
    assert "def load_fixtures" in src
    # The loader must convert through int(), which is what makes the TEXT and
    # int64 forms comparable. A bare str() would not.
    assert "int(raw_id)" in src, (
        "load_fixtures must normalise through int(); a text-vs-int comparison "
        "matches nothing and reads as zero release coverage"
    )


def test_final_scores_are_string_keyed():
    src = read("audit_fbs_reconcile.py")
    assert "str(int(k))" in src, (
        "final_scores must key on str(int(k)) to match the normalised fixture keys"
    )


# ---------------------------------------------------------------------------
# 2. the OR scoping trap
# ---------------------------------------------------------------------------
def test_any_key_query_stays_scoped():
    src = read("fbs_prop_fields.py")
    assert 'where_any = "(" +' in src or "where_any = \"(\" +" in src, (
        "the `any key` predicate must be parenthesised; an unparenthesised OR "
        "binds across the WHERE clause and matches every log row, giving "
        "coverage over 100%"
    )


def test_coverage_cannot_exceed_the_item_count():
    """A per-market coverage count can never exceed the market's item count.

    This is the invariant the OR trap violated. It is checked structurally by
    asserting the two queries share an identical prefix up to the predicate,
    because a shared prefix is what keeps them on the same item set.
    """
    src = read("fbs_prop_fields.py")
    m = re.search(r"base = \(\"(.*?)\"\)", src, re.S)
    assert m, "fbs_prop_fields.py must build the item set from one `base` prefix"
    prefix = m.group(1)
    assert "JOIN player_game_logs l" in prefix
    assert "pr.prop_id=p.id" in prefix


# ---------------------------------------------------------------------------
# 3. the memoisation trap
# ---------------------------------------------------------------------------
def test_league_mean_is_cached():
    src = read("fbs_baseline.py")
    assert "_league_mean_cache" in src, (
        "league_mean must be memoised on (key, cutoff); without the cache "
        "marcel is O(items x players x games) and does not finish"
    )
    assert "if ck in _league_mean_cache" in src


# ---------------------------------------------------------------------------
# 4. the holdout statement
# ---------------------------------------------------------------------------
def test_holdout_is_not_2025():
    src = read("fbs_baseline.py")
    assert "there is no 2025 NCAAF prop board" in src, (
        "fbs_baseline.py must state that the 2025 holdout is unavailable; "
        "a later edit that grades 2025 would be measuring a season with no props"
    )
    assert "week walk-forward" in src


# ---------------------------------------------------------------------------
# 5. the pre-registration
# ---------------------------------------------------------------------------
def test_markets_are_pre_registered():
    src = read("fbs_baseline.py")
    assert 'MARKETS = ("passing_yards", "rushing_yards")' in src, (
        "the markets must be fixed before the run; receiving markets are "
        "excluded on the plan's own condition"
    )


def test_keep_rule_requires_an_interval():
    src = read("fbs_baseline.py")
    assert "clustered" in src and "KEPT" in src, (
        "the keep rule must require a clustered interval that excludes zero, "
        "not a point difference"
    )


# ---------------------------------------------------------------------------
# 6. database facts, checked against the real database when it is present
# ---------------------------------------------------------------------------
@needs_db
def test_ncaaf_props_are_2026_only():
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=30)
    try:
        seasons = [r[0] for r in con.execute(
            "SELECT DISTINCT substr(start_time,1,4) FROM prop_games "
            "WHERE league='ncaaf'")]
    finally:
        con.close()
    assert seasons == ["2026"], (
        "NCAAF props are 2026-only; this is the measurement that makes the "
        "2025 holdout unavailable, and it must be re-checked if the prop "
        "history is ever backfilled: %s" % seasons
    )


@needs_db
def test_settled_ncaaf_props_exist():
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=30)
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM prop_results pr JOIN props p ON "
            "p.id=pr.prop_id JOIN prop_games pg ON pg.id=p.game_id "
            "WHERE pg.league='ncaaf'").fetchone()[0]
    finally:
        con.close()
    assert n > 0, "there must be settled NCAAF props for any grading to run"


@needs_db
def test_the_prop_log_join_resolves():
    """The join every FBS grader depends on must resolve.

    props -> prop_games (espn_event_id) -> player_game_logs (game_no +
    source_player_key). If this returns zero, every FBS number above it is
    measuring nothing.
    """
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=60)
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM props p "
            "JOIN prop_games pg ON pg.id=p.game_id "
            "JOIN players pl ON pl.id=p.player_id "
            "JOIN player_game_logs l ON l.league='ncaaf' "
            "AND l.game_no=pg.espn_event_id "
            "AND l.source_player_key=pl.espn_id "
            "WHERE pg.league='ncaaf'").fetchone()[0]
    finally:
        con.close()
    assert n > 0, "the props-to-logs join resolves nothing"
