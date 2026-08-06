import Head from 'next/head'
import { useEffect, useMemo, useState } from 'react'

// League news engine surface (see docs/PLAN-league-news-engine.md).
// Top-level nav News page: Home tab = catch-all across leagues; per-league
// tabs land per league as data appears. Backend: /api/news (routers/news.py),
// collected out-of-band by ingest_league_news.py.

const LEAGUE_LABELS: Record<string, string> = {
  nfl: 'NFL',
  mlb: 'MLB',
  nba: 'NBA',
  nhl: 'NHL',
  mls: 'MLS',
  ncaaf: 'NCAAF',
  ufc: 'UFC',
  wc: 'FIFA World Cup',
}

const LEAGUE_EMOJIS: Record<string, string> = {
  nfl: '🏈',
  mlb: '⚾',
  nba: '🏀',
  nhl: '🏒',
  mls: '⚽',
  ncaaf: '🏈',
  ufc: '🥊',
  wc: '⚽',
}

const LEAGUE_ORDER = ['nfl', 'mlb', 'nba', 'nhl', 'mls', 'ncaaf', 'ufc']

function leagueLabel(lg: string): string {
  return LEAGUE_LABELS[lg] || lg.toUpperCase()
}

type NewsItem = {
  id: number
  headline: string
  url: string
  source: string
  published: string
  layer: string
  key_player: string | null
}

type LeagueNews = {
  narratives: NewsItem[]
  granular: NewsItem[]
  other: number
}

function layerBadgeClass(layer: string): string {
  switch (layer) {
    case 'injury': return 'bg-red-500/15 text-red-400 border-red-500/30'
    case 'trade': return 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
    case 'staff': return 'bg-amber-500/15 text-amber-400 border-amber-500/30'
    default: return 'bg-zinc-700/40 text-zinc-400 border-zinc-600/40'
  }
}

const LAYER_LABELS: Record<string, string> = {
  injury: 'INJURY',
  trade: 'TRADE',
  staff: 'STAFF',
}

function NewsCard({ item, showLayer }: { item: NewsItem; showLayer: boolean }) {
  return (
    <a
      href={item.url}
      target="_blank"
      rel="noopener noreferrer"
      className="block rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2.5 hover:border-zinc-700 hover:bg-zinc-800/60 transition-colors"
    >
      <div className="flex items-start justify-between gap-3">
        <span className="text-sm leading-snug text-zinc-100">{item.headline}</span>
        {showLayer && item.layer !== 'narrative' && (
          <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold tracking-wide ${layerBadgeClass(item.layer)}`}>
            {LAYER_LABELS[item.layer] || item.layer.toUpperCase()}
          </span>
        )}
      </div>
      <div className="mt-1 flex items-center gap-2 text-[11px] text-zinc-500">
        <span>{item.source}</span>
        {item.key_player && <span className="text-emerald-400/90">★ {item.key_player}</span>}
        {item.published && <span className="truncate">{new Date(item.published).toLocaleDateString()}</span>}
      </div>
    </a>
  )
}

function LeagueSection({ league, data }: { league: string; data: LeagueNews }) {
  return (
    <section className="space-y-3">
      <h2 className="flex items-center gap-2 text-lg font-bold text-zinc-100">
        <span>{LEAGUE_EMOJIS[league] || '📰'}</span>
        <span>{leagueLabel(league)}</span>
      </h2>
      {data.narratives.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Narrative</h3>
          {data.narratives.map((n) => <NewsCard key={n.id} item={n} showLayer={false} />)}
        </div>
      )}
      {data.granular.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Trades · Staff · Injuries</h3>
          {data.granular.map((g) => <NewsCard key={g.id} item={g} showLayer />)}
        </div>
      )}
      {data.narratives.length === 0 && data.granular.length === 0 && (
        <p className="text-sm text-zinc-600">No classified news yet for {leagueLabel(league)}.</p>
      )}
    </section>
  )
}

export default function NewsPage() {
  const [data, setData] = useState<Record<string, LeagueNews> | null>(null)
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
        if (!ignore) setData(json?.leagues ?? {})
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
    const present = Object.keys(data).filter((lg) => lg !== 'unclassified')
    return LEAGUE_ORDER.filter((lg) => present.includes(lg))
      .concat(present.filter((lg) => !LEAGUE_ORDER.includes(lg)).sort())
  }, [data])

  return (
    <>
      <Head><title>News · Legendary Picks</title></Head>
      <div className="mx-auto max-w-4xl space-y-6">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-100">News</h1>
          <p className="mt-1 text-sm text-zinc-500">
            League narratives and the moves that matter — trades, coaching changes, key injuries.
          </p>
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
              {LEAGUE_EMOJIS[lg] || ''} {leagueLabel(lg)}
            </button>
          ))}
        </div>

        {loading && <div className="animate-pulse space-y-3"><div className="h-24 rounded-lg bg-zinc-800" /><div className="h-24 rounded-lg bg-zinc-800" /></div>}
        {error && <p className="text-sm text-red-400">{error}</p>}

        {!loading && !error && data && (
          active === 'home' ? (
            leagues.length === 0
              ? <p className="text-sm text-zinc-600">No news collected yet — the collector runs out-of-band (ingest_league_news.py).</p>
              : <div className="space-y-8">{leagues.map((lg) => <LeagueSection key={lg} league={lg} data={data[lg]} />)}</div>
          ) : (
            <LeagueSection league={active} data={data[active] || { narratives: [], granular: [], other: 0 }} />
          )
        )}
      </div>
    </>
  )
}
