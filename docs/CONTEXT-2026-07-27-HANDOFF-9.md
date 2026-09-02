# LP handoff — 2026-07-27 pt.9 (supersedes pt.8)

**Work queue: `/root/legendarypicks/docs/ROADMAP.md`.** This file is session state and
decisions only.

Nothing is broken. `:3096`, `:8096`, `:8098` and the tunnel are all 200. **No database
changes were made this session** — the migration was designed and scoped, not run.

---

## 0. The jobs waiting for you, in order

### Job 1 — write `backend/team_codes.py`, the one thing blocking everything else

Design is in §2, fully specified, and the measurements it needs are all in this file. The
branch `fix/team-vocabulary` already carries the migration script that imports it and the
published team lists it should embed. **This is maybe an hour of work and nothing else in
the vocabulary thread can start without it.**

### Job 2 — run the NFL migration, gated on the draft board

`backend/migrate_nfl_team_vocabulary.py` (dry run by default). The gate: the board must come
back **byte-identical**, because `nfl_offseason.py:740` already normalises `current_team` at
serialisation, so a correct migration changes the data and not the output. Baseline is
**522 rows, 32 teams, 511 with `team_weeks`** — regenerate it before migrating, since the
scratchpad copy is gone:

```
python3 - <<'PY'
import json, urllib.request
rows, off = [], 0
while True:
    d = json.load(urllib.request.urlopen(
        'http://127.0.0.1:8096/api/nfl/draft-board?limit=100&offset=%d' % off, timeout=30))
    if not d['players']: break
    rows += d['players']; off += 100
json.dump(rows, open('/root/board_before.json','w'), sort_keys=True, indent=0)
print(len(rows))
PY
```

Backup already taken: **`/root/picks.dev.PRE-VOCAB-2026-07-27.db`** (160MB, pre-migration).

### Job 3 — delete the `team_weeks` derivation

This is the payoff, and it is Micah's point, not mine. `team_weeks` is *reconstructed* from
game logs in two places (`nfl_mock_draft.py:206`, `nfl_offseason.py:573`). The only reason
it is derived at all is that the logs speak nflverse and cannot join to `nfl_schedule` —
which now holds the **published 2025 schedule, 285 games, ESPN-keyed**. Once Job 2 lands,
that derivation should be **deleted and replaced by a read of the published schedule**, not
kept in parallel. Three Hermes passes were burned reconstructing this exact table.

`primary_team` survives Job 3: the per-game `team` on each log row is published data. What
is inferred is only the collapse of 17 rows to one team by max-games, and after the
migration that becomes a lookup against a matching vocabulary instead of a guess across two.

### Job 4 — the other three leagues, one gated commit each

MLB (`CWS`, `AZ` — 3,041 rows from statcast), NHL (`UTA`/`LAK`/`TBL`/`SJS`/`NJD` — 7,563 from
nhle.com), NBA (nothing to migrate; needs the All-Star allowlist). **Do not fold these into
Job 2.** I have no output baseline for the MLB and NHL surfaces the way the draft board gives
one for NFL, so each needs its own gate. Separate commits per slice.

### Job 5 — then the v0.7.0 queue pt.8 left, unchanged

Slice D's browser check (`docs/SPEC-slice-D-mock-draft.md` §7.6 — no `sample: 'none'` player
may render a "0 of 17" strip; Jeremiyah Love, any kicker; **still nobody has done it**), then
R4, then merge D → dev → cut v0.7.0. **v0.7.0 = A + D + R4. v0.8.0 = accounts — never open.**

---

## 1. What happened this session

### `dev` was pushed — pt.8's Job 1 is done

`15b5353..07e7610`, 14 commits, with Micah's go-ahead. Slice A, slice D's fixes, the ESPN
normalisation, the AGENTS.md corrections and the `published-first` skill are all on the
remote now. Feature branches were **not** pushed.

### The vocabulary problem is bigger and differently shaped than pt.8 said

pt.8 recorded it as "three copies of the same alias map" plus one unmigrated table. Measuring
it produced four corrections, each of which changes what the fix has to be:

**1. A team code is meaningless without its league.** 30 of the 32 NFL codes are reused by
another league. `WSH` is four franchises. **ESPN publishes `LA` as the Kings**, while in NFL
`LA` is a non-canonical alias for the Rams. A league-blind `STL → LAR` would have rewritten
1,459 MLB and 1,500 NHL game logs into Rams games. This is why the module is league-keyed and
why every migration statement carries a league filter.

