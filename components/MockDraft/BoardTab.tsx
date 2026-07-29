import { useMemo } from 'react'
import type { DraftState } from '../../lib/mockDraft/engine'
import { positionLabel } from '../../lib/nfl/positionLabel'

/* The board tab holds the grid and, under it, the full pick history. The Pick
   Ledger used to sit permanently in the right-hand column showing the last 15
   picks; the header's Last pick line now carries the only part of that a drafter
   needs while choosing, and the complete list belongs where you go to read the
   draft rather than where you go to make a pick. */

export default function BoardTab({ draftState }: { draftState: DraftState }) {
  return (
    <div className="space-y-4">
      <DraftBoardGrid draftState={draftState} />
      <PickHistory draftState={draftState} />
    </div>
  )
}

// ── Draft board grid: rounds (rows) × teams (columns) ──
//
// The axes are this way round because that is how a draft is read. A snake
// draft advances left-to-right across the teams and then wraps to the next
// round, so with teams as columns a round is one row and the serpentine is
// visible as a shape: odd rounds fill left to right, even rounds right to left.
// With teams as rows — the previous layout — a single round was a vertical
// slice through fifteen separate rows and the snake was invisible.
//
// It also scales the right way. Rounds are fixed at 15; teams vary 10–14. Rows
// grow down the page for free; columns hit the width of the screen, so the
// varying axis is the one that gets the horizontal scroller and the sticky
// round column.

export function DraftBoardGrid({ draftState }: { draftState: DraftState }) {
  const { teams, rounds, picks, playerPool, seat } = draftState

  // grid[round][team] — indexed the way it is rendered.
  const grid = useMemo(() => {
    const g: Array<Array<{
      pick_no: number
      name: string
      position: string
      auto: boolean
    } | null>> = Array.from({ length: rounds }, () => Array(teams + 1).fill(null))

    const playerLookup = new Map(playerPool.map(p => [p.player_id, p]))
    for (const pick of picks) {
      const r = Math.ceil(pick.pick_no / teams) - 1 // 0-based round
      const player = playerLookup.get(pick.player_id)
      if (r < 0 || r >= rounds) continue
      g[r][pick.team_no] = {
        pick_no: pick.pick_no,
        name: player?.name ?? `#${pick.player_id}`,
        position: player?.position ?? '',
        auto: pick.auto,
      }
    }
    return g
  }, [teams, rounds, picks, playerPool])

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-hidden">
      <div className="px-4 py-3 border-b border-zinc-800">
        <h4 className="text-sm font-semibold text-zinc-300">
          Draft Board
          <span className="ml-2 text-xs font-normal text-zinc-500 tabular-nums">
            {picks.length}/{teams * rounds} picks
          </span>
          <span className="ml-2 text-xs font-normal text-zinc-600 tabular-nums">
            · {teams} teams
          </span>
        </h4>
      </div>
      <div className="overflow-x-auto">
        {/* w-full so 10 and 12 teams fill the card rather than leaving a dead
            strip down the right; min-w-max so 14 teams overflow into the
            scroller instead of crushing the columns. */}
        <table className="w-full min-w-max text-xs" data-testid="draft-board-grid">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-500">
              <th
                scope="col"
                className="sticky left-0 z-10 bg-zinc-900 text-left py-2 pl-4 pr-2 w-12 font-medium uppercase tracking-wider"
              >
                Rd
              </th>
              {Array.from({ length: teams }, (_, i) => {
                const teamNo = i + 1
                const isUser = teamNo === seat
                return (
                  <th
                    key={teamNo}
                    scope="col"
                    className={`py-2 px-1 min-w-[5rem] font-semibold tabular-nums text-[10px] ${
                      isUser ? 'text-zinc-200 bg-zinc-800/30' : 'text-zinc-500'
                    }`}
                  >
                    T{teamNo}
                    {isUser && (
                      <span className="ml-1 text-[9px] font-normal text-zinc-600">you</span>
                    )}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: rounds }, (_, r) => (
              <tr key={r} className="border-b border-zinc-800/30">
                <th
                  scope="row"
                  className="sticky left-0 z-10 bg-zinc-900 text-left py-2 pl-4 pr-2 font-semibold tabular-nums text-zinc-500"
                >
                  R{r + 1}
                </th>
                {Array.from({ length: teams }, (_, i) => {
                  const teamNo = i + 1
                  const isUser = teamNo === seat
                  const cell = grid[r][teamNo]
                  return (
                    <td
                      key={teamNo}
                      className={`text-center py-2 px-1 align-top ${
                        isUser ? 'bg-zinc-800/20' : ''
                      }`}
                    >
                      {cell ? (
                        <div className="leading-tight">
                          <div
                            className={`font-medium truncate max-w-[5rem] mx-auto ${
                              isUser ? 'text-zinc-200' : 'text-zinc-400'
                            }`}
                          >
                            {cell.name}
                          </div>
                          <span
                            className={`text-[9px] ${
                              isUser ? 'text-zinc-500' : 'text-zinc-600'
                            }`}
                          >
                            {positionLabel(cell.position)}
                          </span>
                          {/* The snake means column order is not pick order in
                              even rounds, so the cell states its own pick. */}
                          <span className="ml-1 text-[9px] tabular-nums text-zinc-700">
                            {cell.pick_no}
                          </span>
                        </div>
                      ) : (
                        <span className="text-zinc-700">—</span>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function PickHistory({ draftState }: { draftState: DraftState }) {
  const rows = useMemo(() => {
    const lookup = new Map(draftState.playerPool.map(p => [p.player_id, p]))
    return [...draftState.picks].reverse().map(pick => ({
      pick,
      player: lookup.get(pick.player_id) ?? null,
    }))
  }, [draftState.picks, draftState.playerPool])

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-hidden">
      <div className="px-4 py-3 border-b border-zinc-800">
        <h4 className="text-sm font-semibold text-zinc-300">
          Every pick
          <span className="ml-2 text-xs font-normal text-zinc-500 tabular-nums">
            {draftState.picks.length}
          </span>
        </h4>
      </div>
      <div className="max-h-[360px] overflow-y-auto divide-y divide-zinc-800/30">
        {rows.map(({ pick, player }) => {
          const isUser = pick.team_no === draftState.seat
          return (
            <div
              key={pick.pick_no}
              className={`flex items-center gap-2 px-4 py-2 text-xs ${
                isUser ? 'border-l-2 border-l-zinc-500 bg-zinc-800/30' : ''
              }`}
            >
              <span className="w-8 shrink-0 tabular-nums text-zinc-600">{pick.pick_no}</span>
              <span className="w-10 shrink-0 tabular-nums text-zinc-500">
                {isUser ? 'you' : `T${pick.team_no}`}
              </span>
              <span className={`truncate ${isUser ? 'font-semibold text-zinc-200' : 'text-zinc-400'}`}>
                {player?.name ?? `#${pick.player_id}`}
              </span>
              <span className="shrink-0 text-[10px] text-zinc-600">
                {positionLabel(player?.position ?? '')}
              </span>
              {pick.auto && <span className="ml-auto shrink-0 text-[10px] text-zinc-600">auto</span>}
            </div>
          )
        })}
        {rows.length === 0 && (
          <div className="px-4 py-6 text-center text-sm text-zinc-600">No picks yet</div>
        )}
      </div>
    </div>
  )
}
