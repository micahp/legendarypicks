// This was NFL-only, on the reasoning that every other league's page is "short
// enough that tabs would add a click and hide nothing worth hiding". That stopped
// being true: Mark Scheifele's page carries 82 game logs and Andrew Vaughn's 65,
// stacked under his season line with no way past them. The tab set is now derived
// from what a player actually has, so a league gets tabs exactly when it has more
// than one thing to show.
//
// Usage and News stay NFL-shaped because their DATA is: `NflUsageTrend` reads snap
// share, and `/api/player/{id}/news` hard-returns an empty list for every other
// league. Offering an empty tab is worse than offering none.
export type PlayerTab = 'overview' | 'usage' | 'gamelog' | 'news'
export const TAB_LABELS: Record<PlayerTab, string> = {
  overview: 'Overview',
  usage: 'Usage',
  gamelog: 'Game Log',
  news: 'News',
}

export function playerTabs(league: string, hasGameLog: boolean): PlayerTab[] {
  const isNfl = league === 'nfl'
  const tabs: PlayerTab[] = ['overview']
  if (isNfl) tabs.push('usage')
  if (hasGameLog) tabs.push('gamelog')
  if (isNfl) tabs.push('news')
  return tabs
}

export default function TabStrip({ tabs, tab, setTab }: {
  tabs: PlayerTab[]
  tab: PlayerTab
  setTab: (t: PlayerTab) => void
}) {
  return (
    <div
      className="flex gap-1 overflow-x-auto border-b border-zinc-800 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      role="tablist"
    >
      {tabs.map((id) => {
        const active = id === tab
        return (
          <button
            key={id}
            role="tab"
            aria-selected={active}
            onClick={() => setTab(id)}
            className={`-mb-px shrink-0 whitespace-nowrap border-b-2 px-2 py-2.5 text-sm font-medium transition-colors sm:px-4 ${
              active
                ? 'border-emerald-400 text-zinc-100'
                : 'border-transparent text-zinc-500 hover:text-zinc-300'
            }`}
          >
            {TAB_LABELS[id]}
          </button>
        )
      })}
    </div>
  )
}
