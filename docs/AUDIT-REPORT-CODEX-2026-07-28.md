Read-only audit report — snapshot `ae0dc37`, 2026-07-28. The audit is red. I changed no repository file or database row, ran no package manager, started/restarted no service, and did not touch Hermes’s worktree. The browser check intercepted both POSTs; draft counts stayed `41 / 1,645` before and after.

### 1. Scope drift during the audit

Command:

```bash
git rev-list --left-right --count dev...HEAD
git log -4 --date=iso-local --pretty='format:%h %ad %s'
```

| Observed | Expected |
|---|---|
| Started at `0 61`; moved during the audit to `0 65` | Brief says `0 59` |
| Four concurrent commits appeared, ending at `ae0dc37` | Stable audit target |

User-visible: indirectly. The new commits affect the test gate and the next backend task, but nothing was merged to the user’s URL.

### 2. Delivery remains split: the user’s URL does not serve this branch

Command:

```bash
curl -sS -o /tmp/live.json -w '%{http_code}\n' \
  http://127.0.0.1:8096/api/nfl/draft/player/16247
curl -sS -o /tmp/branch.json -w '%{http_code}\n' \
  http://127.0.0.1:8098/api/nfl/draft/player/16247
```

| Observed | Expected |
|---|---|
| `:8096` → `404 {"detail":"Not Found"}` | Player-detail endpoint available |
| `:8098` → `200`, Puka payload and overlay data | Same behavior on the URL the user was reviewing |

User-visible: yes. Missing on `https://someone-decorative-wearing-produce.trycloudflare.com`; present on `https://altered-era-sold-explain.trycloudflare.com`, notably `/mock-draft` and `/leagues/nfl?tab=camp`.

### 3. Gate failures still exit successfully

Command:

```bash
LP_GATE_W=/tmp/definitely-missing-lp-audit bash verify-gates.sh B1
echo $?
```

| Observed | Expected |
|---|---|
| Prints `FAIL B1`, then exits `0` | Any printed `FAIL` exits nonzero |

The `no()` helper only echoes; it never records or returns failure. The same applies to assertion failures inside Python that print `FAIL` and exit normally.

User-visible: no direct URL. It can falsely certify every URL covered by the suite.

### 4. `REG-render` still has an inert, green selector

Command:

```bash
LP_GATE_W=/root/lp-team-vocab \
LP_GATE_B=http://127.0.0.1:8098 \
LP_GATE_F=http://127.0.0.1:3098 \
bash verify-gates.sh REG-render
echo $?
```

| Observed | Expected |
|---|---|
| No verdict; exit `0` | Run the named render gate and print PASS/FAIL |

The case label is `render`, while the gate calls itself `REG-render`. `all` now invokes it, but the obvious named invocation remains a false green.

User-visible: indirectly on `/mock-draft` and `/leagues/nfl?tab=camp`.

### 5. The current “read-only regression gate” writes persistent product data

Commands:

```bash
nl -ba scripts/render-gate.js | sed -n '35,115p'
python3 - <<'PY'
import sqlite3
c=sqlite3.connect('file:/root/picks.hermes.db?mode=ro', uri=True)
print(c.execute('select count(*) from nfl_mock_drafts').fetchone()[0])
print(c.execute('select count(*) from nfl_mock_draft_picks').fetchone()[0])
PY
```

| Observed | Expected |
|---|---|
| Gate clicks `Start Draft`; POSTs are not intercepted and there is no cleanup | Regression gate leaves production-shaped DB state unchanged |
| Audit start: `39 drafts / 1,635 picks`; current: `41 / 1,645` after other activity | Stable counts absent real user drafts |

I did not attribute the two new drafts to a specific process, but they match the gate’s persistent-write behavior. My intercepted browser run held counts at `41 / 1,645`.

User-visible: usually hidden by device scoping, but it pollutes `/mock-draft` persistence and invalidates test isolation.

### 6. Most named gate claims remain materially broader than their assertions

Command:

```bash
nl -ba verify-gates.sh | sed -n '22,179p'
```

