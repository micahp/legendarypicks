# TASK (Hermes, backend) — Player Rankings shows no football stats. The data is already there.

**Reported by Micah, 2026-07-28:** *"the player rankings doesn't even have rb carries."*

He is right, and the cause is not missing data. Every stat is already in
`player_game_logs.stats` per game. **No endpoint exposes any of it.** This is an API
surface gap, not an ingest job. Do not go fetch anything.

---

## 0. Read before you write a line

Two sibling questions, in this order. They are not ceremony — the last backend change that
skipped them produced a fabricated D/ST ranking that shipped behind a false comment.

1. **ponytail** — *"does this code need to exist?"*
   (https://github.com/DietrichGebert/ponytail). Not installed here; ask it anyway.
2. **`published-first`** — *"does this value need to be computed?"*
   `.claude/skills/published-first/SKILL.md`. **Load it.** Walk the ladder before any
   `SUM()`/`GROUP BY`.

For this task specifically, the ladder resolves at **rung 1** — the values are already
columns inside `player_game_logs.stats`. You are summing rows over a bound this codebase
already applies elsewhere. **You are not deriving a definition.** If you find yourself
reasoning about what *ought* to count as a game, a carry, or a target rather than reading
what is already there, stop — that is the exact move that cost us eight defects in the
nflverse rollup.

Also load **`honest-data-ui`** (`.claude/skills/honest-data-ui/SKILL.md`) before choosing how
absent values render. §2 rule 2 below is its rule, not mine.

---

## 1. The gap, measured

Everything `/api/nfl/draft-board` and `/api/nfl/draft/player/{id}` return today is a fantasy
abstraction:

```
ppr_per_game_played  ppr_per_team_game  xfp_per_game  snap_pct  target_share
pk_pts_total  pk_pts_per_game  dst_pts_total  dst_pts_per_game
```

Not one carry, yard, reception, completion or touchdown. So a running back's row in Player
Rankings — and his detail overlay — can tell you his PPR average and his target share, but
not how many times he touched the ball.

What is actually in the database, verified per position:

```bash
sqlite3 /root/picks.hermes.db \
  "select stats from player_game_logs where player_id=469 and league='nfl' limit 1;"
```

| position | keys present in `stats` (one game) |
|---|---|
| QB (Josh Allen, 469) | `cmp att pass_yds pass_td intc dropbacks air_yds cpoe pass_epa carries rush_yds rush_td off_snaps off_pct` |
| RB (Gibbs, 7979) | `carries rush_yds rush_td rec targets rec_yds rec_td target_share off_snaps off_pct` |
| WR (Nacua, 16247) | same as RB, plus receiving emphasis |
| TE (McBride, 14572) | `rec targets rec_yds rec_td target_share adot air_yds_share separation cushion yac_above_exp` |
| PK (Aubrey, 882) | `fg_made fg_att fg_pct fg_long fg_made_0_19 … fg_made_60_ fg_missed_* pat_made pat_att gwfg_made gwfg_att` |

The kicker buckets are **exactly ESPN's published kicker column set** (`1-19 20-29 30-39
40-49 50+ LNG FG% FG XP PTS`). That is not a coincidence and it is not ours to redesign —
it is the published contract, so match it rather than inventing a layout.

### 1a. Orchestrator baseline — measured before implementation

Codex measured the exact regular-season source-key population in
`/root/picks.hermes.db` using the same bound required below:

```bash
python3 - <<'PY'
import json, sqlite3
con = sqlite3.connect("file:/root/picks.hermes.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
for pid in (469, 7979, 16247, 14572, 882):
    rows = con.execute(
        """SELECT stats FROM player_game_logs
           WHERE player_id=? AND league='nfl' AND season=2025
             AND CAST(game_no AS INTEGER)<19""",
        (pid,),
    ).fetchall()
    keys = sorted({k for row in rows for k in json.loads(row["stats"] or "{}")})
    print(pid, "games", len(rows), "keys", " ".join(keys))
PY
```

| position / player | regular-season rows | observed source keys |
|---|---:|---|
| QB Josh Allen `469` | 16 | `air_yds att carries cmp cpoe def_pct def_snaps dropbacks fpts fpts_ppr intc off_pct off_snaps pass_epa pass_td pass_yds rush_td rush_yds st_pct st_snaps xfpts_ppr` |
| RB Jahmyr Gibbs `7979` | 17 | `carries def_pct def_snaps fpts fpts_ppr off_pct off_snaps rec rec_td rec_yds rush_td rush_yds st_pct st_snaps target_share targets xfpts_ppr` |
| WR Puka Nacua `16247` | 16 | `adot air_yds_share carries cushion def_pct def_snaps fpts fpts_ppr off_pct off_snaps rec rec_td rec_yds rush_td rush_yds separation st_pct st_snaps target_share targets xfpts_ppr yac_above_exp` |
| TE Trey McBride `14572` | 17 | `adot air_yds_share cushion def_pct def_snaps fpts fpts_ppr off_pct off_snaps rec rec_td rec_yds separation st_pct st_snaps target_share targets xfpts_ppr yac_above_exp` |
| PK Brandon Aubrey `882` | 17 | `carries def_pct def_snaps fg_att fg_blocked fg_long fg_made fg_made_0_19 fg_made_20_29 fg_made_30_39 fg_made_40_49 fg_made_50_59 fg_made_60_ fg_missed fg_missed_0_19 fg_missed_20_29 fg_missed_30_39 fg_missed_40_49 fg_missed_50_59 fg_missed_60_ fg_pct fpts fpts_ppr gwfg_att gwfg_made off_pct off_snaps pat_att pat_made pat_missed rush_td rush_yds st_pct st_snaps xfpts_ppr` |

This inventory is an acceptance boundary:

- read only the published keys named in §2 for that position;
- do not reinterpret unrelated zero-valued keys on a kicker as meaningful rushing stats;
- McBride has no published rushing keys in these rows, so those applicable-but-absent
  totals remain `null`; do not manufacture zeroes;
- D/ST still has no `player_game_logs` rows, so `stats` remains `null`.

The exact pre-change repro is:

```text
Gibbs SQL carries = 243    API stats = null
```

The SQL side is:

```sql
SELECT SUM(CAST(json_extract(stats,'$.carries') AS INTEGER))
FROM player_game_logs
WHERE player_id=7979 AND league='nfl' AND season=2025
  AND CAST(game_no AS INTEGER)<19;
```

### 1b. Existing-field hashes — the no-regression contract

Before this task, Codex canonicalized each complete JSON payload with sorted keys and compact
separators. These hashes cover every existing field, not a hand-picked subset:

| endpoint | pre-task SHA-256 |
|---|---|
| `/api/nfl/draft/player/7979` | `afe618cde5803be8322ea8b07a30cec7b9be5386601954945d6a836a6214de5c` |
| `/api/nfl/draft/player/469` | `063b0808b43e997b2c41784efd48d213712f9bd58869aa227ae31cadf9dde82d` |
| `/api/nfl/draft/player/882` | `3af8599bf9fb47eab9204bd37f70c53e04541b32e13d9c2bddd74788f49ac571` |
| `/api/nfl/draft/player/30116` | `dae33c60afa33ef9980ddbc477fe4fdfa9dd6b92c0c8c3badf87a67dbc6c6d88` |
| `/api/nfl/draft-board?position=QB&limit=100` | `41b7ac25d957c64f91d5eb744a3a5157e0b6d13b9ffaabf7ac1ee38531b56ef6` |
| `/api/nfl/draft-board?position=RB&limit=100` | `6ed725033ae8bae16737095df525dc309fa9ee57c7eaf329f0c5c93091bebd3b` |
| `/api/nfl/draft-board?position=WR&limit=100` | `7624d30237322b236fe38bd9ef2937b784f0287288b91227aa4b1f10aabcfa7f` |
| `/api/nfl/draft-board?position=TE&limit=100` | `906c993a503dd2d171c8ff7677ca5bf7b013576002a6e0d3e269a3efc9d1717c` |
| `/api/nfl/draft-board?position=PK&limit=100` | `ea72334017185a4911c8b73c84fccf3ab783b0f2622405ad3c617c5b372c24db` |
| `/api/nfl/draft-board?position=DEF&limit=100` | `6a50449ac9af8a16483a94842af76c7c0f6e8445589dab1253ad414da40b296d` |

These were measured on the audit snapshot before job15. Job15 intentionally changes the
D/ST detail and DEF-board payload, so the orchestrator must rebaseline those two hashes
after job15 lands and before dispatching this task. The other eight must remain unchanged
through job15.

For this task's after-check, recursively remove only the newly added key named `stats`,
canonicalize the remaining response, and require the hash to equal the post-job15 baseline.
Any other hash change is a regression, even if focused field assertions pass.

---

## 2. What to build

Add per-position **season aggregates** to both endpoints, summed over the same regular-season
rows those endpoints already use for `games_played` (`game_no < _POSTSEASON_FIRST_WEEK`).
**Do not change any existing field** — the frontend and five gates depend on them.

Add one nested object, `stats`, whose keys vary by position:

| position | totals | per-game / rate |
|---|---|---|
| QB | `cmp att pass_yds pass_td intc carries rush_yds rush_td` | `cmp_pct pass_yds_per_game rush_yds_per_game` |
| RB | `carries rush_yds rush_td rec targets rec_yds rec_td` | `rush_yds_per_carry rec_yds_per_rec carries_per_game` |
| WR / TE | `rec targets rec_yds rec_td carries rush_yds rush_td` | `rec_yds_per_rec catch_pct rec_per_game` |
| PK | `fg_made fg_att pat_made pat_att fg_long` + the six distance buckets as made/att **pairs** | `fg_pct` |
| DEF | leave as is — `dst_pts_total` / `dst_pts_per_game` are correct |

Rules, from the reference implementation and from `honest-data-ui`:

1. **Regular season and postseason never merge.** ESPN keeps them in separate containers.
   Use the same week bound the endpoints already use.
2. **`null` for not-applicable, never `0.0`.** A kicker's `rec_yds` is not zero, it is
   absent. A gate already enforces this for PPR (`A1b`, `B2b`) and it will be extended.
3. **Made/attempted stay a pair** (`36-42`), not two divided columns.
4. A player with no logs gets `stats: null`, not an object of zeros.

---

## 3. Done means

Report payloads, not adjectives:

```bash
curl -s "http://127.0.0.1:8098/api/nfl/draft/player/7979" | python3 -m json.tool   # Gibbs RB
curl -s "http://127.0.0.1:8098/api/nfl/draft/player/469"  | python3 -m json.tool   # Allen QB
curl -s "http://127.0.0.1:8098/api/nfl/draft/player/882"  | python3 -m json.tool   # Aubrey PK
```

- Gibbs' `stats.carries` must equal `SELECT SUM(json_extract(stats,'$.carries'))` over his
  regular-season logs. **Print both numbers side by side.** A number that only agrees with
  itself is not verified.
- Aubrey's bucket pairs must sum to `fg_made`/`fg_att`.
- Josh Allen must carry both passing and rushing totals — a QB runs.
- Existing fields byte-identical by the full-payload hash procedure in §1b.
- Job15 lands first. `REG-adp-dst` must already be green before this task starts; real-stats
  must not change its values.
- Gates and frontend verification are orchestrator-owned. Hermes runs only the focused
  backend Python tests and reports their exact command and count.

## 4. Scope

Exact allowed files:

- `backend/routers/nfl_offseason.py` — owns `/api/nfl/draft-board`;
- `backend/routers/nfl_mock_draft.py` — owns `/api/nfl/draft/player/{id}`;
- `backend/test_nfl_offseason_api.py`;
- `backend/test_nfl_mock_draft.py`.

The earlier two-file scope was impossible: the board endpoint does not live in
`nfl_mock_draft.py`. Do not touch any other file, including shared utils, ingest or schema
code, `.tsx`/`.ts`, `pages/`, `components/`, `lib/`, task/spec/docs files, host config,
or `verify-gates.sh`.

Do not duplicate the position/rate/null rules between endpoints. Use one pure formatter
inside the allowed router files; extend the board's existing aggregate scan and the detail
endpoint's existing JSON loop. Do not add an N+1 query or a second full-table scan.

Never run `npm`, `npx`, `yarn`, or `pnpm`. Do not run frontend builds or Jest. Do not start,
stop, restart or kill dev servers, and do not touch `:3093`, `:3096`, `:3098`, `:8093`,
`:8096`, or `:8098`.

Note `player_game_logs` contains **no `DEF` rows at all** — team defenses are not player rows
in it. Anything that infers presence from that table is wrong for D/ST; see B17 in
`TASK-job15-dst-published-adp.md` §6b.
