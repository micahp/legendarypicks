# Result: UEFA Nations League, international friendlies, and dev tunnel

Date: 2026-10-06  
Branch: `dev`  
Scope: dev only; no commit, push, production rebuild, production database write, or order

## Outcome

The dev site is public again at:

`https://psychiatry-blogging-interracial-journal.trycloudflare.com`

UEFA Nations League and men's senior international friendlies now have FotMob-only
scoreboards, upcoming fixtures, current-window player logs, registry steps, and freshness
targets under the logical league keys `unl` and `friendlies`.

## Part A: dev tunnel

The Cloudflare quick tunnel had not died. `legendarypicks-dev-tunnel.service` was active with
`Restart=always` and was repeatedly logging that its origin, `127.0.0.1:3096`, refused the
connection. The missing process was the Next development frontend; it had no listener and no
supervisor.

I added and installed `legendarypicks-dev-frontend.service`, enabled it at boot, and started it.
It runs the repository's existing Next binary directly on `127.0.0.1:3096`, has
`Restart=always`, and does not alter the already-running backend on port 8096. The tunnel was
left running, preserving its hostname.

Verification:

- Frontend service: active, enabled, `Restart=always`.
- Tunnel service: active, `Restart=always`.
- Local `/` and `/scores`: HTTP 200.
- Cloudflare's external resolver `1.1.1.1` returned `104.16.231.132` and `104.16.230.132` for
  the hostname.
- HTTPS requests pinned to the externally returned Cloudflare edge returned HTTP/2 200 for
  `/scores` and `/api/friendlies/games?date=2026-10-06`.
- The public scores HTML contains both new competition filters; the public friendlies API
  returned 10 games from `scoreboard_snapshots`.

An old, unrelated unsupervised `cloudflared` process from August still points at an expired
quick tunnel and logs `Unauthorized: Tunnel not found`. It was not stopped or modified because
the task forbade touching unrelated running processes.

## Part B: FotMob competitions

FotMob's own league documents supplied these IDs and metadata:

| Product key | FotMob ID | FotMob name | Gender | Selected season |
| --- | ---: | --- | --- | --- |
| `unl` | 9806 | UEFA Nations League A | male | 2026/2027 |
| `unl` | 9807 | UEFA Nations League B | male | 2026/2027 |
| `unl` | 9808 | UEFA Nations League C | male | 2026/2027 |
| `unl` | 9809 | UEFA Nations League D | male | 2026/2027 |
| `friendlies` | 114 | Friendlies | male | 2026 |

`unl` intentionally aggregates divisions A-D into one product competition. The ingest checks
FotMob's `details.gender == "male"` before accepting a league document and never calls ESPN for
either competition.

The MANIFEST entries were added before either dev ingest. They declare these as per-match-only
surfaces, not season-total `player_stats` surfaces.

### Scoreboards and fixtures

The full FotMob fixture documents were normalized into the shared scoreboard store:

| League | Stored fixtures | Stored slate days | Date range |
| --- | ---: | ---: | --- |
| `unl` | 156 | 18 | 2026-09-24 through 2026-11-17 |
| `friendlies` | 391 | 57 | 2026-01-17 through 2026-11-17 |

On the October 6 slate, both local APIs returned 10 games with
`X-LP-Data-Source: scoreboard_snapshots`. The friendlies slate included the upcoming Colombia
vs Peru, USA vs Canada, and Mexico vs Chile matches. November Nations League and friendly
fixtures are also stored. Missing FotMob snapshots fail closed as `unavailable`; these routes do
not fall through to ESPN.

### Current-window player logs and identity evidence

The applied dev run used `--days-back 14` and persisted absent identity as `player_id NULL`:

| League | Appearance rows | Fixtures with player stats | Resolved by stable FotMob ID | Unresolved identity |
| --- | ---: | ---: | ---: | ---: |
| `unl` | 3,229 | 103 | 54 | 3,175 |
| `friendlies` | 1,059 | 29 | 117 | 942 |

Identity resolution for national-team appearances uses only FotMob player IDs already bound to
the canonical club-player spine in `player_source_ids`. Repeated bindings to the same canonical
player collapse safely. One FotMob ID bound to multiple canonical players is ambiguous and
misses. There is no national-team name fallback, so a national appearance cannot be merged onto
the wrong same-name club player. This run observed zero ambiguous-ID matches.

FotMob did not publish `content.playerStats` for every finished fixture in the window. Those are
measured as fixture-level misses, not zero-stat appearances: 1 of 104 Nations League fixtures and
39 of 68 friendly fixtures. They remain retryable because no appearance row marks them held.

The first Nations League apply encountered an existing SQLite writer after 10 fixtures and
failed with `database is locked`. The ingest now commits one fixture at a time rather than
holding the writer slot across paced network requests. The retry skipped the 10 committed
fixtures and completed without stopping or restarting another process.

### Registry and freshness

The hourly `fotmob_soccer_logs` registry job now includes both keys with a 14-day detail window.
It still stores each competition's complete fixture document on every run. Both targets use
`player_game_logs_fotmob.game_date` and FotMob's recorded `publisher_schedule` as the freshness
comparison, so a quiet international window does not produce a false stale alert.

Targeted dev freshness result:

- `unl`: caught up through 2026-10-06.
- `friendlies`: caught up through 2026-10-06.

The generic season-stat audit recognizes both MANIFEST entries but reports eight UNVERIFIED
checks because these leagues deliberately have no season-total, position-vocabulary, or ESPN
identity surfaces. It does not falsely certify those absent surfaces. A future audit extension
should measure `player_game_logs_fotmob` directly for per-match-only competitions.

## Verification

- Python syntax compilation passed for all changed backend modules.
- `git diff --check` passed.
- Focused suite: 144 passed, 4 existing FastAPI lifecycle deprecation warnings.
- Required bounded dry runs completed against `backend/data/picks.dev.db` with no writes.
- Dev-only applies completed and the final DB/API counts above were queried back.
- Public `/scores` and the public friendlies API returned HTTP/2 200 through a Cloudflare edge.
- Repository-wide `tsc --noEmit` remains blocked by existing missing Flow dependencies
  (`@onflow/fcl`, `@onflow/typedefs`, `elliptic`, `sha3`, and `services/nbaGames`) and existing
  down-level iteration configuration errors. The running Next dev compiler successfully compiled
  `/scores` after these changes.

## Production handoff

No production database, service, container, or build was touched. Production still needs the
normal code promotion plus the same two FotMob ingest steps against the production database so
the new scoreboard, publisher-schedule, and provider-log rows exist there. The registry timer
will then keep them current. Do not infer production readiness from the dev rows, and do not
rebuild the production container as part of the data promotion.

## Files changed by this task

- `backend/audit_league_stats/cli.py`
- `backend/ingest_fotmob_soccer_logs.py`
- `backend/ingest_league_clubs.py`
- `backend/ingest_registry.py`
- `backend/routers/games/schedule.py`
- `backend/routers/games/scoreboard.py`
- `backend/test_ingest_fotmob_soccer_logs.py`
- `backend/test_scoreboard_ingest.py`
- `components/Game/types.ts`
- `components/Navigation/sports.ts`
- `docs/RESULT-nations-league-friendlies-2026-10-06.md`
- `lib/liveGameStatus.ts`
- `ops/systemd/legendarypicks-dev-frontend.service`
- `pages/scores.tsx`
- `services/sports.ts`
- `/etc/systemd/system/legendarypicks-dev-frontend.service` (installed copy)

Pre-existing unrelated modified and untracked files were left untouched.
