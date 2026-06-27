import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/router'

interface Hit { id: number; name: string; team: string; league: string }

export default function GlobalSearch() {
  const router = useRouter()
  const [q, setQ] = useState('')
  const [results, setResults] = useState<Hit[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (q.length < 2) { setResults([]); return }
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`/api/players/search?q=${encodeURIComponent(q)}`)
        setResults(await r.json()); setOpen(true); setActive(0)
      } catch {}
    }, 200)
    return () => clearTimeout(t)
  }, [q])

  useEffect(() => {
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const go = (id: number) => { setOpen(false); setQ(''); setResults([]); router.push(`/player/${id}`) }

  const onKey = (e: React.KeyboardEvent) => {
    if (!open || !results.length) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive(a => Math.min(a + 1, results.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(a => Math.max(a - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); go(results[active].id) }
    else if (e.key === 'Escape') setOpen(false)
  }

  return (
    <div ref={ref} className="relative w-44 sm:w-56">
      <input
        type="text" value={q} onChange={e => setQ(e.target.value)} onKeyDown={onKey}
        onFocus={() => results.length > 0 && setOpen(true)}
        placeholder="Search players…"
        className="w-full px-3 py-1.5 rounded-lg border border-zinc-800 bg-zinc-900 text-zinc-200 placeholder-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
      />
      {open && results.length > 0 && (
        <div className="absolute top-full right-0 mt-1 w-64 rounded-xl border border-zinc-700 bg-zinc-900 shadow-xl z-50 overflow-hidden">
          {results.slice(0, 8).map((p, i) => (
            <button key={p.id} onClick={() => go(p.id)} onMouseEnter={() => setActive(i)}
              className={`w-full text-left px-4 py-2.5 flex justify-between items-center text-sm ${i === active ? 'bg-zinc-800' : 'hover:bg-zinc-800'}`}>
              <span className="font-medium">{p.name}</span>
              <span className="text-xs text-zinc-500">{p.team} · {p.league?.toUpperCase()}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
