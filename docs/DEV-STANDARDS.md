# Legendary Picks — Development Standards

Non-negotiable. Applies to every change (human or agent). Cite this in task specs; enforce it in review.
Performance and correctness are part of "done" — not a follow-up after someone notices it's slow.

**How work gets reviewed and merged:** `docs/PROCESS-delegated-work-review.md`, and the
agent-facing `.claude/skills/falsify-before-merge`. Load the skill before merging any branch,
before reporting DONE, and before writing acceptance criteria into a task spec.

## Performance (the one that keeps biting us)

1. **A list/board must not download more than it shows.** A list of N items ships N lightweight rows
   (the fields actually rendered), NOT each item's full detail. Detail loads on demand.
   - Concrete miss we shipped once: the Slate tab pulled the *fully-nested* slate — **1.1 MB / 15k
     props / 2.7 s** — just to show a games list. The fix was a `summary` endpoint (**4 KB / 0.1 s**)
     plus per-game props fetched on open. ~270× smaller. That should have been the design from the start.

2. **Initial-render payload budget: aim < 50 KB and < 300 ms.** If a page's first fetch is bigger or
   slower, summarize/paginate and lazy-load the rest. No exceptions for "it works."

3. **Fetch detail on interaction, not in bulk up front.** Expandable/nested content (a game's props, a
   player's history) is fetched when the user opens it — never prefetched for every row.

4. **Measure before you ship.** For any list/board endpoint, record payload size + time
   (`curl -s -o /dev/null -w '%{size_download} %{time_total}' <url>`) and put it in the report. If the
   number is bad, it's not done.

5. **No N+1 and no unbounded nesting in list endpoints.** Aggregate (a `COUNT`) instead of returning
   every child row to compute a count client-side.

## Verification

6. **HTTP 200 is not "it works."** Verify the real render — content present, no console/page errors, no
   horizontal overflow at 390 px, and it *feels* fast (perceived load, not just status code).

7. **Don't touch shared dev servers.** A preview frontend (:3096) + backend (:8096) are managed
   externally. Do not start/kill/restart them; verify against them. Spawning duplicates corrupts the
   tunnel.

## Data must not silently drop off

11. **Every live environment gets its own continuous data feed + freshness monitoring.** Prod once went
    **8 days stale** because the ingest only fed dev and nothing watched prod. A pipeline that "runs on
    a timer" is not enough — timers die, deploys forget, and silence hides it.
    - `monitor_props_freshness.py` + `legendarypicks-props-freshness.timer` (30 min) check each
      provider in each env and fail loudly when its provider-specific threshold is exceeded.
      The monitor deliberately never starts an ingest; recovery stays an operator decision.
    - **PROD DEPLOY CHECKLIST (do not skip):**
      1. Keep the **prod-targeted registry runner** service/timer pointed at the prod DB and
         backend `:8100`, staggered behind `legendarypicks-props.service`.
      2. **Keep `prod` in `monitor_props_freshness.py` `ENVS`** so prod staleness is visible from
         the moment its feed is live.
    - Verify after deploy: `curl :8100/api/props?limit=1` shows a capture within the last hour.

## Cleanliness

8. **Match the surrounding code** — the app's dark/emerald system, `tabular-nums`, the app font (not
   monospace), existing components (reuse `PropChart`, `GameProps`, etc. — don't rebuild).
9. **Additive and reversible** — new query params/fields default off so existing callers are unaffected.
10. **No dead code left behind** when replacing a view; remove the retired path.
