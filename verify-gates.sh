#!/usr/bin/env bash
# Chunk gates for the LP branch work. Expected values FIXED 2026-07-28, before
# the code was written, so they cannot be retrofitted to whatever was produced.
# Owned by Claude, not by Hermes. Run: bash verify-chunks.sh [chunk]
#
# Each gate prints  PASS <id>  or  FAIL <id>  and nothing else that matters.

# Overridable so a delegated worktree can point these at ITS OWN servers. Defaults are
# the main branch tree. A worktree that runs this without overriding them verifies the
# MAIN tree and reports success while its own code was never executed — that is the
# failure mode this parameterisation exists to prevent, so set all three together.
#   LP_GATE_W=/root/lp-<task> LP_GATE_B=http://127.0.0.1:8093 LP_GATE_F=http://127.0.0.1:3093
#
# The defaults were `/root/lp-team-vocab` + :8098/:3098 until 2026-08-02 — a task
# worktree and its servers, all three long gone. `verify-gates.sh all` therefore ran
# every source gate against a directory that does not exist and every HTTP gate against
# a closed port, and reported the result as ordinary red gates: FAIL B1, FAIL B4,
# FAIL A1. Indistinguishable, in the output, from the code being broken. A default that
# names somebody's finished task is a default with an expiry date on it; these name the
# main tree and the pair it actually serves on (`next dev -p 3096`, `uvicorn --port 8096`).
W="${LP_GATE_W:-/root/legendarypicks}"
B="${LP_GATE_B:-http://127.0.0.1:8096}"
F="${LP_GATE_F:-http://127.0.0.1:3096}"
# The PROD backend. COV-prod grades the deployed registry, not the dev one —
# 2026-08-03 proved a dev-green registry can ship prod a leagues page that says
# "isn't available yet" for every league. A gate that only reads $B certifies the
# dev tree, and the deploy was exactly the gap between the two.
P="${LP_GATE_P:-http://127.0.0.1:8100}"
# The file the prod backend serves from. COV-identity grades the SCHEMA, which no
# HTTP surface can report: a table keyed by the player's name serves correct rows
# right up until the spine renames somebody.
D="${LP_GATE_D:-/root/legendarypicks/backend/data/picks.db}"
echo "── gates against W=$W B=$B F=$F P=$P D=$D ──"

# ── the preflight, which is the same rule as the gates ─────────────────────────
# `grep -c pattern /nonexistent` prints 0 and B4 asks three of its six questions as
# "is this count 0?". So the shipped default did not merely fail — it answered half
# of B4 in the affirmative over an empty path. Absence of a file is absence of
# evidence, and evidence unavailable is a FAIL, not a pass and not a skip.
#
# Checked here, once, so no gate has to remember: every W gate calls need_w first.
w_problem=""
if [ ! -d "$W" ]; then
  w_problem="W=$W does not exist"
elif [ ! -d "$W/components" ] || [ ! -d "$W/backend" ] || [ ! -d "$W/lib" ]; then
  w_problem="W=$W is not an LP tree (no components/ + backend/ + lib/)"
elif [ -n "$LP_GATE_W" ] && { [ -z "$LP_GATE_B" ] || [ -z "$LP_GATE_F" ]; }; then
  # The exact mix the header warns about: a worktree's SOURCE graded by the main
  # tree's SERVERS. Every HTTP gate then passes on code the worktree never ran.
  w_problem="LP_GATE_W is set but $( [ -z "$LP_GATE_B" ] && echo LP_GATE_B ) $( [ -z "$LP_GATE_F" ] && echo LP_GATE_F ) is not — this would grade $W's source with $B/$F, which serve a different tree. Set all three."
fi
need_w(){ [ -z "$w_problem" ] && return 0; no "$1" "could not run: $w_problem"; return 1; }

# `grep -c` over a missing file is 0, and 0 is the passing answer to half these
# gates. Assert the surface exists before asking anything about it.
have_files(){ id=$1; shift; for f in "$@"; do [ -f "$f" ] || { no "$id" "missing file: $f — the gate had nothing to read"; return 1; }; done; return 0; }
PY=/root/legendarypicks/backend/venv/bin/python

ok(){ echo "PASS $1  ($2)"; }
no(){ echo "FAIL $1  ($2)"; }

# ── A1 · /api/nfl/draft/player/{id} — right QB, games_missed, kicker parity ──
a1(){
  curl -s --max-time 20 "$B/api/nfl/draft/player/16247" | $PY -c "
import sys,json
d=json.load(sys.stdin)
qb=(d.get('qb') or {})
name=qb.get('name'); gp=qb.get('games_played') or 0
gm='games_missed' in d and d['games_missed'] is not None
# Nacua is LAR. The QB must be the one who actually played, and games_missed must exist.
if name=='Matthew Stafford' and gp>=15 and gm: print('PASS A1  (qb=%s gp=%s games_missed=%s)'%(name,gp,d['games_missed']))
else: print('FAIL A1  (qb=%s gp=%s games_missed_present=%s)'%(name,gp,gm))
"
  curl -s --max-time 20 "$B/api/nfl/draft/player/882" | $PY -c "
import sys,json
d=json.load(sys.stdin)
ppr=d.get('ppr_per_game_played'); snap=d.get('snap_pct'); pk=d.get('pk_pts_per_game')
gp=d.get('games_played') or 0
# A kicker must not assert a PPR average of 0.0 — null or absent is correct there.
#
# But this gate used to accept 'pk is None' as well, and that made it blind to the
# opposite failure: it was green against a backend serving 32 of 38 kickers a real
# points-per-game AND against one serving zero, because absence passed either way.
# Absence is only honest when the player did not play. Aubrey played 17 games, so a
# null here is a missing measurement, not an honest one.
if ppr is None and isinstance(pk,(int,float)) and pk>0: print('PASS A1b (Aubrey ppr=%s gp=%s pk_pts_per_game=%s)'%(ppr,gp,pk))
elif ppr is not None: print('FAIL A1b (Aubrey ppr=%s snap=%s  <- 0.0 is a false measurement)'%(ppr,snap))
else: print('FAIL A1b (Aubrey gp=%s but pk_pts_per_game=%s  <- played, so null is data loss not honesty)'%(gp,pk))
"
  curl -s --max-time 30 "$B/api/nfl/draft-board?season=2026&position=PK&limit=100" | $PY -c "
import sys,json
d=json.load(sys.stdin)
rows=d.get('players') or []
# Population form of the same question. One player passing says nothing about the
# column; assert a COUNT of real values, or the gate certifies an empty database.
elig=[r for r in rows if (r.get('games_played') or 0)>=8]
cov=[r for r in elig if isinstance(r.get('pk_pts_per_game'),(int,float))]
n,c=len(elig),len(cov)
if n>=20 and c>=int(n*0.8): print('PASS A1c (pk_pts_per_game on %d of %d kickers with gp>=8, n_rows=%d)'%(c,n,len(rows)))
else: print('FAIL A1c (pk_pts_per_game on %d of %d kickers with gp>=8, n_rows=%d  <- need n>=20 and 80%% covered)'%(c,n,len(rows)))
"
}

