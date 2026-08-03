import type { PoolPlayer } from '../Leagues/types'
import type { DraftPlayer } from '../../lib/mockDraft/engine'
import { positionLabel, positionRankLabel, showsPositionalRank } from '../../lib/nfl/positionLabel'
import {
  ExpectedPts,
  EXPECTED_PTS_HEADER,
  expectedPtsTitle,
  PoolAvailability,
  ProjectedPoints,
} from './columns'
import PlayerActionButton from './PlayerActionButton'
import InjuryTag from '../Leagues/InjuryTag'
import type { SortOption } from './sort'

/** A rendered list is players plus the rules drawn between them. */
export type PoolRow =
  | { kind: 'player'; dp: DraftPlayer; rank: number }
  | { kind: 'divider'; pickNo: number; round: number; inRound: number }

interface Props {
  rows: PoolRow[]
  playerMap: Map<number, PoolPlayer>
  posRank: Map<number, number>
  byeMap: Map<string, number | null>
  referenceSeason?: number | null
  posOptions: string[]
  posFilter: string
  onPosFilter: (pos: string) => void
  teamOptions: string[]
  teamFilter: string
  onTeamFilter: (team: string) => void
  byeOptions: string[]
  byeFilter: string
  onByeFilter: (bye: string) => void
  scheduleLoaded: boolean
  sortOptions: SortOption[]
  sortKey: string
  onSort: (key: string) => void
  onClearFilters: () => void

  shown: number
  available: number
  drafted: number

  queue: number[]
  onClock: boolean
  completed: boolean
  onSelectPlayer: (playerId: number) => void
  onDraft: (playerId: number) => void
  onQueue: (playerId: number) => void
  onUnqueue: (playerId: number) => void
}

// The divider row's colSpan — one column per td rendered below.
const COLUMNS = 8

