# TASK — prod's Bye column is empty; ingest the 2026 NFL schedule into the prod DB

**This is an AUTHORIZED PRODUCTION DATABASE WRITE.** Micah authorized it on
2026-08-03 after seeing the measurement below. The authorization covers exactly
one table in one database, described here. It does not extend to anything else.

## The defect

`nfl_schedule` on prod holds **2025 only** (285 rows). Dev holds 2024, 2025 and
**2026 (272)**. So on prod `/api/nfl/schedule/2026` returns **404**, and every
Bye cell on the mock-draft pool renders `—`.

Measured in a real browser, 2026-08-03, both at 1280px:

    https://legendarypicks.xyz/mock-draft   33 of 33 rows empty
    http://127.0.0.1:3096/mock-draft         0 of 33 rows empty

Not cosmetic. `components/MockDraft/columns.tsx` says the draft room takes one
decisive number per position and "spends the width it saves on bye week, which
decides more picks in rounds 8-15 than a third decimal of expected points ever
will." The v0.7.0 promotion check was 200-level and could not see this: a 404 on
a sub-resource does not move the page's status code.

## What to do — in this order, one step at a time

**1. Back up the prod DB first.** Same convention the repo already uses:

    cd /root/legendarypicks/backend
    cp -a data/picks.db "data/picks.db.bak-prebye-$(date +%Y%m%d%H%M%S)"

Report the backup filename and its byte size. Do not proceed without it.

**2. Dry-run, and read the output before writing.** It should report 272 games,
272 REG, 272 not yet played, first kickoff 2026-09-09 20:20 NE at SEA. If it
reports anything else, STOP and report — do not write.

    LP_DB_PATH=data/picks.db ./venv/bin/python ingest_nfl_schedule.py \
        --season 2026 --dry-run

**3. The write. `--schedule-only` is mandatory.**

    LP_DB_PATH=data/picks.db ./venv/bin/python ingest_nfl_schedule.py \
        --season 2026 --schedule-only

Without that flag the script also creates and writes `team_game_results` — a
table prod deliberately does not have. Creating it on prod is NOT authorized and
is not part of this task.

**4. Reconcile against the table, not against the script's own output.**
A row count printed by the run is a claim about the run; what the table holds is
the claim that matters.

    SELECT season, COUNT(*) FROM nfl_schedule GROUP BY 1 ORDER BY 1;

Expect `2025 -> 285` **unchanged** and `2026 -> 272` **new**. Confirm
`team_game_results` still does not exist on prod. If 2025's count moved, you
wrote something you were not asked to — restore the backup and report.

**5. Verify the endpoint, then verify the surface.** These are different claims
and you need both.

    curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8100/api/nfl/schedule/2026

If it still 404s after a successful write, say so and stop — do not restart or
rebuild anything to make it pass. A stale cache is a finding, not an obstacle;
report it and I will decide.

Then a **real browser** against the live domain, not curl and not the served
HTML — the pool is client-rendered and grepping HTML for it is a guaranteed
false negative:

    https://legendarypicks.xyz/mock-draft

Read the Bye cells out of the rendered table. Report **how many of how many rows
carry a week**, plus the first six values, plus the console error count. Expect
0 empty of ~33. "Looks right" is not a result.

## Hard limits

- **One database: `/root/legendarypicks/backend/data/picks.db`. One table:
  `nfl_schedule`.** Nothing else.
- **Do not touch the dev DB** (`data/picks.dev.db`) or the dev servers on
  `:3096` / `:8096`. They are managed outside this session.
- **Do not** rebuild, restart, recreate or `docker compose up` anything.
- **Do not** edit any code, `docker-compose.yml`, `CHANGELOG.md`, `package.json`,
  or any git tag. This task produces **no commits**.
- **Do not** touch host config: `/etc`, systemd units, timers, cron, nginx.
- **Do not** run any other ingest, backfill or migration script.

If any step surprises you, stop and report rather than improvising. The backup
from step 1 is the whole rollback: `cp -a` it back over `data/picks.db`.
