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
        <p className="text-sm text-zinc-500">{error || 'Transactions unavailable.'}</p>
      </div>
    )
  }

  if (data.length === 0) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <p className="text-sm text-zinc-500">No recent roster moves.</p>
      </div>
    )
  }

  return (
    <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
      <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-zinc-500 mb-4">
        Offseason Movers
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
            <p className="text-sm text-zinc-300">{t.description}</p>
          </div>
        ))}
      </div>
    </section>
  )
}

function formatDate(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
