import { Tab } from './types'

// ── tabs ──
export default function TabBar({ active, onChange, tabs }: {
  active: Tab
  onChange: (t: Tab) => void
  tabs?: { key: Tab; label: string }[]
}) {
  const defaultTabs: { key: Tab; label: string }[] = [
    { key: 'boxscore', label: 'Box Score' },
    { key: 'playbyplay', label: 'Play-by-Play' },
    { key: 'props', label: 'Props' },
    { key: 'info', label: 'Game Info' },
  ]
  const visibleTabs = tabs ?? defaultTabs
  if (visibleTabs.length === 0) return null

  return (
    <div className="flex gap-0 overflow-x-auto border-b border-zinc-800 -mx-4 px-4">
      {visibleTabs.map(t => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={`px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors ${
            active === t.key
              ? 'text-white'
              : 'text-zinc-500 hover:text-zinc-300'
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}
