import React from 'react'
import Head from 'next/head'
import Link from 'next/link'

// Copy and statuses as the homepage shows them. Edit here, not in the markup. `icon` is a Material Symbols name.
export const MODELS: { name: string; detail: string; status: 'Live' | 'Coming soon'; icon: string }[] = [
  { name: 'NFL', detail: 'Spreads, totals and player props', status: 'Live', icon: 'sports_football' },
  { name: 'NCAAF', detail: 'Spreads, totals and player props', status: 'Live', icon: 'sports_football' },
  { name: 'NHL', detail: 'Spreads, totals and player props', status: 'Live', icon: 'sports_hockey' },
  { name: 'ATP / WTA', detail: 'Match odds and player props', status: 'Live', icon: 'sports_tennis' },
  { name: 'NBA', detail: 'Spreads, totals and player props', status: 'Coming soon', icon: 'sports_basketball' },
  { name: 'MLS', detail: 'Spreads, totals and player props', status: 'Coming soon', icon: 'sports_soccer' },
  { name: 'UFC', detail: 'Match odds and player props', status: 'Coming soon', icon: 'sports_mma' },
]

// The "Model insights" tiles. A tile is shown only when its value is sourced. Until then the value is null and the
// tile is left out, because the homepage shows no number that is not sourced.
export const INSIGHTS: { label: string; value: string | null }[] = [
  { label: 'Calibration', value: null },
  { label: 'Backtests', value: null },
  { label: 'Forecasts', value: null },
  { label: 'Daily grading', value: null },
]

export default function ModelsSlide() {
  const sourced = INSIGHTS.filter((t) => t.value !== null)
  return (
    <section className="relative overflow-hidden rounded-2xl border border-zinc-800 bg-gradient-to-br from-zinc-900 via-ink-900 to-zinc-900">
      <Head>
        {/* Material Symbols, limited to the sport icons used above. display=block keeps the icon names from showing as text. */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0&display=block&icon_names=sports_basketball,sports_football,sports_hockey,sports_mma,sports_soccer,sports_tennis"
        />
      </Head>
      <div className="relative z-10 grid min-w-0 items-center gap-7 p-8 md:grid-cols-[1fr_1.05fr] md:px-12 md:py-12">
        <div className="min-w-0">
          <h2 className="text-balance text-[32px] font-bold leading-[1.12] tracking-tight md:text-[46px] md:leading-[1.06]">
            Prediction models across multiple sports.
          </h2>
          <p className="mt-4 max-w-xl text-zinc-300">
            Track the models powering Legendary Picks. NFL, NCAAF, NHL, and ATP/WTA are live now, with NBA, MLS, and UFC coming soon.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link href="/leagues" className="rounded-lg border border-emerald-600 bg-emerald-600 px-5 py-2.5 font-bold text-white transition-colors hover:bg-emerald-500">
              Explore the models →
            </Link>
          </div>
          <p className="mt-[18px] text-[13px] text-zinc-400">Built for transparent forecasting and research.</p>
        </div>
        <div className="min-w-0 rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <h3 className="text-base font-bold">Models</h3>
          <p className="mt-1 text-xs text-zinc-400">Sport-specific prediction models with transparent metrics.</p>
          <ul className="mt-3 flex flex-col gap-2">
            {MODELS.map((m) => (
              <li
                key={m.name}
                className={`flex min-w-0 items-center justify-between gap-3 rounded-lg border px-3 py-2 ${m.status === 'Live' ? 'border-emerald-500/60 bg-emerald-500/5' : 'border-zinc-800'}`}
              >
                <span className="flex min-w-0 items-center gap-3">
                  <span
                    aria-hidden
                    className={`material-symbols-outlined select-none text-[24px] leading-none ${m.status === 'Live' ? 'text-emerald-400' : 'text-zinc-500'}`}
                  >
                    {m.icon}
                  </span>
                  <span className="flex min-w-0 flex-col">
                    <b className="text-sm">{m.name}</b>
                    <small className="truncate text-xs text-zinc-400">{m.detail}</small>
                  </span>
                </span>
                <span
                  className={
                    m.status === 'Live'
                      ? 'inline-flex shrink-0 items-center gap-1.5 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-bold text-emerald-400'
                      : 'inline-flex shrink-0 items-center gap-1.5 rounded-full border border-zinc-700 px-2 py-0.5 text-[11px] text-zinc-400'
                  }
                >
                  <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" />
                  {m.status}
                </span>
              </li>
            ))}
          </ul>
          {sourced.length > 0 && (
            <>
              <h4 className="mt-4 text-sm font-bold">Model insights</h4>
              <div className="mt-2 grid grid-cols-2 gap-2 tabular-nums">
                {sourced.map((t) => (
                  <span key={t.label} className="flex min-w-0 flex-col rounded-lg border border-zinc-800 px-3 py-2">
                    <i className="text-[11px] not-italic text-zinc-400">{t.label}</i>
                    <b className="text-sm">{t.value}</b>
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
      <div className="pointer-events-none absolute -bottom-24 -right-24 h-72 w-72 rounded-full bg-emerald-500/10 blur-3xl" />
    </section>
  )
}
