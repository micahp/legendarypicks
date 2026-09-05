# TASK: desktop pull of the league-news X handles

**Run on Micah's home PC (residential IP). Different repo, different handles,
and a different drop directory from the newsletter pull. Do not mix them.**

The companion job is `innovative-hype-newsletter/docs/TASK-desktop-pull.md`,
which pulls two personal handles for the newsletter's voice corpus. This one
pulls 17 sports handles for Legendary Picks' league-news lane. Same mechanism,
unrelated data.

## Why this exists

`legendarypicks-news-x.service` has contributed **zero rows since 2026-08-20**.
It fails every run:

```
x: NO WORKING NITTER MIRROR after 3 single attempts
   (nitter.tiekoetter.com:429; nitter.net:410; xcancel.com:400)
```

Every public nitter mirror died with X's 2026-08-24 cease-and-desist and this
box's datacenter IP is rate-limited by X directly. A residential IP with a
logged-in browser is the only surface left.

## Why this lane matters more than the newsletter one

This is the fast lane. From `scripts/news-x-collect.sh`: `@UnderdogNFL` runs
~83 posts/day against a 20-post window, so its feed holds about six hours. The
items that go stale fastest are the ones worth having: **who sat out practice,
who is not travelling, who was just suspended.** That is roster availability,
and it is worthless by the weekend.

Consequence for scheduling: **more often is materially better here.** The
newsletter pull can be daily. This one loses real value at daily. If the
scheduled task can run two or three times a day, do that. The server drops
anything older than 72h on principle (`LP_X_DESKTOP_MAX_AGE_H`), so a stale
drop cannot quietly refill the board with last week's news.

## The handles

Exactly these, and the filename must be the handle:

```
UnderdogNFL  UnderdogMLB  UnderdogNBA  Underdog
TheAthletic  TheAthleticNFL  TheAthleticNHL  TheAthleticCFB
BleacherReport
AdamSchefter  RapSheet  FieldYates
ShamsCharania
JeffPassan  Ken_Rosenthal
FriedgeHNIC
TomBogert
```

The server maps each to a league and **rejects any handle not on this list**,
counting it as `unknown_handle_<name>`. Do not add accounts. The list was
measured: usable share of 20 rows was Shams 80%, TomBogert 44%, Rosenthal 40%,
Friedman 36%, Rapoport 35%, Passan 35%, Yates 25%. Deliberately excluded and
not to be re-added: arielhelwani (0% usable), Brett_McMurphy (5%), PeteThamel
(10%), TomPelissero (10%), FabrizioRomano (scores well but covers European club
soccer, which this product does not).

## Output

```
/root/legendarypicks/data/x_desktop/<YYYY-MM-DD>/<Handle>.jsonl
```

on the server. In the repo, commit to `data/x_desktop/<YYYY-MM-DD>/`.

Same row schema as the newsletter drop, so one scraper can produce both:

```json
{"id": "2094917087898595501",
 "date": "2026-09-05T14:25:40.000Z",
 "text": "Source: RB sat out practice Friday and is not expected to travel."}
```

- `id` REQUIRED, a JSON **string**, digits only. Ids exceed 2^53 and a
  number-typed id arrives corrupted. The server counts these as `bad_id`.
- `date` ISO 8601 UTC preferred.
- `text` REQUIRED and non-empty. An empty-text row is counted `empty_text` and
  dropped: unlike the newsletter, a media-only post carries no league news.
- `media` and `urls` are accepted but currently **unused by this lane**. Skip
  them here; the newsletter pull is where they matter.

## Cutoff

Take the numerically largest `id` already present per handle across
`data/x_desktop/*/<Handle>.jsonl` and collect strictly after it. Snowflake ids
are monotonic; do not trust dates or file order. On a first run with no history,
take the last ~24h.

## Rules

- Profile page only: `https://x.com/<handle>`. Never `x.com/home`.
- Exclude pinned tweets, ads, "Who to follow", promoted cards, poll fragments.
- If a row's author is not that profile, drop it.
- Browser only. No X API, no third-party scraper service, no tunnel, no inbound
  service.
- `git pull --rebase` before pushing. One commit.
- No commit when nothing is new.

## What the server does with it

`collect_x()` tries the nitter mirrors first and falls back to
`collect_x_desktop()` only when every mirror is dead. **A live mirror always
wins**, because it is fresher than a scheduled pull and this lane's value is
perishable. So if the mirrors ever come back, this drop quietly stops being
used, which is correct.

The drop gives the lane something the mirrors never did: the tweet id, so the
stored URL is the canonical `https://x.com/<handle>/status/<id>`. Nitter's RSS
`<link>` pointed at whichever mirror answered, which is not citable and dies
with the mirror. This pipeline separates receipts from chatter and these are
receipts.

Every skipped row is counted and printed by category, and a drop that exists but
yields nothing usable says so explicitly rather than looking like a quiet day:

```
x-desktop: 2 usable post(s) from /root/legendarypicks/data/x_desktop
  (newest folder 2026-09-05) | skipped: bad_id=1, empty_text=1, too_old=1,
  unknown_handle_SomeRandomAccount=1
```

## Report back

Rows per handle, oldest and newest date per handle, which handles produced
nothing, which login you used, and anything that looked wrong. A handle
producing nothing repeatedly is worth flagging: it may have been renamed,
suspended, or gone private.
