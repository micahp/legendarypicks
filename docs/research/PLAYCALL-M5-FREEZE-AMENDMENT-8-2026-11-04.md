# M5 freeze amendment 8, 2026-11-04: one interface for team-keyed tables (LA/LAR, WAS/WSH)

Status: owner-authorized (2026-11-04: "every single place that has the mismatched team codes, I want an interface
between so we never run into this issue again"). No pinned layer file (`slc_config.LAYER_CODE_FILES`) changes. This
amendment changes behaviour for every profile in games of the Rams and Washington, because it fixes a silent miss in the
streak input that V1 and V1.5 have always had. Earlier freeze documents and amendments are not edited.

## What was wrong

The LP database and the play-call tables use the database codes LAR and WSH. The nflverse files, and every table built
from them, use LA and WAS. The other 30 clubs are spelled the same, so a lookup across the two vocabularies works for
them and misses for these two. Two places missed:

| Where | Table spelling | Asked with | What happened |
|---|---|---|---|
| Kicker table (`--playcall-fg-kicker`, v2) | LA, WAS | LAR, WSH (`side_teams`) | Raised: 15 of the 121 v2 games (every Rams and Washington game) failed to load |
| Current streak (`slc_engine`, read by the pinned `slc_playcall`) | LA, WAS | LAR, WSH | Missed silently: `team in current_streak` was false, so the current-streak, team streak-split and league streak-split layers were skipped for that club |

Measured on the V1 and V1.5 season runs (121 games, 2026 weeks 1 to 8): the three streak layers ran on 0.565 (V1) and
0.561 (V1.5) of decisions in the 15 Rams and Washington games against 1.112 and 1.114 in the other 106 games. Every
other layer recorded the same application rate in both groups (the check compares each layer's `runtime_applications`
with `decision_labels`, per game), so these are the only two places the mismatch reached.

The participation field and the snap counts were spelled LA and WAS on both sides (the snapshot rosters and the
tables), so they did not miss; each also had a guard that raises on an unknown team.

## The interface, for the whole app

`backend/team_codes.py` is the one place team codes are defined for every league. `scripts/nfl_team_codes.py` no
longer holds a list: it is the NFL view of the backend module. The backend module gains:

- `TeamKeyed(league, items, team_at=None)`: a dict that stores every team key under its canonical code and translates
  every read and write (`[]`, `get`, `in`, `pop`, `setdefault`, `update`), so either spelling finds the club. An unknown
  code raises in a league whose vocabulary is complete (nfl, mlb, nba, nhl, ligamx; every `players.team` value in dev
  and prod is registered for these). In ncaaf (the list is the 146 FBS clubs; 101 FCS codes appear in `players`) and
  mls (GDL appears in Leagues Cup rows) an unregistered code is used as written and counted in `UNREGISTERED_SEEN` and
  the log. It stays a dict, so pinned layers that only read these tables are protected without being changed.
- `key_code`, `same_team(league, a, b)`, and `to_source(league, source, code)` with named source vocabularies (nflverse,
  statsapi, kalshi, nhle) for writing a key in an outside source's spelling.
- The spellings that were only in hand-written tables: Pro Football Reference NFL codes, RotoWire's MLS and Liga MX
  codes, MoneyPuck's dotted NHL codes, the Athletics' OAK, the Thrashers (ATL to WPG), and a declared historical club
  (NHL ARI, the Coyotes, accepted for old seasons and not counted as a current club).

Every hand-written translation outside the module was replaced. Counted from the diff against `c417da22`, that is 45
source files outside the two team-code modules (19 in backend, 14 in research/nhl, 6 in scripts, 6 in docs/research),
covering NFL, MLB, NHL, MLS and Liga MX across app code, settlement, routers, ingests, migrations and research scripts.
The repo-wide test below reports 0 remaining. Lax lookups (`table.get(code, code)`, which pass an unknown code through) became
strict interface calls, and the league-blind table in `settlement/boxscore_extract.py` (WAS/WSH, ATH/OAK, TBL/TB and
AZ/ARI in one dict) became `same_team(league, ...)` with the league passed by every caller.

`backend/test_team_code_interface.py` fails the build if any tracked source file outside `backend/team_codes.py`
holds a literal pair `'X': 'Y'` naming one club twice, or any line of app code (tests excepted) holds two spellings of
one club. `test_nfl_team_codes.SimulationTablesUseTheInterface` fails if a team-keyed simulation table is not a
`TeamKeyed`.

### Random streams

The v2 random streams are keyed on a hash of the layer descriptions, and the current-streak description embedded the
streak table. Storing that table under canonical keys moved the hash for every game whose streak file names the Rams
or Washington (the week 8 file names all 32 clubs), reseeding those games although nothing else changed (measured:
the only differing input to the stream root was the `current_streak_context` layer hash). The description now records
the table as the file spells it, and lookups use the `TeamKeyed` view, so draws stay exactly as they were.

## Found and not changed here (owner decisions)

- NHL data is split between two spellings in prod and dev: for example the Devils are NJ on 1,550 game-log rows and
  NJD on 22 of 33 player rows, the Kings LA on 76 log rows and LAK on 1,628. A SQL query on one code returns part of a
  club. Code through the interface sees one club; the rows need a migration, and a decision on which NHL vocabulary is
  canonical (ESPN, per 2026-07-27, or the NHL's tricodes, per `migrate_nhl_tricodes.py` 2026-09-07).
- `capture_espn_weekly_projections.py` respelled LAR and WSH to LA and WAS before matching the schedule, which stores
  LAR and WSH: every Rams and Washington player was counted as a bye, and `player_projections` holds 0 of their ESPN
  rows in dev and in prod. The code is fixed; refilling the rows means calling ESPN and writing to both databases.
- NCAAF FCS codes and MLS GDL are unregistered (above).

## Verification

To be filled from the runs below, measured, not expected.