# ── A2 · B1 mid-season team change: denominator must be a real season ──
a2(){
  curl -s --max-time 30 "$B/api/nfl/draft-board?season=2026&limit=100" | $PY -c "
import sys,json
d=json.load(sys.stdin)
bad=[(x['name'],x.get('games_played'),x.get('team_games')) for x in d['players'] if (x.get('team_games') or 0)>18]
neg=[(x['name'],x.get('games_missed')) for x in d['players'] if (x.get('games_missed') or 0)<0]
if not bad and not neg: print('PASS A2  (no team_games>18, no negative games_missed, n=%d)'%len(d['players']))
else: print('FAIL A2  (team_games>18: %s | negative missed: %s)'%(bad[:3],neg[:3]))
"
}

# ── A3 · R4 nfl_schedule exposed; 32 teams, exactly one bye each ──
a3(){
  for p in /api/nfl/schedule /api/nfl/schedule/2025 /api/nfl/team-weeks; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$B$p")
    [ "$code" = "200" ] && echo "  found endpoint $p (200)"
  done
  curl -s --max-time 20 "$B/api/nfl/schedule?season=2025" | $PY -c "
import sys,json
try: d=json.load(sys.stdin)
except Exception as e: print('FAIL A3  (no JSON: %s)'%e); raise SystemExit
teams=d.get('teams') or d
try:
    n=len(teams)
    byes=[t.get('bye_week') for t in teams] if isinstance(teams,list) else []
    onebye=all(isinstance(b,int) for b in byes)
    if n==32 and onebye and len(set(byes))>1: print('PASS A3  (32 teams, byes across %d distinct weeks)'%len(set(byes)))
    else: print('FAIL A3  (teams=%s byes_ok=%s distinct=%s)'%(n,onebye,len(set(byes))))
except Exception as e: print('FAIL A3  (shape: %s)'%e)
" 2>/dev/null || echo "FAIL A3  (endpoint absent)"
}

# ── B1 · position filter offers DEF and PK ──
b1(){
  need_w B1 || return
  f=$W/components/Leagues/hooks/useNflDraftBoard.ts
  have_files B1 "$f" || return
  line=$(grep -n "const POSITIONS" "$f" | head -1)
  if grep -q "'DEF'" "$f" && grep -q "'PK'" "$f"; then ok B1 "$line"; else no B1 "$line"; fi
}

# ── B2 · the branch's fields actually render ──
b2(){
  need_w B2 || { no B2b "could not run: $w_problem"; return; }
  hits=$(cd $W && grep -rl "games_missed\|dst_pts_total\|dst_pts_per_game\|pk_pts" components/ pages/ 2>/dev/null | grep -v "types.ts" | tr '\n' ' ')
  if [ -n "$hits" ]; then ok B2 "rendered in: $hits"; else no B2 "zero hits outside types.ts"; fi
  # and a kicker must not print 0.0 through the served page.
  # This one goes through the FRONTEND proxy on purpose — it proves the served
  # page path, not just the backend. If the frontend is down the gate FAILS;
  # it must never pass by default because the evidence was unavailable.
  body=$(curl -s --max-time 30 "$F/api/nfl/draft-board?season=2026&limit=100&position=PK")
  if [ -z "$body" ]; then
    no B2b "frontend $F unreachable — gate could not run (this is a FAIL, not a skip)"
  else
    printf '%s' "$body" | $PY -c "
import sys,json
raw=sys.stdin.read()
try: d=json.loads(raw)
except Exception as e:
    print('FAIL B2b (frontend returned non-JSON: %s | first 80 chars: %r)'%(e,raw[:80])); raise SystemExit
p=d.get('players',[])
z=[x['name'] for x in p if x.get('ppr_per_game_played')==0.0]
if not p: print('FAIL B2b (frontend served 0 kickers — nothing was measured)')
elif z:   print('FAIL B2b (%d kickers show 0.0: %s)'%(len(z),z[:3]))
else:     print('PASS B2b (no kicker asserts ppr 0.0, n=%d)'%len(p))
"
  fi
}

