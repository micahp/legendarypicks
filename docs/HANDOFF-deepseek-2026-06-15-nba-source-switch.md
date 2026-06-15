# HANDOFF → DeepSeek (2026-06-15): switch NBA data source OFF nba_api

## Do this AFTER you commit/land your current changes (don't lose in-progress work).

## Why (verified from this server, 5.252.52.108)
- `stats.nba.com` (what `nba_api` uses) returns **000 — blocked**. It blocks **datacenter IP ranges**,
  NOT geography: this box is already **US (St. Louis, Contabo)** and still blocked. So a US VPS,
  another VPS, or free public proxies (all datacenter IPs) will NOT fix it. Only residential proxies
  bypass it, and those cost money. → **Abandon `stats.nba.com`/`nba_api` entirely.**
- Verified reachable (200) from this box: **ESPN API** (already integrated via `espn_client.py`) and
  **hoopR / sportsdataverse data releases on GitHub** (static parquet/CSV — never IP-blocked).

## Task: make NBA use the SAME pattern as NFL (ESPN live + published data releases)
1. **Remove the `nba_api` path** from `_get_nba_stats` in `sports_service.py` (and from requirements
   if added). Don't call `stats.nba.com`.
2. **Basic NBA stats → ESPN** (`espn_client.py`): scoreboard, rosters, box scores → per-player lines
   (pts/reb/ast/etc). ESPN endpoints confirmed 200:
   - `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard`
   - `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{id}/roster`
3. **Advanced NBA metrics (TS%, USG%, etc.) → hoopR/sportsdataverse published releases** (GitHub
   parquet), the direct analog to how NFL uses `nfl_data_py`/nflverse. Download the release files;
   don't scrape live. (Repo: `sportsdataverse/hoopR-data`.)
4. Same persistence discipline as everything else: write stats to the DB (a `player_stats` table),
   don't rely on the in-memory `_stats_cache` (it's wiped on every redeploy — separate audit item).
5. Tests (per your league-buildout rules): name-resolution coverage for Bovada NBA players, a sample
   stat fetch, one end-to-end prop settlement. Use a fresh subprocess context.

## Deliverable
Update `_get_nba_stats` + note results in `docs/HANDOFF-deepseek-to-claude-other-leagues-2026-06-15.md`.
Ping when done.
