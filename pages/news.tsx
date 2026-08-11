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
  esports: 'Esports',
  wc: 'FIFA World Cup',
}

const LEAGUE_ORDER = ['nfl', 'mlb', 'nba', 'nhl', 'mls', 'ncaaf', 'ufc', 'esports']

function leagueLabel(lg: string): string {
  return LEAGUE_LABELS[lg] || lg.toUpperCase()
}

type NewsItem = {
  id: number
  league: string
  headline: string
  url: string
  source: string
  published: string
  layer: string
  key_player: string | null
}

type AiNarrative = {
  conv_id: string
  league: string
  title: string
  narrative: string
  fan_voice: string
  paragraph: string
  sources: { headline: string; url: string; source: string; published?: string }[]
  generated_at: string
  // When the card's STORY last moved (newest cited publish time), not when the
  // writer last ran. Dating cards by generation time re-stamped days-old stories
  // on every scheduled run. Falls back to generated_at server-side.
  story_time: string
  source_count: number
}

type LeagueNews = {
  conversations: AiNarrative[]
  narratives: NewsItem[]
  granular: NewsItem[]
  other: number
}

type NewsData = {
  conversations: AiNarrative[]
  leagues: Record<string, LeagueNews>
}

function relativeTime(iso: string): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const diff = Date.now() - t
  const min = Math.floor(diff / 60000)
  if (min < 1) return 'now'
  if (min < 60) return `${min}m`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h`
  const day = Math.floor(hr / 24)
  if (day < 7) return `${day}d`
  const wk = Math.floor(day / 7)
  if (wk < 5) return `${wk}w`
  const mo = Math.floor(day / 30)
  if (mo < 12) return `${mo}mo`
  return `${Math.floor(day / 365)}y`
}

function NewsCard({ item, showLeague }: { item: NewsItem; showLeague?: boolean }) {
  return (
    <a
      href={item.url}
      target="_blank"
      rel="noopener noreferrer"
      className="block rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2.5 hover:border-zinc-700 hover:bg-zinc-800/60 transition-colors"
    >
      <div className="flex items-start justify-between gap-3">
        <span className="text-sm leading-snug text-zinc-100">
          {showLeague && (
            <span className="mr-2 whitespace-nowrap text-zinc-500">
              {leagueLabel(item.league)}
            </span>
          )}
          {item.headline}
        </span>
      </div>
      <div className="mt-1 flex items-center gap-2 text-[11px] text-zinc-500">
        <span>{item.source}</span>
        {item.key_player && <span className="text-emerald-400/90">★ {item.key_player}</span>}
        {item.published && <span className="truncate">{relativeTime(item.published)}</span>}
      </div>
    </a>
  )
}

function AiNarrativeCard({ ai, showLeague }: { ai: AiNarrative; showLeague?: boolean }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-3">
      <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
        {showLeague && ai.league ? `${leagueLabel(ai.league)} · ` : ''}{ai.title || "What everyone's talking about"}
      </p>
      <p className="mt-1 text-[15px] font-semibold leading-snug text-zinc-100">{ai.narrative}</p>
      <p className="mt-1.5 text-sm leading-relaxed text-zinc-400">
        {ai.paragraph}
      </p>
      <div className="mt-2.5 flex items-center gap-2 text-xs text-zinc-500">
        <span className="truncate">{relativeTime(ai.story_time || ai.generated_at)}</span>
        {ai.sources.slice(0, 2).map((s, i) => (
          <span key={i}>
            {i > 0 && <span className="mx-1.5 text-zinc-700">·</span>}
            <a
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-zinc-400 hover:text-emerald-400"
            >
              {s.source}
            </a>
          </span>
        ))}
        {ai.source_count > 2 && (
          <span className="ml-1.5 text-zinc-600">and more</span>
        )}
      </div>
    </div>
  )
}

function LeagueSection({ league, data }: { league: string; data: LeagueNews }) {
  // One flat news list: narrative headlines + trades/staff/injuries mixed,
  // newest first, no layer tags (Micah, 2026-08-08).
  const news = [...data.narratives, ...data.granular].sort(
    (a, b) => new Date(b.published).getTime() - new Date(a.published).getTime()
  )
  return (
    <section className="space-y-3">
      <h2 className="flex items-center gap-2 text-lg font-bold text-zinc-100">
        <span>{leagueLabel(league)}</span>
      </h2>
      {data.conversations.map((c) => <AiNarrativeCard key={c.conv_id} ai={c} />)}
      {news.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">More news</h3>
          {news.map((n) => <NewsCard key={n.id} item={n} />)}
        </div>
      )}
      {data.conversations.length === 0 && news.length === 0 && (
        <p className="text-sm text-zinc-600">No classified news yet for {leagueLabel(league)}.</p>
      )}
    </section>
  )
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
          <p className="mt-1 text-sm text-zinc-500">
            The conversations that matter in each league — the official story and what fans are saying about it.
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