# ── B4 · M7: scrollbar shown, measured availability fields used ──
b4(){
  need_w B4 || return
  room=$W/components/MockDraft/DraftRoom.tsx
  # The four surfaces that RENDER games_played/team_games, measured 2026-08-03:
  #   columns.tsx:189, RostersTab.tsx:98, ResultsScreen.tsx:232 — poolTeamGames direct
  #   PoolList.tsx:324 — row.team_games, which lib/mockDraft/api.ts:100 derives from it
  #
  # This list used to be DraftRoom.tsx + PoolList + ResultsScreen + api.ts, and asked
  # for poolTeamGames in three of them. `5f0e08c` split the 1,053-line DraftRoom into
  # the shell plus PlayersTab/columns/RostersTab and moved every fraction out of it,
  # so from 2026-07-29 the gate sat at 2/3 naming a file with no such responsibility
  # while columns.tsx and RostersTab.tsx — which now carry it — went unmeasured
  # entirely. Both could have hardcoded 17 without moving this number. The gate was
  # asking the right question of the wrong files.
  renderers="$W/components/MockDraft/columns.tsx $W/components/MockDraft/RostersTab.tsx $W/components/MockDraft/ResultsScreen.tsx $W/lib/mockDraft/api.ts"
  files="$room $W/components/MockDraft/PoolList.tsx $renderers"
  # Three of the six checks below pass when their count is 0, which is also what a
  # missing file counts to. Without this line B4 half-agreed with itself over a
  # deleted worktree for the whole of 2026-07-28..08-02.
  have_files B4 $files || return
  hidden=$(grep -En "scrollbar-width:none|::-webkit-scrollbar]:hidden" "$room" 2>/dev/null | wc -l)
  hardcoded=$(grep -En \
    "const TEAM_GAMES|team_games:[[:space:]]*17|possible[[:space:]]*\\+=[[:space:]]*TEAM_GAMES|/\\$\\{TEAM_GAMES\\}" \
    $files 2>/dev/null | wc -l)
  reconstructed=$(grep -En \
    "team_games[[:space:]]*-[[:space:]].*games_played|games_played[[:space:]]*<.*team_games|team_games[[:space:]]*-[[:space:]].*games_played" \
    $files 2>/dev/null | wc -l)
  schedule_users=$(grep -l "poolTeamGames" $renderers 2>/dev/null | wc -l)
  pool_schedule=$(grep -c "row.team_games" "$W/components/MockDraft/PoolList.tsx" 2>/dev/null)
  api_missed=$(grep -c "games_missed:[[:space:]]*player.games_missed" "$W/lib/mockDraft/api.ts" 2>/dev/null)

  if [ "$hidden" = "0" ] &&
     [ "$hardcoded" = "0" ] &&
     [ "$reconstructed" = "0" ] &&
     [ "$schedule_users" = "4" ] &&
     [ "$pool_schedule" -ge "1" ] &&
     [ "$api_missed" = "1" ]; then
    ok B4 "scrollbar shown; schedule weeks used across all four rendering surfaces; games_missed preserved"
  else
    no B4 "hidden=$hidden hardcoded=$hardcoded reconstructed=$reconstructed schedule_users=$schedule_users/4 pool_schedule=$pool_schedule api_missed=$api_missed"
  fi
}

