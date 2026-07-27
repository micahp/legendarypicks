import { useAllDayCollection } from './hooks/useAllDayCollection'
import type { AllDayMoment, AllDayStatus } from './types'

const POSITION_ORDER = ['QB', 'RB', 'WR', 'TE', 'DB', 'LB', 'DL', 'OL', 'K', 'P', 'LS']

function groupByPosition(moments: AllDayMoment[]): [string, AllDayMoment[]][] {
  const groups = new Map<string, AllDayMoment[]>()
  for (const m of moments) {
    const pos = m.position || '?'
    if (!groups.has(pos)) groups.set(pos, [])
    groups.get(pos)!.push(m)
  }
  const known = POSITION_ORDER.filter(p => groups.has(p))
  const unknown = Array.from(groups.keys()).filter(k => !POSITION_ORDER.includes(k)).sort()
  const result: [string, AllDayMoment[]][] = []
  for (const pos of known.concat(unknown)) {
    result.push([pos, groups.get(pos)!])
  }
  return result
}

const TIER_COLORS: Record<string, string> = {
  COMMON: 'text-zinc-400',
  UNCOMMON: 'text-emerald-400',
  RARE: 'text-amber-400',
  LEGENDARY: 'text-purple-400',
  ULTIMATE: 'text-rose-400',
}

