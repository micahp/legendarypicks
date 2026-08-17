# Reasonix Task: v0.7.0 Mock Draft Data Fixes

**Worktree:** `/root/lp-v0613-recut` (branch `recut/v0.6.13`)
**Deadline:** Aug 22, 2026
**Source:** `docs/ROADMAP.md` → "Tasks for Reasonix (v0.7.0 scope — Aug 22 deadline)"

---

## T1. Fix D/ST ADP ingestion — use ESPN published PPR ranks

### Problem
Current `backend/ingest_nfl_adp.py` joins on `espn_id` which is **empty for D/ST** → 0/32 match → derives ADP from fantasy totals (incorrect).

### ESPN Reality (verified)
- `kona_player_info` view with `limit: 20000` returns **32 D/ST** with:
  - `defaultPositionId: 16`
  - `proTeamId: 1-32` (ESPN team IDs)
  - `draftRanksByRankType.PPR.rank` — published PPR rank (234–519)
  - `ownership.percentOwned` — ownership % (0.5%–98.9%)
  - ESPN keys D/ST with **negative IDs**: `-16000 - proTeamId`

### Fix
Update `ingest_nfl_adp.py`:
1. Fetch with `limit: 20000` (no ownership filter)
2. For D/ST (`defaultPositionId == 16`), compute ESPN negative ID: `-16000 - proTeamId`
3. Join on that negative ID to get published PPR rank
4. Store `adp_ppr` column in `nfl_adp` table

### Gates
- `REG-adp-dst` gate (already RED in repo with expected numbers)
- 32/32 D/ST rows with `adp_ppr` populated
- Pool endpoint returns D/ST with real ESPN ADP (DEN 234, SEA 239, etc.)

---

## T2. Expand mock draft pool to full ESPN player universe (11,515 players)

### Problem
Current pool is ~300 players (only drafted/owned). ESPN `kona_player_info` returns **11,515 players** including free agents.

### ESPN Reality (verified)
| Position | Count |
|----------|-------|
| QB | 470 |
| RB | 1,122 |
| WR | 1,791 |
| TE | 882 |
| K | 209 |
| D/ST | 32 |
| **Total** | **~11,515** |

Free agents have `percentOwned = 0` and no draft ranks.

### Fix
1. **`ingest_nfl_adp.py`**: Fetch with `limit: 20000` (no ownership filter). Store ALL players including `percentOwned=0`.
2. **`nfl_mock_draft.py` pool()**: Return full universe (~11,515). UI handles "available" vs "drafted" via filters.
3. Free agents (`percentOwned=0`) render ADP as "—" per `honest-data-ui`.

### Gates
- `nfl_adp` table has ~11,515 rows for 2026
- Pool endpoint `GET /api/nfl/mock-draft/pool?season=2026` returns 11,515 players
- Position breakdown: QB 470, RB 1122, WR 1791, TE 882, K 209, D/ST 32
- Free agents (percentOwned=0) render as "—" in ADP column per honest-data-ui

---

## Worktree Setup

```bash
cd /root/lp-v0613-recut
# Already on branch recut/v0.6.13 with 5 commits:
# da08eea - projection schema + stale test fixture fixes
# cd885fe - pinned artifacts + phase 0-2 findings docs
# 46977fe - ESPN 2026 projection ingest + PPR formula
# 84b17b8 - expose espn_ppr_rank + 2026 projection in pool/detail APIs
# 49eb1c4 - scoped Team Stats migration
```

## Verification

```bash
# Run test suite
/root/legendarypicks/backend/venv/bin/python -m pytest backend/test_*.py -v --tb=short

# Check D/ST ADP
sqlite3 backend/data/picks.dev.db "SELECT team, adp_ppr FROM nfl_adp WHERE position='DEF' AND season=2026 ORDER BY adp_ppr;"

# Check pool size
curl "http://localhost:8096/api/nfl/mock-draft/pool?season=2026" | jq '.players | length'
curl "http://localhost:8096/api/nfl/mock-draft/pool?season=2026" | jq '.players | group_by(.position) | map({position: .[0].position, count: length})'
```

## Constraints
- **Published-first** — do not derive what ESPN publishes
- **Fail-closed** — if ESPN data missing, store NULL not fabricated values
- **Honest UI** — free agents show "—" for ADP, not 999
- **Atomic transactions** — single transaction per ingest
- **No prod mutations** — work only on recut worktree / disposable clone