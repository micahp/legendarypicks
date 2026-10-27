# Handoff: identity duplicates, NBA stakes and box scores (2026-10-27)

Scope: dev only. Nothing on prod was written. Prod was read through `mode=ro` connections only.
Everything below is committed on dev. Nothing new has been pushed in this session.

Read first: section 4. One decision is pending, and it changes prod's behaviour at the daily roster run.

## 1. Commits on dev (in order)

| Commit | What |
|---|---|
| `e4c64ee9` | NFL schedule ingest every 4 hours, not 12. The registry job has no `databases` key, so the prod run also goes to 4 hours. Revisit for prod. |
| `0cb44a3a` | NBA stakes and standings on dev. A fast-forward of the NBA slice only. NBA is in `SUPPORTED`. `nba_teams` seeded for 2026 and 2027. |
| `01dc4a5b` | nba.com player box scores (`ingest_nba_boxscores.py`). Not scheduled. |
| `d7810fc0` | `spine_merge`: catches publisher double listings and unlinked keys. |
| `cc69fff2` | `/api/health` reports `identity_blockers` and `identity_checked_at`. |
| `cedca71d` | `spine_merge`: Leagues Cup keys bind to the home-league player, and cross-league skips are reported. |

Not merged: `feat/nba-standings-stakes` has 116 commits that dev doesn't have. They are the NFL E0 to E3 sequence research, blocked-kick and two-point work, and evidence files. Only the NBA files were brought over.

Earlier in the session: `a12df86a` was pushed to `origin/feat/nba-standings-stakes`, at your request.

## 2. Dev DB changes made today

- `nba_teams` seeded for 2026 and 2027, with the source label citing nba.com's 2026-27 division pages.
- `nba_player_boxes_nbacom`: 43 final regular-season games, 1,489 player rows. Team totals match the schedule score for all 43.
- Seven MLS merges applied from `spine_merge`. The backup from that apply has been deleted, as requested.
- One roster merge applied: 32596 (Miami David Ruiz) into 62630 (Red Bull New York). Two binds applied: mlssoccer 540256 to 33169 (Zambrano), and fotmob 1738398 to 62527 (Thayllon, MLS).
- Backup still on disk: `backend/data/picks.dev.db.pre-spine-merge-roster-20261026.bak` (3.3 GB). Delete it when OK.

## 3. Identity state

| Case | Dev | Prod (read only, not changed) |
|---|---|---|
| Ruiz | Merged into 62630 | 58681 holds fotmob 1348286 and mlssoccer 541416. fotmob 1787871 unbound. |
| Zambrano | 540256 bound to 33169 | 32334 holds mlssoccer 315191673. 540256 unbound. |
| Thayllon (MLS) | 1738398 bound to 62527 | 71244 holds fotmob 1259117 and mlssoccer 315209968. 1738398 unbound. |
| Thayllon (Leagues Cup) | 1738398 unbound. Dry run plans a bind to 62527, not applied. | Unbound. |
| The seven earlier MLS merges | Applied on dev | Not checked. Assume the same duplicates exist on prod until verified. |

Why the roster job still reports 4 conflicts: `published_roster.publish_identities` refuses any player who holds two keys from one publisher. The check is the final conflict test, which compares `keys_by_player_source` for each player. The four are Thayllon (MLS), Thayllon (Leagues Cup), Ruiz and Zambrano. The health count will show 4 until the pending decision in section 4 is made.

Why `spine_merge` missed them, and what was changed:
1. Two rows with the same name, both carrying ids, were skipped as two people. Fixed in `d7810fc0`, which now checks the roster.
2. A publisher key with no player row was never considered. Fixed in `d7810fc0`.
3. The Leagues Cup league guard skipped keys silently. Fixed in `cedca71d`.

These fixes are in `spine_merge` only. The roster layer still refuses the double listings.

## 4. Pending decision: reviewed pairs in `published_roster`

Proposal: a reviewed list of publisher key pairs that are one person, written into `published_roster.py` beside `REVIEWED_ALIASES`, each with its evidence. `publish_identities` would treat a listed pair as one person. Every other conflict stays a refusal. This clears the four conflicts and drops the health count to 0.

