# TASK (Hermes, backend) — persist mock-draft completion

**Queue position:** after job15 and real per-position stats. Backend only.

The browser can tell a user “Draft complete,” but the backend cannot represent that state.
This is a missing state transition, not a data cleanup job.

---

## 0. Read before writing

Ask the two backend questions in order:

1. **Ponytail — does this code need to exist?** Yes. The client has no existing backend
   operation that can persist completion. Do not add a second status calculator or infer a
   status on every GET; add the one missing transition.
2. **Published first — does this value need to be computed?** No external publisher owns
   this state. Completion is an application event. The backend validates that its persisted
   pick ledger is complete, then records the explicit transition.

Read `AGENTS.md` and `.claude/skills/published-first/SKILL.md` before editing.

---

## 1. Ground truth

Measured 2026-07-28 against `/root/picks.hermes.db`:

```bash
python3 - <<'PY'
import sqlite3
con = sqlite3.connect("file:/root/picks.hermes.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
print(dict(con.execute("""
WITH per_draft AS (
  SELECT d.id, d.status, d.completed_at,
         d.rounds*d.teams AS expected_picks,
         COUNT(p.pick_no) AS actual_picks
  FROM nfl_mock_drafts d
  LEFT JOIN nfl_mock_draft_picks p ON p.draft_id=d.id
  GROUP BY d.id
)
SELECT COUNT(*) AS drafts,
       SUM(status='active') AS active,
       SUM(status='complete') AS complete,
       SUM(completed_at IS NOT NULL) AS with_completed_at,
       SUM(actual_picks=expected_picks) AS with_all_picks,
       MAX(actual_picks) AS max_picks,
       SUM(actual_picks) AS total_picks
FROM per_draft
""").fetchone()))
PY
```

Observed:

```text
drafts=41  active=41  complete=0  with_completed_at=0
with_all_picks=7  max_picks=180  total_picks=1645
```

Expected: a persisted draft with all `teams * rounds` picks can transition to `complete`.

This is code-path proof, not usage analytics. The old render gate wrote indistinguishable
test rows into these tables, so do not describe the 41 rows as user activity.

Current source has:

- an INSERT with literal `status='active'`;
- no UPDATE that changes `status` or `completed_at`;
- no completion route;
- a picks guard that rejects non-active drafts, but no route can create that state.

---

## 2. Contract

Add:

```text
POST /api/nfl/mock-draft/{draft_id}/complete
X-Device-Id: <same device that owns the draft>
```

Successful response:

```json
{
  "id": "<draft id>",
  "status": "complete",
  "completed_at": 1785250000000
}
```

Rules:

1. Use the existing `_device_id` contract. Missing device header is `400`; unknown draft
   or another device's draft is `404`, matching the existing read/write routes.
2. A draft is complete only when persisted picks cover the full ledger:
   `COUNT(*) == teams * rounds`, with pick numbers spanning `1..teams*rounds`. The primary
   key already guarantees distinct pick numbers.
3. An incomplete active draft returns `409` and does not change `status`, `updated_at`, or
   `completed_at`.
4. A valid transition sets `status='complete'`, and sets `completed_at` and `updated_at` to
   the same millisecond timestamp.
5. Completion is idempotent. Repeating the request for the same device returns `200` with
   the original `completed_at`; it must not rewrite the timestamp.
6. After completion, the existing append-picks route returns `409` through its existing
   non-active guard. GET and list responses expose the stored `complete` status and
   timestamp without a new response shape.
7. Validate and update in one SQLite transaction so a concurrent pick append cannot race
   the ledger count.

Do not add an automatic status derivation to GET/list. Do not add a second “complete”
definition in another module.

---

## 3. Tests

Focused tests must prove:

- missing device → `400`;
- unknown draft and wrong device → `404`;
- 179 of 180 picks → `409`, with the DB row unchanged;
- 180 of 180 picks → `200`, status/timestamps persisted;
- repeated completion → `200`, original timestamp unchanged;
- appending after completion → `409`;
- GET and list both return `status='complete'` and the same `completed_at`;
- no existing create, append, resume, list, or pool test regresses.

Use only the disposable DB already created by `backend/test_nfl_mock_draft.py`. Do not write
to `/root/picks.hermes.db` during tests, and do not backfill or delete the existing 41 rows.

---

## 4. Scope lock

Exactly these files:

- `backend/routers/nfl_mock_draft.py`
- `backend/test_nfl_mock_draft.py`

Nothing else. In particular:

- no frontend, `lib/`, API client, types, or gate edits — the frontend call is Micah-owned;
- no shared utilities, schema migration, ingest, task/spec/docs changes;
- no `/etc`, systemd, cron, nginx, scripts, or worktree-management commands;
- never run `npm`, `npx`, `yarn`, or `pnpm`;
- do not start, stop, restart, or kill any server or process;
- no push and no merge.

One focused backend commit. Report the commit, exact test command/count, and the observed
179-pick, 180-pick, repeated-completion, post-completion-append, GET, and list payloads.
