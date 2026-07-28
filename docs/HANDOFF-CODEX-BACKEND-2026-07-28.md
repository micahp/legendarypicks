# Codex backend-orchestrator handoff — 2026-07-28

## Stop point

Codex is the backend **orchestrator**, not the backend author. Hermes implements through
`tmux send-keys -t hermes:0.0`; do not use MCP messaging.

The active implementation worktree is:

```text
/root/lp-job15-complete
branch: fix/job15-complete
HEAD:   3938ddd
base:   bd1f8b0
status: clean
```

Do not merge or cherry-pick `fb0f2cd`. The audit merge has already been qualified and
merged on the main feature branch. `abc92bf` proves that the one real loss from that
hand-resolved merge is the pool builder's snap-count/schedule block; the other twelve
missing-symbol reports were false alarms or intentional removals.

Main feature worktree code baseline (the parent of this documentation-only handoff commit):

```text
/root/lp-team-vocab
branch: feat/dst-and-mock-draft
HEAD:   abc92bf
```

Preserve the concurrent modification to `backend/data/esports_team_logos.json` and all
untracked files in that worktree. They are not part of Codex's work.

## Non-negotiable process constraints

- Never run `npm`, `npx`, `yarn`, or `pnpm`, including dry runs.
- Do not start, stop, kill, or restart any server or process on `:3096`, `:3098`,
  `:8096`, or `:8098`.
- Do not start a new dev server.
- Do not push or merge. Claude/Micah owns frontend, gates, servers, merge, and deploy.
- Backend implementation stays in a worktree and within the exact per-task file allowlist.
- Do not touch `/root/lp-job15-dst-published-adp`.
- Use a disposable copy of `/root/picks.hermes.db` for in-process API verification.
- Treat a hand-resolved merge as a rewrite. Audit every named hand-resolved file against
  both parents; the merge commit itself proves nothing.

## Audit state

The durable audit and qualification are already present:

```text
docs/AUDIT-REPORT-CODEX-2026-07-28.md
docs/QUALIFICATION-OF-CODEX-AUDIT-2026-07-28.md
```

Do not recreate or re-merge them.

## Job15: published D/ST ADP

### Commit chain, in order

```text
71458a0 feat: D/ST ingest — resolve 32 via published proTeams map, fail-closed
fbe347d feat: delete dst_rank/_DST_SLOT/interleave, D/ST sort by real ADP, fix B17 player_detail
d014f3f test: ingest fail-closed resolution — 32-of-32 and incomplete-map cases
a7b9a62 fix: guarantee all 32 DEF in pool — separate selection, merge, sort by real ADP
4f5c8e3 fix: honest pool fixture, full-order test, null-ADP reject, B17 regression, exact-set validation
9841681 fix: position-aware ADP sentinel for DEF, remove filterSlotIds, add regression tests
```

Exact aggregate diff from `bd1f8b0` through `9841681`:

```text
backend/ingest_nfl_adp.py
backend/routers/nfl_mock_draft.py
backend/routers/nfl_offseason.py
backend/test_nfl_dst.py
```

### Independent job15 closeout

Command:

```bash
/usr/bin/python3 - <<'PY'
import sqlite3
con = sqlite3.connect("file:/root/picks.hermes.db?mode=ro", uri=True)
print(con.execute("""
    SELECT COUNT(*), COUNT(na.adp), SUM(na.adp IS NULL)
    FROM players p
    LEFT JOIN nfl_adp na ON na.player_id=p.id AND na.season=2026
    WHERE p.league='nfl' AND p.position='DEF' AND p.active=1
""").fetchone())
PY
```

Observed versus expected:

| Measurement | Observed | Expected | User-visible |
|---|---:|---:|---|
| active D/ST | 32 | 32 | `/mock-draft`, Player Rankings |
| joined non-null D/ST ADP | 32 | 32 | `/mock-draft`, `/api/nfl/draft-board?position=DEF` |
| null joined ADP | 0 | 0 | same |

In-process verification was run against a disposable byte-for-byte copy of
`/root/picks.hermes.db` with `LP_DB_PATH` set before imports.

