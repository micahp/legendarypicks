# Team placeholder images — what Underdog's actually are, and what to do about it

**Asked** 2026-08-14 (Micah): write up copying team placeholder images from Underdog, from
this example —
`https://assets.underdogfantasy.com/player-images/nfl/20251015_21-1a20f1da-c502-5224-9c4a-bc363174cd21-Logo_Light.png`

**Short answer:** they are not team logos. They are **one piece of Underdog's own artwork,
recolored per team**, and the colors driving the recolor are published by ESPN. So the same
surface is reproducible without copying anything — §6. Everything needed to copy them anyway
is in §5, because that is a business call, not a technical one.

Everything below was measured on 2026-08-14, not assumed.

---

## 1. What the asset actually is

I downloaded the file in the request, plus two more team placeholders, and looked at them.

| | |
|---|---|
| format | PNG, **512×512**, 8-bit RGBA, non-interlaced |
| size | 34,934 bytes |
| host | Google Cloud Storage (`x-goog-*`, `server: UploadServer`) |
| headers | `cache-control: public,max-age=3600`, `access-control-allow-origin: *`, ETag + `last-modified` |
| auth | none |

**The content is the finding.** The file in the request is a **side-view football helmet in
pewter and red**. Two others pulled for comparison are a **front-facing player silhouette** in
Falcons black/red and Ravens purple/black. There is **no NFL shield, no team logo, no wordmark,
no player likeness** in any of them — it is a single original illustration with the team's two
colors filled in.

That is what "team placeholder" means here: **one drawing, thirty-two color pairs**.

## 2. The URL contract

```
https://assets.underdogfantasy.com/player-images/{sport}/{YYYYMMDD}_{NN}-{team_id}-{variant}.png
                                                  nfl    20251015 _21  1a20f1da-…      Logo_Light
```

- `{team_id}` is **Underdog's own team UUID**, confirmed: the UUID in the requested URL is
  exactly the `team_id` on their player records for that club.
- `{variant}` seen so far: `PlayerLogo` (light/default), `PlayerLogo_Dark`, `Logo_Light`.
  A player record carries `image_url`, `light_image_url` and `dark_image_url` — so the theme
  pairing is theirs, and it matches how our own pages already work.
- **`{YYYYMMDD}` rotates.** The same team_id appears under `20250212_21-…-PlayerLogo.png` and
  `20251015_21-…-Logo_Light.png`. **A stored URL is not a stable address**, which rules out
  writing these into our schema as literals (§5.3).

The UUIDs are not guessable, so the only way to enumerate them is the API.

## 3. Where the URLs come from

`GET https://api.underdogfantasy.com/beta/v5/over_under_lines` — unauthenticated, plain GET,
already documented in `docs/UNDERDOG-API-RECON-2026-07-23.md`. **18.7 MB** in the pull I took
(the recon doc says ~8 MB in July, so it has more than doubled). Image URLs hang off
`players[]`:

```
players[].image_url | .light_image_url | .dark_image_url
```

## 4. Scale — how much of this actually matters

From one pull, 2026-08-14:

| | count |
|---|---|
| players in the payload | 1,554 |
| with a **real headshot** | 1,441 (92.7%) |
| falling back to a **placeholder** | **113 (7.3%)** |
| **distinct placeholder files** | **62** |
| placeholders mapping to exactly one team | 56 of 62 |
| by sport | FIFA 65, NFL 20, CFL 16, NPB 6, CFB 4, MLB 2 |

Two things follow. **62 files is a trivial mirror** — about 2 MB. And the placeholder is a
**7% case**: the interesting asset here is the 1,441 *headshots*, which are a different
question with a much worse answer (they are photographs, almost certainly licensed by
Underdog from a wire service, and not ours to take). This doc is only about the 62.

## 5. If we copy them anyway

Complete, in the order it would be done.

### 5.1 Mirror, never hotlink
Hotlinking `assets.underdogfantasy.com` from our pages spends their bandwidth, puts their
hostname in our users' network logs, and breaks the moment they rotate a date prefix (§2).
If we use these at all, we copy the bytes to our own storage and serve them ourselves.
Precedent to *not* follow: `pages/leagues/esports.tsx:344` hotlinks PandaScore logos today.

