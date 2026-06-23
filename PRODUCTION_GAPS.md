# Production Gaps — Legendary Picks
**Date:** 2026-06-22
**Found by:** live system inspection

---

## Active Failure: Bovada ingest broken

**Status: FAILING — every run for an unknown duration**

The bovada cron outputs `FAIL ingest: HTTP Error 500: Internal Server Error` on every run. Root cause tracked down:

1. The cron script calls `POST http://localhost:8000/api/ingest/bovada`
2. That endpoint returns 404 — it does not exist
3. The actual ingest endpoint is `POST /api/props/ingest`
4. The script has the wrong URL path

Additionally, there are TWO backend instances running:
- **Port 8000** (PID 1279934): Native Python process, Legendary Picks Sports API v2.0.0
- **Port 8100** (PID 4831): Docker container from docker-compose, loopback-bound

The Docker container maps 127.0.0.1:8100→:8000. From the host, both :8000 and :8100 respond, but they may have different code versions or routes.

**Impact:** No new prop data entering the system. The props page still shows data from 6/13-6/20 because the scraper fetches Bovada data successfully (262 props on the last run) but cannot POST it to the API. Every run is a silent no-op — data is scraped and discarded.

**Fix:** Change the cron script endpoint from `/api/ingest/bovada` to `/api/props/ingest`, or fix the 500 error if the endpoint exists but crashes on the payload format.

---

## Gap 1: No monitoring — silent failure for unknown duration

The pipeline runs show ✅ for ingest, link, settle, and coverage on every run. But the Bovada ingest has been failing independently — and nobody knew. There is no alerting, no health dashboard, no "last successful data ingest" timestamp visible anywhere.

**What's needed:** 
- Health check that validates "data freshness" — not just "API responds 200"
- Alert when no new props ingested in > 2 hours
- The Cron job should exit non-zero on failure and surface the error

---

## Gap 2: Two backend instances — version drift risk

Two Legendary Picks API instances on the same host:
- Native Python on :8000 (possibly started by systemd or manual `python main.py`)
- Docker container on :8100 → :8000 (from docker-compose)

Which one is canonical? If they run different code versions, the API behavior could differ between direct calls and nginx-proxied calls. The Docker one may be stale (last built 7+ days ago per `docker ps` uptime).

**Fix:** Kill the native instance and rely on Docker only, or document why both exist and ensure they stay in sync.

---

## Gap 3: No database backups

picks.db is bind-mounted from the host and contains all predictions, props, scores, and player data. There is no backup cron, no WAL checkpoint, no offsite copy. If the disk fails or the file gets corrupted, all historical prediction accuracy data is gone.

**Fix:** Nightly `sqlite3 .backup` to a timestamped file, rsync'd off-host. SQLite supports this trivially.

---

## Gap 4: No test suite for backend data pipeline

The pipeline scripts (ingest, link, settle, coverage) handle real money-adjacent data (prop lines, prediction settlement). They have zero automated tests. Correctness is verified by manual inspection of the coverage report.

**What's needed:** At minimum, integration tests that:
- Feed known input to the settlement engine and verify correct/incorrect flags
- Verify the link_games step doesn't silently drop rows
- Verify coverage report math against a known dataset

---

## Gap 5: Python 3.8 EOL

The backend venv is Python 3.8, which reached end-of-life in October 2024. No security patches. This is a shared host running 8+ sites — a vulnerability in an old Python version affects everything.

**Fix:** Upgrade to Python 3.11 or 3.12. Pip freeze + rebuild venv.

---

## Gap 6: UI issues found during audit

| # | Issue | Impact |
|---|-------|--------|
| 1 | Game cards on /scores use onclick divs, not `<a>` tags | Can't Cmd+click to open in new tab. Keyboard users can't navigate. Accessibility fail. |
| 2 | ESPN game ID "401815621" shown in predictions table instead of team names | Users see opaque numbers instead of readable game identifiers |
| 3 | Duplicate entries in /props list | Same game appears twice, likely from multiple data sources not deduped |
| 4 | "Call of Duty" in league filter but no data | False affordance — looks like a league but shows nothing |

---

## Summary

| # | Gap | Severity | Status |
|---|-----|----------|--------|
| 1 | Bovada ingest failing silently | CRITICAL | Active failure — no new props data |
| 2 | No monitoring/alerting | HIGH | Why #1 went unnoticed |
| 3 | Two backend instances | MEDIUM | Version drift risk |
| 4 | No database backups | MEDIUM | Data loss risk |
| 5 | No test suite | MEDIUM | Regression risk |
| 6 | Python 3.8 EOL | LOW | Security risk, but host-isolated |
| 7 | onclick divs instead of anchors | LOW | Accessibility |
| 8 | Game ID leakage in UI | LOW | UX |

**The production readiness score adjusts from 8/10 to 7/10** when accounting for the active Bovada failure. The app still runs and serves users, but its data freshness is degrading silently.
