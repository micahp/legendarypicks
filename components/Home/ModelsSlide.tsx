import React from 'react'

// Status of each model as the homepage shows it. This is the only data on the slide. Edit it here when a
// league's status changes. No statistics are shown: the homepage carries no number that is not sourced.
export const MODELS: { name: string; detail: string; status: 'Live' | 'Coming soon' }[] = [
  { name: 'NFL', detail: 'Spreads, totals and player props', status: 'Live' },
  { name: 'NHL', detail: 'Spreads, totals and player props', status: 'Live' },
  { name: 'ATP / WTA', detail: 'Match odds and player props', status: 'Live' },
  { name: 'MLB', detail: 'Spreads, totals and player props', status: 'Coming soon' },
  { name: 'NBA', detail: 'Spreads, totals and player props', status: 'Coming soon' },
  { name: 'MLS', detail: 'Spreads, totals and player props', status: 'Coming soon' },
  { name: 'UFC', detail: 'Match odds and player props', status: 'Coming soon' },
]

export default function ModelsSlide() {
  return (
    <section className="relative overflow-hidden rounded-2xl border border-zinc-800 bg-gradient-to-br from-zinc-900 via-ink-900 to-zinc-900">
      <div className="relative z-10 grid min-w-0 items-center gap-7 p-8 md:grid-cols-[1fr_1.05fr] md:px-12 md:py-12">
        <div className="min-w-0">
          <h2 className="text-balance text-[32px] font-bold leading-[1.12] tracking-tight md:text-[46px] md:leading-[1.06]">
            Prediction models across multiple sports.
          </h2>
          <p className="mt-4 max-w-xl text-zinc-300">
            Each model is published with its own page, so you can see what it predicts and how it has done.
          </p>
        </div>
        <div className="min-w-0 rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <h3 className="text-base font-bold">Models</h3>
          <p className="mt-1 text-xs text-zinc-400">Sport-specific prediction models.</p>
          <ul className="mt-3 flex flex-col gap-2">
            {MODELS.map((m) => (
              <li key={m.name} className="flex min-w-0 items-center justify-between gap-3 rounded-lg border border-zinc-800 px-3 py-2">
                <span className="flex min-w-0 flex-col">
                  <b className="text-sm">{m.name}</b>
                  <small className="truncate text-xs text-zinc-400">{m.detail}</small>
                </span>
                <span
                  className={
                    m.status === 'Live'
                      ? 'shrink-0 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-bold text-emerald-400'
                      : 'shrink-0 rounded-full border border-zinc-700 px-2 py-0.5 text-[11px] text-zinc-400'
                  }
                >
                  {m.status}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="pointer-events-none absolute -bottom-24 -right-24 h-72 w-72 rounded-full bg-emerald-500/10 blur-3xl" />
    </section>
  )
}
