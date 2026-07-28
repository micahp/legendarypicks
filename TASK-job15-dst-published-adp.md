# TASK job15 — D/ST ADP is published; stop deriving it

**Owner: Hermes.** Backend only. Everything in this task is measured, not assumed —
the measurements are below and you should reproduce them before changing code.

---

## 1. The finding

`backend/routers/nfl_mock_draft.py:314` says:

```python
# D/ST — no published ADP exists. Derive ranking from fantasy totals.
```

**That comment is false.** Measured against ESPN on 2026-07-28: all 32 D/ST carry a
published average draft position, in the *same payload `ingest_nfl_adp.py` already
downloads*.

```
Broncos D/ST   espn_id=-16007  adp=89.94   owned 98.7%
Texans D/ST    espn_id=-16034  adp=91.81   owned 98.9%
Rams D/ST      espn_id=-16014  adp=98.19   owned 92.5%
Seahawks D/ST  espn_id=-16026  adp=106.50  owned 98.3%
```

**Why we lose them:** ESPN keys D/ST with **negative** ids, `-16000 - proTeamId`.
Our `players` table has all 32 DEF rows (ids 30094–30125) but their `espn_id` is
**empty**. So the lookup in `ingest_nfl_adp.py:56-61` matches **0 of 32**. It does not
raise. It misses — and the miss was then papered over with a derivation.

The derivation is also wrong on the merits: it ranks **SEA #1**; ESPN's published ADP
ranks **DEN #1 and SEA 4th**.

Reproduce before you start:

```bash
cd /root/lp-job15-dst-published-adp/backend
./venv/bin/python - <<'PY'
import json, urllib.request
U=("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/players"
   "?scoringPeriodId=0&view=kona_player_info")
h={"x-fantasy-filter": json.dumps({"players":{"filterSlotIds":{"value":[0]},"limit":1500,
   "sortDraftRanks":{"sortPriority":1,"sortAsc":True,"value":"STANDARD"}}})}
d=json.loads(urllib.request.urlopen(urllib.request.Request(U,headers=h),timeout=60).read().decode())
dst=[p for p in d if p.get('defaultPositionId')==16]
print("D/ST:", len(dst), "with adp:",
      sum(1 for p in dst if p.get('ownership',{}).get('averageDraftPosition')))
PY
```

Expected: `D/ST: 32 with adp: 32`.

Note `filterSlotIds` is **ignored** by this endpoint — `[0]`, `[0,16]` and `[16]` all
return the identical 11,513 rows. Do not "fix" the filter; it is not the problem.

---

## 2. The published team map

`-16000 - proTeamId` needs `proTeamId → team code`. **It is published — do not hardcode
32 rows and do not infer it from nicknames.**

```
https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026?view=proTeamSchedules_wl
  → settings.proTeams[]  →  {id, abbrev, location, name}    (33 rows, includes id 0)
```

Verified: `id=14 abbrev=LAR` → `-16014`, which is exactly the id ESPN returned for
Rams D/ST. `abbrev` is already the ESPN vocabulary this repo treats as canonical
(`LAR`/`WSH`), so it joins to `players.team` directly. **Print `matched N of 32`.**

---

## 3. What to change

Exactly these files. Nothing else.

| file | change |
|---|---|
| `backend/ingest_nfl_adp.py` | Resolve the 32 D/ST. Fetch `proTeams`, build `proTeamId → abbrev`, map each D/ST entity to our `players.id` by `team` + `position='DEF'`, and write its `adp`/`percent_owned` into `nfl_adp` like any other player. Backfill `players.espn_id` for those 32 rows with the negative id so the join is permanent. Print join coverage. |
| `backend/routers/nfl_mock_draft.py` | Delete the derived-D/ST branch: the `dst_rank` block, `_DST_SLOT`, and the interleave at the end of the pool builder. D/ST now sort by real ADP alongside everyone else. Delete the false comment. Keep `games_played`/`games_missed`/`weeks_played`/`team_weeks` for D/ST exactly as they are — those are correct and gated. |
| `backend/test_nfl_mock_draft.py`, `backend/test_nfl_dst.py` | Update expectations that assert `adp is None` or the slot-150 placement. |

`dst_rank` disappears from the payload. That is intended.

---

## 4. Done means

```bash
LP_GATE_W=/root/lp-job15-dst-published-adp \
  LP_GATE_B=http://127.0.0.1:8093 LP_GATE_F=http://127.0.0.1:3093 \
  bash /root/lp-job15-dst-published-adp/verify-gates.sh all
```