# ── COV · the coverage gate. EXPECTED VALUES WRITTEN 2026-08-02, BEFORE THE CODE. ──
#
# Derived from the publisher and from our own per-team counts, NOT from whatever
# the ingest produces — see docs/DATA-COVERAGE-CONTRACT.md §9 for the arithmetic:
#
#   ESPN publishes 1239 nba 2026 type-2 events
#     = 1230 fixtures + 1 NBA Cup final + 4 All-Star exhibitions + 4 postponed shells
#   so ours must be 1231, and every team must land on exactly 82 games
#   (NY and SA at 83 — they played the Cup final, which does not count toward 82).
#
# The 4 games missing on 2026-08-02 (401810401, 401810523, 401810532, 401857824) were
# lost to `BEGIN` inside an open transaction and RECORDED as failures, next to a
# coverage row claiming failure_count=0. COV-honest is the gate for that specific lie:
# it does not check that a run succeeded, it checks that the row cannot claim more
# than the run can support. Do not relax these to make them green.
COVDB="${LP_GATE_DB:-/root/legendarypicks/backend/data/picks.dev.db}"
cov(){
  $PY - "$COVDB" <<'PY'
import sqlite3, sys, os, collections
DB = sys.argv[1]
con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
q = lambda s, a=(): con.execute(s, a).fetchall()

# ── COV-nba ── 1231 games, and every team on exactly 82 but the two Cup finalists.
n = q("SELECT COUNT(DISTINCT game_id) FROM team_game_results WHERE league='nba' AND season=2026")[0][0]
per = dict(q("SELECT team, COUNT(DISTINCT game_id) FROM team_game_results"
             " WHERE league='nba' AND season=2026 GROUP BY team"))
dist = collections.Counter(per.values())
at83 = sorted(t for t, v in per.items() if v == 83)
short = sorted((t, v) for t, v in per.items() if v < 82)
if n == 1231 and dist.get(82) == 28 and at83 == ['NY', 'SA'] and not short:
    print('PASS COV-nba (1231 games, 28 teams at 82, NY/SA at 83)')
else:
    print('FAIL COV-nba (games=%d dist=%s at83=%s short=%s)' % (n, dict(dist), at83, short))

# ── COV-nhl ── the same write bug cost NHL one game; the two tables must agree.
# The player_game_logs side carried NO season filter until 2026-08-02, and that
# omission is why this gate sat green over the season-key split: unfiltered, it
# counted 1312 rows keyed '20252026' and called them the 2026 season. A gate
# that asks a laxer question than its consumers do is not a gate. Both sides now
# name the season, the same way /api/coverage does.
#
# The player_game_logs side also names the PHASE, for the mirror-image reason. It
# counted every NHL row as a regular-season game, which was true only because the
# ingest had never requested any other phase. team_game_results holds the regular
# season and has no game_type column at all, so an unphased count here starts
# disagreeing with it the moment playoff logs land — reporting a season that just
# got more complete as one that broke.
tgr = q("SELECT COUNT(DISTINCT game_id) FROM team_game_results WHERE league='nhl' AND season=2026")[0][0]
pgl = q("SELECT COUNT(DISTINCT game_id) FROM player_game_logs"
        " WHERE league='nhl' AND season=2026 AND game_type='REG'")[0][0]
if tgr == 1312 and pgl == 1312:
    print('PASS COV-nhl (1312 REG in both tables)')
else:
    print('FAIL COV-nhl (team_game_results=%d player_game_logs REG=%d, want 1312/1312)' % (tgr, pgl))

# ── COV-honest ── a coverage row may not claim more than its run can support.
# Three ways the 2026-07-14 row lied, each its own assertion:
bad = []
for run_id, league, status, exp_g, got_g, fc, through in q(
        "SELECT run_id, league, status, expected_games, fetched_games, failure_count,"
        " checked_through FROM team_stats_coverage"):
    actual = q("SELECT COUNT(*) FROM team_stats_ingestion_failures WHERE run_id=?", (run_id,))[0][0]
    if fc != actual:
        bad.append('%s: failure_count=%s but %d rows recorded' % (league, fc, actual))
    # `in_progress` carries the same burden as `complete`: every published game the
    # row claims is present and paired, over a season that has not ended. It is a
    # narrower claim, not a weaker one, so it answers to the same two assertions.
    if status in ('complete', 'in_progress') and actual:
        bad.append('%s: status=%s with %d failures' % (league, status, actual))
    if status in ('complete', 'in_progress') and exp_g != got_g:
        bad.append('%s: status=%s with expected=%s fetched=%s' % (league, status, exp_g, got_g))
    # And one of its own. `in_progress` says "checked through a date"; without the
    # date the claim cannot be falsified, which would make it the loophole the other
    # three values were written to prevent.
    if status == 'in_progress' and not through:
        bad.append('%s: status=in_progress with no checked_through to bound the claim' % league)
    if status not in ('complete', 'in_progress', 'partial', 'unverified'):
        bad.append('%s: status=%r not in the four-value vocabulary' % (league, status))
rows = q("SELECT COUNT(*) FROM team_stats_coverage")[0][0]
if rows and not bad:
    print('PASS COV-honest (%d coverage rows, none claiming more than its run supports)' % rows)
else:
    print('FAIL COV-honest (%s)' % ('no coverage rows at all' if not rows else '; '.join(bad)))

# ── COV-keys ── one league, one season vocabulary, across every table that has
# a season column. NHL carried '20252026' in player_game_logs and player_stats
# while team_game_results and team_stats_coverage said '2026' — so
# 'WHERE season=2026' returned 0 for a season we held complete, and the
# reconcile reported it as missing data. A wrong key does not raise, it misses.
# Shape (4-digit vs 8-digit) is what is compared; two 4-digit years are just two
# seasons. This gate has to hold for every league we add, including ones whose
# publisher we have not met yet.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(DB)), '..')))
try:
    from season_keys import audit_season_keys, SEASON_KEYED_TABLES
except Exception as e:
    print('FAIL COV-keys (cannot import season_keys: %s)' % e)
else:
    split = audit_season_keys(con)
    cross = {}
    for league in sorted({r[0] for t, c in SEASON_KEYED_TABLES
                          for r in q('SELECT DISTINCT %s FROM %s' % (c, t))}):
        shapes = {}
        for table, col in SEASON_KEYED_TABLES:
            for (s,) in q('SELECT DISTINCT season FROM %s WHERE %s=?'
                          ' AND season IS NOT NULL AND season != ""' % (table, col),
                          (league,)):
                shapes.setdefault(len(str(s)), set()).add(table)
        if len(shapes) > 1:
            cross[league] = {k: sorted(v) for k, v in sorted(shapes.items())}
    if split or cross:
        parts = ['%s.%s holds shapes %s' % (f['table'], f['league'],
                                            [s[0] for s in f['shapes']])
                 for f in split]
        parts += ['%s: %s' % (lg, d) for lg, d in sorted(cross.items())]
        print('FAIL COV-keys (%s)' % '; '.join(parts))
    else:
        print('PASS COV-keys (every league speaks one season vocabulary in every table)')

# ── COV-source ── RED ON PURPOSE, and it should stay red until the rows below are
# attributed. Every row in a season-keyed table must say which publisher wrote it.
# The NHL key split was undetectable because nothing recorded that
# team_game_results is ESPN while player_game_logs is nhle.com. Known-unattributed
# as of 2026-08-02: mlb team_game_results (3305) + team_game_stats (16), nfl 2024
# (570) and 2026 (544) team_game_results, and all team_game_stats rows written
# before the column existed. They are NOT stamped by guessing — see
# stamp_team_result_source.py, which attributes only from a recorded run_id.
try:
    from provenance import TRACKED
except Exception as e:
    print('FAIL COV-source (cannot import provenance: %s)' % e)
else:
    unattributed = []
    for table, league_col, _ts in TRACKED:
        cols = {r[1] for r in q('PRAGMA table_info(%s)' % table)}
        if not cols:
            continue
        if 'source' not in cols:
            unattributed.append('%s has no source column at all' % table)
            continue
        for lg, n in q('SELECT %s, COUNT(*) FROM %s WHERE source IS NULL OR source=""'
                       ' GROUP BY %s' % (league_col, table, league_col)):
            unattributed.append('%s.%s %d rows' % (table, lg, n))
    if not unattributed:
        print('PASS COV-source (every row names its publisher)')
    else:
        print('FAIL COV-source (%s)' % '; '.join(unattributed))

# ── COV-gametype ── EXPECTED VALUES WRITTEN 2026-08-02, BEFORE THE CODE.
# `game_type` is the column `routers/nfl_offseason.py` guards on for EXISTENCE and
# then filters on for VALUE. Where the values are NULL, `AND game_type='REG'` matches
# nothing, games_played returns 0, and a healthy player renders "missed 82" in amber.
# So: a league-season we have judged in team_stats_coverage may not hold a single NULL.
#
# The NHL number is the publisher's, not the ingest's: ESPN publishes 1312 nhl 2026
# regular-season events, the same integer COV-nhl asserts. The row count (48,017
# player-games) is deliberately NOT asserted — nobody publishes it, so it could only
# be copied back off our own output, which is the ingest grading itself.
#
# RED ON PURPOSE for nba 2026 until its ingest stamps the column too. Do not scope
# this gate to nhl to make it green — the point is that it names what is left.
gt_bad = []
judged = q("SELECT DISTINCT league, season FROM team_stats_coverage")
for lg, season in judged:
    total, nulls = q("SELECT COUNT(*), SUM(game_type IS NULL) FROM player_game_logs"
                     " WHERE league=? AND season=?", (lg, season))[0]
    if not total:
        continue          # no logs for that season is COV-nhl's problem, not this one
    if nulls:
        gt_bad.append('%s %s: %d/%d rows NULL' % (lg, season, nulls, total))
reg_games = q("SELECT COUNT(DISTINCT game_id) FROM player_game_logs"
              " WHERE league='nhl' AND season=2026 AND game_type='REG'")[0][0]
if reg_games != 1312:
    gt_bad.append('nhl 2026 REG games=%d, published 1312' % reg_games)
# And a phase nobody asked for is a phase nobody has. The ingest requested game
# type 2 and only game type 2, so for a season that ended 2026-06-15 we held none
# of the postseason and nothing said so — the column was uniformly REG, which
# reads exactly like a complete column. 82 is `totalPlayoffGames` from
# api.nhle.com/stats/rest/en/season?cayenneExp=id=20252026, published by the NHL,
# not counted off our own rows.
post_games = q("SELECT COUNT(DISTINCT game_id) FROM player_game_logs"
               " WHERE league='nhl' AND season=2026 AND game_type='POST'")[0][0]
if post_games != 82:
    gt_bad.append('nhl 2026 POST games=%d, published 82' % post_games)
# NBA, added 2026-08-02. Until now this gate's only claim about nba was 'no NULLs',
# which a single uniformly-REG column satisfies just as well as a correct one — the
# exact way NHL held zero postseason games while looking complete. These are counted
# off ESPN's published season types, not off our rows:
#   sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/2026/types/N/events?limit=1
#     type 3 post   -> 85     type 5 playin -> 6
# REG is 1231 rather than type 2's 1239 because ESPN files All-Star weekend inside
# type 2; reconcile_totals derives that subtraction from the publisher, and COV-nba
# asserts the same 1231 against team_game_results.
for phase, expected, note in (('REG', 1231, 'published 1239 type-2 less exhibition and not-played'),
                              ('POST', 85, 'published type-3 events'),
                              ('PLAYIN', 6, 'published type-5 events')):
    got = q("SELECT COUNT(DISTINCT game_id) FROM player_game_logs"
            " WHERE league='nba' AND season=2026 AND game_type=?", (phase,))[0][0]
    if got != expected:
        gt_bad.append('nba 2026 %s games=%d, %s %d' % (phase, got, note, expected))
if not gt_bad:
    print('PASS COV-gametype (every judged season has game_type on every row;'
          ' nhl 2026 = 1312 REG / 82 POST; nba 2026 = 1231 REG / 85 POST / 6 PLAYIN)')
else:
    print('FAIL COV-gametype (%s)' % '; '.join(gt_bad))
PY

  # ── COV-api ── the registry has to be reachable, and every league the switcher
  # offers must have a complete row behind it. A hardcoded switcher passes this
  # gate by accident today; after the change it can only pass by being derived.
  curl -s --max-time 20 "$B/api/coverage" | $PY -c "
import sys, json
try: d = json.load(sys.stdin)
except Exception as e: print('FAIL COV-api (no JSON from /api/coverage: %s)' % e); raise SystemExit
rows = d if isinstance(d, list) else d.get('coverage', [])
need = {'league','season','status'}
missing = [r for r in rows if not need <= set(r)]
complete = sorted({r['league'] for r in rows if r.get('status') == 'complete'})
if rows and not missing and complete:
    print('PASS COV-api (%d rows, complete=%s)' % (len(rows), complete))
else:
    print('FAIL COV-api (rows=%d malformed=%d complete=%s)' % (len(rows), len(missing), complete))
"

  # ── COV-prod ── the DEPLOYED registry, not the dev one. Added 2026-08-03 after
  # v0.7.0 shipped a prod whose /api/coverage returned [] (the team_stats_coverage
  # tables were never migrated) — the leagues page rendered "isn't available yet"
  # for every league while every dev gate was green. The fix that closed it was
  # migrate_team_stats_from_dev.py against a verified clone, then the swap. This
  # gate exists so the next promotion proves the prod surface, not the dev one.
  curl -s --max-time 20 "$P/api/coverage" | $PY -c "
import sys, json
try: d = json.load(sys.stdin)
except Exception as e: print('FAIL COV-prod (no JSON from prod /api/coverage: %s)' % e); raise SystemExit
rows = d if isinstance(d, list) else d.get('coverage', [])
need = {'league','season','status'}
missing = [r for r in rows if not need <= set(r)]
complete = sorted({r['league'] for r in rows if r.get('status') == 'complete'})
if rows and not missing and complete:
    print('PASS COV-prod (%d rows, complete=%s)' % (len(rows), complete))
else:
    print('FAIL COV-prod (rows=%d malformed=%d complete=%s)' % (len(rows), len(missing), complete))
"

  # ── COV-leaders ── every league the registry offers must actually serve stats.
  #
  # Added 2026-08-03, when TWO leagues were serving 503 on prod at the same time
  # while every other gate was green and the leagues page itself looked fine:
  #   mlb — 71 stale rows stranded under a placeholder name_norm, real duplicates
  #   nhl — 21 rows the spine had not matched, and ZERO real duplicates; the guard
  #         was counting NULL player_ids as one co-owning player
  # Both surfaced as an empty Stats tab, not an error message. The Batting sub-tab
  # loads first, so a single 503 there rendered zero tables and Pitching was never
  # reached — which is why "MLB pitching isn't returning" was the report.
  #
  # The league list comes from the DEPLOYED registry rather than a literal, so a
  # league added later cannot quietly escape this gate. Sub-surfaces are listed
  # per league because a league's second stat type is exactly what the first one
  # failing hides.
  $PY - "$P" <<'PY'
import json, sys, urllib.request
P = sys.argv[1]
SUBTYPES = {"mlb": ["batting", "pitching"]}   # extend when a league gains a second type

def get(url):
    with urllib.request.urlopen(url, timeout=25) as fh:
        return json.load(fh), fh.status

try:
    reg, _ = get(P + "/api/coverage")
except Exception as exc:
    print("FAIL COV-leaders (prod registry unreachable: %s)" % exc)
    raise SystemExit
rows = reg if isinstance(reg, list) else reg.get("coverage", [])
leagues = sorted({r["league"] for r in rows if r.get("league")})
if not leagues:
    print("FAIL COV-leaders (registry named no leagues — nothing was measured)")
    raise SystemExit

bad, checked = [], 0
for lg in leagues:
    for kind in SUBTYPES.get(lg, [None]):
        url = "%s/api/%s/leaders?limit=5%s" % (P, lg, "&type=" + kind if kind else "")
        label = lg + ("/" + kind if kind else "")
        checked += 1
        try:
            doc, _ = get(url)
        except Exception as exc:
            # An HTTPError carries the detail; a 503 that says WHY is the whole point.
            detail = getattr(exc, "read", lambda: b"")()[:120].decode("utf-8", "replace")
            bad.append("%s: %s %s" % (label, exc, detail))
            continue
        if not (doc.get("leaders") or []):
            bad.append("%s: 200 but zero leaders" % label)
if bad:
    print("FAIL COV-leaders (%d/%d surfaces broken: %s)" % (len(bad), checked, "; ".join(bad[:4])))
else:
    print("PASS COV-leaders (%d surfaces across %s all serve rows)" % (checked, ",".join(leagues)))
PY

  # ── COV-identity ── the prod table is keyed by the PLAYER, not by their name.
  #
  # COV-leaders catches the outage; this catches the cause, which is the only one
  # of the two that can be fixed once. `player_stats` was keyed
  # UNIQUE(name_norm,league,season,stat_type), so when the spine resolved
  # `mlbam_680869` into `zack gelof` the key moved out from under the row and the
  # next ingest inserted a second one. Zack Gelof sat at 54 games beside his
  # current 66 and /api/mlb/leaders failed closed on it.
  #
  # This grades the DEPLOYED file rather than the dev one, for the same reason
  # COV-prod does: the migration is a property of a database, not of a branch, and
  # a green dev schema says nothing about what prod is serving from. It asserts
  # the registered migration AND its eight data conditions, so a re-introduced
  # unowned source or duplicate owner goes red before it can take a league down.
  $PY - "$D" <<'PY'
import sys
sys.path.insert(0, "/root/legendarypicks/backend")
import migrate_player_stats as mps

path = sys.argv[1]
try:
    result = mps.check_database(path)
except Exception as exc:
    # An unreadable database is evidence unavailable, which is a FAIL. A gate that
    # skips here would report green over a schema nobody looked at.
    print("FAIL COV-identity (cannot read %s: %s)" % (path, exc))
    raise SystemExit
dirty = {k: v for k, v in result.issues.items() if v}
if result.ok and not dirty:
    print("PASS COV-identity (%s: UNIQUE(player_id,league,season,stat_type), 0 offending rows)"
          % mps.MIGRATION_ID)
else:
    # `detail` already enumerates the offending counts when the state is blocked;
    # appending them again is how a gate's own output stops being readable.
    extra = "" if (result.state == "blocked" or not dirty) else \
        " | " + ", ".join("%s=%d" % kv for kv in sorted(dirty.items()))
    print("FAIL COV-identity (%s: %s%s)" % (result.state, result.detail, extra))
PY
}