**2. Every non-canonical code came from a non-ESPN ingest.** Traced through the `source`
column, not guessed:

| league | non-canonical | written by | canonical from same source |
|---|---|---|---|
| NFL | 760 | `nflverse_weekly` | 10,456 |
| MLB | 3,041 | `statcast`/`statcast_pitcher` | 42,286 |
| NHL | 7,563 | `nhle.com` | 40,454 |
| NBA | 25 | `espn` | 24,061 |

**NBA is the control** — the one league sourced entirely from ESPN, 99.9% canonical, and its
25 exceptions are `STRIPES`/`STARS`/`WORLD`, All-Star rosters that are not franchises at all.
Micah called this before it was measured. It means the durable fix is **conversion at each
non-ESPN ingest boundary**; the data migration is only cleanup of what already leaked.

**3. `players.team` holds both vocabularies at once, split by `active`.** Actives are ESPN
(32 codes); the 1,724 inactive NFL rows are nflverse (`LA` 850, `WAS` 873, `AZ` 1). So
`a4a2136`'s "matches the players table exactly, 32 for 32" was checked against a table
containing both languages — **the check was vacuous**, and any query that forgets `active = 1`
silently joins across two vocabularies.

**4. 2024 was never re-ingested.** `nfl_schedule` and `team_game_results` are ESPN for 2025
and 2026 but still `LA`/`WAS` for 2024 (19 and 39 rows). `a4a2136` only touched the seasons
it re-ran.

### Full measured scope of the NFL migration

14 columns, 7 tables, ~14,900 cells. All league-scoped or NFL-by-definition:

| table.column | filter | rows |
|---|---|---|
| `players.team` | `league='nfl'` | 1,724 |
| `player_stats.team` / `.nfl_team` | `league='nfl'` | 72 / 72 |
| `player_game_logs.team` / `.opponent` | `league='nfl'` | 760 / 701 |
| `team_game_results.team` / `.opponent` | `league='nfl'` | 39 / 39 |
| `nfl_schedule.home_team` / `.away_team` | — | 19 / 20 |
| `nfl_depth_chart.team` | — | 56 |
| `nfl_pbp.posteam`/`.defteam`/`.home_team`/`.away_team` | — | 2,736 / 2,811 / 2,797 / 3,091 |

`team_stats_team_inventory`'s `LA`/`STL` are **NHL parity rows** (`run_id` starts
`nhl-parity-`) and are correctly excluded. The three tables without a league column were
confirmed NFL by reading their writers (`ingest_nfl_schedule.py`, `ingest_nfl_pbp_logs.py`,
`ingest_nfl_depth_charts.py`), not by trusting the name.

---

## 2. `backend/team_codes.py` — the spec, ready to write

Replaces four disagreeing maps: `ingest_nfl_schedule.py:70`, `routers/nfl_offseason.py:72`,
`settlement.py:147` (function-local, bidirectional, the only one that knows `AZ`), and a
*comment* at `routers/nfl_mock_draft.py:200`. `link_prop_games.py` is a fifth in a different
shape (full name → abbrev) and can wait.

```python
CANONICAL: dict[str, frozenset]   # 'nfl'|'mlb'|'nba'|'nhl' -> the published codes
ALIASES:   dict[str, dict]        # per league, non-canonical -> canonical, each with its source
NON_FRANCHISE: dict[str, frozenset]  # nba: STRIPES, STARS, WORLD — allowlist, not aliases

normalize(league, code) -> str            # raises UnknownTeamCode on anything unrecognised
normalize_optional(league, code) -> str|None   # None only for empty/None; typos still raise
is_canonical(league, code) -> bool
```

**`normalize` must raise.** All four maps it replaces used `aliases.get(code, code)`, which
passes unknowns straight through — that is precisely why every failure in this family has
been invisible. A vocabulary bug that raises is a five-minute fix; the same bug returning a
plausible number costs three rebuild passes.

Embed the canonical sets from **`docs/espn-team-codes-2026-07-27.json`** (committed on the
branch), fetched from `site.api.espn.com/apis/site/v2/sports/{football/nfl,baseball/mlb,
basketball/nba,hockey/nhl}/teams?limit=60` — all four returned 200 from this box, no bot-wall.
Do not re-derive them from our own tables; that is the mistake that made the original check
vacuous.

