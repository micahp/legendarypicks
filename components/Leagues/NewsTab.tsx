import type { LeagueNews, NewsConversation, NewsItem } from './types'

/**
 * League news. Three things the feed publishes, kept visibly distinct because
 * they are different kinds of claim:
 *
 *  - **Conversations** are synthesised across several sources. They are the only
 *    text here we wrote, so they carry the count of what they were built from
 *    and link every source.
 *  - **Stories** are published articles from an outlet.
 *  - **Latest** is the granular wire, much of which is social posts.
 *
 * A masthead is not a verification. `espn-ligamx` and `@TomBogert` both arrive
 * in the same `source` field, and rendering both as "reported by" would promote
 * a tweet to an outlet — so a handle is labelled a post and styled as the weaker
 * claim it is.
 */
export default function NewsTab({
  leagueName,
  news,
  loading,
  error,
}: {
  leagueName: string
  news: LeagueNews | null
  loading: boolean
  error: string | null
}) {
  if (error) {
    return (
      <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-400">
        {error}
      </div>
    )
  }
  if (loading) return <NewsSkeleton />

  const conversations = news?.conversations ?? []
  const narratives = news?.narratives ?? []
  const granular = news?.granular ?? []
  if (!conversations.length && !narratives.length && !granular.length) {
    return <div className="text-sm text-zinc-500">No news published for {leagueName} yet.</div>
  }

  return (
    <div className="space-y-8">
      {conversations.length > 0 && (
        <section className="space-y-3">
          <SectionHeading>What they're talking about</SectionHeading>
          {conversations.map(conversation => (
            <ConversationCard key={conversation.conv_id} conversation={conversation} />
          ))}
        </section>
      )}

      {narratives.length > 0 && (
        <section className="space-y-3">
          <SectionHeading>Stories</SectionHeading>
          <ItemList items={narratives} />
        </section>
      )}

      {granular.length > 0 && (
        <section className="space-y-3">
          <SectionHeading>Latest</SectionHeading>
          <ItemList items={granular} />
        </section>
      )}
    </div>
  )
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">{children}</h2>
  )
}

function ConversationCard({ conversation }: { conversation: NewsConversation }) {
  const sources = conversation.sources ?? []
  return (
    <article className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900">
      <div className="px-4 py-3">
        <h3 className="text-sm font-semibold text-zinc-100">{conversation.title}</h3>
        <p className="mt-1 text-sm text-zinc-300">{conversation.narrative}</p>
        {conversation.paragraph && (
          <p className="mt-2 text-sm leading-relaxed text-zinc-400">{conversation.paragraph}</p>
        )}
        {conversation.fan_voice && (
          <p className="mt-2 border-l-2 border-zinc-700 pl-3 text-sm italic text-zinc-400">
            {conversation.fan_voice}
          </p>
        )}
      </div>
      {sources.length > 0 && (
        // The count is stated, not implied by the list: this text was written
        // FROM these, so how many is part of how much weight it carries.
        <div className="border-t border-zinc-800 px-4 py-2.5">
          <div className="text-[11px] uppercase tracking-wider text-zinc-500">
            Built from {sources.length} source{sources.length === 1 ? '' : 's'}
          </div>
          <ul className="mt-1.5 space-y-1">
            {sources.map((source, index) => (
              <li key={`${source.url}-${index}`}>
                <a
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-zinc-400 transition-colors hover:text-emerald-400"
                >
                  {source.headline}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  )
}

function ItemList({ items }: { items: NewsItem[] }) {
  return (
    <div className="divide-y divide-zinc-800 overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900">
      {items.map(item => (
        <a
          key={item.id}
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="block px-4 py-3 transition-colors hover:bg-zinc-800/30"
        >
          <div className="text-sm text-zinc-200">{item.headline}</div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-zinc-500">
            <SourceTag source={item.source} />
            <span aria-hidden="true">·</span>
            <time dateTime={item.published}>{publishedLabel(item.published)}</time>
          </div>
        </a>
      ))}
    </div>
  )
}

/**
 * A handle is a post; anything else is an outlet. Both arrive in one field, and
 * the distinction is the point — a social post is one person's claim, and
 * presenting it with the same weight as a masthead is how a tweet gets read as
 * reporting.
 */
function SourceTag({ source }: { source: string }) {
  const isSocial = source.trim().startsWith('@')
  return (
    <span className={isSocial ? 'text-zinc-500' : 'font-medium text-zinc-400'}>
      {isSocial ? `Post by ${source}` : source}
    </span>
  )
}

/** Absent or unparseable timestamps read as unknown, never as "now". */
function publishedLabel(published: string) {
  if (!published) return 'time unknown'
  const at = new Date(published)
  if (Number.isNaN(at.getTime())) return 'time unknown'
  const minutes = Math.round((Date.now() - at.getTime()) / 60000)
  if (minutes < 0) return at.toLocaleDateString()
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days <= 7) return `${days}d ago`
  return at.toLocaleDateString()
}

function NewsSkeleton() {
  return (
    <div className="space-y-3">
      {[0, 1, 2].map(row => (
        <div key={row} className="rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-4">
          <div className="h-3 w-1/3 animate-pulse rounded bg-zinc-800" />
          <div className="mt-2 h-3 w-3/4 animate-pulse rounded bg-zinc-800" />
        </div>
      ))}
    </div>
  )
}