### 5.2 Enumerate, don't guess
```
GET /beta/v5/over_under_lines           →  players[].{image_url,light_image_url,dark_image_url}
filter to URLs matching /Logo|Silhouette/i   →  62 distinct files
download each once                       →  ~2 MB total
```
Keep the response's `etag` and `last-modified` per file; both are served, so a refresh is a
conditional GET, not a re-download.

### 5.3 Store by OUR key, not theirs
Underdog's `team_id` is a UUID (and for FIFA, a **Sportradar** `sr_competitor_NNNN` id). Our
canonical team vocabulary is ESPN's (`docs/` team-code convention — ESPN codes like `LAR`,
`WSH`, `CHW`). Those do not join. A crosswalk is required, and a wrong crosswalk here does not
raise — it silently paints one club's colors on another's players, which is exactly the failure
mode `.claude/skills/fail-loudly` exists for.

So: file the asset under our team code, resolve the crosswalk **once at ingest**, and refuse
rather than default when a team_id does not map. Never write their URL into a serving table —
it rotates.

### 5.4 What it costs us going forward
- A recurring job to re-read the API (18.7 MB) purely to notice a filename rotated.
- A crosswalk to maintain every time either side adds a team.
- An asset set whose art direction is Underdog's, on our pages, in their color treatment.

### 5.5 The rights question — briefly, and it's your call
These are Underdog's original illustrations. There is no license offered on that CDN, and a
public URL with `access-control-allow-origin: *` is a technical fact, not a grant. Copying them
means shipping another operator's artwork as our own product surface, and they are a direct
competitor in exactly this category. I have written the full how-to above rather than
withholding it; I would not ship it without you making that call deliberately.

Worth noting what *isn't* at issue: since these carry no league marks (§1), the NFL/team
trademark question that usually dominates sports imagery does not arise here. The only rights
holder in the frame is Underdog.

## 6. What I'd do instead — and why it's cheap

The recolor is the whole trick, and **the colors are published**. Verified:

```
GET sports.core.api.espn.com/v2/sports/football/leagues/nfl/teams/1
→ {"abbreviation":"ATL", "color":"a71930", "alternateColor":"000000"}
```

`a71930` / `000000` is precisely the red-and-black of the Falcons placeholder I downloaded.
Underdog is doing the same thing we would be: taking published team colors and filling a
silhouette. Per `.claude/skills/published-first`, the value is published — we should read it,
not copy someone's render of it.

So the build is:

1. **Two SVGs**, drawn once: a front-facing helmeted silhouette and a side-view helmet. These
   are ~50 lines of path data each and the only real work in this proposal.
2. **`color` / `alternateColor` per team from ESPN**, ingested into a `team_colors` table.
   Neither `picks.db` nor `picks.dev.db` holds any color field today — I checked every table.
   Cost: one request per team (32 for NFL), well inside the host budget in
   `.claude/skills/espn-request-budget`, and it changes ~never, so it is cached forever.
3. **Fill at render time** with `currentColor`/CSS variables. An inline SVG recolors per theme
   for free, which is better than Underdog's approach — they ship two PNGs per team to do what
   one SVG does, and a 512×512 PNG at a 40px avatar size is ~35 KB for nothing
   (`docs/DEV-STANDARDS.md`: a list must not download more than it renders).

That gets us the same surface, at a smaller payload, with no crosswalk, no rotation problem, no
recurring 18.7 MB poll, and nothing of anyone else's in it.

## 7. The bigger question this actually raises

**We render no player or team imagery at all today.** The only `<img>` tags in the app are
esports logos hotlinked from PandaScore and news thumbnails from the article feed. There is no
headshot on the player page, no team mark on `GameCard`.

So "team placeholders" is not a gap-filling task — it is the *second* half of a feature whose
first half does not exist. A placeholder is what shows when a headshot is missing; with no
headshots, the placeholder is simply the image, on every player, forever. Worth deciding what
we want on the player surface before building the fallback for it.

## 8. Decision needed

1. **Mirror Underdog's 62 files** (§5) — fastest, and it is their artwork.
2. **Draw two SVGs and fill them with ESPN's published colors** (§6) — recommended. Smaller,
   theme-native, no crosswalk, nothing borrowed.
3. **Neither yet** — settle §7 first, since the placeholder only makes sense next to a headshot.

I'd take 2, and I'd want an answer on 3 before either.