| Gate | Observed assertion | Expected assertion | User-visible |
|---|---|---|---|
| A1 | `games_missed` merely exists | Correct value for the named player | `/mock-draft`, `/leagues/nfl?tab=camp` overlays |
| A1b | Allows `pk_pts_per_game is None` | Kicker parity requires the published kicking value | Player Rankings PK view |
| A2 | First 100 only; rejects only `team_games > 18` and negative missed | Exact denominator and all eligible players, including the named midseason case | Player Rankings |
| A3 | 32 rows, integer byes, more than one distinct bye week | 32 unique teams, one valid bye each, complete schedule | Mock-draft bye filter |
| B1 | Finds `'DEF'` and `'PK'` anywhere in one source file | Rendered, interactive controls | Player Rankings |
| B2 | Any one target field anywhere outside `types.ts`; B2b checks JSON | All named fields rendered with correct null semantics | Both NFL draft surfaces |
| B4 | Greps only literal `"TEAM_GAMES - "` | No runtime hardcoded denominator | `/mock-draft` |
| REG-pool | Checks `300` and `DEF=32`; printed range is not asserted | Required placement/order invariant | `/mock-draft` |
| REG-adp-dst | Four values within ±12; no provenance check | Published ESPN values for all 32 | Both NFL draft surfaces |
| REG-dst | Row count only | Correct entities, fields, ordering, and values | Player Rankings |
| REG-jest | Only `lib/mockDraft` | Relevant frontend regressions across touched surfaces | All touched UI |

The pre-`REG-render` full run produced 13 passes and the intended red `REG-adp-dst`. I did not rerun current `all` because it now performs persistent POSTs.

### 7. SEA D/ST has three incompatible presence contracts

Command:

```bash
curl -s 'http://127.0.0.1:8098/api/nfl/draft-board?position=DEF&limit=40' |
  jq '.players[] | select(.name=="SEA D/ST") |
      {name,games_played,sample,dst_pts_per_game}'
curl -s 'http://127.0.0.1:8098/api/nfl/draft/player/30116' |
  jq '{name,games_played,sample,dst_pts_per_game}'
curl -s 'http://127.0.0.1:8098/api/player/30116' |
  jq '{name,regular_season_games,coverage,data_status}'
curl -s 'http://127.0.0.1:8098/api/players/search?q=SEA%20D%2FST'
```

| Surface | Observed | Expected |
|---|---|---|
| Draft board | `17, full, 9.6` | `17, full, 9.6` |
| Draft overlay endpoint | `0, none, 9.6` | Same presence as board |
| Generic player endpoint | `0`, all coverage false, `unavailable` | D/ST season coverage |
| Search | `[]` | SEA D/ST discoverable |

Root cause confirmed:

```sql
SELECT DISTINCT p.position
FROM player_game_logs l JOIN players p ON p.id=l.player_id
WHERE l.league='nfl';
```

Observed: 25 positions, no `DEF`. Expected: code that handles D/ST does not interpret absence from this table as zero games.

User-visible: yes. On altered-era `/mock-draft`, the SEA overlay says “No NFL sample” beside `164.0` total and `9.6/game`; `/player/30116` is unavailable; global search cannot find it.

### 8. The merge lost the snap-count availability implementation

Command:

```bash
git show e43ca6c:backend/routers/nfl_mock_draft.py |
  rg -n 'nfl_snap_counts|nfl_schedule'
rg -n 'nfl_snap_counts|nfl_schedule|player_game_logs' \
  backend/routers/nfl_mock_draft.py
```

Observed: commit `e43ca6c` used `nfl_snap_counts + nfl_schedule`; current pool code uses only `player_game_logs`. The loss occurred across merge `fb0f2cd`.

A complete API comparison produced:

```text
pool=300  board=595  overlap=269
any mismatch=59
games_played=28  games_missed=40
weeks_played=28  team_weeks=22
CeeDee Lamb: pool 13 / board 14
Josh Allen:  pool 16 / board 17
```

Expected: identical availability facts for the same `player_id`.

User-visible: yes. `/mock-draft` and `/leagues/nfl?tab=camp` disagree for 59 of 269 overlapping ranked players.

### 9. The actual mock-draft UI fabricates D/ST ADP and contradicts its own overlay

Command: isolated Playwright context connected to existing `:9222`, with every mock-draft POST fulfilled locally; then navigate to:

```text
http://127.0.0.1:3098/mock-draft
```

Observed versus expected:

| Observed | Expected |
|---|---|
| 300 initial rows; DEF filter 32 | 300 / 32 — passes |
| SEA row: `17/17`, ADP `999.0` | Honest null as `—`, or published `106.5` after job15 |
| SEA overlay: “No NFL sample”, `164.0`, `9.6` | `17 full` beside the scoring values |
| Zero console/page errors | Zero — passes |
| POSTs intercepted: create + picks; DB unchanged | Read-only audit |

User-visible: yes, altered-era `/mock-draft`.

### 10. Player Rankings renders correctly shaped controls, but D/ST ordering/data are still false

Same intercepted browser probe at:

```text
http://127.0.0.1:3098/leagues/nfl?tab=camp
```

