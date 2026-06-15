# HANDOFF → DeepSeek (2026-06-15): fix stats coverage gaps (investigated)

Measured from the live DB. Read AGENTS.md §6–9 first (ops rules). Don't touch DayStrip.tsx /
PlayerSearch (my landed fixes). Fresh subprocess per item; tests must pass.

## Findings (from props→players→player_stats join)
- **MLB: 92/120 prop-players covered (76%) — 28 missing.** Two causes below.
- NBA/NFL/NHL: 0 current props (off-season) — coverage N/A now, but see #3/#4.

## 1. [P1] Fix the NAME-JOIN fragility (recovers most of the 28 missing)
`player_stats` is matched to players by **name** (it has `player_name`, no stable id). Misses include
**Bobby Witt Jr.** — a star who HAS Statcast data → this is a name-format mismatch (suffix "Jr.",
punctuation, accents), not absent data. Fix one of:
- (preferred) add `player_id` (or `espn_id`/`statcast_id`) to `player_stats` and join on that, OR
- normalize names on BOTH write (ingest) and read (handler): lowercase, strip punctuation + suffixes
  (jr/sr/ii/iii), strip accents. 
Verify: after the fix, `bobby witt jr.`, `francisco alvarez`, etc. resolve to a stats row.

## 2. [P1] MLB batting/two-way + pitcher completeness
Only **5 pitching rows / 87 batting**. Shohei Ohtani returns `batting:null` (ingested pitching-only).
`ingest_statcast.py` must:
- pull **batting for ALL position players** that have props (28 missing are mostly pitchers + name
  mismatches + a few un-ingested batters), and
- pull **both batting AND pitching for two-way players** (Ohtani).
Target: ~100% of MLB prop-players have at least one stats row; Ohtani has both batting + pitching.

## 3. [P2] NBA stat_type mislabel
NBA rows are stored with `stat_type='batting'` (baseball copy-paste). Relabel to a proper NBA type
(e.g. `'season'` or `'nba'`) in `ingest_hoopR.py` + anywhere the handler filters on it. Cosmetic but
wrong; fix before NBA props go live.

## 4. [P3] NHL breadth (defer-ok)
Only 10 stars ingested. Broaden `ingest_nhl.py` (ESPN rosters) so NHL prop-players resolve once NHL
props appear. Lower priority (no NHL props right now).

## Verification (required, paste results)
Re-run the coverage check after fixes:
```python
# props->players name vs player_stats name, per league; report covered/total %
```
Target: MLB ≥ ~95%. Confirm Bobby Witt Jr. + Ohtani(batting+pitching) resolve. NBA stat_type no
longer 'batting'.

## Deliverable
Update docs/HANDOFF-deepseek-to-claude-other-leagues-2026-06-15.md with before/after coverage % + ping.

---
## REVISED STANDARD (2026-06-15): coverage = full TEAM ROSTERS, not prop-players
Measured roster-based: **MLB 92/780 (11%)** — whole teams at 0/26 (SD, ATL, MIL, NYY, STL, CHW, CLE,
CHC...). The prop-based 76% was misleading. New target: **every player on every ESPN roster has a
stats row.** Denominator = `espn.roster(league, team)` over all `espn.team_strength(league)` teams.

### Do this
- **Ingest the FULL roster universe**, not just prop-players. Iterate all teams' ESPN rosters; ensure
  every rostered player gets a stats row (batting for position players, pitching for pitchers, BOTH for
  two-way like Ohtani).
- **Efficiency:** do NOT make ~780 per-player Statcast calls. Use pybaseball bulk: `statcast(start,end)`
  pulls all pitches league-wide for a window in one go → group by batter/pitcher → aggregate per player.
  One bulk pull covers the whole league. (Same idea for NBA/NFL: the hoopR/nfl_data_py season tables are
  already league-wide — ingest all rows, not a per-player subset.)
- Coverage report = **per team**: `covered/roster_size` for each team, plus league total. Target ≥95%.

### Verify
Re-run roster-based coverage (espn rosters as denominator): MLB ≥95%, no team at 0, Bobby Witt Jr. +
Ohtani(batting+pitching) present. Paste per-team before/after.
