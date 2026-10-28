# Consumers of players.team: inventory and corrections (2026-10-28)

`players.team` is the last club written to a player row. Nothing refreshes it on a transfer, and the legacy job only
fills a blank value (`COALESCE`). It is therefore not a current club for MLS. With the cutover on, a current MLS club
comes from the membership snapshot (`mls_resolution.current_team`, `mls_resolution.club_now_sql`).

The inventory covers every backend reader found by searching for `players` joined to `team`, and every
player-table team read in routers. Each reader is classed as current MLS (corrected), historical (left unchanged, as
the directive requires), another league or the World Cup module (not MLS, unchanged), or vocabulary (codes, not clubs).

## Current MLS consumers, corrected (active only when the cutover is on)

| Reader | Use | Correction |
|---|---|---|
| `routers/props.py` props list (`player_team`) | club shown on a prop row | upcoming games show the membership club; a departed MLS player shows no club; past games keep the stored club |
| `routers/props.py` props board (`player_team`) | club shown on a board card | same rule as above |
| `routers/players/stats.py` population team | club in a season leaderboard | a current member shows the membership club; a departed player shows the season club from `player_stats`, never the stored club |
| `promote_mls_player_stats.py` | creates players from a sidecar database | with the cutover on, a new MLS player is refused here; creation belongs to onboarding. Stat updates for existing players are unchanged |
| `refresh_soccer_player_teams.py` | copies clubs from roster rows into `players.team` | MLS is skipped with the cutover on: the club is read from the snapshot |
| `ingest_rotowire_props.py` `resolve_player` (MLS and Leagues Cup board rows) | matches RotoWire board rows to people, and binds their keys | found in the second pass; the first inventory missed it. It matched names against stored clubs and bound keys by name. With the cutover on, a bound key counts only for a current member, the name answer comes from the gated resolver, and a name match writes no binding. A departed person is queued `not_in_spine`. Gate off: legacy unchanged |
| `_core.py` resolver, team narrowing | matches a name at a club | membership club (gated resolver) |
| `backfill_from_published_roster.py` | binds keys to people | membership evidence only; no observation row read |
| `spine_merge.py` planning | proposes merges on shared keys | membership keys only; no observation row read |

## Historical readers (unchanged, by directive)

| Reader | Use | Note |
|---|---|---|
| `_core.py` analytics base query (`pl.team`) | team in historical prop analysis | describes past props; unchanged |
| `routers/props.py` past-game rows | club on a settled prop | unchanged by the rule above |
| `settlement/settle_game.py` (`pl.team as player_team`, 4 queries) | the player's team when settling a historical prop | **open finding.** Settlement uses the stored club. For a transferred MLS player, that club can be stale, so settlement could use the wrong team. Changing settlement changes historical outcomes, so it is not changed here. A separate decision is needed. |
| `ingest_fotmob_soccer_logs.py` (`p.team`) | club for a game log being attributed | attribution of historical logs; unchanged |
| `ingest_rotowire_soccer_stats.py` (`COALESCE(l.team, p.team)`) | game team, log first | historical; unchanged |
| `ingest_fotmob_soccer_logs.py` (`spine`, `player_source_ids` index, `p.team`) | attributes FotMob game logs to people; the FotMob key binds first, the name fallback reads `players` | historical attribution, unchanged by directive. Not re-verified in this work for transferred players. Open for a separate historical decision |

## Vocabulary (codes, not clubs)

| Reader | Use | Note |
|---|---|---|
| `club_crosswalk.py` | learns the code vocabulary from `published_roster` and `players.team` pairs | teaches code names, not current clubs; a stale pair gives a stale code, which is still a valid code. Unchanged. |

## Other leagues and the dormant World Cup module (unchanged)

NFL (`ingest_nfl_adp.py`, `ingest_nfl_projections.py`, `ingest_nfl_dst.py`, `routers/nfl_mock_draft/*`,
`routers/nfl_offseason/board.py`, `routers/players/nfl_projections.py`), NHL (`migrate_nhl_tricodes.py`), MLB
(`refresh_mlb_player_teams.py`, `ingest_mlb_spine_identity.py`, `scripts/plan_mlb_identity_repairs.py`), NCAAF
(`ingest_ncaaf_logs.py`, `repair_ncaaf_wrong_binding_props.py`, `audit_ncaaf_duplicate_players.py`), UFC, esports,
`game_extras.py`, `routers/players/search.py`, `routers/players/projections.py`, `wc_context.py` (World Cup, dormant), audit and migration scripts. None of these is MLS current-club
logic.

## Checks

- The expression helper returns the legacy SQL unchanged when the cutover is off (test
  `test_with_the_cutover_off_the_club_expressions_are_the_legacy_sql`).
- An upcoming game shows the current club, a past game the stored club, and a departed player's season club is shown
  instead of a stale stored club (tests in `test_mls_cutover_consumers.py`).
