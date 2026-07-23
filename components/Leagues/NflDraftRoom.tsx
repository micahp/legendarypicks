import type { NflDraftBoard, NflDraftNotes, NflDraftPlayer, NflDraftSort } from './types'
import { POSITIONS, SORT_LABELS } from './hooks/useNflDraftBoard'
import type { DraftPosition } from './hooks/useNflDraftBoard'

interface Props {
  data: NflDraftBoard | null
  loading: boolean
  error: string | null
  position: DraftPosition
  sort: NflDraftSort
  offset: number
  notes: NflDraftNotes
  onSelectPosition: (position: DraftPosition) => void
  onSelectSort: (sort: NflDraftSort) => void
  onSetOffset: (offset: number) => void
  onSetRank: (playerId: number, rank: number | null) => void
  onToggleWatch: (playerId: number) => void
  onToggleFade: (playerId: number) => void
}

export default function NflDraftRoom({
  data,
  loading,
  error,
  position,
  sort,
  offset,
  notes,
  onSelectPosition,
  onSelectSort,
  onSetOffset,
  onSetRank,
  onToggleWatch,
  onToggleFade,
}: Props) {
  return (
    <section className="space-y-4">
      <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-zinc-500">
        Player Rankings
      </h3>

      {/* Position pills */}
      <div
        className="flex flex-wrap items-center gap-1.5"
        role="radiogroup"
        aria-label="Filter by position"
      >
        {POSITIONS.map(pos => (
          <button
            key={pos}
            type="button"
            role="radio"
            aria-checked={position === pos}
            onClick={() => onSelectPosition(pos)}
            className={`rounded-lg border px-3 py-1.5 text-xs font-semibold uppercase tracking-wide transition-colors ${
              position === pos
                ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                : 'border-zinc-700 bg-zinc-800/60 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200'
            }`}
          >
            {pos === 'all' ? 'All' : pos}
          </button>
        ))}
      </div>

      {/* Sort row */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-zinc-500">Sort:</span>
        {(Object.keys(SORT_LABELS) as NflDraftSort[]).map(key => (
          <button
            key={key}
            type="button"
            onClick={() => onSelectSort(key)}
            className={`rounded-md border px-2.5 py-1 text-xs font-medium transition-colors ${
              sort === key
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                : 'border-zinc-800 bg-zinc-900 text-zinc-500 hover:border-zinc-700 hover:text-zinc-300'
            }`}
          >
            {SORT_LABELS[key]}
          </button>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="space-y-2 animate-pulse">
          {[0, 1, 2, 3, 4].map(i => (
            <div key={i} className="h-12 rounded-lg bg-zinc-800" />
          ))}
        </div>
      )}

      {/* Table */}
      {!loading && !error && data && (
        <div className="space-y-3">
          <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-800 text-zinc-500 text-[11px] uppercase tracking-wider">
                  <th className="text-left py-3 pl-4 pr-2 w-10">#</th>
                  <th className="text-left py-3 px-2">Player</th>
                  <th className="text-center py-3 px-2">Pos</th>
                  <th className="text-center py-3 px-2">Team</th>
                  <th className="text-right py-3 px-2">G</th>
                  <th className="text-right py-3 px-2">ADP</th>
                  <th className="text-right py-3 px-2">Season Proj</th>
                  {sort !== 'adp' && sort !== 'season_proj_pts' && <th className="text-right py-3 px-2">{SORT_LABELS[sort]}</th>}
                  <th className="text-right py-3 px-2">
                    <span className="inline-flex items-center gap-1">
                      Rank
                      <span className="font-normal normal-case tracking-normal">(you)</span>
                    </span>
                  </th>
                  <th className="text-center py-3 pr-4 pl-2">Watch</th>
                  <th className="text-center py-3 pr-4 pl-2">Fade</th>
                </tr>
              </thead>
              <tbody>
                {data.players.map(player => (
                  <DraftPlayerRow
                    key={player.player_id}
                    player={player}
                    sort={sort}
                    noteRank={notes.rank[player.player_id]}
                    watched={notes.watch[player.player_id] === true}
                    faded={notes.fade[player.player_id] === true}
                    onSetRank={rank => onSetRank(player.player_id, rank)}
                    onToggleWatch={() => onToggleWatch(player.player_id)}
                    onToggleFade={() => onToggleFade(player.player_id)}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {data.eligible_players > 0 && (
            <Pagination
              offset={data.offset}
              limit={data.limit}
              total={data.eligible_players}
              returned={data.returned_players}
              onChange={onSetOffset}
            />
          )}
        </div>
      )}

      {!loading && !error && !data && (
        <div className="text-center py-12 text-zinc-500 text-sm">
          Draft board unavailable.
        </div>
      )}
    </section>
  )
}

function DraftPlayerRow({
  player,
  sort,
  noteRank,
  watched,
  faded,
  onSetRank,
  onToggleWatch,
  onToggleFade,
}: {
  player: NflDraftPlayer
  sort: NflDraftSort
  noteRank: number | undefined
  watched: boolean
  faded: boolean
  onSetRank: (rank: number | null) => void
  onToggleWatch: () => void
  onToggleFade: () => void
}) {
  const sortValue = player[sort]
  const sortDisplay =
    sortValue != null
      ? typeof sortValue === 'number'
        ? sortValue.toFixed(1)
        : String(sortValue)
      : '—'

  return (
    <tr className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
      <td className="py-2.5 pl-4 pr-2 text-zinc-500 text-xs tabular-nums">
        {player.rank}
      </td>
      <td className="py-2.5 px-2">
        <a
          href={`/player/${player.player_id}`}
          className="font-medium text-zinc-200 hover:text-emerald-400 transition-colors"
        >
          {player.name}
        </a>
      </td>
      <td className="py-2.5 px-2 text-center">
        <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[11px] font-semibold uppercase text-zinc-400">
          {player.position}
        </span>
      </td>
      <td className="py-2.5 px-2 text-center text-zinc-400 text-xs">
        {player.current_team}
        {player.team_changed === true && (
          <span className="ml-1 text-emerald-400" title={`Was ${player.reference_team}`}>↗</span>
        )}
      </td>
      <td className="py-2.5 px-2 text-right font-mono tabular-nums text-zinc-400 text-xs">
        {player.games}
      </td>
      <td className="py-2.5 px-2 text-right font-mono tabular-nums text-zinc-300 font-semibold">
        {player.adp != null ? player.adp.toFixed(1) : '—'}
        {player.percent_owned != null && (
          <div className="text-[10px] font-normal text-zinc-600">{player.percent_owned.toFixed(1)}% owned</div>
        )}
      </td>
      <td className="py-2.5 px-2 text-right font-mono tabular-nums text-zinc-300 font-semibold">
        {player.season_proj_pts != null ? player.season_proj_pts.toFixed(1) : '—'}
        {player.games_assumed != null && (
          <div className="text-[10px] font-normal text-zinc-600">{player.games_assumed} gms assumed</div>
        )}
      </td>
      {sort !== 'adp' && sort !== 'season_proj_pts' && (
        <td className="py-2.5 px-2 text-right font-mono tabular-nums text-zinc-300 font-semibold">
          {sortDisplay}
        </td>
      )}
      <td className="py-2.5 px-2 text-right">
        <input
          type="number"
          min={1}
          max={999}
          value={noteRank ?? ''}
          onChange={e => {
            const v = e.target.value
            if (v === '') {
              onSetRank(null)
            } else {
              const n = parseInt(v, 10)
              if (n >= 1 && n <= 999) onSetRank(n)
            }
          }}
          className="w-14 rounded border border-zinc-700 bg-zinc-800 py-1 px-1.5 text-xs font-mono tabular-nums text-zinc-300 text-right focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          aria-label={`Your rank for ${player.name}`}
        />
      </td>
      <td className="py-2.5 pr-4 pl-2 text-center">
        <button
          type="button"
          aria-pressed={watched}
          onClick={onToggleWatch}
          className={`text-lg leading-none transition-colors ${
            watched ? 'text-amber-400' : 'text-zinc-700 hover:text-zinc-400'
          }`}
          title={watched ? 'Remove watch' : 'Add to watch list'}
        >
          {watched ? '★' : '☆'}
        </button>
      </td>
      <td className="py-2.5 pr-4 pl-2 text-center">
        <button
          type="button"
          aria-pressed={faded}
          onClick={onToggleFade}
          className={`text-sm font-bold leading-none transition-colors ${
            faded ? 'text-red-400' : 'text-zinc-700 hover:text-zinc-400'
          }`}
          title={faded ? 'Remove fade' : 'Mark as fade'}
        >
          {faded ? '✕' : '✕'}
        </button>
      </td>
    </tr>
  )
}

function Pagination({
  offset,
  limit,
  total,
  returned,
  onChange,
}: {
  offset: number
  limit: number
  total: number
  returned: number
  onChange: (offset: number) => void
}) {
  const hasPrev = offset > 0
  const hasNext = offset + returned < total
  const start = offset + 1
  const end = offset + returned

  return (
    <div className="flex items-center justify-between gap-3 text-xs text-zinc-500">
      <span className="tabular-nums">
        {start}–{end} of {total}
      </span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          disabled={!hasPrev}
          onClick={() => onChange(Math.max(0, offset - limit))}
          className="rounded border border-zinc-800 bg-zinc-900 px-2.5 py-1 hover:bg-zinc-800 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          Prev
        </button>
        <button
          type="button"
          disabled={!hasNext}
          onClick={() => onChange(offset + limit)}
          className="rounded border border-zinc-800 bg-zinc-900 px-2.5 py-1 hover:bg-zinc-800 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          Next
        </button>
      </div>
    </div>
  )
}