# ── always-on regressions: nothing already working may break ──
reg(){
  # ── REG-pool · the draft pool is the six draftable positions and nothing else ──
  #
  # This gate used to read `len(p)==11515` AND those same six per-position counts,
  # which sum to 4,506. For both halves to hold, 7,009 players would have had to sit
  # in positions the gate never named. `9895508` (2026-08-01 09:16) constrained the
  # query to _DRAFT_POSITIONS on purpose and the pool went 11,515 -> 4,507, so from
  # that minute the gate was not merely red, it was UNSATISFIABLE — its total
  # asserted the universe while its parts asserted the constraint. A total that
  # contradicts its own breakdown is not an expectation, it is two.
  #
  # Rewritten 2026-08-03 as claims that cannot drift apart:
  #   - no position outside the six may appear (this is the 9895508 decision itself)
  #   - len(players) must equal the sum of the counts (catches dupes and truncation)
  #   - DEF is exactly 32, because the league has exactly 32 defenses
  #   - the volatile four get a +/-3% band around counts measured against the served
  #     DB on 2026-08-03. Roster churn moves these by ones (RB was 1122 on 07-31 and
  #     is 1123 today); a source or join change moves them by hundreds. The band is
  #     for the first and must stay tight enough to catch the second.
  curl -s --max-time 60 "$B/api/nfl/mock-draft/pool?season=2026" | $PY -c "
import sys,json,collections
d=json.load(sys.stdin);p=d['players']
c=collections.Counter(x['position'] for x in p)
DRAFTABLE={'QB','RB','WR','TE','PK','DEF'}
base={'QB':470,'RB':1123,'WR':1791,'TE':882,'PK':209}
why=[]
stray=sorted(set(c)-DRAFTABLE)
if stray: why.append('undraftable positions served: %s'%stray)
if len(p)!=sum(c.values()): why.append('len=%d but counts sum to %d'%(len(p),sum(c.values())))
if c['DEF']!=32: why.append('DEF=%d, the league has 32'%c['DEF'])
for k,v in base.items():
    if abs(c[k]-v) > max(1, round(v*0.03)): why.append('%s=%d, baseline %d'%(k,c[k],v))
print(('PASS REG-pool (%d, %s)'%(len(p),dict(c))) if not why else ('FAIL REG-pool (%d %s :: %s)'%(len(p),dict(c),'; '.join(why))))
"
  # ── REG-adp-dst — EXPECTED VALUES WRITTEN 2026-07-31, BEFORE THE CODE. ──
  # Measured directly from ESPN the same day (kona_player_info, limit 20000).
  # All 32 D/ST carry a published PPR rank (234-519) and ESPN keys them with
  # NEGATIVE ids (-16000 - proTeamId). v0.7.0 T1: the pool's D/ST ADP IS that
  # published PPR rank (DEN 234, SEA 239, HOU 236, LAR 240) — previously the
  # pool showed averageDraftPosition (DEN 89.9) which job15 landed.
  # This gate is RED until the v0.7.0 ingest lands on the served DB. Do not
  # relax it to make it green — a diff to these numbers is a finding.
  # Tolerance is for ESPN drift only.
  curl -s --max-time 60 "$B/api/nfl/mock-draft/pool?season=2026" | $PY -c "
import sys,json
d=json.load(sys.stdin);p=d['players']
dst={x['team']:x for x in p if x['position']=='DEF'}
nulls=[t for t,x in dst.items() if x.get('adp') is None]
exp={'DEN':234,'HOU':236,'LAR':240,'SEA':239}
bad=[(t,v,dst.get(t,{}).get('adp')) for t,v in exp.items()
     if dst.get(t,{}).get('adp') is None or abs(dst[t]['adp']-v)>12]
if len(dst)==32 and not nulls and not bad:
    print('PASS REG-adp-dst (32 D/ST, published PPR-rank ADP, DEN=%d SEA=%d)'%(dst['DEN']['adp'],dst['SEA']['adp']))
else:
    print('FAIL REG-adp-dst (n=%d null_adp=%d off_expected=%s)'%(len(dst),len(nulls),bad))
"
  curl -s --max-time 30 "$B/api/nfl/draft-board?season=2026&limit=100&position=DEF" | $PY -c "
import sys,json
d=json.load(sys.stdin);p=d.get('players',[])
print('PASS REG-dst (32 rows)' if len(p)==32 else 'FAIL REG-dst (%d rows)'%len(p))
"
  # Test runners: capture the EXIT CODE, never just grep the output. A runner that
  # dies (SIGBUS on a corrupt native binary, OOM, import error) prints nothing, and
  # a bare `grep | tail -1` turns that silence into a green line. These fail loud.
  # These three run IN $W. `cd` to a path that is not there fails the whole command
  # substitution, which reads back as exit≠0 — a runner that died, not a workspace
  # that was never there. Two different repairs; say which one it is.
  if ! need_w REG-pytest; then no REG-jest "could not run: $w_problem"; no REG-jest-all "could not run: $w_problem"
  else
  pyout=$(cd $W/backend && LP_DB_PATH=/root/picks.hermes.db ./venv/bin/python -m pytest test_nfl_mock_draft.py test_nfl_dst.py test_mock_draft_completion.py test_mock_draft_setup.py -q 2>&1); pyrc=$?
  pysum=$(printf '%s' "$pyout" | grep -E "passed|failed|error" | tail -1)
  if [ $pyrc -eq 0 ] && [ -n "$pysum" ]; then ok REG-pytest "$pysum"
  else no REG-pytest "exit=$pyrc  last: ${pysum:-<no output — runner died>}"; fi

  # REG-jest was `--testPathPattern='lib/mockDraft'` — 4 of the repo's 8 suites.
  # "jest 40/40" was therefore a claim about half the frontend, the same defect
  # REG-pytest has: a green gate is a claim about its SURFACE. Two gates now, so
  # the narrow one stays the go/no-go for mock-draft work and the wide one makes
  # the rest impossible to lose again.
  jsout=$(cd $W && /root/legendarypicks/node_modules/.bin/jest --testPathPattern='lib/mockDraft' --no-coverage 2>&1); jsrc=$?
  jssum=$(printf '%s' "$jsout" | grep -E "^Tests:" | tail -1)
  if [ $jsrc -eq 0 ] && [ -n "$jssum" ]; then ok REG-jest "$jssum"
  elif [ $jsrc -ge 128 ]; then no REG-jest "jest died with signal (exit=$jsrc, $( [ $jsrc -eq 135 ] && echo 'SIGBUS — corrupt native binary in the shared node_modules' || echo 'killed' )) — NO frontend tests ran"
  else no REG-jest "exit=$jsrc  ${jssum:-<no 'Tests:' line — nothing ran>}"; fi

  # ── REG-jest-all — RED ON PURPOSE, like REG-adp-dst. ──
  # The full frontend suite. As of 2026-07-28 it is 2 failed / 70 passed: both
  # failures are in components/Game/WCContext.test.tsx, introduced by 6719a1f
  # (WC match-minute chronology), and neither touches the mock draft. It is here
  # red rather than absent because a suite you cannot see cannot be fixed, and
  # because the count is what stops the next narrow gate being read as "green".
  jaout=$(cd $W && /root/legendarypicks/node_modules/.bin/jest --no-coverage 2>&1); jarc=$?
  jasum=$(printf '%s' "$jaout" | grep -E "^Tests:" | tail -1)
  if [ $jarc -eq 0 ] && [ -n "$jasum" ]; then ok REG-jest-all "$jasum"
  elif [ $jarc -ge 128 ]; then no REG-jest-all "jest died with signal (exit=$jarc) — NO frontend tests ran"
  else no REG-jest-all "exit=$jarc  ${jasum:-<no 'Tests:' line — nothing ran>}"; fi
  fi
  # Package COUNT is not package INTEGRITY. On 2026-07-28 an interrupted `npm install`
  # left next-swc truncated while the count stayed 538 and :3096 kept serving 200 off
  # the old (deleted) inode. Load the binary; presence proves nothing.
  n=$(ls /root/legendarypicks/node_modules | wc -l)
  swc=/root/legendarypicks/node_modules/@next/swc-linux-x64-gnu/next-swc.linux-x64-gnu.node
  # Two commands inside the inner bash so it forks node instead of exec'ing it —
  # the SIGBUS report is then written to the INNER shell's stderr, which we drop.
  swcrc=$(bash -c "node -e \"require('$swc')\" >/dev/null 2>&1; echo \$?" 2>/dev/null)
  if [ "$swcrc" = "0" ]; then ok REG-modules "$n packages, next-swc loads"
  else no REG-modules "$n packages BUT next-swc fails to load (exit=$swcrc) — corrupt native binary; every frontend build and jest run is dead"; fi
  echo -n "live dev server :3096 "; curl -s -o /dev/null -w "%{http_code}\n" --max-time 10 http://127.0.0.1:3096/
}