| Observed | Expected |
|---|---|
| Nine filters; DEF=32, PK=32 | Pass |
| DEF headers position-aware | Pass |
| PK headers position-aware | Pass |
| First DEF is alphabetical `ARI D/ST`, ADP `—` | Published order headed by DEN; published ADP present |
| 414px viewport: `scrollWidth=399`, `clientWidth=399` | No page-level horizontal overflow — passes |

User-visible: yes, altered-era `/leagues/nfl?tab=camp`.

### 11. The engine destroys the backend’s claimed D/ST ordinal

Command:

```bash
node_modules/.bin/tsc lib/mockDraft/engine.ts \
  --module commonjs --target es2020 --outDir /tmp/lp-audit-engine
node <<'JS'
/* 200 seeded full drafts using createDraft/autopick;
   once with source null, once with the page's null→999 mapping */
JS
```

Measured:

| Input | Backend DEF indices | Engine initial indices | DEF pick range | Rounds | Max/team |
|---|---:|---:|---:|---|---:|
| Honest `null` | 150–181 | 268–299 | 122–156 | R11 458, R12 1,899, R13 43 | 1 |
| UI `999` | 150–181 | 268–299 | 133–180 | R12 519, R13 1,364, R14 493, R15 24 | 1 |

Expected: the task’s promised backend-source ordinal remains stable. It cannot: `createDraft()` first moves all nulls to 268–299, then `botPick()` recomputes indices against the shrinking `availablePool`.

User-visible: yes, altered-era `/mock-draft`. The one-D/ST roster cap works; timing/order does not match the stated source of truth.

### 12. Published D/ST ADP still joins 0 of 32

Command:

```bash
python3 - <<'PY'
import sqlite3
c=sqlite3.connect('file:/root/picks.hermes.db?mode=ro', uri=True)
# count players, ids, ADP and joined DEF rows
PY
```

| Measure | Observed | Expected |
|---|---:|---:|
| NFL players | 24,678 | 24,678 |
| Missing NFL `espn_id` | 7,889 | Measured ground truth |
| D/ST entities | 32 | 32 |
| D/ST with `espn_id` | 0 | 32 usable published identifiers |
| `nfl_adp` rows | 9,611 | Measured ground truth |
| Joined D/ST ADP | 0 | 32 |
| NFL game logs | 25,062 | Measured ground truth |

User-visible: yes. Both altered-era draft surfaces show null/fabricated/derived ordering instead of ESPN’s published values. `REG-adp-dst` is correctly red; I did not alter it.

### 13. Team vocabulary is clean in core branch tables, but not in snap counts; the live DB is mixed

Command:

```bash
SELECT team, count(*) FROM nfl_snap_counts
WHERE team IN ('LA','WAS','AZ') GROUP BY team;
```

| DB/table | Observed | Expected |
|---|---|---|
| Branch `players`, NFL logs, schedule | ESPN-canonical `LAR/WSH/ARI` | Canonical — passes |
| Branch `nfl_snap_counts` | `LA=648`, `WAS=651`; 1,299 aliases | Canonical `LAR/WSH`; zero aliases |
| Live dev DB | Mixed `LA/LAR`, `WAS/WSH`, plus one `AZ` player | One vocabulary per join boundary |

Current branch snap consumers join by `player_id/week`, so I found no present branch URL made wrong solely by `nfl_snap_counts.team`. It is a latent silent-miss hazard for any future team join. The live URL does not expose the branch draft endpoints yet.

### 14. The zero-byte DB is a decoy, not the database `:8096` reads

Command:

```bash
tr '\0' '\n' </proc/2288190/environ | rg '^LP_DB_PATH='
stat -c '%n %s' \
  /root/legendarypicks/picks.dev.db \
  /root/legendarypicks/backend/data/picks.dev.db
```

| Observed | Expected |
|---|---|
| `:8096` uses `/root/legendarypicks/backend/data/picks.dev.db` | A nonempty real DB |
| Documented root-level file is 0 bytes / 0 tables | It must not be the active DB |
| Active file is 162,836,480 bytes / 39 tables | Consistent |

User-visible: no defect here; this resolves C4’s launch-path contradiction.

### 15. Job 9’s “self-repairing upsert” is unreachable

Command:

```bash
nl -ba backend/ingest_nfl_snap_counts.py | sed -n '182,247p'
rg -n 'idempotent re-runs' JOB-RESULTS.md
```

