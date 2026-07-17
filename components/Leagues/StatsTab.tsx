import {
  directionDisplay,
  formatMetric,
  formatSignedMetric,
  formatTeamMetric,
} from './presentation'
import type { LeadersData, SubView, TeamAggregatesData } from './types'

type MlbType = 'batting' | 'pitching'

interface StatsTabProps {
  league: string
  leagueName: string
  supportsTeamStats: boolean
  subView: SubView
  mlbType: MlbType
  leaders: LeadersData | null
  playerLoading: boolean
  playerError: string | null
  playerFilterError: boolean
  teamAggregates: TeamAggregatesData | null
  teamLoading: boolean
  teamError: string | null
  teamCategory: string | null
  onSelectSubView: (view: SubView) => void
  onSelectMlbType: (type: MlbType) => void
  onSelectStatCategory: (category: string) => void
  onSelectSortMetric: (metric: string) => void
  onResetFilters: () => void
  onSelectTeamCategory: (category: string) => void
}

export default function StatsTab({
  league,
  leagueName,
  supportsTeamStats,
  subView,
  mlbType,
  leaders,
  playerLoading,
  playerError,
  playerFilterError,
  teamAggregates,
  teamLoading,
  teamError,
  teamCategory,
  onSelectSubView,
  onSelectMlbType,
  onSelectStatCategory,
  onSelectSortMetric,
  onResetFilters,
  onSelectTeamCategory,
}: StatsTabProps) {
  return (
    <>
      {supportsTeamStats && teamAggregates?.supported && (
        <SubViewTabs value={subView} onChange={onSelectSubView} />
      )}

      {league === 'mlb' && subView === 'players' && (
        <MlbTypeTabs value={mlbType} onChange={onSelectMlbType} />
      )}

      {subView === 'players' && (
        <PlayerStats
          leagueName={leagueName}
          leaders={leaders}
          loading={playerLoading}
          error={playerError}
          filterError={playerFilterError}
          onSelectCategory={onSelectStatCategory}
          onSelectSortMetric={onSelectSortMetric}
          onResetFilters={onResetFilters}
        />
      )}

      {supportsTeamStats && subView === 'teams' && (
        <TeamStats
          leagueName={leagueName}
          aggregates={teamAggregates}
          loading={teamLoading}
          error={teamError}
          category={teamCategory}
          onSelectCategory={onSelectTeamCategory}
        />
      )}
    </>
  )
}

function SubViewTabs({
  value,
  onChange,
}: {
  value: SubView
  onChange: (view: SubView) => void
}) {
  return (
    <div className="flex gap-0 border-b border-zinc-800 -mx-4 px-4">
      {(['players', 'teams'] as SubView[]).map(view => (
        <button
          key={view}
          type="button"
          onClick={() => onChange(view)}
          className={`px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px capitalize ${
            value === view
              ? 'border-emerald-500 text-white'
              : 'border-transparent text-zinc-500 hover:text-zinc-300'
          }`}
        >
          {view}
        </button>
      ))}
    </div>
  )
}

