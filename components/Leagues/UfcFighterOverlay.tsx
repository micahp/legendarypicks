import { useEffect, useRef } from 'react'
import type { UfcOptimizerFighter } from './ufcOptimizer'
import { formatLocalFightTime } from './UfcSlateRail'

function money(value: number): string {
  return `$${value.toLocaleString()}`
}

function valueFor(fighter: UfcOptimizerFighter): number | null {
  return fighter.target === null ? null : fighter.target / (fighter.salary / 1000)
}

function shown(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

export default function UfcFighterOverlay({
  fighter,
  opponent,
  metricLabel,
  sourceUrl,
  sourceDescription,
  locked,
  excluded,
  onTarget,
  onLock,
  onExclude,
  onClose,
}: {
  fighter: UfcOptimizerFighter
  opponent: UfcOptimizerFighter | null
  metricLabel: string
  sourceUrl: string | null
  sourceDescription: string
  locked: boolean
  excluded: boolean
  onTarget: (value: string) => void
  onLock: (enabled: boolean) => void
  onExclude: (enabled: boolean) => void
  onClose: () => void
}) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const value = valueFor(fighter)

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeRef.current?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-4" role="dialog" aria-modal="true" aria-label={`${fighter.name} optimizer details`}>
      <button type="button" className="absolute inset-0 cursor-default bg-black/70" aria-label="Close fighter details" onClick={onClose} />
      <div className="relative z-10 max-h-[92vh] w-full overflow-y-auto rounded-t-2xl border border-zinc-800 bg-zinc-900 shadow-2xl sm:max-w-[560px] sm:rounded-xl">
        <button
          ref={closeRef}
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute right-3 top-3 rounded-md p-2 text-zinc-500 hover:text-zinc-200"
        >
          <span aria-hidden="true" className="text-xl leading-none">×</span>
        </button>

        <header className="border-b border-zinc-800 px-5 pb-4 pt-5 pr-12 sm:px-6">
          <div className="flex flex-wrap items-center gap-2">
            {fighter.weightClass && <span className="rounded bg-zinc-800 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">{fighter.weightClass}</span>}
            {fighter.country && <span className="text-xs text-zinc-500">{fighter.country}</span>}
          </div>
          <h2 className="mt-2 text-xl font-bold text-zinc-100">{fighter.name}</h2>
          <p className="mt-1 text-sm text-zinc-500">
            vs {opponent?.name || 'Opponent unavailable'} · {formatLocalFightTime(fighter.startTime)}
          </p>
        </header>

        <div className="space-y-5 p-5 sm:p-6">
          <section className="grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="DFS summary">
            <Metric label="Salary" value={money(fighter.salary)} />
            <Metric label={metricLabel} value={fighter.fppg === null ? '—' : fighter.fppg.toFixed(2)} />
            <Metric label="Value / $1K" value={value === null ? '—' : value.toFixed(2)} />
            <Metric label="Moneyline" value={shown(fighter.moneyline)} />
          </section>

          <section>
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Fight card</h3>
            <dl className="mt-2 grid grid-cols-2 overflow-hidden rounded-lg border border-zinc-800 sm:grid-cols-3">
              <Detail label="Record" value={fighter.record} />
              <Detail label="Age" value={fighter.age} />
              <Detail label="Height" value={fighter.height} />
              <Detail label="Reach" value={fighter.reach} />
              <Detail label="Class" value={fighter.weightClass} />
              <Detail label="Opponent ML" value={opponent?.moneyline} />
            </dl>
          </section>

          <section>
            <label htmlFor="ufc-overlay-target" className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
              Optimization target
            </label>
            <div className="mt-2 flex items-center gap-3">
              <input
                id="ufc-overlay-target"
                type="number"
                min="0"
                step="0.01"
                value={fighter.target ?? ''}
                onChange={event => onTarget(event.target.value)}
                className="w-28 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-right font-mono text-sm tabular-nums text-zinc-100 outline-none focus:border-emerald-500"
              />
              <p className="text-xs leading-5 text-zinc-600">Editable. The published source value remains visible above.</p>
            </div>
          </section>

          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              aria-pressed={locked}
              onClick={() => onLock(!locked)}
              className={`rounded-lg border px-4 py-2.5 text-sm font-semibold ${locked ? 'border-emerald-500 bg-emerald-500/10 text-emerald-300' : 'border-zinc-700 text-zinc-300 hover:border-zinc-600'}`}
            >
              {locked ? 'Locked' : 'Lock fighter'}
            </button>
            <button
              type="button"
              aria-pressed={excluded}
              onClick={() => onExclude(!excluded)}
              className={`rounded-lg border px-4 py-2.5 text-sm font-semibold ${excluded ? 'border-red-500/60 bg-red-500/10 text-red-300' : 'border-zinc-700 text-zinc-300 hover:border-zinc-600'}`}
            >
              {excluded ? 'Excluded' : 'Exclude fighter'}
            </button>
          </div>

          <p className="text-[10px] leading-4 text-zinc-600">
            {sourceDescription}
            {sourceUrl && <> <a href={sourceUrl} target="_blank" rel="noreferrer" className="text-zinc-500 underline hover:text-zinc-300">View source</a>.</>}
          </p>
        </div>
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 px-3 py-3">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-600">{label}</p>
      <p className="mt-1 font-mono text-base font-bold tabular-nums text-zinc-200">{value}</p>
    </div>
  )
}

function Detail({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="border-b border-r border-zinc-800 px-3 py-2.5 last:border-r-0">
      <dt className="text-[10px] uppercase tracking-wider text-zinc-600">{label}</dt>
      <dd className="mt-0.5 text-sm tabular-nums text-zinc-300">{shown(value)}</dd>
    </div>
  )
}