| Measurement | Observed | Expected | User-visible |
|---|---:|---:|---|
| pool rows | 300 | 300 | `/api/nfl/mock-draft/pool`, `/mock-draft` |
| DEF rows / distinct IDs / distinct teams | 32 / 32 / 32 | 32 / 32 / 32 | same |
| duplicate DEF teams | 0 | 0 | same |
| DEF with null ADP | 0 | 0 | same |
| payloads containing `dst_rank` | 0 | 0 | same |
| RB/WR/TE/QB/PK/DEF | 73/97/36/37/25/32 | 73/97/36/37/25/32 | same |
| DEF board rows / non-null ADP | 32 / 32 | 32 / 32 | Player Rankings |
| board head | DEN 89.97, HOU 91.84, LAR 98.23, SEA 106.51, PIT 118.24, BAL 134.54 | exact | Player Rankings |
| module/page filters omitting `filterSlotIds` | true / true | true / true | next ADP ingest |

The filter check intercepted `urllib.request.urlopen` locally; it did not use the network.

Focused test command:

```bash
cd /root/lp-job15-complete/backend
/usr/bin/python3 -m unittest test_nfl_dst -q
```

Observed: `Ran 47 tests ... OK`. Expected: all pass.

Do not claim `test_nfl_mock_draft.py` passed in this worktree:

- `/usr/bin/python3 -m unittest test_nfl_dst test_nfl_mock_draft -q` fails at import
  because system Python has no `httpx`.
- The already-installed backend venv has `httpx`, but its first
  `TestClient` request hangs. A single test timed out after 20 seconds:

```bash
timeout 20s /root/legendarypicks/backend/venv/bin/python3 \
  -m unittest test_nfl_mock_draft.TestNflMockDraft.test_pool_returns_players -v
```

Observed: exit `124`, stuck after printing the test name. This is a baseline test-environment
blocker, not a green or red code result. No dependency was installed.

Job15 is ready for Claude/Micah to merge in commit order, subject to their gates and server
reload. The null-ADP fallback in `lib/mockDraft/engine.ts` is frontend-owned and must be
deleted after the backend lands; do not tune it.

## Finding 8: targeted restore completed, zero-parity acceptance NOT met

Hermes restored only the two historical pool blocks from
`e43ca6c:backend/routers/nfl_mock_draft.py`:

1. merge `nfl_snap_counts` presence into the pool aggregate;
2. source team weeks from `nfl_schedule`.

Commit:

```text
3938ddd fix: merge snap-count presence, source team_weeks from nfl_schedule
```

The commit changes exactly:

```text
backend/routers/nfl_mock_draft.py
```

No merge/cherry-pick of `e43ca6c` or `fb0f2cd` occurred.

### Exhaustive comparison method

The comparison must fully paginate the board; `limit` is capped at 100:

```python
board = []
offset = 0
eligible = None
while eligible is None or offset < eligible:
    page = nfl_offseason.nfl_draft_board(
        position=None, sort="adp", q=None, limit=100, offset=offset,
    )
    eligible = page["eligible_players"]
    board.extend(page["players"])
    offset += 100
```

Then key pool and board rows by `player_id` and compare:

```text
games_played
games_missed
weeks_played
team_weeks
```

The earlier `board=800`, `overlap=237`, `49 players` measurement stopped after eight
100-row pages. On the post-job15 branch the board reports 1,821 eligible rows, so the
exhaustive denominator is different.

### Before `3938ddd`

| Measurement | Observed | Expected |
|---|---:|---:|
| pool / board / overlap | 300 / 1821 / 273 | exhaustive current counts |
| players with any disagreement | 60 | 0 |
| games_played mismatches | 29 | 0 |
| games_missed mismatches | 41 | 0 |
| weeks_played mismatches | 29 | 0 |
| team_weeks mismatches | 22 | 0 |
| CeeDee Lamb games, pool/board | 13 / 14 | 14 / 14 |
| Josh Allen games, pool/board | 16 / 17 | 17 / 17 |
| Brandon Aubrey team weeks, pool/board | 17 / 0 | 17 / 17 |

### After `3938ddd`

| Measurement | Observed | Expected |
|---|---:|---:|
| pool / board / overlap | 300 / 1821 / 273 | unchanged |
| players with any disagreement | **39** | **0** |
| mismatched field cells | 49 | 0 |
| games_played mismatches | 3 | 0 |
| games_missed mismatches | 15 | 0 |
| weeks_played mismatches | 3 | 0 |
| team_weeks mismatches | 28 | 0 |
| CeeDee Lamb games, pool/board | 14 / 14 | 14 / 14 |
| Josh Allen games, pool/board | 17 / 17 | 17 / 17 |
| DEN and HOU D/ST games/team weeks | 17/17 on both | equal |
| Brandon Aubrey team weeks, pool/board | **17 / 0** | **17 / 17** |

