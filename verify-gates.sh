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
W="${LP_GATE_W:-/root/lp-team-vocab}"
B="${LP_GATE_B:-http://127.0.0.1:8098}"
F="${LP_GATE_F:-http://127.0.0.1:3098}"
echo "── gates against W=$W B=$B F=$F ──"
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
# A kicker must not assert a PPR average of 0.0. null or absent is correct.
if ppr in (None,) and (pk is None or pk>0): print('PASS A1b (Aubrey ppr=%s pk_pts_per_game=%s)'%(ppr,pk))
else: print('FAIL A1b (Aubrey ppr=%s snap=%s pk=%s  <- 0.0 is a false measurement)'%(ppr,snap,pk))
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
  f=$W/components/Leagues/hooks/useNflDraftBoard.ts
  line=$(grep -n "const POSITIONS" "$f" | head -1)
  if grep -q "'DEF'" "$f" && grep -q "'PK'" "$f"; then ok B1 "$line"; else no B1 "$line"; fi
}

# ── B2 · the branch's fields actually render ──
b2(){
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

# ── B4 · M7: scrollbar shown, TEAM_GAMES hardcode gone ──
b4(){
  f=$W/components/MockDraft/DraftRoom.tsx
  s=$(grep -c "scrollbar-width:none\|::-webkit-scrollbar\]:hidden" "$f")
  t=$(grep -c "TEAM_GAMES - " "$f")
  if [ "$s" = "0" ] && [ "$t" = "0" ]; then ok B4 "scrollbar shown, games_missed from API"
  else no B4 "hidden-scrollbar refs=$s  TEAM_GAMES-arithmetic refs=$t"; fi
}

# ── always-on regressions: nothing already working may break ──
reg(){
  curl -s --max-time 30 "$B/api/nfl/mock-draft/pool?season=2026&limit=400" | $PY -c "
import sys,json,collections
d=json.load(sys.stdin);p=d['players']
c=collections.Counter(x['position'] for x in p)
i=[j for j,x in enumerate(p) if x['position']=='DEF']
okk = len(p)==300 and c['DEF']==32
print(('PASS REG-pool (300, DEF 32 @%d-%d)'%(i[0],i[-1])) if okk else ('FAIL REG-pool (%d %s DEF@%s)'%(len(p),dict(c),i[:1])))
"
  # ── REG-adp-dst — EXPECTED VALUES WRITTEN 2026-07-28, BEFORE THE CODE. ──
  # Measured directly from ESPN the same day. All 32 D/ST carry a published ADP;
  # ESPN keys them with NEGATIVE ids (-16000 - proTeamId), which is why the
  # espn_id join in ingest_nfl_adp.py matched 0 of 32 and the router grew a
  # derived dst_rank behind the comment "no published ADP exists".
  # This gate is RED until that ingest lands. Do not relax it to make it green —
  # a diff to these numbers is a finding. Tolerance is for ESPN drift only.
  curl -s --max-time 30 "$B/api/nfl/mock-draft/pool?season=2026&limit=400" | $PY -c "
import sys,json
d=json.load(sys.stdin);p=d['players']
dst={x['team']:x for x in p if x['position']=='DEF'}
nulls=[t for t,x in dst.items() if x.get('adp') is None]
exp={'DEN':89.9,'HOU':91.8,'LAR':98.2,'SEA':106.5}
bad=[(t,v,dst.get(t,{}).get('adp')) for t,v in exp.items()
     if dst.get(t,{}).get('adp') is None or abs(dst[t]['adp']-v)>12]
if len(dst)==32 and not nulls and not bad:
    print('PASS REG-adp-dst (32 D/ST, published ADP, DEN=%.1f SEA=%.1f)'%(dst['DEN']['adp'],dst['SEA']['adp']))
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
  pyout=$(cd $W/backend && LP_DB_PATH=/root/picks.hermes.db ./venv/bin/python -m pytest test_nfl_mock_draft.py test_nfl_dst.py -q 2>&1); pyrc=$?
  pysum=$(printf '%s' "$pyout" | grep -E "passed|failed|error" | tail -1)
  if [ $pyrc -eq 0 ] && [ -n "$pysum" ]; then ok REG-pytest "$pysum"
  else no REG-pytest "exit=$pyrc  last: ${pysum:-<no output — runner died>}"; fi

  jsout=$(cd $W && /root/legendarypicks/node_modules/.bin/jest --testPathPattern='lib/mockDraft' --no-coverage 2>&1); jsrc=$?
  jssum=$(printf '%s' "$jsout" | grep -E "^Tests:" | tail -1)
  if [ $jsrc -eq 0 ] && [ -n "$jssum" ]; then ok REG-jest "$jssum"
  elif [ $jsrc -ge 128 ]; then no REG-jest "jest died with signal (exit=$jsrc, $( [ $jsrc -eq 135 ] && echo 'SIGBUS — corrupt native binary in the shared node_modules' || echo 'killed' )) — NO frontend tests ran"
  else no REG-jest "exit=$jsrc  ${jssum:-<no 'Tests:' line — nothing ran>}"; fi
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
  out=$(cd $W && LP_GATE_F="$F" timeout 400 node scripts/render-gate.js 2>&1); rc=$?
  line=$(printf '%s' "$out" | grep -E "^(PASS|FAIL) REG-render" | tail -1)
  if [ $rc -eq 0 ] && [ -n "$line" ]; then echo "$line"
  elif [ $rc -eq 124 ]; then no REG-render "timed out after 400s — browser never finished"
  else no REG-render "exit=$rc  ${line:-<no verdict line — the gate itself died>}"; fi
}

# ── the runner's own verdict ───────────────────────────────────────────────────
# Until 2026-07-28 this script printed FAIL and exited 0. Every gate, including
# `all`: ok() and no() are both a bare echo, and nothing summed them. Anything
# wrapping this in `verify-gates.sh all && deploy` read a red suite as green.
# Caught by Codex's audit; the repro is one line:
#   LP_GATE_W=/tmp/nope bash verify-gates.sh B1   ->  "FAIL B1 ()"  exit 0
#
# Two rules now, and they are the same rule the gates apply to the code:
#   1. exit = number of FAIL lines. No allowlist, not even for REG-adp-dst,
#      which is red on purpose — so `all` legitimately exits 1 until job15
#      lands. An allowlist is how a suite gets quietly relaxed; a number that
#      never lies is cheaper to trust than a list someone has to maintain.
#   2. A gate that emits NO verdict is a FAIL, not a skip. On 2026-07-28 the
#      `all` dispatch ran 14 gates and silently skipped REG-render because the
#      function was written but never added to the case. The count below is what
#      makes that structurally impossible to repeat, rather than fixed once.
ALL_IDS="A1 A1b A2 A3 B1 B2 B2b B4 REG-pool REG-adp-dst REG-dst REG-pytest REG-jest REG-modules REG-render"

out=$(mktemp) || exit 2
trap 'rm -f "$out"' EXIT

{
  case "${1:-all}" in
    A1) a1;; A2) a2;; A3) a3;; B1) b1;; B2) b2;; B4) b4;; reg) reg;; render) regrender;;
    all) a1; a2; a3; b1; b2; b4; echo "--- regressions ---"; reg; regrender;;
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

echo "── $passes passed, $fails failed ──"
exit $((fails > 0 ? 1 : 0))
