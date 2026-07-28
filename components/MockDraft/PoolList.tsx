import { useMemo } from 'react'
import type { PoolPlayer } from '../Leagues/types'
import { AvailabilityStrip } from '../Leagues/NflDraftRoom'
import { poolToDraftRow } from '../../lib/mockDraft/api'

interface Props {
  players: PoolPlayer[]
  onStartDraft: () => void
}

/**
 * The mock-draft pool list. ~300 players, each row reuses DraftPlayerRow
 * for the availability strip — the differentiator. No note columns (rank,
 * watch, fade) — those live on the research board, not here.
 *
 * sample='none' rendering: per honest-data-ui §6.3:
 *   - PK → "Kicker games not tracked" (our gap, not theirs)
 *   - all else → "Rookie — no NFL sample" (grey, not accent, not zero)
 */
export default function PoolList({ players, onStartDraft }: Props) {
  const rows = useMemo(
    () => players.map((p, i) => poolToDraftRow(p, i + 1)),
    [players],
  )

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-xl font-bold text-zinc-100">
            Mock Draft Pool
          </h3>
          <p className="text-sm text-zinc-500 mt-0.5">
            {players.length} players · 12 teams · 15 rounds · PPR
          </p>
        </div>
        <button
          type="button"
          onClick={onStartDraft}
          className="rounded-lg border border-zinc-700 bg-zinc-800 px-5 py-2.5 text-sm font-semibold text-zinc-200 transition-colors hover:border-zinc-600 hover:bg-zinc-700"
        >
          Start Draft
        </button>
      </div>

      {/* Player pool table — same two-tone card, same column structure,
          but columns that don't apply (PPR, xFP, snap, target, notes) render
          as dashes because pool data doesn't carry them. */}
      <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-500 text-[11px] uppercase tracking-wider">
              <th className="text-left py-3 pl-4 pr-2 w-10">#</th>
              <th className="text-left py-3 px-2">Player</th>
              <th className="text-center py-3 px-2">Pos</th>
              <th className="text-left py-3 px-2 min-w-[9.5rem]">
                Available
                <span className="ml-1 font-normal normal-case tracking-normal text-zinc-600">
                  by team schedule
                </span>
              </th>
              <th className="text-right py-3 px-2">ADP</th>
              <th className="text-right py-3 px-2">Owned</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <PoolRow key={row.player_id} row={row} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

/** A single pool row — reuses DraftPlayerRow with no note callbacks,
 *  then overlays just the columns we need (ADP, percent_owned). */
function PoolRow({
  row,
}: {
  row: ReturnType<typeof poolToDraftRow>
}) {
  const noSample = row.sample === 'none'
  const isKicker = row.position === 'PK'
  const hasAvailability =
    !noSample && row.team_games != null && row.games_missed != null

  return (
    <tr className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
      <td className="py-2.5 pl-4 pr-2 text-zinc-500 text-xs tabular-nums">
        {row.rank}
      </td>
      <td className="py-2.5 px-2">
        <span className="font-medium text-zinc-200">
          {row.name}
        </span>
        <div className="text-[10px] text-zinc-600">{row.current_team}</div>
      </td>
      <td className="py-2.5 px-2 text-center">
        <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[11px] font-semibold uppercase text-zinc-400">
          {row.position}
        </span>
      </td>

      {/* Availability — the differentiator. Accent marks missed games. */}
      <td className="py-2.5 px-2">
        {noSample ? (
          <span className="text-[11px] text-zinc-500">
            {isKicker
              ? 'Kicker games not tracked'
              : 'Rookie — no NFL sample'}
          </span>
        ) : !hasAvailability ? (
          <span className="text-[11px] text-zinc-500">
            Availability unavailable
          </span>
        ) : (
          <>
            <div className="flex items-baseline gap-1.5">
              <span
                className={`font-mono tabular-nums text-sm font-semibold ${
                  row.games_missed > 0 ? 'text-amber-400' : 'text-zinc-300'
                }`}
              >
                {row.games_played}/{row.team_games}
              </span>
              {row.games_missed > 0 && (
                <span className="text-[10px] text-zinc-600">
                  missed {row.games_missed}
                </span>
              )}
            </div>
            <AvailabilityStrip
              weeksPlayed={row.weeks_played}
              teamWeeks={row.team_weeks}
              name={row.name}
            />
          </>
        )}
      </td>

      <td className="py-2.5 px-2 text-right font-mono tabular-nums text-zinc-300 font-semibold">
        {row.adp != null ? row.adp.toFixed(1) : '—'}
      </td>
      <td className="py-2.5 pr-4 pl-2 text-right font-mono tabular-nums text-zinc-400 text-xs">
        {row.percent_owned != null ? `${row.percent_owned.toFixed(1)}%` : '—'}
      </td>
    </tr>
  )
}
