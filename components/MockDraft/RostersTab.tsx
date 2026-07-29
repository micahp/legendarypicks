import { useMemo } from 'react'
import type { PoolPlayer } from '../Leagues/types'
import type { DraftState } from '../../lib/mockDraft/engine'
import { getRosterState } from '../../lib/mockDraft/engine'
import { poolTeamGames } from '../../lib/mockDraft/availability'
import { positionLabel } from '../../lib/nfl/positionLabel'
import { buildRosterSlots, type RosterSlot } from './roster'
import { noSampleLabel } from './columns'

/* Rosters, plural — ESPN's fourth tab holds every team, and so does this one.
   The engine already has every pick, and what an opponent still needs is the
   draft skill this tab exists to serve: if the three teams picking before you
   all have their quarterback, the quarterback run is not coming. Yours is
   first because it is the one you check between every pick. */

interface Props {
  draftState: DraftState
  playerMap: Map<number, PoolPlayer>
  referenceSeason?: number | null
}

export default function RostersTab({ draftState, playerMap, referenceSeason }: Props) {
  const teams = useMemo(() => {
    const order = [
      draftState.seat,
      ...Array.from({ length: draftState.teams }, (_, i) => i + 1).filter(
        n => n !== draftState.seat,
      ),
    ]
    return order.map(teamNo => ({
      teamNo,
      isUser: teamNo === draftState.seat,
      roster: getRosterState(draftState, teamNo),
    }))
  }, [draftState])

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      {teams.map(({ teamNo, isUser, roster }) => (
        <div
          key={teamNo}
          className={`overflow-hidden rounded-xl border bg-zinc-900 ${
            isUser ? 'border-zinc-600' : 'border-zinc-800'
          }`}
        >
          <div className="flex items-baseline gap-2 border-b border-zinc-800 px-4 py-2.5">
            <h4 className={`text-sm font-semibold ${isUser ? 'text-zinc-100' : 'text-zinc-400'}`}>
              {isUser ? 'Your roster' : `Team ${teamNo}`}
            </h4>
            <span className="ml-auto text-xs tabular-nums text-zinc-500">
              {roster.totalPicks}/{draftState.rounds}
            </span>
          </div>
          <div className="divide-y divide-zinc-800/50">
            {buildRosterSlots(roster.players, playerMap).map((slot, i) => (
              <RosterSlotRow key={i} slot={slot} referenceSeason={referenceSeason} />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export function RosterSlotRow({
  slot,
  referenceSeason,
}: { slot: RosterSlot; referenceSeason?: number | null }) {
  const pp = slot.poolPlayer
  const teamGames = pp ? poolTeamGames(pp) : null
  const measured = pp && pp.sample !== 'none' && teamGames != null && pp.games_missed != null

  return (
    <div className={`flex items-center gap-2 px-4 py-2 text-xs ${slot.isStarter ? '' : 'opacity-70'}`}>
      <span
        className={`w-12 shrink-0 font-semibold tabular-nums ${
          slot.isStarter ? 'text-zinc-300' : 'text-zinc-500'
        }`}
      >
        {slot.label}
      </span>
      {slot.player ? (
        <>
          <span className="flex-1 truncate font-medium text-zinc-200">{slot.player.name}</span>
          <span className="shrink-0 text-[10px] text-zinc-500">
            {positionLabel(slot.player.position)}
          </span>
          {measured && pp && (
            <span
              className={`shrink-0 font-mono text-[10px] tabular-nums ${
                (pp.games_missed ?? 0) > 0 ? 'text-amber-400' : 'text-zinc-600'
              }`}
            >
              {pp.games_played}/{teamGames}
            </span>
          )}
          {/* "rookie" was an inference and a wrong one for anyone who simply
              missed the season. Say what we actually know. */}
          {pp && pp.sample === 'none' && (
            <span className="shrink-0 text-[10px] text-zinc-600">
              {noSampleLabel(pp.position, pp.has_prior_nfl_sample, referenceSeason)}
            </span>
          )}
        </>
      ) : (
        <span className="flex-1 text-zinc-700">—</span>
      )}
    </div>
  )
}
