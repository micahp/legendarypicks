TASK: find out whether RotoWire's soccer stats feed gives PER-MATCH player rows.

This is a lead, not a conclusion. One measurement decides whether it solves the
settlement problem or is just better season aggregates.

WHY IT MATTERS
  `passes_attempted` cannot be answered by anything we currently store:
    - FotMob publishes ACCURATE passes only. Mapping it onto attempted is
      explicitly refused in ingest_fotmob_soccer_logs.py:54, and I violated that
      today and reverted it -- 0 of 222 mls props have the named statistic.
    - ESPN's core api HAS `totalpasses` (_CORE_TARGET_STATS in
      ingest_soccer_logs.py) but `--deep` has never been run for these leagues:
      0 stored rows carry it in mls, lcup, ligamx or wc.
    - The RotoWire PICKS RELAY does not carry it either. Its `hitRates` block is
      a hit/miss bitstring against RotoWire's own line ("01010000011110110010")
      plus a projection. No actual value, no dates, and anchored to one line, so
      it cannot grade a prop priced at a different number.

  And ESPN is the wrong answer regardless: settlement should stop spending the
  budget the live site spends.

THE ENDPOINT (found 2026-08-26, undocumented, read off the page's own JS)

  https://www.rotowire.com/soccer/tables/player-stats.php
    ?season=2026&position=A&start=1&end=38
    &EPL=0&FRAN=0&LIGA=0&SERI=0&BUND=0&MLS=1&NWSL=0&LMX=0
    &ENG_CH=0&UCL=0&WOC=0&UEL=0&EURO=0&FAC=0&WWC=0

  Send a Referer of https://www.rotowire.com/soccer/stats.php.
  Every parameter is REQUIRED; omitting one returns
  {"error":"The <NAME> parameter is required."} one at a time.
  `start`/`end` are MATCHWEEKS, not dates. Competitions are boolean flags --
  MLS and LMX (Liga MX) are both there, which covers two of our three leagues.

  It returns JSON, 97 columns. The ones that matter:
    p    passes            ap   accurate passes     <- the attempted/accurate split
    cr   crosses           acr  accurate crosses
    tkl  tackles           tklw tackles won
    cl   clearances        ecl  effective clearances
    cc   chances created   bcc  big chances created
    int, blk, touch, dr/dw (dribbles), sv, gc, cs, plus set pieces and penalties
  Also `opp`, `homeaway`, `formation`, `gp`, `min`, `team`, `position`, and a
  stable player `ID` + `URL`.

THE ONE MEASUREMENT
  Does `start=N&end=N` return ONE ROW PER MATCH, or a season total filtered to
  that week? `opp` and `homeaway` being columns suggests per-match, but that is
  an inference and inferences are what this repo keeps paying for.

  Compare a single player across two adjacent single-week calls against what we
  already store for the same fixtures in `player_game_logs_all`. If `gp` is 1 and
  `opp` names the actual opponent, it is per-match. If `gp` is the season count,
  it is an aggregate and this lead is dead for settlement.

IF IT IS PER-MATCH, THEN
  - Measure the real request cost: `position` appears to be a required filter
    (my `position=A` call returned 5 rows), so a full pull may be
    positions x matchweeks. Count it before building.
  - Identity is the hard part, as always. RotoWire has its own player `ID`; we
    key on our spine. Match within a fixture's roster and FAIL CLOSED on
    ambiguity, exactly as ingest_fotmob_soccer_logs does.
  - It would be a THIRD provider. Under the design settled today that means its
    OWN table plus a column in the joining view -- never merged into another
    provider's row. See scripts_split_provider_logs.py.

CAVEATS, stated because they are easy to forget
  - This is NOT the picks relay. It is an HTML table's JSON backend with no
    documented contract, and it can change shape without notice. That is exactly
    why the picks relay is archived whole every day; if this becomes a
    dependency it deserves the same treatment.
  - I have made 7 requests to it in total. Do not hammer it.

Scope: your worktree only. Do not touch core_markets.py or routers/props.py.
