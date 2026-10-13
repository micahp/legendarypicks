import React from 'react'
import Link from 'next/link'
import type { Featured, Load } from './types'
import PropHistoryCard from './PropHistoryCard'
import { QuietCard } from './CardShell'

export default function FirstHero({ featured }: { featured: Load<Featured> }) {
  const loading = featured.status === 'loading'
  const data = featured.status === 'ready' ? featured.data : null
  return (
    <section className="relative overflow-hidden rounded-2xl border border-zinc-800 bg-gradient-to-br from-zinc-900 via-ink-900 to-zinc-900">
      <div className="relative z-10 grid min-w-0 items-center gap-7 p-8 md:grid-cols-[1.05fr_1fr] md:px-12 md:py-12">
        <div className="min-w-0">
          <h1 className="text-balance text-[32px] font-bold leading-[1.12] tracking-tight md:text-[46px] md:leading-[1.06]">
            Live prop lines and hit rate history across 11 leagues.
          </h1>
          <p className="mt-4 max-w-xl text-zinc-300">
            See how often any player has cleared a line over their last 5, 10 and 20 games and the full season before you decide.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link href="/props?tab=props" className="rounded-lg border border-emerald-600 bg-emerald-600 px-5 py-2.5 font-bold text-white transition-colors hover:bg-emerald-500">
              Open the prop board
            </Link>
          </div>
          <p className="mt-[18px] text-[13px] text-zinc-400">Free to browse. No signup.</p>
        </div>
        {loading ? <QuietCard label="Example prop history" kind="loading" /> : <PropHistoryCard prop={data?.prop} />}
      </div>
      <div className="pointer-events-none absolute -bottom-24 -right-24 h-72 w-72 rounded-full bg-emerald-500/10 blur-3xl" />
    </section>
  )
}
