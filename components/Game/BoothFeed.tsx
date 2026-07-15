import { useEffect, useState } from 'react'
import ListenLive from '../ListenLive'

type Insight = { tag: string; subject: string; quote: string; strength: number; ts?: string }

const TAG_STYLE: Record<string, string> = {
  'Key man': 'bg-amber-500/15 text-amber-300 border-amber-500/25',
  Momentum: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25',
  Tactical: 'bg-sky-500/15 text-sky-300 border-sky-500/25',
  Mentality: 'bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/25',
  Fatigue: 'bg-orange-500/15 text-orange-300 border-orange-500/25',
}

const clock = (ts?: string) => (ts && ts.length >= 16 ? ts.slice(11, 16) : '')

export default function BoothFeed({ gameId }: { gameId: string }) {
  const [items, setItems] = useState<Insight[] | null | undefined>(undefined)

  useEffect(() => {
    let alive = true
    const load = () =>
      fetch(`/api/wc/${gameId}/context?limit=40`)
        .then(r => (r.ok ? r.json() : null))
        .then(d => { if (alive) setItems(d?.insights ?? []) })
        .catch(() => { if (alive) setItems([]) })
    load()
    const t = setInterval(load, 30000) // refresh the feed while the match runs
    return () => { alive = false; clearInterval(t) }
  }, [gameId])

  return (
    <div className="space-y-4">
      {/* listen + read: the audio player anchors the feed */}
      <ListenLive />

      {items === undefined ? (
        <div className="space-y-3 animate-pulse">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-3 bg-zinc-800 rounded w-full" />
          ))}
        </div>
      ) : !items || items.length === 0 ? (
        <p className="text-sm text-zinc-500 py-8 text-center">
          Nothing from the booth yet — reads appear as the broadcast calls the game.
        </p>
      ) : (
        <ol className="space-y-3">
          {items.map((it, i) => (
            <li key={i} className="flex gap-3">
              <span className="mt-0.5 w-10 shrink-0 text-right font-mono text-[11px] tabular-nums text-zinc-600">
                {clock(it.ts)}
              </span>
              <span className={`mt-0.5 shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium ${TAG_STYLE[it.tag] || 'bg-zinc-800 text-zinc-400 border-zinc-700'}`}>
                {it.tag}
              </span>
              <p className="text-sm leading-snug text-zinc-300">
                {it.subject && <span className="font-semibold text-zinc-100">{it.subject}: </span>}
                <span className="text-zinc-400">“{it.quote}”</span>
              </p>
            </li>
          ))}
        </ol>
      )}
      <p className="text-[10px] text-zinc-600">Reads pulled live from the match broadcast · refreshes every 30s.</p>
    </div>
  )
}
