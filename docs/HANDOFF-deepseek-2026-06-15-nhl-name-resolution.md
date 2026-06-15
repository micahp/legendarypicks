# HANDOFF → DeepSeek (2026-06-15): NHL name resolution — replace the ~10 hardcoded stars

Read AGENTS.md first (guiding principle: roster = ground truth, not a convenient sample; §4 sweep;
build-before-commit; verify render not 200).

## Problem
NHL name→ID resolution is hardcoded to ~6–10 stars (McDavid, Matthews, MacKinnon, Draisaitl,
Pastrnak, Kucherov) because `suggest.svc.nhle.com` (name search) doesn't resolve from this server.
Stats-by-ID via `api-web.nhle.com/v1/player/{id}/landing` works fine; the gap is only the name→ID map.
Result: any NHL player not in the hardcoded list returns nothing. Coverage ≈ 10 of ~700 players.

## Fix: build a COMPLETE name→ID map from full rosters (roster-based standard)
Use a source that WORKS from this server — pick whichever is cleaner:
- **Option A (preferred, keeps your nhle stats path):** `api-web.nhle.com/v1/roster/{TEAM}/current` per
  team → gives every rostered player's name + NHL id. Iterate all 32 teams, build the name→id map,
  persist it (e.g. into `players`/`player_stats` like the other leagues). Then resolution covers the
  whole league and stats still come from the landing endpoint you already use.
- **Option B:** ESPN NHL rosters (confirmed 200 here: `espn.roster('nhl', team)` over
  `espn.team_strength('nhl')`) for name resolution, like NBA/MLB/NFL.
Remove the hardcoded 6-star fallback once the full map works.

## Tests (required)
- Roster-based coverage: % of NHL rostered players that resolve to an id — target ≥95%, no team at 0.
- A NON-star (e.g. a 4th-line forward / backup) resolves and returns stats.
- Build compiles (`docker compose build` → "Compiled successfully") BEFORE committing.
Fresh subprocess for the work. Don't touch scores.tsx / GameCard.tsx (Claude's UI changes are live).

## Deliverable
Per-team coverage before/after in docs/HANDOFF-deepseek-to-claude-other-leagues-2026-06-15.md + ping.
