import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/router'

interface Hit { id: number; name: string; team: string | null; league: string }

export default function GlobalSearch() {
  const router = useRouter()
  const [q, setQ] = useState('')
  const [results, setResults] = useState<Hit[]>([])
  const [open, setOpen] = useState(false)        // results dropdown
  const [active, setActive] = useState(0)
  const [mobileOpen, setMobileOpen] = useState(false)  // mobile expanded input
  const ref = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

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
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) { setOpen(false); setMobileOpen(false) }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  useEffect(() => { if (mobileOpen) inputRef.current?.focus() }, [mobileOpen])

  const go = (id: number) => { setOpen(false); setMobileOpen(false); setQ(''); setResults([]); router.push(`/player/${id}`) }

  const onKey = (e: React.KeyboardEvent) => {
    if (!open || !results.length) { if (e.key === 'Escape') setMobileOpen(false); return }
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive(a => Math.min(a + 1, results.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(a => Math.max(a - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); go(results[active].id) }
    else if (e.key === 'Escape') { setOpen(false); setMobileOpen(false) }
  }

  return (
    <div ref={ref} className="relative flex items-center justify-end">
      {/* Mobile: search icon that toggles the input */}
      <button
        type="button" onClick={() => setMobileOpen(o => !o)} aria-label="Search players"
        className="sm:hidden p-1.5 text-zinc-400 hover:text-zinc-200">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
      </button>

      {/* Input — inline on desktop; on mobile shown only when the icon is tapped */}
      <div className={`${mobileOpen ? 'block absolute right-0 top-full mt-2 w-64 z-50' : 'hidden'} sm:block sm:static sm:right-auto sm:top-auto sm:mt-0 sm:w-56`}>
        <input
          ref={inputRef} type="text" value={q} onChange={e => setQ(e.target.value)} onKeyDown={onKey}
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
                <span className="text-xs text-zinc-500">{p.team ? `${p.team} · ` : ''}{p.league?.toUpperCase()}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
