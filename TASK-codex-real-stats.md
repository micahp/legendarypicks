# TASK (Codex, backend) — Player Rankings shows no football stats. The data is already there.

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
- Existing fields byte-identical. `bash verify-gates.sh all` still 13 PASS + REG-render, and
  `REG-adp-dst` still RED (that is job15's, not yours).

## 4. Scope

`backend/` only — `routers/nfl_mock_draft.py` and its tests. **No `.tsx`/`.ts`** (I own the
frontend and will render this once it lands). Never run `npm`/`npx`. Do not start dev servers
or restart `:3096`/`:8096`. Do not touch `verify-gates.sh`.

Note `player_game_logs` contains **no `DEF` rows at all** — team defenses are not player rows
in it. Anything that infers presence from that table is wrong for D/ST; see B17 in
`TASK-job15-dst-published-adp.md` §6b.