export default function PlayersTab(p: Props) {
  const filtered = p.posFilter !== 'ALL' || p.teamFilter !== 'ALL' || p.byeFilter !== 'ALL'

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs text-zinc-600 tabular-nums">
          {p.shown} of {p.available} available · {p.drafted} drafted
        </span>
      </div>

      {/* ── Filter bar ── */}
      <div className="flex flex-wrap items-center gap-2">
        {/* Position. The labels are NOT uppercased in CSS: "D/ST" and "All" are
            the strings a drafter reads, and a text-transform means the rendered
            text and the authored text differ, which is exactly the gap the old
            alphabetical ordering hid in. */}
        <div
          data-testid="position-filter"
          className="flex items-center gap-1"
          role="radiogroup"
          aria-label="Filter by position"
        >
          {p.posOptions.map(pos => (
            <button
              key={pos}
              type="button"
              role="radio"
              aria-checked={p.posFilter === pos}
              onClick={() => p.onPosFilter(pos)}
              className={`rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide transition-colors ${
                p.posFilter === pos
                  ? 'border-zinc-500 bg-zinc-700 text-zinc-200'
                  : 'border-zinc-800 bg-zinc-900 text-zinc-500 hover:border-zinc-700 hover:text-zinc-400'
              }`}
            >
              {pos === 'ALL' ? 'All' : positionLabel(pos)}
            </button>
          ))}
        </div>

        <span className="text-zinc-700">|</span>

        {/* Sort. ESPN's second dropdown selects which stat the column shows; ours
            selects the order, which is the thing a drafter actually wants and the
            thing ESPN's RK column is doing invisibly. */}
        <label htmlFor="pool-sort" className="sr-only">Sort players</label>
        <select
          id="pool-sort"
          value={p.sortKey}
          onChange={e => p.onSort(e.target.value)}
          className="rounded-md border border-zinc-800 bg-zinc-900 px-2 py-0.5 text-[11px] font-medium text-zinc-400 focus:border-zinc-600 focus:outline-none"
        >
          {p.sortOptions.map(o => (
            <option key={o.key} value={o.key}>{o.label}</option>
          ))}
        </select>

        <select
          value={p.teamFilter}
          onChange={e => p.onTeamFilter(e.target.value)}
          className="rounded-md border border-zinc-800 bg-zinc-900 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-zinc-400 focus:border-zinc-600 focus:outline-none"
          aria-label="Filter by team"
        >
          {p.teamOptions.map(t => (
            <option key={t} value={t}>{t === 'ALL' ? 'All Teams' : t}</option>
          ))}
        </select>

        <select
          value={p.byeFilter}
          onChange={e => p.onByeFilter(e.target.value)}
          disabled={!p.scheduleLoaded}
          className={`rounded-md border border-zinc-800 bg-zinc-900 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide focus:border-zinc-600 focus:outline-none ${
            p.scheduleLoaded ? 'text-zinc-400' : 'text-zinc-700 cursor-not-allowed'
          }`}
          aria-label="Filter by bye week"
        >
          <option value="ALL">{p.scheduleLoaded ? 'Bye Week' : 'Bye (loading…)'}</option>
          {p.byeOptions.filter(b => b !== 'ALL').map(b => (
            <option key={b} value={b}>Week {b}</option>
          ))}
        </select>

        {filtered && (
          <button
            type="button"
            onClick={p.onClearFilters}
            className="rounded-md border border-zinc-800 px-2 py-0.5 text-[10px] font-medium text-zinc-500 transition-colors hover:border-zinc-600 hover:text-zinc-300"
          >
            Clear
          </button>
        )}
      </div>

      <div className="overflow-y-auto max-h-[calc(100vh-340px)] rounded-xl border border-zinc-800 bg-zinc-900">
        <table data-testid="pool-table" className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-zinc-900">
            <tr className="border-b border-zinc-800 text-zinc-500 text-[11px] uppercase tracking-wider">
              <th data-col="rank" className="text-left py-2.5 pl-3 pr-2 w-10">#</th>
              <th data-col="player" className="text-left py-2.5 px-2">Player</th>
              <th data-col="proj" className="text-right py-2.5 px-2 w-20">
                Proj <span className="block font-normal normal-case tracking-normal text-zinc-600">2026 PPR</span>
              </th>
              <th data-col="xfp" className="text-right py-2.5 px-2 w-20" title={expectedPtsTitle(p.referenceSeason)}>
                {EXPECTED_PTS_HEADER}
                {p.referenceSeason != null && (
                  <span className="block font-normal normal-case tracking-normal text-zinc-600">{p.referenceSeason} PPR</span>
                )}
              </th>
              <th data-col="bye" className="text-right py-2.5 px-2 w-12">Bye</th>
              <th data-col="adp" className="text-right py-2.5 px-2 w-16">ADP</th>
              <th data-col="avail" className="text-left py-2.5 px-2 min-w-[8rem]">Available</th>
              <th data-col="action" className="w-20" />
            </tr>
          </thead>
          <tbody>
            {p.rows.map(row =>
              row.kind === 'divider' ? (
                <tr
                  key={`divider-${row.pickNo}`}
                  data-testid="your-pick-divider"
                  className="border-y border-zinc-600 bg-zinc-800/40"
                >
                  <td colSpan={COLUMNS} className="py-1 px-3">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-300">
                      Your pick (R{row.round},P{row.inRound})
                    </span>
                    <span className="ml-2 text-[10px] text-zinc-500">
                      overall #{row.pickNo} — where ADP expects your turn to fall
                    </span>
                  </td>
                </tr>
              ) : (
                <PoolRowView
                  key={row.dp.player_id}
                  dp={row.dp}
                  rank={row.rank}
                  poolPlayer={p.playerMap.get(row.dp.player_id) ?? null}
                  posRank={p.posRank.get(row.dp.player_id)}
                  bye={p.byeMap.get(row.dp.team) ?? null}
                  referenceSeason={p.referenceSeason}
                  queued={p.queue.includes(row.dp.player_id)}
                  onClock={p.onClock}
                  completed={p.completed}
                  onSelect={p.onSelectPlayer}
                  onDraft={p.onDraft}
                  onQueue={p.onQueue}
                  onUnqueue={p.onUnqueue}
                />
              ),
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function PoolRowView({
  dp, rank, poolPlayer, posRank, bye, referenceSeason, queued, onClock, completed,
  onSelect, onDraft, onQueue, onUnqueue,
}: {
  dp: DraftPlayer
  rank: number
  poolPlayer: PoolPlayer | null
  posRank?: number
  bye: number | null
  referenceSeason?: number | null
  queued: boolean
  onClock: boolean
  completed: boolean
  onSelect: (id: number) => void
  onDraft: (id: number) => void
  onQueue: (id: number) => void
  onUnqueue: (id: number) => void
}) {
  if (!poolPlayer) return null
  return (
    <tr
      onClick={() => onSelect(dp.player_id)}
      className="border-b border-zinc-800/40 transition-colors cursor-pointer hover:bg-zinc-800/30"
    >
      <td data-col="rank" className="py-2 pl-3 pr-2 text-zinc-500 text-xs tabular-nums">
        {rank}
      </td>
      <td data-col="player" className="py-2 px-2">
        <div className="flex items-center gap-1.5">
          <span className="font-medium text-zinc-200">{dp.name}</span>
          <InjuryTag status={poolPlayer.injury_status} compact />
        </div>
        <div className="text-[10px] text-zinc-600">
          {dp.team}
          {' · '}
          <span className="font-semibold text-zinc-500">{positionLabel(dp.position)}</span>
          {posRank != null && showsPositionalRank(dp.position) && (
            <>
              {' · '}
              <span className="tabular-nums">{positionRankLabel(dp.position, posRank)}</span>
            </>
          )}
        </div>
      </td>
      <td data-col="proj" className="py-2 px-2 text-right font-mono tabular-nums text-xs">
        <ProjectedPoints player={poolPlayer} />
      </td>
      <td data-col="xfp" className="py-2 px-2 text-right font-mono tabular-nums text-xs">
        <ExpectedPts player={poolPlayer} />
      </td>
      <td data-col="bye" className="py-2 px-2 text-right font-mono tabular-nums text-xs text-zinc-500">
        {bye ?? <span className="text-zinc-700">—</span>}
      </td>
      <td data-col="adp" className="py-2 pr-3 pl-2 text-right font-mono tabular-nums text-xs text-zinc-400">
        {dp.adp != null ? dp.adp.toFixed(1) : <span className="text-zinc-600">—</span>}
      </td>
      <td data-col="avail" className="py-2 px-2">
        <PoolAvailability poolPlayer={poolPlayer} referenceSeason={referenceSeason} />
      </td>
      <td data-col="action" data-testid="row-action" className="py-2 pr-3 pl-1 text-center">
        <PlayerActionButton
          playerId={dp.player_id}
          name={dp.name}
          onClock={onClock}
          queued={queued}
          completed={completed}
          onDraft={onDraft}
          onQueue={onQueue}
          onUnqueue={onUnqueue}
        />
      </td>
    </tr>
  )
}
