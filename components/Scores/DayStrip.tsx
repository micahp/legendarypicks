import { useMemo } from 'react'

interface DayStripProps {
  date: string
  onChange: (date: string) => void
}

function toISODate(d: Date): string {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export default function DayStrip({ date, onChange }: DayStripProps) {
  const selected = new Date(date)
  const days = useMemo(() => {
    const start = new Date(selected)
    // Center selected day in a 7-day window
    start.setDate(selected.getDate() - 3)
    return Array.from({ length: 7 }).map((_, i) => {
      const d = new Date(start)
      d.setDate(start.getDate() + i)
      return d
    })
  }, [date])

  const go = (offset: number) => {
    const d = new Date(selected)
    d.setDate(selected.getDate() + offset)
    onChange(toISODate(d))
  }

  const isToday = (d: Date) => {
    const now = new Date()
    return (
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate()
    )
  }

  return (
    <div className="flex items-center justify-between gap-3 bg-zinc-900 text-zinc-100 rounded-xl px-3 py-2">
      <button
        type="button"
        onClick={() => go(-7)}
        className="px-2 py-1 rounded-md hover:bg-zinc-800"
        aria-label="Previous week"
      >
        ‹
      </button>
      <div className="flex-1 grid grid-cols-7 gap-2">
        {days.map((d) => {
          const iso = toISODate(d)
          const active = iso === date
          return (
            <button
              key={iso}
              type="button"
              onClick={() => onChange(iso)}
              className={[
                'rounded-lg px-2 py-2 text-center transition',
                active
                  ? 'bg-emerald-500 text-black font-semibold shadow'
                  : 'bg-zinc-800 hover:bg-zinc-700',
              ].join(' ')}
            >
              <div className="text-xs uppercase tracking-wide opacity-70">
                {d.toLocaleDateString(undefined, { weekday: 'short' })}
              </div>
              <div className="text-base leading-none">{d.getDate()}</div>
              {isToday(d) && <div className="text-[10px] mt-0.5 opacity-60">Today</div>}
            </button>
          )
        })}
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => go(7)}
          className="px-2 py-1 rounded-md hover:bg-zinc-800"
          aria-label="Next week"
        >
          ›
        </button>
        <button
          type="button"
          onClick={() => onChange(toISODate(new Date()))}
          className="px-2 py-1 rounded-md bg-zinc-800 hover:bg-zinc-700"
        >
          Today
        </button>
      </div>
    </div>
  )
}


