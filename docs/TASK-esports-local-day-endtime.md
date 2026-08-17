# TASK (Codex): esports board — group by end time, in the viewer's local day

Repo **/root/legendarypicks**, branch `dev`. Read `docs/DEV-STANDARDS.md` and `AGENTS.md` first, follow both.
**Do this only after the UFC Predict tab task is done** (Claude will hand it to you; don't start early).

## OPERATING RULES (read before anything)
- **Dev servers are externally managed and already running: frontend `:3096`, backend `:8096`.**
  **NEVER start / kill / restart a dev server or uvicorn. Never run `kill`/`pkill` on node or python.**
  Verify against the running services; re-request a page if it looks stale (HMR recompiles).
- **Follow `docs/DEV-STANDARDS.md`:** measure any payload you change; **HTTP 200 is not proof it works** —
  verify the actual grouping in the browser.
- **Do NOT commit or push. Claude owns git.** Report files changed + verification when done.

## PROBLEM
The esports board (`pages/esports.tsx`) groups matches into day buckets (Today / Yesterday / dated) by
**start time only** (`localDateKey(m.startTime)`), and the slate payload has **no end time at all**. A
match that ends late at night can land in the wrong day bucket, and a *finished* game should be filed
under the day it **ended**, not the day it was scheduled to start. Grouping is already done client-side
in the browser's local timezone (`new Date(ms)`) — keep that; this task only adds an **end time** and makes
finished matches group by it.

Concrete case: CDL "TEX vs PAR" — `begin_at` 2026-07-18T01:01Z, `end_at` 2026-07-18T02:08Z (= 8:01–9:08 PM
CT, July 17). It should sit under the July-17 (local) results, keyed off when it ended.

## STEP 1 — backend: surface `endTime` (epoch ms) on every match
- In **`backend/routers/esports/pandascore.py`**, every emitted match dict that carries `"startTime"`
  (there are multiple build sites, incl. ~line 545 and ~line 628) must ALSO carry
  **`"endTime": _iso_to_ms(m.get("end_at"))`** — i.e. `None` when PandaScore has no `end_at`.
  - **CRITICAL — `end_at` is frequently NULL** on PandaScore finished matches (see the comment at
    `pandascore.py:128-136`; that's why the finished feed sorts by `scheduled_at`, not `end_at`). So
    `endTime` is best-effort: often null. **Never** invent one; the frontend falls back to `startTime`.
- **Trace `startTime` through to the emitted `/api/esports/upcoming` payload** (`slate.py` /
  `slate_state.py` reshape matches into the final surface dict — the response currently exposes a fixed
  key set that does NOT include an end time). Add `endTime` right alongside `startTime` in that
  normalization so it actually reaches the JSON. Other sources (GRID, bovada, LoL) that lack an end time
  simply emit `endTime: null` — additive, don't break them.
- **Verify:** `curl -s http://127.0.0.1:8096/api/esports/upcoming | python3 -c "import sys,json;
  d=json.load(sys.stdin)['matches']; f=[m for m in d if m.get('finished')];
  print('finished:',len(f),'with endTime:',sum(1 for m in f if m.get('endTime')))"` — a chunk of
  finished matches carry a real `endTime`, the rest null (expected). Note payload size before/after.

## STEP 2 — frontend: group finished matches by end time (viewer-local, unchanged tz)
In **`pages/esports.tsx`**:
- Add `endTime: number | null` to the `UpMatch` type (next to `startTime`).
- Introduce a single **grouping timestamp** helper, e.g. `groupTime(m) = (m.finished ? (m.endTime ?? m.startTime) : m.startTime)`.
  Use it in `groupByDay` (the `localDateKey(...)` call) AND for the bucket's display label
  (`dayKey(...)`), replacing the raw `m.startTime` there. Live/scheduled matches keep using `startTime`.
- Keep `new Date(ms)` exactly as-is — it already groups in the **viewer's browser-local timezone**. Do
  not hardcode any timezone and do not move grouping server-side.
- The per-card clock (`fmtClock`) and time-sort within a day can stay on `startTime` — only the day
  BUCKET changes. (Optional: for finished games you may show end time; not required.)

## CONSTRAINTS (scope lock)
- **Touch ONLY:** `backend/routers/esports/pandascore.py`, the slate normalization in
  `backend/routers/esports/slate.py` (and/or `slate_state.py`) where the payload dict is built, and
  `pages/esports.tsx`. Additive only. **Do not** touch the state machine's live/finished/scheduled
  derivation, the team matcher, streams, props, or the UFC work.
- Don't change how live/scheduled matches are grouped — only finished matches switch to end-time.

## VERIFY (against running :3096 / :8096 — do not restart anything)
1. The STEP 1 curl shows `endTime` present on finished matches (and null-safe elsewhere).
2. In the browser on `/esports`, Results groups by the day each match **ended** in your local time; a
   match that ended just after local midnight is filed under the day it ended, and one whose `end_at`
   is null still appears (fell back to start time) — no match disappears or is un-grouped.
3. Report: files changed, the finished/endTime counts + payload size, and the browser check. No commit.