| Observed | Expected |
|---|---|
| Existing `(player_id, week)` keys `continue` at lines 183–185 | Existing rows reach the upsert |
| `ON CONFLICT DO UPDATE` is at lines 238–243 | Re-runs repair existing null/bad values |
| Results claim “idempotent re-runs” | Claim matches execution |

The DB currently has `20,627` snap rows and all `20,627` have non-null offensive/special-teams values because it was rebuilt once. A later corrupt value will not self-repair.

User-visible: not currently; future availability/stat refreshes can silently stay stale.

### 16. Job 13’s specified fallback instructs its own defeat

Command:

```bash
nl -ba TASK-job13-engine-dst-seam.md | sed -n '76,112p'
nl -ba lib/mockDraft/engine.ts | sed -n '206,283p'
```

| Observed | Expected |
|---|---|
| Spec calls shrinking `availablePool` index the backend source of truth | Stable backend ordinal |
| Engine re-sorts nulls last, then recomputes the shrinking index each pick | Preserve the backend’s 150–181 placement |

User-visible: yes, altered-era `/mock-draft`; quantified in finding 11.

Job 11 also contains a procedural contradiction (“touch only” runtime files while requiring a results-file edit). Job 10’s execution touched shared `types.ts` despite its allowlist. I found no comparable runtime self-defeat in jobs 12 or 14.

### 17. TypeScript has 25 real diagnostics hidden by configuration

Command:

```bash
node_modules/.bin/tsc --noEmit --pretty false --incremental false
rg -n 'ignoreBuildErrors' next.config.js
```

| Observed | Expected |
|---|---|
| 25 errors | 0 |
| 20 `TS2307` missing-module diagnostics | Resolvable imports or removed dead island |
| 4 `TS2802` downlevel-iteration errors: 3 DraftRoom, 1 Scores | Compiler target/code agree |
| 1 `TS2339`: `PoolPlayer.team_games` | Runtime contract/type agree |
| `typescript.ignoreBuildErrors: true` | Builds do not conceal type failures |

The missing-module imports are in a legacy component island not imported by current pages, so I found no current URL failure from those 20. The `team_games` error is real schema drift on `/mock-draft`; today all NFL teams happen to have 17 games, masking the hardcoded fallback.

### 18. Two WC tests fail outside the gate’s test path

Command:

```bash
node_modules/.bin/jest components/Game/WCContext.test.tsx \
  --no-coverage --runInBand
```

| Observed | Expected |
|---|---|
| `2 failed, 1 passed` | `3 passed` |
| Missing old “Opening read” / “Keep this read” assertions | Tests match the current `right_now`/phase-aware contract |
| `REG-jest` still reports 36 mock-draft tests green | Gate covers touched/relevant suites |

The component contract evolved while the tests remained stale; this does not by itself prove a current rendering bug, but the polling behavior those tests were meant to guard is no longer protected.

User-visible risk: `/game/wc/760517`.

### 19. One untracked runtime asset would disappear from a merge

Command:

```bash
git status --porcelain=v1 --untracked-files=all
stat -c '%n %s' backend/data/esports_team_logos.json
rg -n 'esports_team_logos.json' backend
```

| Observed | Expected |
|---|---|
| 19 untracked entries | Delivery-relevant inputs tracked or deliberately excluded |
| `backend/data/esports_team_logos.json`, 2,443 bytes, loaded by `pandascore.py` | Runtime asset included in delivery |
| Handoffs/tasks/specs also untracked | Audit/delivery record retained intentionally |
| Logs, empty `nohup.out`, and `backend/venv` symlink untracked | Local artifacts ignored |

User-visible: the JSON can affect team-logo rendering on altered-era `/esports` after a clean merge/deploy.

### 20. `filterSlotIds` is ignored upstream, but current downstream code does not trust it

Commands:

```bash
rg -n 'filterSlotIds|_DRAFT_POSITIONS|position IN' \
  backend/ingest_nfl_adp.py backend/routers/nfl_mock_draft.py
```

Observed: the ingest receives the broad identical payload, but stores position metadata; draft consumers independently restrict eligible positions. Expected upstream filtering would narrow the payload, but downstream correctness must not depend on it.

User-visible: no current defect found from this item. It is misleading/dead request filtering, not the cause of the D/ST ADP miss.

Overall roadmap result: M1 is partial (entity/slot yes; published ADP and coherent D/ST detail no), M2 regressed in the merge, M3 renders and interacts, M4/M6 were explicitly scratched, M5 works for skill players but contradicts D/ST, and M7 still carries the hardcoded-denominator schema gap. The altered-era UI itself rendered with zero console errors; the failures are data semantics, endpoint consistency, ordering, delivery, and false-green verification—not a current first-render crash.
