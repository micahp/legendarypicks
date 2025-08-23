import { useEffect, useRef, useState } from 'react'

interface CalendarPopoverProps {
  date: string
  onChange: (date: string) => void
}

function toISODate(d: Date): string {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export default function CalendarPopover({ date, onChange }: CalendarPopoverProps) {
  const [open, setOpen] = useState(false)
  const [cursor, setCursor] = useState(() => new Date(date))
  const anchorRef = useRef<HTMLButtonElement | null>(null)
  const panelRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    setCursor(new Date(date))
  }, [date])

  useEffect(() => {
    if (!open) return
    const onClickAway = (e: MouseEvent) => {
      const panel = panelRef.current
      const anchor = anchorRef.current
      if (!panel || !anchor) return
      const t = e.target as Node
      if (!panel.contains(t) && !anchor.contains(t)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickAway)
    return () => document.removeEventListener('mousedown', onClickAway)
  }, [open])

  const start = new Date(cursor)
  start.setDate(1)
  const firstDay = start.getDay()
  const gridStart = new Date(start)
  gridStart.setDate(1 - firstDay)
  const days = Array.from({ length: 42 }).map((_, i) => {
    const d = new Date(gridStart)
    d.setDate(gridStart.getDate() + i)
    return d
  })

  return (
    <div className="relative">
      <button
        ref={anchorRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="px-3 py-2 rounded-lg bg-zinc-900 text-zinc-100 hover:bg-zinc-800"
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        📅
      </button>
      {open && (
        <div
          ref={panelRef}
          role="dialog"
          className="absolute mt-2 right-0 z-50 w-80 rounded-xl border border-zinc-800 bg-zinc-900 text-zinc-100 shadow-xl p-3"
        >
          <div className="flex items-center justify-between mb-2">
            <button
              type="button"
              className="px-2 py-1 rounded hover:bg-zinc-800"
              onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))}
              aria-label="Previous month"
            >
              ‹
            </button>
            <div className="font-semibold">
              {cursor.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}
            </div>
            <button
              type="button"
              className="px-2 py-1 rounded hover:bg-zinc-800"
              onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))}
              aria-label="Next month"
            >
              ›
            </button>
          </div>
          <div className="grid grid-cols-7 gap-1 text-xs uppercase tracking-wide opacity-70">
            {['S','M','T','W','T','F','S'].map((d) => (
              <div key={d} className="text-center py-1">{d}</div>
            ))}
          </div>
          <div className="mt-1 grid grid-cols-7 gap-1">
            {days.map((d) => {
              const inMonth = d.getMonth() === cursor.getMonth()
              const iso = toISODate(d)
              const selected = iso === date
              return (
                <button
                  key={iso}
                  type="button"
                  onClick={() => { onChange(iso); setOpen(false) }}
                  className={[
                    'py-1.5 text-center rounded-md transition',
                    inMonth ? 'text-zinc-200' : 'text-zinc-500',
                    selected ? 'bg-emerald-500 text-black font-semibold' : 'hover:bg-zinc-800',
                  ].join(' ')}
                >
                  {d.getDate()}
                </button>
              )
            })}
          </div>
          <div className="mt-3 flex justify-between">
            <button
              type="button"
              onClick={() => { onChange(toISODate(new Date())); setOpen(false) }}
              className="px-2 py-1 rounded-md bg-zinc-800 hover:bg-zinc-700"
            >
              Today
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="px-2 py-1 rounded-md hover:bg-zinc-800"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  )
}


