import Head from 'next/head'
import Link from 'next/link'
import { useEffect, useState } from 'react'
import LiveDot from '../components/LiveDot'

// The homepage leads with props — the most differentiated surface we have.
// Micah's framing: "props" alone is a noun; the differentiator is the HISTORY,
// that we say how the line landed. Scoreboard and predictions are secondary;
// news, live esports and mock drafts are surfaced instead of under-sold.
// honest-data-ui: no number on this page that is not sourced. Everything here
// is static copy except the esports live dot, which reads /api/esports/upcoming
// and is ABSENT when the read fails — never a hardcoded "live", never a zero.
function EsportsLiveIndicator() {
  const [live, setLive] = useState<boolean | null>(null)
  useEffect(() => {
    let ignore = false
    fetch('/api/esports/upcoming', { cache: 'no-store' })
      .then((r) => r.json())
      .then((d) => { if (!ignore) setLive(Array.isArray(d?.matches) && d.matches.some((m: any) => m.live)) })
      .catch(() => { /* absent, not zero */ })
    return () => { ignore = true }
  }, [])
  if (live !== true) return null
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-red-400">
      <LiveDot />
      Live now
    </span>
  )
}

export default function Home() {
  return (
    <>
      <Head>
        <title>Legendary Picks: props with history, and how every line landed</title>
        <meta name="description" content="Player props with settled history: how the line landed, hit rates, and projections. Live scores, predictions, news, esports and mock drafts." />
        <link rel="canonical" href="https://legendarypicks.xyz/" />
        {/* Open Graph (Facebook/LinkedIn/iMessage/etc.) */}
        <meta property="og:title" content="Legendary Picks: props with history, and how every line landed" />
        <meta property="og:description" content="Player props with settled history: how the line landed, hit rates, and projections. Live scores, predictions, news, esports and mock drafts." />
        <meta property="og:image" content="https://legendarypicks.xyz/og-image.png" />
        <meta property="og:image:width" content="1200" />
        <meta property="og:image:height" content="630" />
        <meta property="og:url" content="https://legendarypicks.xyz/" />
        <meta property="og:type" content="website" />
        <meta property="og:site_name" content="Legendary Picks" />
        {/* Twitter / X card */}
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content="Legendary Picks: props with history, and how every line landed" />
        <meta name="twitter:description" content="Player props with settled history: how the line landed, hit rates, and projections. Live scores, predictions, news, esports and mock drafts." />
        <meta name="twitter:image" content="https://legendarypicks.xyz/og-image.png" />
      </Head>

      <section className="relative overflow-hidden rounded-2xl border border-zinc-800 bg-gradient-to-br from-zinc-900 via-ink-900 to-zinc-900 p-8 md:p-12">
        <div className="relative z-10 max-w-3xl">
          <h1 className="text-4xl md:text-6xl font-extrabold tracking-tight leading-tight">
            Every prop line, and what it did.
          </h1>
          <p className="mt-4 text-zinc-300 max-w-xl">
            Player props with the aftermath: how each line landed, hit rates over
            the season, and projections built from the player&apos;s own game logs.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link href="/props?tab=props" className="px-5 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold transition-colors">
              Browse the prop board
            </Link>
            <Link href="/scores" className="px-5 py-2.5 rounded-lg border border-zinc-700 hover:bg-zinc-800 transition-colors">
              Scoreboard
            </Link>
            <Link href="/predict" className="px-5 py-2.5 rounded-lg border border-zinc-700 hover:bg-zinc-800 transition-colors">
              Predictions
            </Link>
          </div>
        </div>
        <div className="pointer-events-none absolute -right-24 -bottom-24 h-72 w-72 rounded-full bg-emerald-500/10 blur-3xl" />
      </section>

      {/* Primary surface: props and their history. Position and space carry the
          hierarchy — the props card is the first and largest; everything else
          is smaller or further down. */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-8">
        <Link
          href="/props?tab=props"
          className="md:col-span-2 rounded-xl border border-zinc-800 bg-zinc-900 p-6 hover:border-emerald-500/40 transition-colors"
        >
          <h2 className="text-xl font-bold mb-2">Player props, with the history</h2>
          <p className="text-sm text-zinc-400">
            Every line carries its record: how it landed, hit rate over the last
            5 / 10 / 20 settled props and the season, and projections from the
            player&apos;s own game distribution. A prop is a promise; this is where
            you see whether it kept them.
          </p>
          <span className="inline-block mt-4 text-sm font-semibold text-emerald-400">
            Browse the prop board →
          </span>
        </Link>

        <div className="flex flex-col gap-4">
          <Link href="/scores" className="rounded-xl border border-zinc-800 bg-zinc-900 p-6 hover:border-zinc-700 transition-colors">
            <h3 className="font-bold text-lg mb-2">Live Scores</h3>
            <p className="text-sm text-zinc-400">Real-time scores across 8+ leagues with box scores and play-by-play.</p>
          </Link>
          <Link href="/predict" className="rounded-xl border border-zinc-800 bg-zinc-900 p-6 hover:border-zinc-700 transition-colors">
            <h3 className="font-bold text-lg mb-2">Predictions</h3>
            <p className="text-sm text-zinc-400">Pick winners and track your accuracy over the season.</p>
          </Link>
        </div>
      </div>

      {/* The surfaces the homepage used to under-sell. */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
        <Link href="/news" className="rounded-xl border border-zinc-800 bg-zinc-900 p-6 hover:border-zinc-700 transition-colors">
          <h3 className="font-bold text-lg mb-2">News</h3>
          <p className="text-sm text-zinc-400">League news and features behind the slate.</p>
        </Link>
        <Link href="/esports" className="rounded-xl border border-zinc-800 bg-zinc-900 p-6 hover:border-zinc-700 transition-colors">
          <div className="flex items-center justify-between mb-2">
            <h3 className="font-bold text-lg">Esports</h3>
            <EsportsLiveIndicator />
          </div>
          <p className="text-sm text-zinc-400">Live broadcasts, brackets and matches across the circuit.</p>
        </Link>
        <Link href="/mock-draft" className="rounded-xl border border-zinc-800 bg-zinc-900 p-6 hover:border-zinc-700 transition-colors">
          <h3 className="font-bold text-lg mb-2">Mock Draft</h3>
          <p className="text-sm text-zinc-400">Run a mock draft against the full player pool.</p>
        </Link>
      </div>
    </>
  )
}