# ── REG-render · the only gate that renders React ──
# Every other gate above greps source or reads JSON. On 2026-07-28 all eight were green
# while the pool page crashed on first render. This one drives chromium, clicks, and fails
# on any console error. Exit code only — never grep its output.
# Negative control (do not delete this note): pointed at :3096, the branch without the
# overlay or the DEF/PK filters, it FAILS with "overlay never appeared" and "found 7 pills".
# A gate that has only ever passed has not been tested.
regrender(){
  need_w REG-render || return
  have_files REG-render "$W/scripts/render-gate.js" || return
  out=$(cd $W && LP_GATE_F="$F" timeout 400 node scripts/render-gate.js 2>&1); rc=$?
  line=$(printf '%s' "$out" | grep -E "^(PASS|FAIL) REG-render" | tail -1)
  if [ $rc -eq 0 ] && [ -n "$line" ]; then echo "$line"
  elif [ $rc -eq 124 ]; then no REG-render "timed out after 400s — browser never finished"
  else no REG-render "exit=$rc  ${line:-<no verdict line — the gate itself died>}"; fi
}

# ── OVL-width · the player overlay measured at the width a phone gives it ──
#
# "It was nice not to have to scroll to see all the stats" has now been declared
# fixed twice — once by trimming a column list, once by widening the card — and
# neither attempt was ever measured against the thing asked about. Nothing in the
# suite rendered the overlay at all: REG-render drives the mock-draft page and the
# camp tab, and stops at the row.
#
# This opens the real overlay in a real browser at 390px and 1280px, walks every
# game-log tab, and compares scrollWidth to clientWidth on the actual scroll
# container. A number, not an opinion, about the only surface the brief names.
#
# Scoped to the game log on purpose. Overview's SEASON STATS is ten columns and
# 560px and scrolls at both widths — measured and printed by the script, never
# asserted on. ESPN's own season-stats row scrolls on mobile, and the brief was
# always the per-week table, where a sideways scroll costs you the comparison
# between weeks. One season row has nothing to compare across.
ovlwidth(){
  need_w OVL-width || return
  have_files OVL-width "$W/scripts/overlay-width-gate.js" || return
  out=$(cd $W && LP_GATE_F="$F" timeout 400 node scripts/overlay-width-gate.js 2>&1); rc=$?
  line=$(printf '%s' "$out" | grep -E "^── [0-9]+ passed" | tail -1)
  fails=$(printf '%s' "$out" | grep -c '^FAIL ')
  if [ $rc -eq 0 ] && [ -n "$line" ]; then ok OVL-width "$line"
  elif [ $rc -eq 124 ]; then no OVL-width "timed out after 400s — browser never finished"
  elif [ -n "$line" ]; then
    no OVL-width "$line :: $(printf '%s' "$out" | grep '^FAIL ' | head -2 | tr '\n' ' ')"
  else no OVL-width "exit=$rc  <no summary line — the gate itself died>  $(printf '%s' "$out" | tail -1)"; fi
}

