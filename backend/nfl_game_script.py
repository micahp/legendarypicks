"""nfl_game_script.py -- Spec B 4.1 game script: SPEC A's projected margin for each team-game.

Kept apart from nfl_player_projection_v2 so the engine stays free of SPEC A's fitting code.

Margins are SPEC A version 1 (nfl_backtest, the adopted model the weekly lock publishes as
nfl-ratings-v1) at its frozen configuration: half_life 6, cap 14, cap_points off. For a backtest each
game's margin is the walk-forward prediction from games before its week only (nfl_backtest.backtest_season,
weeks 2 on). The margin for a team is its projected points minus its opponent's.

PRE-REGISTERED 2026-10-13, before any fit or 2025 number:
  factor(team-game, col) = clamp(1 + B_col * margin, 0.75, 1.25), applied to the engine's projected team
  targets (col 'tgt') and carries ('car'). The engine has no separate pass rate: team targets and carries
  are its pass and rush volumes, so a script effect on pass rate shows up as opposite signs of B_tgt and
  B_car. A team-game with no margin gets factor 1.
  B_col fitted on 2024 weeks 3 to 18 by least squares without intercept on (actual / projected - 1)
  against margin, over team-games (backtest --fit-script). Frozen, then 2025 run once.
  Adopted only if, on 2025 weeks 3 to 18: (a) team-level MAE of projected targets and of projected carries
  are each lower with the factor than without, (b) the paired player MAE of targets, receptions and
  receiving yards are each no higher than the engine without it (1.562, 1.207, 15.849 on the dev DB copied
  2026-10-13), and (c) the Spec B 5 gate passes.
"""
import nfl_backtest as nb

V1 = {"half_life": 6.0, "cap": 14.0, "cap_points": None}
CLAMP = (0.75, 1.25)


def margins_walk_forward(con, seasons):
    """{(season, game_id, team): projected margin for team} from SPEC A v1 walk-forward predictions."""
    out = {}
    for season in seasons:
        for r in nb.backtest_season(con, season, V1):
            out[(season, r["game_id"], r["home"])] = r["proj_margin"]
            out[(season, r["game_id"], r["away"])] = -r["proj_margin"]
    return out


def points_walk_forward(con, seasons):
    """{(season, game_id, team): (projected points, actual points)} from SPEC A v1 walk-forward predictions."""
    out = {}
    for season in seasons:
        for r in nb.backtest_season(con, season, V1):
            m, t = r["proj_margin"], r["proj_total"]
            am, at = r["actual_margin"], r["actual_total"]
            out[(season, r["game_id"], r["home"])] = ((t + m) / 2.0, (at + am) / 2.0)
            out[(season, r["game_id"], r["away"])] = ((t - m) / 2.0, (at - am) / 2.0)
    return out


def margins_live(con, season, week):
    """{(season, game_id, team): margin} from the latest nfl-ratings-v1 lock for the week, or {}."""
    row = con.execute(
        "SELECT run_id FROM model_runs WHERE league='nfl' AND season=? AND week=? AND model='nfl-ratings-v1' "
        "AND status='ok' ORDER BY started_at DESC LIMIT 1", (season, week)).fetchone()
    if row is None:
        return {}
    out = {}
    for gid, home, away, margin in con.execute(
            "SELECT game_id, home, away, proj_margin FROM game_projections WHERE run_id=?", (row[0],)):
        out[(season, gid, home)] = margin
        out[(season, gid, away)] = -margin
    return out


def factor(margin, b):
    if margin is None or b is None:
        return 1.0
    return min(CLAMP[1], max(CLAMP[0], 1.0 + b * margin))
