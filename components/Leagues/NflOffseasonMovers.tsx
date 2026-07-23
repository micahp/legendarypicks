import type { ReactNode } from 'react'
import type { NflTransaction } from './types'

interface Props {
  data: NflTransaction[] | null
  loading: boolean
  error: string | null
}

export default function NflOffseasonMovers({ data, loading, error }: Props) {
  if (loading) {
    return (
      <div className="animate-pulse space-y-3 rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <div className="h-4 w-40 rounded bg-zinc-800" />
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-4 w-full rounded bg-zinc-800" />
        ))}
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <p className="text-sm text-zinc-500">{error || 'Trades unavailable.'}</p>
      </div>
    )
  }

  if (data.length === 0) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <p className="text-sm text-zinc-500">No recent trades.</p>
      </div>
    )
  }

  return (
    <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
      <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-zinc-500 mb-4">
        Recent Trades
      </h3>
      <div className="space-y-3">
        {data.map((t, i) => (
          <div key={`${t.date}-${t.team}-${i}`} className="flex items-start gap-3">
            <span className="mt-0.5 shrink-0 w-12 text-right text-[11px] tabular-nums text-zinc-600">
              {formatDate(t.date)}
            </span>
            {t.team ? (
              <span className="mt-0.5 shrink-0 rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-zinc-400">
                {t.team}
              </span>
            ) : null}
            <p className="text-sm text-zinc-300">{boldPlayers(t.description, t.players)}</p>
          </div>
        ))}
      </div>
    </section>
  )
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

// Bold the player name(s) the backend already extracted, without dangerouslySetInnerHTML.
function boldPlayers(text: string, players?: string[]): ReactNode {
  if (!players || players.length === 0) return text
  const pattern = new RegExp(`(${players.map(escapeRegExp).join('|')})`, 'g')
  const parts = text.split(pattern)
  return parts.map((part, i) =>
    players.includes(part) ? <strong key={i} className="font-semibold text-zinc-100">{part}</strong> : part
  )
}

function formatDate(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
