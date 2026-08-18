import Head from 'next/head'
import { useEffect, useMemo, useState } from 'react'
import {
  AiNarrativeCard,
  LeagueSection,
  LEAGUE_LABELS,
  NewsCard,
  leagueLabel,
  relativeTime,
} from '../components/News/LeagueSection'
import type { AiNarrative, LeagueNews, NewsItem } from '../components/News/LeagueSection'

// League news engine surface (see docs/PLAN-league-news-engine.md).
// Top-level nav News page: Home tab = catch-all across leagues; per-league
// tabs land per league as data appears. Backend: /api/news (routers/news.py),
// collected out-of-band by ingest_league_news.py.

const LEAGUE_ORDER = ['nfl', 'mlb', 'nba', 'nhl', 'mls', 'ncaaf', 'ufc', 'esports']

type NewsData = {
  conversations: AiNarrative[]
  leagues: Record<string, LeagueNews>
}

export default function NewsPage() {
  const [data, setData] = useState<NewsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [active, setActive] = useState('home')

  useEffect(() => {
    let ignore = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await fetch('/api/news')
        const json = await res.json()
        if (!ignore) setData({ conversations: json?.conversations ?? [], leagues: json?.leagues ?? {} })
      } catch {
        if (!ignore) setError('Unable to load news.')
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [])

  const leagues = useMemo(() => {
    if (!data) return []
    const present = Object.keys(data.leagues).filter((lg) => lg !== 'unclassified')
    return LEAGUE_ORDER.filter((lg) => present.includes(lg))
      .concat(present.filter((lg) => !LEAGUE_ORDER.includes(lg)).sort())
  }, [data])

  return (
    <>
      <Head><title>News · Legendary Picks</title></Head>
      <div className="mx-auto max-w-4xl space-y-6">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-100">News</h1>
        </div>

        <div className="flex items-center gap-2 overflow-x-auto border-b border-zinc-800 pb-2 text-sm [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <button
            onClick={() => setActive('home')}
            className={`whitespace-nowrap rounded-full px-3 py-1 transition-colors ${
              active === 'home' ? 'bg-emerald-500/15 text-emerald-400' : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            Home
          </button>
          {leagues.map((lg) => (
            <button
              key={lg}
              onClick={() => setActive(lg)}
              className={`whitespace-nowrap rounded-full px-3 py-1 transition-colors ${
                active === lg ? 'bg-emerald-500/15 text-emerald-400' : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              {leagueLabel(lg)}
            </button>
          ))}
        </div>

        {loading && <div className="animate-pulse space-y-3"><div className="h-24 rounded-lg bg-zinc-800" /><div className="h-24 rounded-lg bg-zinc-800" /></div>}
        {error && <p className="text-sm text-red-400">{error}</p>}

        {!loading && !error && data && (
          active === 'home' ? (
            (() => {
              // Esports cards stay off Home until their quality is there
              // (Micah, 2026-08-07) — they still live on the Esports tab.
              const homeConvs = data.conversations.filter((c) => c.league !== 'esports')
              // One flat news feed below the conversations: narrative
              // headlines + trades/staff/injuries mixed, newest first, no tags.
              const homeNews = Object.values(data.leagues)
                .flatMap((lg) => [...lg.narratives, ...lg.granular])
                .filter((n) => n.league !== 'esports')
                .sort((a, b) => new Date(b.published).getTime() - new Date(a.published).getTime())
              return homeConvs.length === 0 && homeNews.length === 0
                ? <p className="text-sm text-zinc-600">No conversations collected yet — the collector runs out-of-band (ingest_league_news.py).</p>
                : (
                  <div className="space-y-3">
                    <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-500">Conversations across leagues</h2>
                    {homeConvs.map((c) => (
                      <AiNarrativeCard key={c.conv_id} ai={c} showLeague />
                    ))}
                    {homeNews.length > 0 && (
                      <div className="space-y-2">
                        <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-500">More news</h2>
                        {homeNews.map((n) => <NewsCard key={n.id} item={n} showLeague />)}
                      </div>
                    )}
                  </div>
                )
            })()
          ) : (
            <LeagueSection league={active} data={data.leagues[active] || { conversations: [], narratives: [], granular: [], other: 0 }} />
          )
        )}
      </div>
    </>
  )
}