# ── the runner's own verdict ───────────────────────────────────────────────────
# Until 2026-07-28 this script printed FAIL and exited 0. Every gate, including
# `all`: ok() and no() are both a bare echo, and nothing summed them. Anything
# wrapping this in `verify-gates.sh all && deploy` read a red suite as green.
# Caught by Codex's audit; the repro is one line:
#   LP_GATE_W=/tmp/nope bash verify-gates.sh B1   ->  "FAIL B1 ()"  exit 0
#
# Two rules now, and they are the same rule the gates apply to the code:
#   1. exit = number of FAIL lines. No allowlist, not even for REG-adp-dst or
#      REG-jest-all, both of which are red on purpose — so `all` legitimately
#      exits 2 until job15 and the WCContext defect land. An allowlist is how a suite gets quietly relaxed; a number that
#      never lies is cheaper to trust than a list someone has to maintain.
#   2. A gate that emits NO verdict is a FAIL, not a skip. On 2026-07-28 the
#      `all` dispatch ran 14 gates and silently skipped REG-render because the
#      function was written but never added to the case. The count below is what
#      makes that structurally impossible to repeat, rather than fixed once.
ALL_IDS="A1 A1b A1c A2 A3 B1 B2 B2b B4 COV-nba COV-nhl COV-honest COV-keys COV-source COV-gametype COV-api COV-prod COV-leaders COV-identity REG-pool REG-adp-dst REG-dst REG-pytest REG-jest REG-jest-all REG-modules REG-render OVL-width"