function MlbTypeTabs({
  value,
  onChange,
}: {
  value: MlbType
  onChange: (type: MlbType) => void
}) {
  return (
    <div className="flex items-center gap-2">
      {(['batting', 'pitching'] as const).map(type => (
        <button
          key={type}
          type="button"
          onClick={() => onChange(type)}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors capitalize ${
            value === type
              ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
              : 'bg-zinc-900 text-zinc-500 border border-zinc-800 hover:text-zinc-300'
          }`}
        >
          {type}
        </button>
      ))}
    </div>
  )
}

interface PlayerStatsProps {
  leagueName: string
  leaders: LeadersData | null
  loading: boolean
  error: string | null
  filterError: boolean
  onSelectCategory: (category: string) => void
  onSelectSortMetric: (metric: string) => void
  onResetFilters: () => void
}

function PlayerStats({
  leagueName,
  leaders,
  loading,
  error,
  filterError,
  onSelectCategory,
  onSelectSortMetric,
  onResetFilters,
}: PlayerStatsProps) {
  return (
    <>
      {leaders?.categories?.length ? (
        <div className="flex flex-wrap items-center gap-2" aria-label="Player stat categories">
          {leaders.categories.map(category => (
            <button
              key={category.key}
              type="button"
              onClick={() => onSelectCategory(category.key)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                leaders.category === category.key
                  ? 'border-emerald-500/30 bg-emerald-500/20 text-emerald-400'
                  : 'border-zinc-800 bg-zinc-900 text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {category.label}
            </button>
          ))}
        </div>
      ) : null}

      {!loading && !error && leaders?.change_metric && leaders.comparison ? (
        <WhatChanged leaders={leaders} />
      ) : null}

      {error && (
        <div className="space-y-2 rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          <div>{error}</div>
          {filterError && (
            <button
              type="button"
              onClick={onResetFilters}
              className="rounded-lg border border-red-400/30 px-2.5 py-1 text-xs font-semibold text-red-300 hover:bg-red-500/10"
            >
              Reset stats filters
            </button>
          )}
        </div>
      )}

      {loading ? (
        <div className="text-zinc-500 text-sm py-8 text-center">Loading players...</div>
      ) : error ? null : !leaders?.leaders?.length ? (
        <div className="text-center py-12 text-zinc-500 text-sm">
          Player statistics are not available for {leagueName} yet.
        </div>
      ) : (
        <PlayerLeadersTable leaders={leaders} onSelectSortMetric={onSelectSortMetric} />
      )}
    </>
  )
}

function WhatChanged({ leaders }: { leaders: LeadersData }) {
  const comparison = leaders.comparison!
  return (
    <section
      aria-labelledby="what-changed-heading"
      className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-zinc-800 px-4 py-3">
        <div>
          <h2 id="what-changed-heading" className="text-sm font-semibold text-zinc-100">
            What changed
          </h2>
          <p className="mt-0.5 text-xs text-zinc-500">
            {comparison.recent_label} vs {comparison.baseline_label}
          </p>
        </div>
        {comparison.status === 'display_only' && (
          <span className="rounded-full border border-zinc-700 px-2.5 py-1 text-[11px] font-medium text-zinc-400">
            Display-only trend
          </span>
        )}
      </div>

      {leaders.changes.length === 0 || comparison.qualified_leaders === 0 ? (
        <p className="px-4 py-4 text-sm text-zinc-400">
          Not enough valid game history for a Last 5 comparison.
        </p>
      ) : (
        <div className="divide-y divide-zinc-800">
          {leaders.changes.map(change => {
            const direction = directionDisplay(change.direction)
            return (
              <div key={`${change.player_id}-${change.metric.key}`} className="px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                  <div className="min-w-0">
                    <a
                      href={`/player/${change.player_id}`}
                      className="font-medium text-zinc-200 transition-colors hover:text-emerald-400"
                    >
                      {change.name}
                    </a>
                    {change.team && (
                      <span className="ml-1.5 text-xs text-zinc-500">{change.team}</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 font-mono text-sm tabular-nums text-zinc-300">
                    <span role="img" aria-label={direction.label} className={direction.className}>
                      {direction.glyph}
                    </span>
                    <span>
                      {formatSignedMetric(change.metric, change.delta)} {change.metric.label}
                    </span>
                  </div>
                </div>
                <p className="mt-1 text-xs text-zinc-500">
                  Recent {formatMetric(change.metric, change.recent_value)} · Earlier{' '}
                  {formatMetric(change.metric, change.baseline_value)} · {change.recent_games}{' '}
                  recent / {change.baseline_games} earlier
                </p>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

function PlayerLeadersTable({
  leaders,
  onSelectSortMetric,
}: {
  leaders: LeadersData
  onSelectSortMetric: (metric: string) => void
}) {
  const sortedLabel = leaders.columns.find(metric => metric.key === leaders.stat)?.label
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 text-xs text-zinc-500">
        <span>Season {leaders.season}</span>
        <span>·</span>
        <span>Sorted by {sortedLabel || leaders.stat}</span>
      </div>

      <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-500 text-[11px] uppercase tracking-wider">
              <th className="text-left px-4 py-3 font-medium w-10">#</th>
              <th className="text-left px-3 py-3 font-medium">Player</th>
              <th className="text-right px-3 py-3 font-medium">GP</th>
              {leaders.columns.map(metric => (
                <th
                  key={metric.key}
                  aria-sort={metric.key === leaders.stat ? 'descending' : 'none'}
                  className="px-3 py-3 text-right font-medium"
                >
                  <button
                    type="button"
                    onClick={() => onSelectSortMetric(metric.key)}
                    className={`inline-flex items-center gap-1 whitespace-nowrap hover:text-zinc-200 ${
                      metric.key === leaders.stat ? 'text-emerald-400' : 'text-zinc-500'
                    }`}
                  >
                    {metric.label}
                    {metric.key === leaders.stat && <span aria-hidden="true">↓</span>}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {leaders.leaders.map((leader, index) => (
              <tr
                key={`${leader.player_id}-${leader.team}-${index}`}
                className="border-b border-zinc-800/50 hover:bg-zinc-800/30"
              >
                <td className="px-4 py-2.5 text-zinc-500 text-xs">{index + 1}</td>
                <td className="px-3 py-2.5">
                  <a
                    href={`/player/${leader.player_id}`}
                    className="font-medium text-zinc-200 hover:text-emerald-400 transition-colors"
                  >
                    {leader.name}
                  </a>
                  {leader.team && (
                    <span className="text-zinc-500 ml-1.5 text-xs">{leader.team}</span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-right font-mono tabular-nums text-zinc-400">
                  {leader.games}
                </td>
                {leaders.columns.map(metric => (
                  <td
                    key={metric.key}
                    className={`px-3 py-2.5 text-right font-mono tabular-nums ${
                      metric.key === leaders.stat
                        ? 'text-emerald-300 font-bold'
                        : 'text-zinc-300'
                    }`}
                  >
                    {formatMetric(metric, leader[metric.key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

interface TeamStatsProps {
  leagueName: string
  aggregates: TeamAggregatesData | null
  loading: boolean
  error: string | null
  category: string | null
  onSelectCategory: (category: string) => void
}

function TeamStats({
  leagueName,
  aggregates,
  loading,
  error,
  category,
  onSelectCategory,
}: TeamStatsProps) {
  if (loading) {
    return <div className="text-zinc-500 text-sm py-8 text-center">Loading team stats...</div>
  }
  if (error) {
    return (
      <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
        Team statistics are hidden because complete measured coverage is not available.
      </div>
    )
  }
  if (!aggregates?.teams.length) {
    return <div className="text-zinc-500 text-sm">No measured team data available for {leagueName}.</div>
  }

  const categories = aggregates.categories ?? []
  const activeCategory = categories.find(item => item.key === category) ?? categories[0]
  const columns = activeCategory?.columns ?? aggregates.columns ?? []
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
        <span>Season {aggregates.season}</span>
        <span>·</span>
        <span>{aggregates.coverage.games} captured completed games</span>
        <span>·</span>
        <span>Through {aggregates.coverage.last_game_date}</span>
      </div>
      {categories.length > 1 && (
        <div className="flex flex-wrap items-center gap-2" aria-label="Team stat categories">
          {categories.map(item => (
            <button
              key={item.key}
              type="button"
              onClick={() => onSelectCategory(item.key)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                activeCategory?.key === item.key
                  ? 'border-emerald-500/30 bg-emerald-500/20 text-emerald-400'
                  : 'border-zinc-800 bg-zinc-900 text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
      <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-400 text-xs uppercase tracking-wider">
              <th className="text-left py-3 pr-4 pl-4">#</th>
              <th className="text-left py-3 pr-4">Team</th>
              {columns.map(column => (
                <th key={column.key} className="text-right py-3 px-3 whitespace-nowrap">
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {aggregates.teams.map((team, index) => (
              <tr key={team.team} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                <td className="py-3 pr-4 pl-4 text-zinc-500">{index + 1}</td>
                <td className="py-3 pr-4 font-semibold text-zinc-200">{team.team}</td>
                {columns.map(column => (
                  <td
                    key={column.key}
                    className="py-3 px-3 text-right text-zinc-200 font-mono tabular-nums"
                  >
                    {formatTeamMetric(column, team[column.key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!aggregates.coverage.external_schedule_reconciled && (
        <p className="text-xs text-zinc-600">
          Covers captured completed games; not independently reconciled against the official schedule.
        </p>
      )}
    </div>
  )
}
