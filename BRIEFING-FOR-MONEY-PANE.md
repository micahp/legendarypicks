# Briefing for the money pane (from the mls-ncaaf worktree session)

You're the news-engine POC agent. Here's where the relevant context lives in the
mls-ncaaf worktree, in case you want to switch over and branch off.

## The worktree
- Path: /root/lp-league-mls-ncaaf  (branch: feat/league-mls-ncaaf, off dev 34401d7)
- Servers: Next :3101 / backend :8101 (replaced leagues-cup), own copy DB:
  /root/lp-league-mls-ncaaf/backend/data/picks.dev.db
- node_modules + backend/venv are symlinks to /root/legendarypicks — NEVER
  npm/npx/yarn from the worktree (wipes the shared install, kills :3096).

## Docs that matter
- HANDOFF-2026-08-06.md (worktree root) — the current state + ordered plan.
  Recent progress this session: roster/identity spine DONE (mls 956 players,
  ncaaf 15,029), MLS logs 14,543/15,361 resolved (94.7%), mls team-results
  backfill WIRED + RUN (507/510 games, draws → result='D'), reconcile →
  coverage "partial" (3 games still missing, 403 blips).
- docs/PROVIDER-AUDIT-2026-08-06.md — full provider audit (MLS/NCAAF/CONCACAF/
  tennis). Key: NCAAF log rows should move to CFBD (~1-6 calls/season vs 888
  ESPN summaries).
- docs/PROVIDER-AUDIT-VERIFY-2026-08-06.md — live verification of the 5
  previously-unverified items (Underdog tennis rows exist but 0 active lines;
  Kalshi URL shapes work; FotMob men's CCC = 297; tennis-data.co.uk live on
  http://; concacaf has a CMS content API, no scores endpoint).
- docs/PLAN-league-mls-ncaaf.md — waves, measured data, tournament tracking
  decision (tournament games under their OWN league key: lcup/ccc/campeones).

## CFBD API key (the pending NCAAF decision)
- Key saved as CFBD_API_KEY in ~/.hermes/.env (not in any git tree).
- Free tier confirmed: 1,000 calls/month, historical data + core endpoints,
  no credit card. "Use the free key for docs, sample requests, and small
  exporter pulls before you decide what the season workflow needs."
- Open decision: build the NCAAF log ingest on CFBD (99% request cut) or stay
  ESPN for consistency with MLS. Handoff recommends CFBD, flags it as Micah's
  call. If you take this, verify key availability and the payload shape first.

## ESPN budget (espn-request-budget skill — read it before any ESPN call)
- site.api.espn.com is WALLED from this box (403). Use site.web.api.espn.com
  and sports.core.api.espn.com via the shared paced_http client (espn_client).
- Limit is a COUNT per host (~100), not a rate. Disk cache makes re-runs free.
- Your sketch already fixed its urllib → paced_http usage. Keep that.
