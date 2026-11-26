# Legendary Picks API — agent reference

Start here for a live or upcoming game, schedule, game ID, matchup or SLC snapshot. Use LP as the first data access path: it already consolidates publisher feeds, cached scoreboards and stored results. A first-party API response is not independent proof of upstream freshness or forecast eligibility.

## 1. Choose the configured environment

| Environment | Backend base |
|---|---|
| Managed development host | `http://127.0.0.1:8096` (normal default) |
| Production host | `http://127.0.0.1:8100` (separate stack; do not mutate or restart) |
| Other worktree/container | Its configured backend or existing authorized proxy; localhost means the current machine |

See [root README](../README.md) and [Compose](../docker-compose.yml). Do not assume the server's loopback is reachable from a remote agent. If the active stack cannot be reached, report the connection error and check the authorized environment; do not restart it. Discover actual route names and parameters from the deployed FastAPI schema:

```bash
BASE="${LP_API_BASE:-http://127.0.0.1:8096}"
curl -fsS --max-time 15 "$BASE/openapi.json" | jq -r '.paths | keys[]'
```

## 2. Scoreboard / scheduling

| Endpoint | Use |
|---|---|
| `GET /api/{league}/games?date=YYYY-MM-DD` | Daily slate, scheduled start, game state, teams, scores |
| `GET /api/{league}/schedule-dates` | Candidate dates around a requested anchor; see OpenAPI for parameters |
| `GET /api/nfl/schedule-weeks` | NFL phase/week catalog |
| `GET /api/nfl/schedule-week` | NFL week slate; inspect required parameters |
| `GET /api/nfl/schedule?season=2026` | Team weeks and byes, **not** a kickoff-by-game catalog |

The daily scoreboard returns an array for NFL and the normal sports serving path. Example for today's NFL slate in Central time (replace date/time zone with the user's requested one):

```bash
BASE="${LP_API_BASE:-http://127.0.0.1:8096}"
DAY="$(TZ=America/Chicago date +%F)"
DIR="$(mktemp -d)"
URL="$BASE/api/nfl/games?date=$DAY"
curl -fsS --max-time 15 -D "$DIR/headers.txt" -o "$DIR/games.json" "$URL"
date -u +%FT%TZ > "$DIR/observed_at.txt"
cat "$DIR/headers.txt"
jq -r '.[] | [.game_id,.date,.state,.status,.away.abbrev,.home.abbrev] | @tsv' "$DIR/games.json"
```

Stop on a failed request, invalid JSON or an unavailable source; do not reuse a previous response as if current. Preserve the URL, response, response headers and actual observation time in the run's evidence directory (or the approved immutable capture store).

| Field | Meaning / caveat |
|---|---|
| `game_id` | Scoreboard/source identifier; may be ESPN event ID or a stored result ID. Not automatically the SLC game ID. |
| `date` | Publisher event start, normally ISO 8601 with UTC offset. DB fallback can be day-only with `date_precision: day`. |
| `state` | `pre`, `in`, `post` are common publisher states; inspect `status` and `completed` too. |
| `away.abbrev`, `home.abbrev` | Team codes; normalize with existing helpers. |
| `X-LP-Data-Source` | E.g. scoreboard_snapshots, espn, team_game_results, bovada, unavailable. |
| `X-LP-Data-Age` | Snapshot age in seconds when supplied; absent is not proof of freshness. |

Source: [scoreboard handler](../backend/routers/games/scoreboard.py), [ESPN parser](../backend/espn_client/scoreboard.py), [schedule routing](../backend/routers/games/schedule.py). The serving path can preserve older scheduled/completed data, and uses a 15-minute snapshot ceiling with exceptions; that is not a guarantee that a pregame status is current. A successful HTTP response can still be unavailable. Near kickoff, inspect age/status, and if necessary obtain fresh authorized LP evidence. Do not launch upstream ingestion or restart services just to refresh the result.

## 3. Resolve "starting now" correctly

Compare actual UTC timestamps, not display strings. Query neighboring calendar dates if the user's timezone crosses the API's date bucket; deduplicate IDs and verify the requested local day. A game explicitly named by the user must not be replaced with another matchup. If no game was named, select the earliest credible future scheduled game in the requested window, report the time difference, and identify ties/ambiguity. Inspect delayed, cancelled, postponed and suspended statuses explicitly. A `pre` label with a past scheduled start is not sufficient to establish pregame eligibility.

This example lists future `pre` candidates (not proof that any is ready to simulate). Run after a successful capture:

```bash
python3 - "$DIR/games.json" <<'PY'
import json, sys
from datetime import datetime, timezone

now = datetime.now(timezone.utc)
games = json.load(open(sys.argv[1]))
if not isinstance(games, list):
    raise SystemExit("Expected a scoreboard array")
candidates = []
for g in games:
    if g.get("state") != "pre" or g.get("completed"):
        continue
    if g.get("date_precision") == "day" or not g.get("date"):
        continue
    status = str(g.get("status") or "").lower()
    if not status or any(x in status for x in
        ("delay", "postpon", "cancel", "suspend", "tbd")):
        continue
    try:
        start = datetime.fromisoformat(g["date"].replace("Z", "+00:00"))
    except (ValueError, TypeError):
        continue
    if start.tzinfo is None or start <= now:
        continue
    candidates.append((start, g))
for start, g in sorted(candidates, key=lambda item: item[0]):
    print(g["game_id"], start.astimezone(timezone.utc).isoformat(),
          g["away"]["abbrev"], "@", g["home"]["abbrev"], g["status"],
          "minutes_until_start=", round((start-now).total_seconds()/60, 1))
if not candidates:
    raise SystemExit("No eligible future pregame candidate in this response")
PY
```

