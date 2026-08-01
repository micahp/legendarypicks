import { useEffect, useState } from 'react'


export interface PlayerNewsArticle {
  id: number
  source_player_id: string
  headline: string
  notes: string
  analysis: string
  injury_status: string | null
  injury_type: string | null
  injury_location: string | null
  return_date: string | null
  published: string
  link: string
}

export interface PlayerNewsResponse {
  player_id: number
  name: string
  source: string
  data_status: 'ready' | 'stale' | 'no_news' | 'unavailable' | 'unsupported'
  message: string | null
  source_updated_at?: string | null
  articles: PlayerNewsArticle[]
}

interface Props {
  playerId: number
  compact?: boolean
}

type ViewState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'loaded'; data: PlayerNewsResponse }


function isPlayerNewsResponse(value: unknown): value is PlayerNewsResponse {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<PlayerNewsResponse>
  const statuses = new Set(['ready', 'stale', 'no_news', 'unavailable', 'unsupported'])
  return (
    typeof candidate.player_id === 'number' &&
    typeof candidate.name === 'string' &&
    typeof candidate.source === 'string' &&
    typeof candidate.data_status === 'string' &&
    statuses.has(candidate.data_status) &&
    Array.isArray(candidate.articles) &&
    (!['ready', 'stale'].includes(candidate.data_status) || candidate.articles.length > 0)
  )
}


export function formatNewsDate(
  value: string,
  includeYear = false,
  locale?: string,
): string {
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  const parsed = dateOnly
    ? new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]))
    : new Date(value)
  if (Number.isNaN(parsed.getTime())) return 'Date unavailable'
  return parsed.toLocaleDateString(locale, {
    month: 'short',
    day: 'numeric',
    ...(includeYear ? { year: 'numeric' as const } : {}),
  })
}


export default function PlayerNews({ playerId, compact = false }: Props) {
  const [state, setState] = useState<ViewState>({ kind: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    setState({ kind: 'loading' })

    fetch(`/api/player/${playerId}/fantasy-news?limit=10`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(`Fantasy news request failed (${response.status})`)
        const body: unknown = await response.json()
        if (!isPlayerNewsResponse(body)) throw new Error('Fantasy news returned an invalid response')
        return body
      })
      .then(data => setState({ kind: 'loaded', data }))
      .catch(error => {
        if (error instanceof Error && error.name === 'AbortError') return
        setState({ kind: 'error', message: 'Fantasy news is temporarily unavailable.' })
      })

    return () => controller.abort()
  }, [playerId])

  if (state.kind === 'loading') {
    return (
      <div className="space-y-3 animate-pulse" aria-label="Loading fantasy news">
        {[0, 1, 2].map(index => (
          <div key={index} className="h-16 rounded-lg bg-zinc-800" />
        ))}
      </div>
    )
  }

  if (state.kind === 'error') {
    return <NewsState title="Fantasy news unavailable" message={state.message} />
  }

  const { data } = state
  if (data.data_status === 'unavailable' || data.data_status === 'unsupported') {
    return (
      <NewsState
        title="Fantasy news unavailable"
        message={data.message || 'Fantasy news is temporarily unavailable.'}
      />
    )
  }
  if (data.data_status === 'no_news') {
    return (
      <NewsState
        title="No recent fantasy news"
        message={data.message || 'No recent fantasy news for this player.'}
      />
    )
  }

  return (
    <div className={compact ? 'space-y-3' : 'space-y-4'}>
      {data.data_status === 'stale' && (
        <div
          className="rounded-md border border-amber-900/50 bg-amber-950/20 px-3 py-2 text-xs text-amber-300"
          role="status"
        >
          {data.message || 'Showing cached fantasy news while the latest refresh is delayed.'}
        </div>
      )}

      {data.articles.map(article => (
        <article
          key={article.id}
          className={`rounded-lg border border-zinc-800 bg-zinc-900/50 ${compact ? 'p-3 space-y-1.5' : 'p-4 space-y-2'}`}
        >
          <div className="flex items-start gap-2">
            <a
              href={article.link}
              target="_blank"
              rel="noopener noreferrer"
              className="flex-1 min-w-0"
            >
              <h4 className={`${compact ? 'text-xs' : 'text-sm'} font-semibold text-zinc-100 hover:text-emerald-400 transition-colors`}>
                {article.headline}
              </h4>
            </a>
            {article.injury_status && (
              <span className={`shrink-0 rounded bg-red-500/10 px-1.5 py-0.5 ${compact ? 'text-[9px]' : 'text-[10px]'} font-bold text-red-400 uppercase`}>
                {article.injury_status}
              </span>
            )}
          </div>

          <p className={`${compact ? 'text-[11px]' : 'text-xs'} text-zinc-400 leading-relaxed`}>
            {article.notes}
          </p>

          {article.analysis && (
            <div className={`rounded-md bg-zinc-800/50 ${compact ? 'px-2.5 py-1.5' : 'px-3 py-2'} border-l-2 border-emerald-500/50`}>
              <p className={`${compact ? 'text-[10px] mb-0.5' : 'text-[11px] mb-1'} font-semibold uppercase tracking-wider text-emerald-400/70`}>
                Fantasy Spin
              </p>
              <p className={`${compact ? 'text-[11px]' : 'text-xs'} text-zinc-300 leading-relaxed`}>
                {article.analysis}
              </p>
            </div>
          )}

          <div className={`flex flex-wrap items-center gap-x-3 gap-y-1 ${compact ? 'text-[9px]' : 'text-[10px]'} text-zinc-600`}>
            <time dateTime={article.published}>
              {formatNewsDate(article.published, !compact)}
            </time>
            {article.return_date && (
              <span>Estimated return: {formatNewsDate(article.return_date)}</span>
            )}
            {article.injury_type && (
              <span className="text-red-400/60">{article.injury_type}</span>
            )}
          </div>
        </article>
      ))}

      <p className={`${compact ? 'text-[9px]' : 'text-[10px]'} text-zinc-600`}>
        Source: {data.source}
      </p>
    </div>
  )
}


function NewsState({ title, message }: { title: string; message: string }) {
  return (
    <div className="py-6 text-center" role="status">
      <p className="text-sm font-medium text-zinc-400">{title}</p>
      <p className="mt-1 text-xs text-zinc-600">{message}</p>
    </div>
  )
}
