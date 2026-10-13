# TASK: reverse-engineer FanDuel's API contract, answer one question

## The question (this is the deliverable, not the code)

**Does FanDuel publish PLAYER STAT props for the four Leagues Cup fixtures?**

Player stat props means per-player over/under lines on: shots, shots on target,
passes attempted, goalie saves, clearances, crosses, tackles, assists, dribbles.

It does NOT mean goalscorer markets (anytime/first scorer), and it does NOT mean
team totals (`Each team 2+ Shots on Target`). Both of those already exist
elsewhere and are not what is being asked.

The four fixtures (ESPN `soccer/concacaf.leagues.cup`):

| Fixture | Kickoff UTC |
|---|---|
| CF Monterrey vs Chicago Fire | 2026-08-26 00:30 |
| Club Leon vs Real Salt Lake | 2026-08-26 02:30 |
| Deportivo Toluca vs Austin FC | 2026-08-27 00:30 |
| Club America vs Columbus Crew | 2026-08-27 02:45 |

**A clean "no" is a complete and valuable answer.** Two books that DO carry these
fixtures (Bovada, Pinnacle) price zero player stat markets on them. The null
result is the likely one. Report it plainly; do not stretch a team-total or a
goalscorer market into a "yes".

## Why FanDuel specifically

Measured 2026-08-25 from this box:

- `sbapi.nj.sportsbook.fanduel.com` **answers us** -- it is not IP-blocked.
  `/api/content-managed-page?page=HOME&...` returns **400**, meaning the path
  exists and the parameter contract is wrong. Every other path tried returned 404.
- 20 state hosts (nj/pa/oh/mi/va/co/in/ia/tn/az/wv/il/ny/ks/la/md/ma/ky/nc/vt)
  all behave the same.
- `_ak=FhMFpcPWXMeyZxOx` was the public key tried. It may be stale.

## Method that is known to work here

For RotoWire the contract was recovered by fetching the page, extracting the
`<script src=...>` bundle, and grepping the bundle for the fetch call. That found
`fetch('/picks/api/lines.php')` with no params. Do the same to FanDuel's web app:
find the bundle, find how it builds the sportsbook request, read the real
parameter set off the code rather than guessing.

## HARD LIMITS -- read these

1. **Do NOT attempt to bypass any IP block.** PrizePicks (Cloudflare 403, static
   error id, UA-independent) and DraftKings (Akamai Access Denied) are
   network-level denies and are **OUT OF SCOPE ENTIRELY**. No proxies, no
   header/TLS-fingerprint spoofing, no third-party fetch relays, no residential
   egress. If FanDuel turns out to deny the same way, STOP and report that.
2. **Write exactly two new files. Modify none.**
   - `docs/FANDUEL-API-CONTRACT-2026-08-25.md` -- the findings
   - `/tmp/claude-0/-root/2e2fb54f-bafb-4eb9-a810-09f61cc5d7a8/scratchpad/fanduel_probe.py`
3. **Do NOT touch**: anything under `backend/`, `pages/`, `components/`,
   `bovada_scraper/`, any `.db` file, any existing file at all.
4. **Do NOT touch host config**: no `/etc`, no systemd, no cron, no timers.
   A worktree does not isolate these.
5. **Do NOT restart any server.** Ports 3096/8096, 3097/8097, 3098/8098 are in
   use by running dev stacks. Leave them alone.
6. **Do NOT write to any database.**
7. Be polite to the publisher: no tight retry loops, no parallel hammering. A
   refusal is a refusal -- do not retry a 403.

## What "done" looks like

`docs/FANDUEL-API-CONTRACT-2026-08-25.md` containing:

1. The working request(s), verbatim and copy-pasteable, or a clear statement that
   none was found and what the blocker was.
2. The parameter contract read off their bundle, with the bundle URL cited.
3. **The answer to the question**: for each of the four fixtures, the player stat
   markets found, with real player names and lines -- or "none, and here is the
   market list that IS published, which is what proves it".
4. Every request you made, with its status code, so the negative result is
   checkable.

Do not report success on the basis of a 200 alone. A 200 that returns European
soccer, or team totals, or goalscorer markets, does not answer the question.
