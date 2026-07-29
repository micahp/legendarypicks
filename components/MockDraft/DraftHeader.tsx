import { useMemo } from 'react'
import type { DraftState, DraftPlayer } from '../../lib/mockDraft/engine'
import { nextTeam } from '../../lib/mockDraft/engine'
import { positionLabel } from '../../lib/nfl/positionLabel'

/* ── The persistent chrome ──────────────────────────────────────────────────
   Above the tabs and never inside one: whatever tab you are reading, the clock
   is still running and the pick you are about to lose is still yours to lose.

   ESPN shows three header states — a pre-draft countdown, another manager on
   the clock with their countdown, and your own turn. We have two, and the
   missing one is not an omission:

     · There is no pre-draft countdown because there is no lobby. The pool screen
       is the pre-draft state and it has a Start Draft button, not a timer.
     · "Another manager is on the clock" lasts milliseconds here. commitPick runs
       every bot pick between your turns in one synchronous loop, so there is no
       interval during which a bot is deciding. What we render instead, honestly,
       is that the bots are picking — and the Last pick line, which is the part
       of ESPN's state that actually carries information.

   Colour does no work here. ESPN turns the whole header green when it is your
   turn; our accent marks absence only (honest-data-ui §5), so your turn is
   marked with weight, a rule, and position instead. */

interface Props {
  draftState: DraftState
  /** Remaining seconds on your pick, or null when it is not your turn. */
  clockSeconds: number | null
  /** Your turn AND the client is accepting a pick. */
  onClock: boolean
  /** Exactly the player the 0:00 timeout would take — not a second guess at it. */
  autoPick: DraftPlayer | null
}

function describe(p: DraftPlayer | null | undefined): string {
  if (!p) return ''
  return `${p.name}, ${positionLabel(p.position)}, ${p.team}`
}

export default function DraftHeader({ draftState, clockSeconds, onClock, autoPick }: Props) {
  const { teams, rounds, currentPick, seat, completed, picks } = draftState
  const total = teams * rounds
  const round = Math.ceil(currentPick / teams)

  const lastPick = useMemo(() => {
    const pick = picks[picks.length - 1]
    if (!pick) return null
    const player = draftState.playerPool.find(p => p.player_id === pick.player_id) ?? null
    return { pick, player }
  }, [picks, draftState.playerPool])

  return (
    <div className="space-y-2">
      <div
        data-testid="draft-status-header"
        className={`rounded-lg border bg-zinc-900 px-4 py-3 ${
          onClock ? 'border-zinc-600 border-l-4 border-l-zinc-300' : 'border-zinc-800'
        }`}
      >
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-sm font-semibold text-zinc-300">Round {round}</span>
          <span className="text-xs text-zinc-500">·</span>
          <span data-testid="draft-pick-counter" className="text-sm text-zinc-400 tabular-nums">
            Pick {currentPick} of {total}
          </span>

          <div className="ml-auto flex items-baseline gap-2">
            {completed ? (
              <span className="text-sm font-semibold text-zinc-300">Draft complete</span>
            ) : onClock ? (
              <>
                <span className="text-sm font-bold text-zinc-100">You are on the clock</span>
                <span className="text-xs text-zinc-500">·</span>
                <span
                  data-testid="draft-clock"
                  className={`font-mono tabular-nums text-sm ${
                    clockSeconds != null && clockSeconds <= 10
                      ? 'font-bold text-zinc-100'
                      : 'font-medium text-zinc-400'
                  }`}
                >
                  0:{String(clockSeconds ?? 0).padStart(2, '0')}
                </span>
              </>
            ) : (
              <span className="text-sm text-zinc-400">
                Team {nextTeam(currentPick, teams)} picking
              </span>
            )}
          </div>
        </div>

        {/* Sub-bar. ESPN puts the last pick here and, on your turn, what it would
            take for you. The auto-pick line is the same value handleTimeout will
            actually use, passed in — a second computation of it could disagree
            with what happens at 0:00, and a promise the clock breaks is worse
            than no promise. */}
        <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs">
          {lastPick && (
            <span data-testid="last-pick" className="text-zinc-500">
              Last pick{' '}
              <span className="text-zinc-600 tabular-nums">#{lastPick.pick.pick_no}</span>{' '}
              <span className="text-zinc-500">
                {lastPick.pick.team_no === seat ? 'you' : `Team ${lastPick.pick.team_no}`}
              </span>
              {' — '}
              <span className="text-zinc-400">{describe(lastPick.player)}</span>
              {lastPick.pick.auto && <span className="ml-1 text-zinc-600">auto</span>}
            </span>
          )}
          {onClock && autoPick && (
            <span data-testid="auto-pick-hint" className="ml-auto text-zinc-500">
              Your auto pick would be <span className="text-zinc-400">{describe(autoPick)}</span>
            </span>
          )}
        </div>
      </div>

      <RoundStrip draftState={draftState} />
    </div>
  )
}

/* ── The round strip ────────────────────────────────────────────────────────
   ESPN's scrolling pick cards, which scroll *through* the round boundary rather
   than stopping at it — the useful question at pick 12 of a snake is "how long
   until 13", and that answer lives in the next round. Every team but yours is a
   bot here, so every one of them carries ESPN's AUTO flag; that is what those
   teams are, not a decoration. */

const LOOKBACK = 2
const LOOKAHEAD = 14

function RoundStrip({ draftState }: { draftState: DraftState }) {
  const { teams, rounds, currentPick, seat } = draftState
  const total = teams * rounds

  const cards = useMemo(() => {
    const from = Math.max(1, currentPick - LOOKBACK)
    const to = Math.min(total, currentPick + LOOKAHEAD)
    const out = []
    for (let p = from; p <= to; p++) {
      const teamNo = nextTeam(p, teams)
      out.push({
        pickNo: p,
        round: Math.ceil(p / teams),
        inRound: ((p - 1) % teams) + 1,
        teamNo,
        isUser: teamNo === seat,
        isCurrent: p === currentPick,
        startsRound: (p - 1) % teams === 0,
      })
    }
    return out
  }, [teams, total, currentPick, seat])

  return (
    <div
      data-testid="round-strip"
      className="flex gap-1.5 overflow-x-auto rounded-lg border border-zinc-800 bg-zinc-900 px-2 py-2"
    >
      {cards.map(c => (
        <div
          key={c.pickNo}
          data-pick={c.pickNo}
          className={`shrink-0 rounded-md border px-2 py-1 leading-tight ${
            c.isCurrent
              ? 'border-zinc-500 bg-zinc-700'
              : c.isUser
                ? 'border-zinc-600 bg-zinc-900'
                : 'border-zinc-800 bg-zinc-900'
          }`}
        >
          {c.startsRound && (
            <div className="text-[9px] font-semibold uppercase tracking-wider text-zinc-600">
              Round {c.round}
            </div>
          )}
          <div
            className={`text-[10px] tabular-nums ${
              c.isCurrent ? 'font-semibold text-zinc-100' : 'text-zinc-500'
            }`}
          >
            Pick {c.inRound} ({c.pickNo})
          </div>
          <div className="flex items-baseline gap-1">
            <span
              className={`text-[10px] ${
                c.isUser ? 'font-semibold text-zinc-200' : 'text-zinc-500'
              }`}
            >
              {c.isUser ? 'You' : `Team ${c.teamNo}`}
            </span>
            {!c.isUser && (
              <span className="text-[8px] uppercase tracking-wider text-zinc-600">auto</span>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