export default function LineupsTab() {
  const {
    address, inputValue, setInputValue, data, loading, pageLoading, error,
    offset, limit, totalPages, currentPage,
    submit, clear, goToPage,
  } = useAllDayCollection()

  const hasSearched = !!data || loading

  return (
    <div className="space-y-6" data-testid="lineups-tab">
      {/* Address input */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-3">
        <label className="block text-sm font-medium text-zinc-400">
          Flow wallet address
        </label>
        <div className="flex gap-2">
          <input
            type="text"
            value={inputValue}
            onChange={e => setInputValue(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && submit(inputValue)}
            placeholder="0x..."
            className="flex-1 bg-ink-900 border border-zinc-700 rounded px-3 py-2 text-sm text-zinc-100
                       placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500
                       font-mono"
            autoFocus
          />
          <button
            onClick={() => submit(inputValue)}
            disabled={loading}
            className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded
                       hover:bg-emerald-500 disabled:opacity-50 transition-colors"
          >
            {loading && !pageLoading ? 'Loading…' : 'Look up'}
          </button>
        </div>
        {address && !loading && (
          <button
            onClick={clear}
            className="text-xs text-zinc-500 hover:text-zinc-400 transition-colors"
          >
            Clear & try another address
          </button>
        )}
        <p className="text-xs text-zinc-600">
          Paste a Flow wallet address that holds NFL All Day moments. Nothing is stored server-side.
        </p>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-900/30 border border-red-800 rounded-lg p-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Empty state — before any search */}
      {!hasSearched && (
        <div className="text-center py-12 text-zinc-500 space-y-2">
          <p className="text-lg">🏈</p>
          <p>Paste a Flow wallet address above to see its NFL All Day moments.</p>
          <p className="text-xs text-zinc-600">
            You can find your address in your Dapper Wallet or Blocto settings.
          </p>
        </div>
      )}

      {/* Loading skeleton — full load only (first search) */}
      {loading && !pageLoading && !data && (
        <div className="space-y-3 animate-pulse">
          {[1, 2, 3].map(i => (
            <div key={i} className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
              <div className="h-4 bg-zinc-800 rounded w-48 mb-2" />
              <div className="h-3 bg-zinc-800 rounded w-32" />
            </div>
          ))}
        </div>
      )}

      {/* Results (kept visible during page transitions with subtle loading indicator) */}
      {data && (
        <div className="space-y-4">
          {/* Summary bar */}
          {data.status === 'ok' ? (
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
              <span className="text-zinc-300 tabular-nums">
                {data.returned < data.total
                  ? `Showing ${data.returned.toLocaleString()} of ${data.total.toLocaleString()} moments`
                  : `${data.total.toLocaleString()} moment${data.total !== 1 ? 's' : ''}`}
              </span>
              {data.unmatched > 0 && (
                <span className="text-amber-400 tabular-nums">
                  {data.unmatched.toLocaleString()} not matched to a player
                </span>
              )}
              {data.nonPlayer > 0 && (
                <span className="text-zinc-500 tabular-nums">
                  {data.nonPlayer.toLocaleString()} team moment
                  {data.nonPlayer !== 1 ? 's' : ''}
                </span>
              )}
              {data.sources.length > 0 && data.sources[0] !== data.address && (
                <span className="text-xs text-zinc-500 font-mono">
                  via linked account{data.sources.length !== 1 ? 's' : ''}{' '}
                  {data.sources.join(', ')}
                </span>
              )}
            </div>
          ) : (
            <EmptyResult status={data.status} address={data.address} />
          )}

          {/* Page loading bar — subtle, does not blank the list */}
          {pageLoading && (
            <div className="h-0.5 bg-zinc-800 rounded-full overflow-hidden">
              <div className="h-full bg-emerald-500/50 animate-pulse w-1/3 rounded-full" />
            </div>
          )}

          {/* Moments by position */}
          {data.returned > 0 && (
            <div className={`space-y-6 ${pageLoading ? 'opacity-60 transition-opacity' : ''}`}>
              {groupByPosition(data.moments).map(([pos, moments]) => (
                <div key={pos}>
                  <h3 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider mb-2">
                    {pos}
                    <span className="ml-2 text-zinc-600 tabular-nums font-normal">
                      {moments.length}
                    </span>
                  </h3>
                  <div className="space-y-2">
                    {moments.map(m => (
                      <MomentCard key={m.momentId} moment={m} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Paging controls */}
          {data.returned > 0 && data.total > limit && (
            <div className="flex items-center justify-between pt-2">
              <button
                onClick={() => goToPage(Math.max(0, offset - limit))}
                disabled={offset === 0 || pageLoading}
                className="px-3 py-1.5 text-sm text-zinc-400 bg-zinc-900 border border-zinc-800 rounded
                           hover:text-zinc-200 hover:border-zinc-700 disabled:opacity-30 disabled:cursor-not-allowed
                           transition-colors"
              >
                ← Previous
              </button>

              <span className="text-sm text-zinc-500 tabular-nums">
                Page {currentPage} of {totalPages}
              </span>

              <button
                onClick={() => goToPage(offset + limit)}
                disabled={offset + limit >= data.total || pageLoading}
                className="px-3 py-1.5 text-sm text-zinc-400 bg-zinc-900 border border-zinc-800 rounded
                           hover:text-zinc-200 hover:border-zinc-700 disabled:opacity-30 disabled:cursor-not-allowed
                           transition-colors"
              >
                Next →
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** An empty result is three different facts. Say which one it is. */
function EmptyResult({ status, address }: { status: AllDayStatus; address: string }) {
  const copy: Record<Exclude<AllDayStatus, 'ok'>, { headline: string; detail: string }> = {
    no_account: {
      headline: 'No such account on Flow',
      detail: `${address} has never been created on Flow mainnet. Check the address for a typo.`,
    },
    no_collection: {
      headline: 'This wallet has never held an All Day moment',
      detail:
        'The account exists but has no NFL All Day collection. If you use Dapper, paste the ' +
        'address shown in your Dapper wallet — we follow its linked accounts automatically.',
    },
    empty: {
      headline: 'Collection is empty',
      detail: 'This wallet has an All Day collection set up but holds no moments right now.',
    },
  }
  const { headline, detail } = copy[status]

  return (
    <div className="border border-zinc-800 rounded-lg p-4">
      <p className="text-sm text-zinc-300">{headline}</p>
      <p className="text-xs text-zinc-500 mt-1 max-w-prose">{detail}</p>
    </div>
  )
}

function MomentCard({ moment }: { moment: AllDayMoment }) {
  const hasPlayer = !!moment.player && moment.player.name
  // A team highlight names no player on chain. Calling that "not in player database"
  // blames our spine for data AllDay never published — the opposite of honest.
  const isTeamMoment = moment.isPlayerMoment === false
  const isUnmatched = !moment.player && !isTeamMoment

  return (
    <div
      className={`bg-zinc-900 border rounded-lg p-3 flex items-center gap-3
        ${isUnmatched ? 'border-zinc-800 opacity-60' : 'border-zinc-800 hover:border-zinc-700 transition-colors'}`}
    >
      {/* Thumbnail */}
      {moment.thumbnail && (
        <img
          src={moment.thumbnail}
          alt={moment.displayName}
          className="w-12 h-12 rounded object-cover flex-shrink-0 bg-zinc-800"
          loading="lazy"
        />
      )}

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-sm font-medium truncate ${isUnmatched ? 'text-zinc-500' : 'text-zinc-100'}`}>
            {hasPlayer ? (
              <a
                href={`/player/${moment.player!.id}`}
                className="hover:text-emerald-400 transition-colors"
              >
                {moment.player!.name}
              </a>
            ) : (
              moment.displayName || `${moment.firstName} ${moment.lastName}`.trim() || 'Unknown player'
            )}
          </span>
          {hasPlayer && (
            <>
              <span className="text-xs text-zinc-500 tabular-nums">{moment.player!.position}</span>
              <span className="text-xs text-zinc-600 tabular-nums">{moment.player!.team}</span>
            </>
          )}
        </div>

        <div className="flex items-center gap-2 mt-1 flex-wrap">
          <span className="text-xs text-zinc-500">{moment.playType}</span>
          {moment.seriesName && (
            <span className="text-xs text-zinc-600">{moment.seriesName}</span>
          )}
          {moment.setName && moment.setName !== 'Base' && (
            <span className="text-xs text-zinc-600">{moment.setName}</span>
          )}
          <span className={`text-xs font-medium ${TIER_COLORS[moment.tier] || 'text-zinc-500'}`}>
            {moment.tier}
          </span>
          <span className="text-xs text-zinc-600 tabular-nums">
            #{moment.serial}
          </span>
        </div>

        {isUnmatched && (
          <div className="mt-1">
            <span className="text-xs text-amber-500/70">
              Unmatched — {moment.firstName} {moment.lastName} not in player database
            </span>
          </div>
        )}

        {isTeamMoment && (
          <div className="mt-1">
            <span className="text-xs text-zinc-500">
              Team moment — All Day names no player for this one
            </span>
          </div>
        )}
      </div>

      {/* External link */}
      {moment.url && (
        <a
          href={moment.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-zinc-600 hover:text-zinc-400 flex-shrink-0"
        >
          ↗
        </a>
      )}
    </div>
  )
}
