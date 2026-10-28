"""A prop with no player-ID match stays pending, even when the box score has the player.

Without an ESPN id, the box-score section is found by the stored club, which is today's club. A player who moved clubs
would be matched in the wrong place, so the prop waits for a player-ID match. See docs/issues/settlement-name-only-pending.md.
"""
import settlement
from test_settlement_db_only import _settlement_database


def test_a_name_only_prop_stays_pending_even_when_the_box_score_has_the_player():
    con = _settlement_database()
    con.execute("UPDATE players SET espn_id = NULL WHERE id = 1")
    con.commit()

    result = settlement.settle_game(con, 1)

    assert result == {"settled": 0, "void": 0, "unmappable": 0, "pending": 1, "errors": 0}
    assert con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0] == 0


def test_the_same_prop_with_a_player_id_settles():
    con = _settlement_database()

    result = settlement.settle_game(con, 1)

    assert result["settled"] == 1
    assert result["pending"] == 0
