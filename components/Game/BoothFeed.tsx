import { useEffect, useState } from 'react'
import ListenLive from '../ListenLive'

type Prop = { player: string; market: string; line: string; lean: string }
type Insight = {
  tag: string
  subject: string
  quote: string
  strength: number
  ts?: string
  headline?: string
  analysis?: string
  prop?: Prop
}
type BoothContext = { insights?: Insight[] }

const LEAN_STYLE: Record<string, { cls: string; mark: string }> = {
  back: { cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30', mark: '▲' },
  fade: { cls: 'bg-red-500/15 text-red-300 border-red-500/30', mark: '▼' },
  watch: { cls: 'bg-zinc-700/40 text-zinc-300 border-zinc-600/50', mark: '•' },
}

const TAG_STYLE: Record<string, string> = {
  'Key man': 'bg-amber-500/15 text-amber-300 border-amber-500/25',
  Momentum: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25',
  Tactical: 'bg-sky-500/15 text-sky-300 border-sky-500/25',
  Mentality: 'bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/25',
  Fatigue: 'bg-orange-500/15 text-orange-300 border-orange-500/25',
}

const clock = (ts?: string) => (ts && ts.length >= 16 ? ts.slice(11, 16) : '')

function PropChip({ prop }: { prop: Prop }) {
  const s = LEAN_STYLE[prop.lean] || LEAN_STYLE.watch
  return (
    <span className={`mt-1 inline-flex max-w-full flex-wrap items-center gap-x-1.5 rounded-md border px-2 py-0.5 text-xs font-medium ${s.cls}`}>
      <span className="text-[10px]">{s.mark}</span>
      <span className="text-[9px] uppercase tracking-wide opacity-70">{prop.lean}</span>
      <span className="font-semibold">{prop.player}</span>
      <span className="opacity-80">{prop.market}</span>
      <span className="font-mono tabular-nums">{prop.line}</span>
    </span>
  )
}

export default function BoothFeed({ gameId }: { gameId: string }) {
  const [ctx, setCtx] = useState<BoothContext | null | undefined>(undefined)

  useEffect(() => {
    let alive = true
    const load = () =>
      fetch(`/api/wc/${gameId}/context?limit=40`)
        .then(r => (r.ok ? r.json() : null))
        .then(d => { if (alive) setCtx(d) })
        .catch(() => { if (alive) setCtx(null) })
    load()
    const t = setInterval(load, 30000) // refresh the feed while the match runs
    return () => { alive = false; clearInterval(t) }
  }, [gameId])

  const items = ctx?.insights ?? []

  return (
    <div className="space-y-4">
      {/* The audio and its enriched reads are one booth surface. */}
      <ListenLive />

      {ctx === undefined ? (
        <div className="space-y-3 animate-pulse">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-3 bg-zinc-800 rounded w-full" />
          ))}
        </div>
      ) : !ctx || items.length === 0 ? (
        <p className="text-sm text-zinc-500 py-8 text-center">
          Nothing from the booth yet — reads appear as the broadcast calls the game.
        </p>
      ) : (
        <section className="overflow-hidden rounded-lg border border-emerald-500/20 bg-ink-900">
          <div className="flex items-center justify-between gap-3 border-b border-zinc-800 px-3 py-2.5">
            <h3 className="text-[10px] font-medium uppercase tracking-[0.18em] text-emerald-400">Booth intelligence</h3>
            <span className="text-right text-[10px] text-zinc-600">takeaway first · quote as evidence</span>
          </div>
          <ol className="divide-y divide-zinc-800/70">
            {items.map((it, i) => (
              <li key={i} className="px-3 py-3">
                <div className="flex gap-2.5">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex flex-wrap items-center gap-1.5">
                      <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium ${TAG_STYLE[it.tag] || 'bg-zinc-800 text-zinc-400 border-zinc-700'}`}>
                        {it.tag}
                      </span>
                      {it.subject && <span className="text-[10px] font-medium text-zinc-400">{it.subject}</span>}
                      {clock(it.ts) && <span className="font-mono text-[10px] tabular-nums text-zinc-600">{clock(it.ts)}</span>}
                    </div>
                    <p className="text-sm font-semibold leading-snug text-zinc-100">
                      {it.headline || `${it.subject || it.tag} is worth watching`}
                    </p>
                    {it.analysis && <p className="mt-0.5 text-xs leading-snug text-zinc-400">{it.analysis}</p>}
                    <p className="mt-1 text-xs leading-snug text-zinc-600">
                      <span className="font-medium uppercase tracking-wide text-zinc-500">Booth: </span>
                      “{it.quote}”
                    </p>
                    {it.prop && <div><PropChip prop={it.prop} /></div>}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}
      <p className="text-[10px] text-zinc-600">Reads pulled live from the match broadcast · refreshes every 30s.</p>
    </div>
  )
}
