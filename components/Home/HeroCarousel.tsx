import React, { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import type { Featured, Load } from './types'
import PropHistoryCard from './PropHistoryCard'
import GameCard from './GameCard'
import PlayoffOddsCard from './PlayoffOddsCard'
import { QuietCard } from './CardShell'

type Slide = { key: string; dot: string; title: string; body: string; href: string; cta: string; proof: string; card: React.ReactNode }

const reducedMotion = () =>
  typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

export default function HeroCarousel({ featured }: { featured: Load<Featured> }) {
  const loading = featured.status === 'loading'
  const data = featured.status === 'ready' ? featured.data : null
  const odds = data?.playoff_odds

  // Slide 1 always shows its text; its card falls back to a quiet state. Slides 2 and 3 are
  // built from real data, so once the read has finished they are dropped when it is absent.
  const slides: Slide[] = [
    {
      key: 'props', dot: 'prop lines',
      title: 'Live prop lines and hit rate history across 11 leagues.',
      body: 'See how often any player has cleared a line over their last 5, 10 and 20 games and the full season before you decide.',
      href: '/props?tab=props', cta: 'Open the prop board', proof: 'Free to browse. No signup.',
      card: loading ? <QuietCard label="Example prop history" kind="loading" /> : <PropHistoryCard prop={data?.prop} />,
    },
  ]
  if (loading || data?.game) {
    slides.push({
      key: 'nfl', dot: 'NFL projections',
      title: "This week's NFL games, projected, with the line beside each one.",
      body: 'A projected score for every game, locked 90 minutes before kickoff and graded after every game, so you can see how much to trust it.',
      href: '/leagues/nfl?tab=model', cta: 'Open the NFL board', proof: 'Free board. Full breakdowns for members.',
      card: loading ? <QuietCard label="Example game" kind="loading" /> : <GameCard game={data?.game} />,
    })
  }
  if (loading || odds) {
    slides.push({
      key: 'odds', dot: 'playoff odds',
      title: "See every team's playoff chances for the rest of the season.",
      body: odds?.sims
        ? `Simulation-backed odds: ${odds.sims.toLocaleString('en-US')} simulated seasons, updated each week from the games already played.`
        : 'Simulation-backed odds, updated each week from the games already played.',
      href: '/nfl/playoff-odds', cta: 'See the playoff odds',
      proof: odds ? `Free for all ${odds.teams_in_run} teams.` : 'Free for every team.',
      card: loading ? <QuietCard label="Example playoff odds" kind="loading" /> : <PlayoffOddsCard odds={odds} />,
    })
  }

  const rail = useRef<HTMLDivElement>(null)
  const [index, setIndex] = useState(0)
  const count = slides.length
  const current = Math.min(index, count - 1)

  const go = useCallback((i: number) => {
    const el = rail.current
    if (!el) return
    setIndex(i)
    const target = el.children[i] as HTMLElement | undefined
    if (target && typeof el.scrollTo === 'function') {
      el.scrollTo({ left: target.offsetLeft - el.offsetLeft, behavior: reducedMotion() ? 'auto' : 'smooth' })
    }
  }, [])

  const sync = () => {
    const el = rail.current
    if (!el || el.clientWidth <= 0) return
    setIndex(Math.min(count - 1, Math.max(0, Math.round(el.scrollLeft / el.clientWidth))))
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowRight' && current < count - 1) { go(current + 1); e.preventDefault() }
    if (e.key === 'ArrowLeft' && current > 0) { go(current - 1); e.preventDefault() }
  }

  useEffect(() => { if (index > count - 1) setIndex(Math.max(0, count - 1)) }, [index, count])

  return (
    <section
      className="relative overflow-hidden rounded-2xl border border-zinc-800 bg-gradient-to-br from-zinc-900 via-ink-900 to-zinc-900"
      aria-roledescription="carousel"
      aria-label="What Legendary Picks shows"
    >
      <div
        ref={rail}
        onScroll={sync}
        onKeyDown={onKeyDown}
        tabIndex={0}
        className="flex snap-x snap-mandatory overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden motion-safe:scroll-smooth"
        data-testid="slides"
      >
        {slides.map((s, i) => (
          <article
            key={s.key}
            id={`slide-${i + 1}`}
            aria-label={`Slide ${i + 1} of ${count}`}
            className="relative z-10 grid min-w-0 flex-[0_0_100%] snap-start items-center gap-7 p-8 md:grid-cols-[1.05fr_1fr] md:px-12 md:pb-10 md:pt-12"
          >
            <div className="min-w-0">
              <h1 className="text-balance text-[32px] font-bold leading-[1.12] tracking-tight md:text-[46px] md:leading-[1.06]">{s.title}</h1>
              <p className="mt-4 max-w-xl text-zinc-300">{s.body}</p>
              <div className="mt-6 flex flex-wrap gap-3">
                <Link href={s.href} className="rounded-lg border border-emerald-600 bg-emerald-600 px-5 py-2.5 font-bold text-white transition-colors hover:bg-emerald-500">
                  {s.cta}
                </Link>
              </div>
              <p className="mt-[18px] text-[13px] text-zinc-400">{s.proof}</p>
            </div>
            {s.card}
          </article>
        ))}
      </div>
      <div className="relative z-20 flex justify-center gap-2 pb-[18px]" role="tablist" aria-label="Choose a slide">
        {slides.map((s, i) => (
          <button
            key={s.key}
            type="button"
            role="tab"
            aria-label={`Show slide ${i + 1}, ${s.dot}`}
            aria-selected={i === current}
            onClick={() => go(i)}
            className={`h-2 rounded-full p-0 transition-all ${i === current ? 'w-[22px] bg-emerald-400' : 'w-2 bg-zinc-600'}`}
          />
        ))}
      </div>
      <div className="pointer-events-none absolute -bottom-24 -right-24 h-72 w-72 rounded-full bg-emerald-500/10 blur-3xl" />
    </section>
  )
}
