# Phase 3 findings — ESPN 2026 projection/rank ingest (clone only)

Date: 2026-07-31. Target: `/root/lp-v0613-recut/backend/data/rehearsal-v0.6.13.db` (disposable prod clone).
No production DB writes. Only the clone was touched.

## Files added (worktree `recut/v0.6.13`)
- `backend/ppr_scoring.py` — LP PPR formula module (QB / RB-WR-TE / K / D/ST + PA tier).
- `backend/ingest_nfl_projections.py` — deterministic, fail-closed ingest from the PINNED snapshot.
- `backend/test_nfl_ppr_scoring.py` — 13 named-position fixture tests (REG-projection-formula).

## Stat IDs pinned empirically (measured, cross-checked)
- From snapshot + community map (cwendt94/espn-api constant.py) + live 2025 payloads:
  games=210, pass_att=0, pass_cmp=1, pass_yds=3, pass_td=4, INT=20 (NOT 15 — 15 is 40+yd TD bonus),
  rush_att=23, rush_yds=24, rush_td=25, rec=53, targets=58, rec_yds=42, rec_td=43,
  fumbles=68, fumbles_lost=72; K: fgm_0_39=80, fgm_40_49=77, fgm_50+=74, fg_made=83, fg_att=84,
  fg_missed=85, xp_made=86, xp_att=87 (made+missed=att verified per range on real K data);
  D/ST: sack=99, INT=95, FR=96, TD=94, safety=98, PA=120, yds=127.
- 32/32 D/ST entities in the snapshot carry projections.

## Bugs caught by the gates (and fixed)
1. **JSON string keys** — ESPN stat maps have STRING keys ("42"); lookups with int keys returned
   None → every projection stored 0.0. Fixed with `normalize_stats()`; regression test added.
2. **IDP/P punters computed as QB** — `_position_of()` defaulted unmapped ESPN position IDs to
   QB, so LB/CB/S/DE/DT and P rows got a QB formula over empty stats → 0.0. Fixed: position
   comes from `players.position`; non-draftable positions store NULL. Regression test added.
3. **Return specialists** — Cowing/Covey/Dallas etc. have ONLY return-yard stat keys (101-119);
   our formula scores none → stored 0.0, which would render as a fabricated zero. Fixed: formula
   returns None when no input stat is present. Regression test added.

## Gates (all measured on the clone)
| Gate | Result |
|---|---|
| REG-projection-coverage | pool 285/300 with projection (>=283); 32/32 D/ST; 15 honest nulls; **0 zeros** |
| REG-rank-source | CeeDee Lamb=9, Justin Jefferson=11. Drake London=14, Rashee Rice=16 — the 07-29 plan's 13/14 are stale; live feed TODAY also says 14/16 (ranks move daily in draft season). |
| REG-projection-formula | Jefferson 292.798, Allen 363.627 (independent hand-calcs) pass; 13 tests green |
| REG-projection-source | stored payload_checksum bbae5344… == pinned snapshot sha256 |
| REG-projection-null | missing projections are NULL, never 0 (13 pool nulls + 15 incl. return specialists) |

## Still open in Phase 3
- Expose `espn_ppr_rank` + `proj_pts` in `pool()` (backend/routers/nfl_mock_draft.py) — sort default by RK.
- Expose rank + `projection_2026` in `player_detail()`.
- Re-run the full backend suite.