out=$(mktemp) || exit 2
trap 'rm -f "$out"' EXIT

{
  case "${1:-all}" in
    # Accept the id each gate PRINTS, not just an internal shorthand. Codex ran
    # `verify-gates.sh REG-render` — the name the gate calls itself — and got no
    # verdict and exit 0, because the label here was `render`. A gate you cannot
    # invoke by its own name is a gate that reports green when you ask for it.
    A1|a1|A1b|A1c) a1;; A2|a2) a2;; A3|a3) a3;; B1|b1) b1;; B2|b2|B2b) b2;; B4|b4) b4;;
    # Same rule as REG-render below: every id the suite prints must be invocable.
    # `verify-gates.sh REG-pool` hit the `*)` arm and reported `unknown gate`,
    # which at least fails loud — but a name you have to know the shorthand for
    # is a name people stop using.
    reg|REG|regressions|REG-pool|REG-adp-dst|REG-dst|REG-pytest|REG-jest|REG-jest-all|REG-modules) reg;;
    render|REG-render|regrender) regrender;;
    OVL-width|ovl|overlay) ovlwidth;;
    cov|COV|coverage|COV-nba|COV-nhl|COV-honest|COV-keys|COV-source|COV-gametype|COV-api|COV-prod|COV-leaders|COV-identity) cov;;
    all) a1; a2; a3; b1; b2; b4; echo "--- coverage ---"; cov; echo "--- regressions ---"; reg; regrender; ovlwidth;;
    *) echo "FAIL runner (unknown gate '$1' — nothing ran)";;
  esac
} 2>&1 | tee "$out"

fails=$(grep -cE '^FAIL +' "$out")
passes=$(grep -cE '^PASS +' "$out")

# Missing verdicts only checkable for `all`, where the full id set is known.
missing=""
if [ "${1:-all}" = "all" ]; then
  for id in $ALL_IDS; do
    grep -qE "^(PASS|FAIL) +$id\b" "$out" || missing="$missing $id"
  done
fi

if [ -n "$missing" ]; then
  echo "FAIL runner (no verdict emitted by:$missing — a gate that did not run is not a gate that passed)"
  fails=$((fails + $(echo $missing | wc -w)))
fi

# Rule 2 applied to SINGLE-gate runs, where the id set is not known but the count is.
# Until 2026-08-02 the check above was the only one, so it covered `all` and nothing
# else, and a named gate that emitted no verdict at all was scored 0 failed / exit 0:
#
#   LP_GATE_B=http://127.0.0.1:9999 bash verify-gates.sh A1
#     -> a JSONDecodeError traceback, "── 0 passed, 0 failed ──", exit 0
#
# Every A/REG gate pipes curl into python, and python given an empty body raises
# before it can print either verdict. So the one input that means "the thing you are
# grading is not running" produced the same exit code as a clean pass — for anything
# shaped like `verify-gates.sh A1 && deploy`. A run that measured nothing is a FAIL.
if [ $((passes + fails)) -eq 0 ]; then
  echo "FAIL runner (gate '${1:-all}' emitted no verdict at all — nothing was measured; check W/B/F above are up)"
  fails=1
fi

echo "── $passes passed, $fails failed ──"
exit $((fails > 0 ? 1 : 0))