Hermes reported “49 disagreements,” but that is the sum of mismatched field cells.
The correct union is 39 players.

User-visible surfaces: `/api/nfl/mock-draft/pool`, `/api/nfl/draft-board`,
`/mock-draft`, and Player Rankings.

### Residual mechanism

The exact one-file historical restore cannot produce zero parity:

- 21 PK rows have authoritative pool `team_weeks` but board `team_weeks=[]`.
  `nfl_offseason._pk_aggregates` replaces the general presence aggregate and carries no
  `team_weeks`.
- Evan McPherson, Will Reichard, and Cairo Santos also differ in games/weeks because the
  PK board aggregate counts stat rows and drops snap-only presence.
- Eleven rookies/no-presence players have pool `games_missed=null` but board
  `games_missed=17`. Honest absent-data semantics favor `null`.
- Rashid Shaheed has pool `games_missed=-1` versus board `0`; the pool subtraction needs
  a non-negative clamp or the authoritative team-game denominator.
- Seven skill players differ in `team_weeks`. Three are mid-season team-selection
  disagreements caused by adding snap counts into `team_counts`; four are snap-only
  players for whom the board refuses to assign the published snap team.

The last user instruction restricted finding 8 to
`backend/routers/nfl_mock_draft.py` and forbade every other file. Reaching zero now
requires a scope decision. Do not silently broaden it.

Likely minimal follow-up scope, only if Micah authorizes it:

```text
backend/routers/nfl_mock_draft.py
backend/routers/nfl_offseason.py
backend/test_nfl_mock_draft.py
backend/test_nfl_offseason_api.py
```

The correct direction is to preserve authoritative schedule weeks, preserve snap presence,
use log-derived primary team when logs exist, use published snap team only for snap-only
players, return null rather than 17 missed games when presence is absent, and clamp missed
games non-negative. Do not “fix” parity by erasing the pool's valid PK schedule.

## Remaining queue

Do not dispatch either item until job15/finding-8 scope is resolved and merged:

1. `TASK-hermes-real-stats.md`
2. `TASK-hermes-mock-draft-completion.md`

The real-stats task has pre-task payload hashes. Re-capture every affected hash after the
availability work lands; any board correction above changes existing fields and therefore
invalidates the old baselines. The SQL acceptance remains:

```text
Gibbs SQL carries = 243
API stats.carries = 243
```

Hermes, not Codex, implements backend code. Section 0 of the real-stats task remains
mandatory: ask Ponytail, then load `published-first` and `honest-data-ui`; use existing
published JSON columns and render absent/not-applicable values as `null`, never `0.0`.

## Out-of-repo cleanup still in flight at handoff

Hermes's automatic self-improvement curator mutated:

```text
/root/.hermes/skills/legendarypicks-workflow/SKILL.md
```

Expected exact state:

```text
size: 34267 bytes
MD5:  3d3b85dbbc46a93ae61da99ab175f9bf
```

At the instant this handoff was written, Hermes was still reconstructing the exact file.
The size was 34267 but MD5 was still:

```text
021cd3bf537093c2146e3c78f4e8e304
```

The next session's **first action** must be:

```bash
md5sum /root/.hermes/skills/legendarypicks-workflow/SKILL.md
stat -c '%s' /root/.hermes/skills/legendarypicks-workflow/SKILL.md
tmux capture-pane -p -t hermes:0.0 -S -80
```

If the expected MD5 is not restored, keep Hermes on that exact undo only. Do not let the
curator's out-of-scope mutation survive and do not change any repo commit while restoring it.

Deterministic recovery is available in `/root/.hermes/state.db`:

1. `messages.id=26158` is a `skill_view` result whose inner JSON `.content` is the
   34249-byte state with MD5 `aeef05e4317ed4c7313226017b771197`.
2. Replay the four exact corrections recorded at message IDs `26160`, `26162`, `26164`,
   and `26168`: restore `## Commit hygiene` plus its blank line; add the blank line before
   `## UI architecture references`; remove the two extra EOF blank lines; restore the
   single final newline.
3. Message `26170` records that this exact sequence produced the expected 34267-byte,
   `3d3b85dbbc46a93ae61da99ab175f9bf` file.

Hermes had been given this deterministic recipe when the handoff ended.
