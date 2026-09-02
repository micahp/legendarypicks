# Objective

Tell a reader who is NOT playing in an MLS or Leagues Cup match BEFORE kickoff, on the
game detail page, and say honestly how confident we are.

This is the roadmap item raised 2026-08-10 ("Who is actually playing — soccer availability
before kickoff"). The news engine reports absences after the fact — Messi missing the
Monterrey match after his father's death, Suárez serving a six-game Leagues Cup ban that
Micah only discovered mid-match. A reader deciding anything about a match needs that
before it starts, not in the recap.

Soccer is the hard case and therefore the valuable one. The NFL has questionable/doubtful,
the NBA has an injury report; soccer has neither convention, so an MLS starter can vanish
at the last minute for an international call-up, a rest day, a suspension, or something
nobody saw coming.

**Step one is a question, not a build: what is actually published?** Answer it with
evidence before writing an ingest. Then ship whatever the evidence supports.

# Constraints

**Files you may create or modify. Nothing else.**

- `backend/probe_soccer_availability.py` (new)
- `docs/SOCCER-AVAILABILITY.md` (new)
- `docs/evidence/soccer-availability-probe.json` (new)
- `backend/espn_client.py` — additive only: new functions. Do not change `summary()`,
  `lineups()`, `boxscore()`, `_get()`, the host constants, or any existing behaviour.
- `backend/sports_service.py` — additive only: the game-detail payload may gain one new key.
- `components/Game/SoccerBoxScore.tsx` and `pages/game/[league]/[gameId].tsx` — render only.
- `backend/test_soccer_availability.py` (new)

**Forbidden, without exception:**

- Host configuration of any kind — `/etc`, systemd, cron, nginx. A git worktree does not
  isolate these and this is a shared box.
- Shared utilities and helpers used by other leagues. Do not "improve" `_get`, the cache,
  the pacing, or any ingest that is not named above.
- Database migrations, schema changes, and writes to `picks.db` or `picks.dev.db`.
- `git push`, tags, releases, branch changes, and restarting any running server. Commit
  locally if you like; pushing is Micah's call.
- Paid APIs, new paid subscriptions, and signing up for anything.
- Scraping behind a login, a paywall, or a CAPTCHA. If a source presents a CAPTCHA, stop
  and record that it did.

**Rate limits are real here and this box has history.** ESPN blocks per HOST and the limit
is a request COUNT per host (roughly 100), not a rate — pacing does not buy more. Probe a
handful of fixtures, not every fixture. Liquipedia has IP-blocked this box before: one
probe, then stop.

# Engineering Reference

`docs/DEV-STANDARDS.md` and `AGENTS.md` govern. Beyond those, the rules this particular
task keeps getting broken by:

1. **A gap is a statement about which endpoint you asked.** "ESPN does not publish it" is
   only true after you have asked the site API, the core API, and the team surface, and
   written down what each one said. We have repeatedly under-read our publishers and then
   built a derivation for a value that was published all along.

2. **Two numbers need the same ruler.** If you compare soccer to the NFL, hit the same
   endpoint shape for both in the same run. A count from one endpoint and a count from
   another is not a comparison.

3. **A 403 is a statement about the host, not about publication.** This box gets 403s from
   some ESPN hosts and from PFR. If a host refuses, record the refusal, try the other host,
   and try Wayback. Never convert a 403 into "not published".

4. **Presence is not integrity, and `count: 0` is an answer.** An endpoint that exists and
   returns an empty list is publishing "nothing to report", which is different from an
   endpoint that 404s. Record which one you got. Never report "evidence unavailable" as a
   pass.

5. **Absence is marked, not implied.** Per `docs/` UI doctrine, the accent goes on what is
   MISSING. A player we cannot vouch for must not silently look available.

## What is already known — verified 2026-08-10, do not re-derive

Probed from this box, against live ESPN:

| Surface | Result |
|---|---|
| `soccer/usa.1/summary?event=<pre fixture>` | **No `injuries` key at all.** Keys are boxscore, broadcasts, format, gameInfo, hasOdds, header, lastFiveGames, leaders, meta, news, odds, pickcenter, rosters, standings, wallclockAvailable |
| `rosters[]` on a `pre` fixture | present but **empty** — 0 players, no formation. It fills at kickoff, which is exactly too late |
| `sports.core.api.espn.com/.../soccer/leagues/usa.1/teams/9/injuries` | **exists, `count: 0`** |
| same endpoint, Inter Miami (20232) | `count: 0` |
| same endpoint, EPL Arsenal (359) | `count: 0` |
| same endpoint, **NFL Kansas City (12)** — the control | **`count: 67`** |

So the schema is league-agnostic and the data is not: ESPN carries injuries for the NFL
and publishes nothing for soccer, mid-season, on the same endpoint. `lineups()` in
`backend/espn_client.py` already reads `rosters` — that is the confirmed XI at kickoff and
is prior art worth reusing, but it is not availability.

That is where the investigation starts. It is not where it ends.

# Definition of Done

1. `docs/evidence/soccer-availability-probe.json` exists, was produced by running the
   probe, and records for every candidate surface: the URL asked, the HTTP status, the
   item count, and a short verbatim sample. It includes the NFL control row so the soccer
   rows can be read against the same ruler.
2. `docs/SOCCER-AVAILABILITY.md` states, per surface, whether soccer availability is
   published — and where the answer is "no", says whether that is a 404, an empty list, or
   a refusal, because those are three different facts.
3. The game detail page shows something true and useful before kickoff for an MLS or
   Leagues Cup fixture. What that is depends on the evidence:
   - **If a publisher surface carries availability** — ingest it and show it, attributed.
   - **If none does** — show what we DO hold, labelled for what it is: absences the news
     corpus already reports (`news_items` / the narrative pipeline has the Messi
     bereavement and the Suárez ban), plus the honest statement that no availability
     report is published for this league. An empty confident-looking panel is worse than
     a panel that says nobody publishes this.
4. Tests pass, and at least one of them pins the behaviour when the publisher returns
   nothing. A test that asserts a tautology (`assert not 0`) does not count.
5. No file outside the Constraints list is modified. `git status` proves it.

# Tasks

- [ ] [TODO] Write `backend/probe_soccer_availability.py`. It asks each candidate surface
      for MLS (`usa.1`) and Leagues Cup (`concacaf.leagues.cup`), plus the NFL control, and
      writes `docs/evidence/soccer-availability-probe.json`. Candidates must include, at
      minimum: the site-API summary for a `pre` fixture, the core-API team injuries
      endpoint, the site-API team surface, the team roster surface, and the league news
      surface. Acceptance: the script runs, the JSON exists, and every row has url, status,
      count and sample.
- [ ] [TODO] Answer the question in `docs/SOCCER-AVAILABILITY.md` from that JSON, citing
      it. State plainly which of the three the roadmap asked about is true: ESPN does not
      display it, the reporting rules differ, or nobody publishes it via an API. Where you
      cannot tell, say so and say what would settle it.
- [ ] [TODO] Add the availability read to `backend/espn_client.py` as a NEW function, and
      expose it through the game-detail payload in `backend/sports_service.py`. If the
      evidence says nothing is published, this function returns the honest empty shape —
      it still exists, so the frontend has one contract to render either way.
- [ ] [TODO] Render it on the soccer game detail page before kickoff. Absence is the
      accent. If we do not know, the panel says we do not know and why.
- [ ] [TODO] `backend/test_soccer_availability.py` — pin the empty-publisher case, the
      populated case, and the shape of the payload key.

# Verification

- [ ] Unit tests: `backend/venv/bin/python -m pytest backend/test_soccer_availability.py -q`
      passes, and the pre-existing suite is not broken —
      `backend/venv/bin/python -m pytest backend/test_news.py -q` still passes 43.
- [ ] The probe JSON was produced by an actual run against live endpoints, not written by
      hand, and the NFL control row is present and non-zero. If the control is zero, the
      probe is broken — do not report soccer's zero as a finding.
- [ ] `git status --porcelain` lists only files named in Constraints.
- [ ] The rendered panel was checked against a real `pre` fixture, by id, and the fixture
      id is recorded in the doc. Live ids as of 2026-08-10: MLS 761712 (RBNY @ ATL,
      2026-08-15), Leagues Cup 401863612 (PAC @ CLT, 2026-08-11).

# Current Status

Not started. The known-facts table above is verified; everything below it is open.

# Next Recommended Task

Write the probe. Do not skip it because the table above already looks like an answer —
the table is five endpoints and the question is whether there is a sixth.
