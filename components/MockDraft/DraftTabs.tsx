import { useRef } from 'react'

/* ── Tabs at every width ────────────────────────────────────────────────────
   One implementation, one set of gates, and the board gets the room. A
   breakpoint-conditional shell would mean two layouts, of which only the one
   the gate happens to open at 1400px is ever verified.

   Tab state is local and deliberately NOT in the URL: the clock is running, and
   a history entry per tab switch turns the browser Back button into a way to
   leave a draft you are in the middle of. */

export type DraftTabId = 'players' | 'queue' | 'board' | 'rosters'

interface Tab {
  id: DraftTabId
  label: string
}

const TABS: Tab[] = [
  { id: 'players', label: 'Players' },
  { id: 'queue', label: 'Queue' },
  { id: 'board', label: 'Board' },
  { id: 'rosters', label: 'Rosters' },
]

interface Props {
  value: DraftTabId
  onChange: (id: DraftTabId) => void
  /** ESPN's queue badge. Rendered even at 0 — a badge that appears and vanishes
   *  is read as a notification; this one is a count of what you lined up. */
  queueCount: number
}

export default function DraftTabs({ value, onChange, queueCount }: Props) {
  const ref = useRef<HTMLDivElement | null>(null)

  function onKeyDown(e: React.KeyboardEvent) {
    const idx = TABS.findIndex(t => t.id === value)
    let next = idx
    if (e.key === 'ArrowRight') next = (idx + 1) % TABS.length
    else if (e.key === 'ArrowLeft') next = (idx - 1 + TABS.length) % TABS.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = TABS.length - 1
    else return
    e.preventDefault()
    onChange(TABS[next].id)
    const el = ref.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]
    el?.focus()
  }

  return (
    <div
      ref={ref}
      role="tablist"
      aria-label="Draft room"
      onKeyDown={onKeyDown}
      className="flex items-stretch gap-1 border-b border-zinc-800"
    >
      {TABS.map(t => {
        const selected = t.id === value
        return (
          <button
            key={t.id}
            id={`tab-${t.id}`}
            role="tab"
            type="button"
            aria-selected={selected}
            aria-controls={`panel-${t.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(t.id)}
            className={`-mb-px flex items-baseline gap-1.5 border-b-2 px-3 py-2 text-sm transition-colors ${
              selected
                ? 'border-zinc-300 font-semibold text-zinc-100'
                : 'border-transparent text-zinc-500 hover:text-zinc-300'
            }`}
          >
            {t.label}
            {t.id === 'queue' && (
              <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-zinc-400">
                {queueCount}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
