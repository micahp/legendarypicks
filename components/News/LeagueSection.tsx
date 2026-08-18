/**
 * The News page's own league rendering, moved here unchanged so the league hub's
 * News tab is the same component rather than a second design of the same thing.
 *
 * Everything below is lifted verbatim from pages/news.tsx — the flat
 * newest-first list with no layer tags (Micah, 2026-08-08), the conversation
 * cards above it, and the relative-time format. pages/news.tsx now imports from
 * here, so the two surfaces cannot drift.
 */
export const LEAGUE_LABELS: Record<string, string> = {
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


export function leagueLabel(lg: string): string {
  return LEAGUE_LABELS[lg] || lg.toUpperCase()
}


export type NewsItem = {
  id: number
  league: string
  headline: string
  url: string
  source: string
  published: string
  layer: string
  key_player: string | null
}

export type AiNarrative = {
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


export type LeagueNews = {
  conversations: AiNarrative[]
  narratives: NewsItem[]
  granular: NewsItem[]
  other: number
}


export function relativeTime(iso: string): string {
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


export function NewsCard({ item, showLeague }: { item: NewsItem; showLeague?: boolean }) {
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


export function AiNarrativeCard({ ai, showLeague }: { ai: AiNarrative; showLeague?: boolean }) {
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


export function LeagueSection({ league, data }: { league: string; data: LeagueNews }) {
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