Pairs and evidence:
- **Thayllon, LAFC:** fotmob 1259117 and fotmob 1738398. LAFC's release names Thayllon Roberth, a Brazilian forward on loan from Avai, born in Paco do Lumiar. There is one LAFC Thayllon. The fotmob page itself was not checked.
- **David Ruiz, Red Bull New York:** fotmob 1348286, fotmob 1787871 and mlssoccer 541416. A 22-year-old Honduran midfielder, born in Miami, loaned from Inter Miami to New York through 2026.
- **Marcos Zambrano, New England:** mlssoccer 315191673 and mlssoccer 540256. Loaned from Real Salt Lake in March 2026, with the permanent option exercised in July 2026. Also a separate row, Marcos Zambrano-Delgado (32939), which is a different player and not touched.

Prod effect: prod has the same pairs in the same unresolved state. The daily roster job runs the working tree against prod, so shipping this change writes bindings to prod at its next run. That is the reason it is held.

Options:
- (a) Ship it to both DBs. Prod is written at the next daily run.
- (b) Gate the list to dev only. This needs a flag, which I'd avoid.
- (c) Hold until prod is in scope. Before any prod run, dry-run the job against a copy of prod and check its output.

## 5. Other open items

- Apply the planned dev bind: Leagues Cup fotmob 1738398 to 62527. One reversible write.
- Delete the leftover backup in section 2 when OK.
- **NBA box scores:** not scheduled, which needs a scheduler OK. Not yet wired into prop settlement, so 2026-27 props still won't settle from these rows. The SportsDataverse 2026-27 box score file still returns 404 (last checked 2026-10-26).
- **Grade correction for game 0022600092:** the grade row stores PHX 82. nba.com has 83. The winner is right. The point, spread and total errors on G2 and G3 are off by one. Grades are meant to be immutable, so this needs a decision: a correction record is the usual choice.
- **NFL 4-hour cadence:** this also applies to the prod run. Confirm it's wanted for prod.
- **Prod NBA:** `nba_teams` is not seeded on prod, and prod's 2026-27 schedule finals are not refreshed. Waiting on the dev-first decision.
- **Dev server:** `lp-dev-backend-8096.service` runs uvicorn with `--reload`, and it already serves the new health fields. The dev server was not restarted. `legendarypicks-dev-frontend.service` (port 3096) was not touched.
- **Other uncommitted work in the dev checkout is not ours**, and was left alone: `.claude/skills/measurement-is-a-claim/SKILL.md`, `components/Leagues/types.ts`, `pages/leagues/[league].tsx`, `research/nhl/prospective-2026-27/forecasts.jsonl`, plus untracked `backend/data/nba-model*`, `backend/data/nba-model-source/` and `docs/research/nba-almanac-2026-27.pdf`.

## 6. Verification

- Dry run, dev: `cd backend && ./venv/bin/python spine_merge.py --db data/picks.dev.db`. Expect 0 merges and one bind (Leagues Cup 1738398) until that bind is applied.
- Tests: `./venv/bin/python -m pytest -q test_spine_merge.py test_identity_status.py test_ingest_nba_boxscores.py` (39 + 3 + 4 pass as of this session).
- Health: `curl http://127.0.0.1:8096/api/health`.
- Prod reads: open `backend/data/picks.db` with `mode=ro` only.

## 7. Key code

- `published_roster.py`: `publish_identities` (final conflict check), `NO_MINT_LEAGUES`, `REVIEWED_ALIASES`.
- `spine_merge.py`: `build_plan`, `_roster_double_groups`, `_unbound_binds`, `apply_plan`.
- `ingest_published_rosters.py`: prints `identity_blockers=N` on applied runs.
- `identity_status.py` and `routers/games/misc.py`: health fields.
- `ingest_nba_boxscores.py`: nba.com box scores, with its test.
- `stakes.py` and `nba_standings_store.py`: NBA stakes, read from the database.

## 8. Process note

The timers run the working tree against prod. Anything committed to dev takes effect in prod's jobs at their next run. Check the prod effect of any registry or ingest change before committing it.