- **`REG-adp-dst` goes green.** It is committed and currently RED, with the expected
  numbers already written down (`b8cc4b1`). **Making it green by editing the gate is
  the one unacceptable outcome.** If a number genuinely disagrees with ESPN, say so and
  stop — the measurement wins, and then the gate changes in the same commit as the
  evidence.
- `REG-pool` stays green: 300 players, 32 DEF.
- `REG-pytest` stays green.
- Report **`matched N of 32`** for the D/ST join and the ADP you wrote for DEN, HOU,
  LAR, SEA. "Verified" is not a result; counts are.

---

## 5. Scope lock

- **Backend only.** Do not touch any `.tsx`, `.ts`, `pages/`, `components/`, `lib/`.
  A parallel task owns those and will collide with you.
- **Do not touch `verify-gates.sh`.** It is the scoreboard, not your file.
- **Do not touch host config** — no `/etc`, no `systemd`, no `cron`, no nginx.
- **Never run `npm`, `npx`, `yarn`, or `pnpm`.** `node_modules` in your worktree is a
  **symlink to the shared install**; an `npx` there empties it and takes down every
  dev server on this box. This already happened on 2026-07-28 and cost a morning.
- **Do not write to `/root/picks.hermes.db` outside the ingest itself**, and do not
  re-run other ingests to "refresh" things.
- Do not "improve" the ADP ingest beyond D/ST. Kickers already resolve (38 with ADP).
- One commit per logical slice. Do not push.

## 6. Resources

The box is tight: swap was 3404/4095 MB when this was written. Your worktree's dev
servers are on the ports the script prints. Do not start extra ones. Do not run a full
backfill — this ingest is two HTTP calls and ~9,600 upserts.

---

## 6. ADDENDUM 2026-07-28 09:5x — two corrections to §3, read before starting

### 6a. §3 contradicts itself. Do NOT delete the whole D/ST block.

§3 says *"Delete the derived-D/ST branch: the `dst_rank` block"* and, in the same cell,
*"Keep `games_played`/`games_missed`/`weeks_played`/`team_weeks` for D/ST exactly as they
are."* Those are the same loop. `backend/routers/nfl_mock_draft.py:332-351` computes the
ranking **and** the availability fields in one pass over `dst_rows`:

```python
for i, dr in enumerate(dst_rows, start=1):
    weeks = [int(w) for w in (dr["weeks_csv"] or "").split(",") if w]
    gp = len(weeks)
    ...
    "dst_rank": i,                      # <- DELETE this
    "games_played": gp,                 # <- KEEP these four, they are the only
    "games_missed": ...,                #    correct source of D/ST availability
    "weeks_played": weeks,              #    anywhere in the codebase
    "team_weeks": tw,
```

**Delete only:** `dst_rank`, `_DST_SLOT`, the interleave, and the false comment at :314.
**Keep:** the `dst_rows` query and the four availability fields. Merge the D/ST dicts into
the normal ADP-sorted list instead of splicing them at a fixed slot.

`REG-pool` (300 players, 32 DEF) and `REG-dst` (32 rows) will catch you if the block is
lost wholesale — but they will catch it *after* you have deleted the derivation, so read
this first.

### 6b. B17 — `player_detail` reports the opposite of the board for the same D/ST

Add to your scope, same file. Measured 2026-07-28 against `:8098`, SEA D/ST (`player_id`
30116), same season, same entity:

```
GET /api/nfl/draft-board?position=DEF   ->  games_played=17  games_missed=0   sample=full
GET /api/nfl/draft/player/30116         ->  games_played=0   games_missed=17  sample=none
```

Both cannot be true. The board is right. `player_detail` (:617) has **no D/ST branch at
all** — it falls through to the generic path at :668, `games_played = len(log_rows)`, over
`player_game_logs`. **That table holds touches, not presence**: a row exists only when a
player recorded a pass, rush or reception. A team defense records none, so it returns zero
rows and the endpoint concludes the defense never played. The payload then contradicts
itself, carrying `dst_pts_total=164.0` alongside `games_played=0`.

This is now user-visible: the mock draft pool opens this overlay on tap (`c92e5df`), so
all 32 defenses render "No NFL sample" over a real 164-point season.

**Fix:** give `player_detail` the same `dst_rows` source the pool builder uses, for
`position='DEF'` only. Do not change the generic path — every other position is correct.

**Done means:** `/api/nfl/draft/player/30116` returns `games_played=17`, `games_missed=0`,
`sample='full'`, `weeks_played` non-empty, and agrees field-for-field with the D/ST entry
in `/api/nfl/draft-board?position=DEF`. Report both payloads side by side, not "verified".
