# TASK (Codex): UEFA Nations League + international friendlies in LegendaryPicks; fix the dev tunnel

Repo `/root/legendarypicks`, branch `dev`. Do not commit or push; leave changes in the working tree
and list every file you changed. Do not rebuild or restart the prod container (prod gets DB changes,
never a rebuild). Do not touch `/root/prediction-market-trading` (the trade desk is a later step).

## Part A: fix the dev tunnel (it died again)

Read first: `/root/.claude/projects/-root/memory/reference_lp_dev_tunnel_and_servers.md` and
`reference_tunnel_dns_nxdomain.md` (a fresh tunnel hostname resolves NXDOMAIN from this box, so do not
judge it by resolving it here). Find why it died this time (logs, unit status), bring it back, and make
it restart on its own if it is not already a supervised service. Report the working URL and how you
verified it from outside this box's DNS.

## Part B: add two soccer competitions

1. **UEFA Nations League** and **international friendlies** (men's senior national teams).
2. Rules that apply here (all in `/root/.claude/projects/-root/memory/`):
   - **Never ESPN** for soccer (`feedback_never_use_espn.md`): FotMob is the soccer source
     (`ingest_fotmob_soccer_logs.py`, `LEAGUES` dict of FotMob league ids).
   - **A new league is a MANIFEST entry BEFORE the ingest** (`reference_lp_league_stat_audit.md`,
     COV-statset).
   - **Coverage contract** (`project_lp_data_coverage_contract.md`): a missing row is `unknown`, an
     ambiguous key misses and never raises.
   - National-team players also play club football: the player spine must not merge a national-team
     appearance onto the wrong club player by name. Read `feedback_the_roster_is_the_crosswalk.md`.
3. Deliver: FotMob league ids found from FotMob itself (not guessed), the league keys, scoreboard /
   fixtures for both so tonight's and upcoming matches appear, player logs ingested for the current
   window, and a registry job (`ingest_registry.py`) with a freshness target, like `fotmob_soccer_logs`.
   Run the relevant tests plus one dry run against the dev DB; apply to dev only. Write what you did and
   what prod would need to `docs/RESULT-nations-league-friendlies-2026-10-06.md`.