This deliberately does not auto-run a simulation. Verify headers, matchup, date and kickoff again at the actual freeze/launch boundary.

## 4. Map scoreboard ID to SLC game ID

NFL SLC builders use the nflverse-shaped `nfl_schedule.game_id` (SEASON_WEEK_AWAY_HOME); ESPN scoreboard IDs are normally numeric. The schedule ingestion schema calls the ESPN column **`espn`** (not `espn_id`, despite a historical docstring). Look up in the selected model's configured database, read-only. Example:

```bash
python3 - "$DB" "$SCOREBOARD_GAME_ID" <<'PY'
import sqlite3, sys
from pathlib import Path

db, game_id = sys.argv[1:]
with sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True) as con:
    rows = con.execute(
        "SELECT game_id, season, week, gameday, gametime, away_team, home_team, espn "
        "FROM nfl_schedule WHERE CAST(espn AS TEXT)=? OR game_id=?",
        (game_id, game_id)).fetchall()
if len(rows) != 1:
    raise SystemExit(f"Expected one exact schedule mapping; got {len(rows)}")
print(rows[0])
PY
```

Check both teams, home/away orientation and intended local date against the captured scoreboard; do not construct a guessed ID. For another provider ID or missing crosswalk, inspect existing schedule/crosswalk data and resolve the exact matchup without guessing. Do not use timezone-free `gametime` as a verified UTC kickoff. Canonical normalization is [backend/team_codes.py](../backend/team_codes.py) and [scripts/nfl_team_codes.py](../scripts/nfl_team_codes.py); LP uses LAR/WSH, nflverse ID strings use LA/WAS. Source: [schedule ingestion](../backend/ingest_nfl_schedule.py).

## 5. Build the actual modeling snapshot

The scoreboard capture is separate from the model-input snapshot. Use the builder on the **selected model commit**. Read the [NFL model index](model-cards/nfl/README.md), its artifact manifest and branch-specific preflight. The maintained [pregame_snapshot.py](../scripts/nfl_sequence/pregame_snapshot.py) validates cutoff and schedule/depth versions.

For the November 26 CEG player-integration candidate, the existing [build_matchup_snapshot.py at a277103e](https://github.com/micahp/legendarypicks/blob/a277103e292a9e9f1aa5cfae2b0e0ebd4a5e95eb/scripts/nfl_sequence/build_matchup_snapshot.py) enforces a cutoff exactly **90 minutes before verified kickoff**, validates news/starter evidence, and accepts optional paired pinned roster artifacts. It is not present in every older worktree. Check `--help` on the selected branch before execution. Example with previously resolved and verified variables (not literal values):

```bash
python3 scripts/nfl_sequence/build_matchup_snapshot.py \
  --db "$DB" --capture-dir "$CAPTURE_DIR" --game "$SLC_GAME_ID" \
  --as-of "$CUTOFF_UTC" --kickoff-utc "$KICKOFF_UTC" \
  --kickoff-source-url "$URL" --evaluation verified_forecast \
  --out-dir "$NEW_OUTPUT_DIR"
```

Use the applicable frozen schedule version, depth charts, membership/eligibility, availability/injury and starter evidence, and pinned model-specific artifacts (including HE snap counts when enabled). Pass required roster overlays and their provenance; run the model-specific roster and source preflight before any simulation. Keep source bytes, acquisition times, artifact hashes and builder status. The example does not supply those artifacts or guarantee that the builder will accept a particular source URL. Do not overwrite an existing frozen snapshot. A snapshot.json file alone is not success: the builder can write it before refusing evidence, and the status/summary and exit code matter.

If T−90 has already passed, only evidence genuinely available at or before T−90 can populate that frozen snapshot; a fresh scoreboard query may identify the matchup now but cannot be misrepresented as an earlier capture. If kickoff has already passed, do not describe a newly constructed run as a prospective pregame prediction. Reuse verified frozen artifacts, or use the branch's legitimate retrospective mode and label it accordingly. Never silently downgrade an intended forecast to exploratory replay, change cutoff, or admit post-cutoff evidence to make a gate pass.

Report: API URL/environment, observed UTC and source/age, scoreboard ID and SLC ID, teams, kickoff and cutoff UTC, pinned model commit, snapshot/evidence paths and hashes, preflight outcome, blockers and whether forecast/replay is eligible.

## 6. External sources are exceptional, not prohibited

LP first for facts LP serves. If the API/schema, approved DB and stored captures cannot supply a required fact or cannot establish freshness, record what was tried and why it failed. A specific official/approved source may then be necessary for kickoff confirmation, missing injuries, inactives, news, weather or other required evidence. Capture its actual publication and acquisition times; never substitute a search snippet for a reproducible input. Do not bypass a failed preflight, invent a game, change production, or run a fast-host batch without approval.

This guide is source-checked against dev `05e97b05` and the cited candidate pin; endpoint reachability and example execution have not been verified from the documentation editor's environment.