Alias sets, measured against the DB:
`nfl` — `LA`→LAR, `WAS`→WSH, `AZ`→ARI, plus historical `JAC`→JAX, `OAK`→LV, `SD`→LAC,
`STL`→LAR (safe once league-keyed). `mlb` — `CWS`→CHW, `AZ`→ARI. `nhl` — `UTA`→UTAH,
`LAK`→LA, `TBL`→TB, `SJS`→SJ, `NJD`→NJ (**note the inversion**: ESPN publishes the shorter
code). `nba` — none.

**Then the process fix, which matters more than the migration:** make
`ingest_nfl_weekly_stats.py`, `ingest_nfl_pbp_logs.py`, `ingest_nfl_depth_charts.py`,
`ingest_mlb_logs.py`, `ingest_mlb_pitcher_logs.py` and `ingest_nhl_logs.py` call
`normalize()` at their write boundary, and switch `ingest_nfl_schedule.py` off its private
map. Add a test asserting no team-bearing column holds a non-canonical code for its league —
that is what makes this non-recurrable rather than cleaned up once. Delete
`nfl_offseason._normalize_team` (line 113) and its two call sites (740, 744): it is a
read-site band-aid, and after the migration it is a no-op.

---

## 3. State

- **`dev` = `07e7610`, pushed, clean.**
- **`fix/team-vocabulary` = `fc06a14`**, branched off dev, in worktree **`/root/lp-team-vocab`**.
  One WIP commit: the migration script (correct scoping, **does not run** — imports the
  unwritten `team_codes`) and the published team lists. Nothing else.
- `feat/slice-D-mock-draft` = `bc3038d`, checked out in the main repo, what `:3096` serves.
  **It does NOT contain `a4a2136`** — D merged dev at `9c53eea`, which predates the ESPN
  normalisation. No conflict when D merges, but D's verification ran without that code.
- `feat/slice-a-draft-notes` = `53830bf`, merged, kept. `feat/slice-D-pass-2` = `fadaf3a`,
  merged, worktree still up at `/root/lp-slice-D-pass-2` with its own backend on `:8098`
  (no reload). Tear down when D is settled. `feat/nfl-allday` = `825d116`, pushed, untouched.
- **Prod is v0.6.7.** R6 (deploy) still behind v0.7.0.
- `:3096` frontend, `:8096` backend (reload), `:8098` worktree backend. Tunnel
  `https://someone-decorative-wearing-produce.trycloudflare.com` → 3096, cloudflared pid
  3928058. **Don't touch cloudflared.**
- Mock-draft pool needs `?season=2026` and lives on `:8098` only. Draft board caps `limit` at
  100 — page it.

---

## 4. Traps

**`node_modules` has been emptied twice in one day** by an agent running `npm` from a
worktree against the symlinked shared install. Both process fixes are in (`7c11568`,
`5c98ad1`). `ls node_modules | wc -l` should read **538** — check that BEFORE blaming `.next`.
Recovery is `npm ci` in the main repo (~45s) then
`./node_modules/.bin/next dev --port 3096`. I ran no npm in `/root/lp-team-vocab`; the
vocabulary work is Python-only and should stay that way.

**Branch churn under the live dev server.** Main repo stays on `feat/slice-D-mock-draft`.
Do vocabulary work in `/root/lp-team-vocab`; do merges in a throwaway worktree.

**`--season 2025` must use `--schedule-only`** — ESPN already owns 544 rows of 2025 in
`team_game_results` under different `game_id`s, and `game_id` is part of that primary key, so
a second source doubles the season instead of upserting.

**Still deliberately outstanding:** `settlement.py`'s map is cross-league ESPN-boxscore
matching — a different job. Leave it, but stop it being anyone's vocabulary source.

---

## 5. The lesson

pt.7's was *a green test suite is a claim, not a result.* pt.8's was *the claim and the
evidence can both be present and still not match.* This one is narrower and worse:

**A verification is only as good as the thing it diffs against.** `a4a2136` checked the new
ESPN schedule against `players` and got 32-for-32 — but `players` contains both vocabularies,
so nothing could have failed that check. The green was structural. It could not have caught
the 2024 rows it missed, and it did not.

The second lesson is Micah's, twice. He asked "do we need rosters" and "where were all our
codes from" — and both questions moved the work further than the code I was writing at the
time. The first found that `team_weeks` should be deleted rather than fixed; the second found
that the split has one cause across four leagues and the real fix is at the ingest boundary.
**Neither was answerable by reading the file I had open.**
