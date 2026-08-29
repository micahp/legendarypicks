TASK: make MLS settlement DB-first, so it stops calling ESPN per event.

WHY. Your residue replay issued ~45 paced ESPN summary requests. That is correct
behaviour for the code as written -- `mls_settle` fetches a summary per event --
but it spends the SAME budget the live site spends, on a day ESPN already 403'd
this box three times. The data it fetches is already on disk.

WHAT IS ALREADY STORED (measured on managed dev, read-only, 2026-08-26)

  `player_game_logs`        21,177 mls rows, source='espn'
      goals / assists / shots / sot        on all 21,177
      fouls_committed / fouls_suffered / saves / shots_faced /
      goals_conceded / offsides / yellow_cards / red_cards /
      first_goal                          on 4,516 (the newer deep run)

  `player_game_logs_fotmob`  9,679 mls rows, 314 fixtures, 8,955 resolved
      tackles 8,955, passes 8,955, clearances 8,955, chances_created 8,409,
      dribbles 3,993, crosses 3,589, plus shots / sot / goals / assists /
      fouls_committed / fouls_suffered / saves / goals_conceded / interceptions
      / recoveries / minutes

  `player_game_logs_all`     the VIEW that joins them on (player_id, game_date),
      one row per appearance, each provider's line in its own COLUMN
      (`espn_stats`, `fotmob_stats`). 26,071 mls rows. Provenance is the column
      a value was read from -- there is no merged blob and no source stamp to
      trust.

  So every field `_MLS_ROSTER_MARKETS`, `_MLS_ROSTER_SUM_MARKETS` and
  `_MLS_DEEP_LOG_MARKETS` name is available WITHOUT a live request, for the
  appearances we hold. What is NOT available stays PENDING -- which is already
  your contract for deep markets, and the right one: 0 tackles is a real result,
  so writing 0 because we did not look would grade a bet nobody measured.

YOUR PART
  Change `settlement/mls_settle.py` to read `player_game_logs_all` instead of
  fetching a summary per event. Prefer `espn_stats` where both providers carry a
  field (ESPN is the identity spine every player_id is keyed on); fall through to
  `fotmob_stats` for the markets ESPN does not publish. Keep the live summary
  fetch ONLY for `_MLS_EVENT_MARKETS` (first_goal_scorer) if the stored
  `first_goal` field cannot answer it -- and check whether it can, since it is on
  4,516 rows.

  Scope: settlement/ and its tests. Do NOT touch core_markets.py or
  routers/props.py -- both were rewritten on dev today.

MY PART, done
  - FotMob run for mls: the 9,679 rows above. Different host, no ESPN budget.
  - core_markets mapped for tackles / clearances / chances_created /
    shots_assisted / crosses.
  - `passes_attempted` deliberately NOT mapped, and you were right to catch it:
    FotMob publishes ACCURATE passes, the market asks ATTEMPTED, and
    ingest_fotmob_soccer_logs.py:54 already said not to. Reverted, with a test.
    The honest FotMob coverage is 50 props with the exact named statistic, not
    the 186 appearance-covered I first reported.

ONE THING TO CARRY BACK
  You found 19 `sot` props with an exact roster match and published
  shotsOnTarget BEFORE that game's last settlement, still ungraded. That is not
  a data gap -- it is the settler missing rows it had evidence for. Whatever the
  cause, it should be a test, because a settler that silently skips gradeable
  rows is the failure this whole exercise exists to find.
