import Head from 'next/head'
import Link from 'next/link'

export default function Home() {
  return (
    <>
      <Head>
        <title>Legendary Picks: Every play. Every stat. One scoreboard.</title>
        <meta name="description" content="Live scores, prop lines, daily slates, and player stats across the NBA, NFL, MLB & NHL. Every play. Every stat. One scoreboard." />
        <link rel="canonical" href="https://legendarypicks.xyz/" />
        {/* Open Graph (Facebook/LinkedIn/iMessage/etc.) */}
        <meta property="og:title" content="Legendary Picks: Every play. Every stat. One scoreboard." />
        <meta property="og:description" content="Live scores, prop lines, daily slates, and player stats across the NBA, NFL, MLB & NHL." />
        <meta property="og:image" content="https://legendarypicks.xyz/og-image.png" />
        <meta property="og:image:width" content="1200" />
        <meta property="og:image:height" content="630" />
        <meta property="og:url" content="https://legendarypicks.xyz/" />
        <meta property="og:type" content="website" />
        <meta property="og:site_name" content="Legendary Picks" />
        {/* Twitter / X card */}
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content="Legendary Picks: Every play. Every stat. One scoreboard." />
        <meta name="twitter:description" content="Live scores, prop lines, daily slates, and player stats across the NBA, NFL, MLB & NHL." />
        <meta name="twitter:image" content="https://legendarypicks.xyz/og-image.png" />
      </Head>

      <section className="relative overflow-hidden rounded-2xl border border-zinc-800 bg-gradient-to-br from-zinc-900 via-ink-900 to-zinc-900 p-8 md:p-12">
        <div className="relative z-10 max-w-3xl">
          <h1 className="text-4xl md:text-6xl font-extrabold tracking-tight leading-tight">
            Every play. Every stat. One scoreboard.
          </h1>
          <p className="mt-4 text-zinc-300 max-w-xl">
            Live scores, box scores, and play-by-play across the NBA, NFL, MLB, NHL and more.
            Fast, clean, no noise.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link href="/scores" className="px-5 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold transition-colors">
              View Scoreboard
            </Link>
            <Link href="/predict" className="px-5 py-2.5 rounded-lg border border-zinc-700 hover:bg-zinc-800 transition-colors">
              Predictions
            </Link>
          </div>
        </div>
        <div className="pointer-events-none absolute -right-24 -bottom-24 h-72 w-72 rounded-full bg-emerald-500/10 blur-3xl" />
      </section>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-8">
        {[
          { title: 'Live Scores', desc: 'Real-time scores across 8+ leagues with box scores and play-by-play.', href: '/scores' },
          { title: 'Predictions', desc: 'Pick winners and track your accuracy over the season.', href: '/predict' },
          { title: 'Prop Data', desc: 'Coming soon — player prop outcomes, hit rates, and trends.', href: '#' },
        ].map((card) => (
          <Link
            key={card.title}
            href={card.href}
            className="rounded-xl border border-zinc-800 bg-zinc-900 p-6 hover:border-zinc-700 transition-colors"
          >
            <h3 className="font-bold text-lg mb-2">{card.title}</h3>
            <p className="text-sm text-zinc-400">{card.desc}</p>
          </Link>
        ))}
      </div>
    </>
  )
}
