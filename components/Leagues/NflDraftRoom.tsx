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
  query: string
  notes: NflDraftNotes
  onSelectPosition: (position: DraftPosition) => void
  onSelectSort: (sort: NflDraftSort) => void
  onSetQuery: (query: string) => void
  onClearQuery: () => void
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
  query,
  notes,
  onSelectPosition,
  onSelectSort,
  onSetQuery,
  onClearQuery,
  onSetOffset,
  onSetRank,
  onToggleWatch,
  onToggleFade,
}: Props) {
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 pb-2">
        <h3 className="text-xl font-bold text-zinc-100">
          Player Rankings
        </h3>

        {/* Search. Research is name-driven — you arrive wanting one player. */}
        <div className="relative w-full sm:w-64">
          <span
            aria-hidden="true"
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-zinc-600"
          >
            ⌕
          </span>
          <input
            type="search"
            value={query}
            onChange={e => onSetQuery(e.target.value)}
            placeholder="Search rankings"
            aria-label="Search player rankings by name"
            className="w-full rounded-lg border border-zinc-700 bg-zinc-800/60 py-1.5 pl-8 pr-8 text-sm text-zinc-200 placeholder:text-zinc-600 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 [&::-webkit-search-cancel-button]:hidden"
          />
          {query !== '' && (
            <button
              type="button"
              onClick={onClearQuery}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded px-1 text-sm leading-none text-zinc-500 transition-colors hover:text-zinc-200"
            >
              ✕
            </button>
          )}
        </div>
      </div>

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

      {/* No match. Say which search found nothing, not just "no results". */}
      {!loading && !error && data && data.players.length === 0 && (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-12 text-center">
          <p className="text-sm text-zinc-400">
            {data.query
              ? `No player named “${data.query}” on the board.`
              : 'No players match these filters.'}
          </p>
          {data.query && (
            <button
              type="button"
              onClick={onClearQuery}
              className="mt-3 rounded-md border border-zinc-700 px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:border-zinc-600 hover:text-zinc-100"
            >
              Clear search
            </button>
          )}
        </div>
      )}

      {/* Table */}
      {!loading && !error && data && data.players.length > 0 && (
        <div className="space-y-3">
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
                      of {data.team_games}
                    </span>
                  </th>
                  <th className="text-right py-3 px-2">
                    PPR
                    <span className="block font-normal normal-case tracking-normal text-zinc-600">
                      / game played
                    </span>
                  </th>
                  <th className="text-right py-3 px-2">
                    PPR
                    <span className="block font-normal normal-case tracking-normal text-zinc-600">
                      / team game
                    </span>
                  </th>
                  <th className="text-right py-3 px-2">
                    Expected
                    <span className="block font-normal normal-case tracking-normal text-zinc-600">
                      PPR / game
                    </span>
                  </th>
                  <th className="text-right py-3 px-2">Snap</th>
                  <th className="text-right py-3 px-2">Tgt</th>
                  <th className="text-right py-3 px-2">ADP</th>
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
  noteRank,
  watched,
  faded,
  onSetRank,
  onToggleWatch,
  onToggleFade,
}: {
  player: NflDraftPlayer
  noteRank: number | undefined
  watched: boolean
  faded: boolean
  onSetRank: (rank: number | null) => void
  onToggleWatch: () => void
  onToggleFade: () => void
}) {
  const noSample = player.sample === 'none'
  const thin = player.sample === 'thin'
  const missed = player.team_games - player.games_played

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
        <div className="text-[10px] text-zinc-600">
          {player.current_team}
          {player.depth_rank != null && ` · ${player.position}${player.depth_rank}`}
          {/* A team change is information, not an achievement — no accent. */}
          {player.team_changed === true && player.depth_team && (
            <span className="ml-1 text-zinc-500">from {player.depth_team}</span>
          )}
        </div>
      </td>
      <td className="py-2.5 px-2 text-center">
        <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[11px] font-semibold uppercase text-zinc-400">
          {player.position}
        </span>
      </td>

      {/* Availability — the headline. Accent marks the games he missed. */}
      <td className="py-2.5 px-2">
        {noSample ? (
          <span className="text-[11px] text-zinc-500">No NFL sample</span>
        ) : (
          <>
            <div className="flex items-baseline gap-1.5">
              <span
                className={`font-mono tabular-nums text-sm font-semibold ${
                  missed > 0 ? 'text-amber-400' : 'text-zinc-300'
                }`}
              >
                {player.games_played}/{player.team_games}
              </span>
              {missed > 0 && (
                <span className="text-[10px] text-zinc-600">
                  missed {missed}
                </span>
              )}
            </div>
            <AvailabilityStrip
              weeksPlayed={player.weeks_played}
              teamWeeks={player.team_weeks}
              name={player.name}
            />
          </>
        )}
      </td>

      {/* Both averages, side by side. They diverge exactly when availability drops. */}
      <td className="py-2.5 px-2 text-right font-mono tabular-nums">
        <StatValue value={player.ppr_per_game_played} muted={thin} />
        {thin && !noSample && (
          <div className="text-[10px] font-normal text-zinc-600">
            n={player.games_played}
          </div>
        )}
      </td>
      <td className="py-2.5 px-2 text-right font-mono tabular-nums">
        <StatValue value={player.ppr_per_team_game} strong />
      </td>
      <td className="py-2.5 px-2 text-right font-mono tabular-nums">
        <StatValue value={player.xfp_per_game} />
      </td>
      <td className="py-2.5 px-2 text-right font-mono tabular-nums text-zinc-400 text-xs">
        {player.snap_pct != null ? `${player.snap_pct.toFixed(0)}%` : '—'}
      </td>
      <td className="py-2.5 px-2 text-right font-mono tabular-nums text-zinc-400 text-xs">
        {player.target_share != null ? `${player.target_share.toFixed(1)}%` : '—'}
      </td>
      <td className="py-2.5 px-2 text-right font-mono tabular-nums text-zinc-300 font-semibold">
        {player.adp != null ? player.adp.toFixed(1) : '—'}
        {player.percent_owned != null && (
          <div className="text-[10px] font-normal text-zinc-600">{player.percent_owned.toFixed(1)}% owned</div>
        )}
      </td>
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

/** A dash that is visibly not a zero. Absence is a claim about us. */
function StatValue({
  value,
  strong,
  muted,
}: {
  value: number | null
  strong?: boolean
  muted?: boolean
}) {
  if (value == null) return <span className="text-zinc-700">—</span>
  return (
    <span
      className={
        muted
          ? 'text-zinc-500'
          : strong
            ? 'text-zinc-200 font-semibold'
            : 'text-zinc-400'
      }
    >
      {value.toFixed(1)}
    </span>
  )
}

/**
 * One cell per game the player's team actually played — 17, not 18, because a
 * bye is not an absence. Played renders quiet; the saturated colour is reserved
 * for the games he missed, which is the information no competitor shows.
 */
function AvailabilityStrip({
  weeksPlayed,
  teamWeeks,
  name,
}: {
  weeksPlayed: number[]
  teamWeeks: number[]
  name: string
}) {
  if (teamWeeks.length === 0) return null
  const played = new Set(weeksPlayed)
  const missedCount = teamWeeks.filter(week => !played.has(week)).length

  return (
    <div
      className="mt-1 flex gap-[2px]"
      role="img"
      aria-label={`${name} played ${weeksPlayed.length} of ${teamWeeks.length} games, missing ${missedCount}`}
    >
      {teamWeeks.map(week => (
        <span
          key={week}
          title={`Week ${week}: ${played.has(week) ? 'played' : 'did not play'}`}
          className={`h-3 w-[5px] rounded-[1px] ${
            played.has(week) ? 'bg-zinc-700' : 'bg-amber-500'
          }`}
        />
      ))}
    </div>
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
