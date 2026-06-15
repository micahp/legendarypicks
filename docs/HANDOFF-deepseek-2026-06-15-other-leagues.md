# HANDOFF → DeepSeek (2026-06-15): build out the OTHER leagues + tests

## Where the product is now (already shipped today)
Prop analytics product. Already built: Bovada open API = prop LINES; **MLB stats via pybaseball/
Statcast** (with name-resolution fix so all Bovada MLB players resolve); 5-tab architecture
(Lines, Slate, Performance, Matchups, Model); advanced-analytics-by-sport doc. The **Performance**
tab is the per-player stats dashboard that each league's stat source feeds.

## Task: replicate the MLB integration for the remaining leagues
Match the pattern MLB already established (stat source → resolve Bovada player names → real stats in
Performance tab → settle props). Per league:
- **NFL** → `nfl_data_py` (Python port of nflverse/nflfastR): weekly player stats, EPA, usage,
  snap share, targets/carries. Deepest free source — this is the priority league.
- **NBA** → `nba_api` (stats.nba.com) or `hoopR`: player box scores + advanced (TS%, usage rate,
  minutes). Resolve Bovada NBA player names.
- **NHL** → NHL stats API: player box (shots, points, TOI) + Corsi/Fenwick where available.
- (NCAA/UFL/etc. only if Bovada carries lines and a clean stat source exists — otherwise skip.)
For each: the SAME name-resolution discipline as MLB (Bovada name ↔ stat-source ID), and wire the
stats into the existing Performance tab + prop settlement.

## REQUIRED: do a few tests per league (don't ship blind)
- **Name resolution coverage**: assert ~all current Bovada players for that league resolve to a real
  stat-source ID (log any misses — this was the MLB bug class).
- **Stat fetch**: pull one known player's recent games; assert non-empty, sane values.
- **Prop settlement**: settle one real prop end-to-end (line → actual stat → hit/miss) and verify.
Keep tests in the repo's test layout; they must pass before considering a league done.

## REQUIRED workflow: isolate each league in its OWN fresh subprocess context
Do NOT build all leagues in one long-running context — it poisons/hallucinates as it fills. Instead,
spawn a **fresh headless subprocess per league** (clean context), e.g. one `claude -p "<self-
contained league task>"` invocation per league (NFL, then NBA, then NHL), each given only what it
needs from this doc. Review each subprocess's diff + test output in the MAIN context before merging.
This keeps your orchestration context small and the per-league work uncontaminated.

## Deliverable
Per league: integration + passing tests + a short note in
`docs/HANDOFF-deepseek-to-claude-other-leagues-2026-06-15.md` (what resolved, test results, any
unresolved players/sources). Ping me when NFL is done (don't wait for all three).
