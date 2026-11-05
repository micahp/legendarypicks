# Injury reconstruction 2025, v1 (research only)

Status: source audit and a one-game check are done. A rule-based gold-set extractor (v1) was evaluated once on a 77-item test split; its OUT precision is 88.9%, below the 98% gate, so no automatic exclusion is enabled. See `EXTRACTOR-RESULTS.md`. Nothing here feeds the 2025 realism run, which keeps its injury-excluded inputs.

## Question

Can the 2025 injury designations used by the replay be recovered from sources that were verifiably public before each game's cutoff? Scaling to all 272 games waits until coverage and disagreement are measured on a sample.

## Protocol v1

- **Cutoff.** Kickoff minus 90 minutes, both in UTC. The 49ers' own report says "final decisions on gameday availability will be announced 90 minutes prior to kickoff." Kickoff comes from nflverse `gametime`, which is Eastern. SF at LA, week 5, kicks off 2025-10-02 20:15 ET, so the cutoff is 2025-10-02 22:45 UTC.
- **Publication time and retrieval time are separate.** The body's date line is the publisher's claim. It shows no time zone; the Pacific time zone is inferred from the team's locale. The Wayback capture timestamp is the retrieval time. A capture shows that the content existed at that moment, so a capture before the cutoff is evidence that the content was public before the cutoff, even if the page was edited later.
- **Evidence tiers** (as in `parked.md`):
  - Tier 1: an archived capture before the cutoff whose text contains the designation, and whose capture content matches the record. Only tier 1 may enter the cutoff-safe injury-aware replay.
  - Tier 2: dated but not verified. A date line or a live page with no capture before the cutoff, or a manually maintained source with no capture time. Corroboration only.
  - Tier 3: retrospective only, such as in-game recaps or final datasets. Never a pregame input.
- **Identity.** Each record joins to `gsis_id` in nflverse `injuries_2025` (week, team, name). Team codes use nflverse spelling at the boundary (`LA`, `WAS`); the team sites are mapped from that.
- **Pregame vs. in-game.** Pregame records are reports and inactives published before the cutoff. In-game recaps are labels for later realism tests and are never pregame inputs for the same game.

## Sources

1. **Football Sheets (2025 injury archive): not accessible without an account.** The Substack post (2025-09-12, "New NFL injury report data now on Knack") describes all 32 teams on one page, "view full injury reports from previous weeks" through a filter, and day-by-day practice data. It says the page is "manually updated, so it will not necessarily be up-to-date." It gives no timestamps, only dates, and no archive by date. The public site (`footballsheets.com`) renders a login form only when loaded in headless Chromium. The injury pages are behind that login. No credentials were used and no login was attempted. Even with access, this source is at most tier 2 for pregame use: manual edits, no capture time.
2. **Team injury articles (49ers.com, therams.com, and the other 30 team sites).** Live pages give date lines and full tables. The archive matters: Wayback captures can show what a page said before the cutoff. The Wayback index went offline under parallel queries (503 and 504 responses), so the team-by-team pulls run sequentially with retries.
3. **NFL.com weekly injury pages.** The Wayback query for `nfl.com/injuries/league/2025/reg5` returned no captures. Earlier notes record captures for 2025 weeks 0, 1 and 6 only; week 6 is pre-cutoff but partial (15 of 164 designations).
4. **RotoWire.** The injury report page returns 200 from this box. Dated news items are not yet tested against archive captures.

## Week 5 check: SF at LA (2025-10-02, kickoff 20:15 ET)

Both reports are tier 1. Each has a Wayback capture before the cutoff (cutoff 2025-10-02 22:45 UTC):

| Team | Page | Date line | Capture (UTC) | Records |
|---|---|---|---|---|
| LA | therams.com injury report | Oct 01, 2025 at 02:19 PM | 2025-10-02 00:34:55 | Higbee (hip) Doubtful; Havenstein (ankle) Doubtful, both DNP Mon to Wed. Full table in the capture. |
| SF | 49ers.com injury report ahead of #SFvsLAR | Oct 01, 2025 at 01:50 PM | 2025-10-01 22:52:50 | Purdy (toe), Pearsall (knee), Jennings (ankle, rib), Watkins (calf), Beal (ankle) Out; C.J. West (thumb) Questionable; Mac Jones named to start. |

Agreement with nflverse `injuries_2025`: all 8 designations match in status and body part. Identity: all 8 join to a GSIS id.

Completeness caveats:
- The 49ers capture has only the Wednesday game-status list in prose. The live page also shows a practice table, but the capture does not contain it. So the SF players with no designation (for example Jones, Gross-Matos, Green, Williams, Winters) are not verified before the cutoff from that capture. This matters for any rule that treats a missing report as healthy: "not on the report" is not verified as "no designation."
- The Rams team page lists practice-only entries (Avila, Parkinson, Kinchens, shoulder and ankle) with no game status. nflverse leaves those blank. That is a definitional difference, not an error: the team page reports practice limits, nflverse reports game designations plus practice status.
- Sportskeeda says Jones was on the report with a knee injury. The 49ers table has the same entry with no designation, so there is no conflict on status.
- The Rams report is also listed as "Doubtful" by nflverse and matches, but a later AP report says the Rams placed Higbee and Havenstein on injured reserve. That is post-game information. It does not enter this record.

Evidence rows are in `evidence-v1.csv` in this folder.

## Open items

- Finish the sequential Wayback pulls for all 32 team injury article lists, 2025-08-15 to 2026-01-15. Output: `scratchpad/injury-recon/cdx/`. Pulls are still in progress.
- Choose 15 to 20 games and measure coverage per game: designations recovered before the cutoff, identities matched, Out and Doubtful exclusions recovered, starter changes recovered, unresolved.
- RotoWire dated news: test whether archived captures exist before the cutoff for the SF and LA week 5 items.
- Football Sheets: needs a user-provided account or export before it can be assessed. Without access, it is excluded from the sample.
- The hindsight-only arm and the uncertainty fallback are not built yet. Both wait for the coverage measurement.
