import { useMemo, useState } from 'react'
import {
  directionDisplay,
  formatMetric,
  formatSignedMetric,
  formatTeamMetric,
  seasonLabel,
} from './presentation'
import FilterPill from './FilterPill'
import type {
  LeadersData,
  SubView,
  TeamAggregate,
  TeamAggregatesData,
  TeamColumn,
  TeamStatCategory,
} from './types'

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
  onSelectSeason: (season: string) => void
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
  onSelectSeason,
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

      {subView === 'players' && leaders && (
        <PlayerFilterBar
          league={league}
          isMlb={league === 'mlb'}
          mlbType={mlbType}
          leaders={leaders}
          onSelectMlbType={onSelectMlbType}
          onSelectSeason={onSelectSeason}
          onSelectCategory={onSelectStatCategory}
        />
      )}

      {subView === 'players' && (
        <PlayerStats
          leagueName={leagueName}
          leaders={leaders}
          loading={playerLoading}
          error={playerError}
          filterError={playerFilterError}
          onSelectSortMetric={onSelectSortMetric}
          onResetFilters={onResetFilters}
        />
      )}

      {supportsTeamStats && subView === 'teams' && (
        <TeamStats
          league={league}
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

/**
 * The player filter bar: season, MLB batting/pitching, stat category — one row
 * of pills, the way a standings page reads. Season leads, so the year sits in
 * the same first position on every league and on the standings tab.
 *
 * Every option here is the API's own, never a list this component knows. The
 * seasons are the ones `player_stats` actually holds and the categories are the
 * ones whose metrics have values for the selected season (measured 2026-08-17:
 * this is why NBA never offers True Shooting % — the column is 100% NULL, so
 * the endpoint drops it rather than serve a sort that does nothing).
 *
 * The season pill stays on screen even when only one season exists, because it
 * is the only thing that says which season the table below is.
 */
function PlayerFilterBar({
  league,
  isMlb,
  mlbType,
  leaders,
  onSelectMlbType,
  onSelectSeason,
  onSelectCategory,
}: {
  league: string
  isMlb: boolean
  mlbType: MlbType
  leaders: LeadersData
  onSelectMlbType: (type: MlbType) => void
  onSelectSeason: (season: string) => void
  onSelectCategory: (category: string) => void
}) {
  const seasons = leaders.available_seasons ?? []
  const categories = leaders.categories ?? []
  if (!isMlb && seasons.length === 0 && categories.length === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-2">
      {seasons.length > 0 && (
        <FilterPill
          label="Season"
          value={leaders.season ?? seasons[0]}
          options={seasons.map(season => ({
            value: season,
            label: seasonLabel(league, season),
          }))}
          onSelect={onSelectSeason}
        />
      )}
      {isMlb && (
        <FilterPill
          label="Stat type"
          value={mlbType}
          options={[
            { value: 'batting', label: 'Batting' },
            { value: 'pitching', label: 'Pitching' },
          ]}
          onSelect={value => onSelectMlbType(value as MlbType)}
        />
      )}
      {categories.length > 0 && (
        <FilterPill
          label="Stat category"
          value={leaders.category ?? categories[0].key}
          options={categories.map(category => ({
            value: category.key,
            label: category.label,
          }))}
          onSelect={onSelectCategory}
        />
      )}
    </div>
  )
}

interface PlayerStatsProps {
  leagueName: string
  leaders: LeadersData | null
  loading: boolean
  error: string | null
  filterError: boolean
  onSelectSortMetric: (metric: string) => void
  onResetFilters: () => void
}

function PlayerStats({
  leagueName,
  leaders,
  loading,
  error,
  filterError,
  onSelectSortMetric,
  onResetFilters,
}: PlayerStatsProps) {
  return (
    <>
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
      <div className="text-xs text-zinc-500">Sorted by {sortedLabel || leaders.stat}</div>

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
  league: string
  leagueName: string
  aggregates: TeamAggregatesData | null
  loading: boolean
  error: string | null
  category: string | null
  onSelectCategory: (category: string) => void
}

function TeamStats({
  league,
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
    <TeamStatsTable
      league={league}
      season={aggregates.season}
      categories={categories}
      activeCategory={activeCategory}
      columns={columns}
      teams={aggregates.teams}
      onSelectCategory={onSelectCategory}
    />
  )
}

/**
 * Every column here sorts, and the sort happens in the browser because this
 * table IS the whole population — all 32 NFL teams, all 137 in NCAAF. That is
 * what makes a client-side sort honest; the player leaders table above is a top
 * N for one stat, so its headers re-query instead.
 *
 * Numbers sort high-to-low and the team name sorts A-Z, which is what
 * "descending" means for each. A team with no value for the sorted column goes
 * last in either direction — absence is not a low score, and sorting it as one
 * would put it where a real worst-in-league belongs.
 */
function TeamStatsTable({
  league,
  season,
  categories,
  activeCategory,
  columns,
  teams,
  onSelectCategory,
}: {
  league: string
  season?: number | string | null
  categories: TeamStatCategory[]
  activeCategory?: TeamStatCategory
  columns: TeamColumn[]
  teams: TeamAggregate[]
  onSelectCategory: (category: string) => void
}) {
  const [sortKey, setSortKey] = useState<string | null>(null)

  const sortedTeams = useMemo(() => {
    if (!sortKey) return teams
    const rows = [...teams]
    rows.sort((a, b) => {
      const left = a[sortKey]
      const right = b[sortKey]
      const leftMissing = left === null || left === undefined || left === ''
      const rightMissing = right === null || right === undefined || right === ''
      if (leftMissing || rightMissing) return leftMissing === rightMissing ? 0 : leftMissing ? 1 : -1
      if (sortKey === 'team') return String(left).localeCompare(String(right))
      return Number(right) - Number(left)
    })
    return rows
  }, [teams, sortKey])

  return (
    <div className="space-y-3">
      {(season !== null && season !== undefined) || categories.length > 1 ? (
        <div className="flex flex-wrap items-center gap-2">
          {season !== null && season !== undefined && (
            <FilterPill
              label="Season"
              value={season}
              options={[{ value: season, label: seasonLabel(league, season) }]}
              onSelect={() => undefined}
            />
          )}
          {categories.length > 1 && (
            <FilterPill
              label="Team stat category"
              value={activeCategory?.key ?? categories[0].key}
              options={categories.map(item => ({ value: item.key, label: item.label }))}
              onSelect={onSelectCategory}
            />
          )}
        </div>
      ) : null}
      <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-400 text-xs uppercase tracking-wider">
              <th className="text-left py-3 pr-4 pl-4">#</th>
              <th
                aria-sort={sortKey === 'team' ? 'ascending' : 'none'}
                className="text-left py-3 pr-4"
              >
                <button
                  type="button"
                  onClick={() => setSortKey('team')}
                  className={`inline-flex items-center gap-1 whitespace-nowrap hover:text-zinc-200 ${
                    sortKey === 'team' ? 'text-emerald-400' : 'text-zinc-400'
                  }`}
                >
                  Team
                  {sortKey === 'team' && <span aria-hidden="true">↓</span>}
                </button>
              </th>
              {columns.map(column => (
                <th
                  key={column.key}
                  aria-sort={sortKey === column.key ? 'descending' : 'none'}
                  className="text-right py-3 px-3 whitespace-nowrap"
                >
                  <button
                    type="button"
                    onClick={() => setSortKey(column.key)}
                    className={`inline-flex items-center gap-1 whitespace-nowrap hover:text-zinc-200 ${
                      sortKey === column.key ? 'text-emerald-400' : 'text-zinc-400'
                    }`}
                  >
                    {column.label}
                    {sortKey === column.key && <span aria-hidden="true">↓</span>}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedTeams.map((team, index) => (
              <tr key={team.team} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                <td className="py-3 pr-4 pl-4 text-zinc-500">{index + 1}</td>
                <td className="py-3 pr-4 font-semibold text-zinc-200">{team.team}</td>
                {columns.map(column => (
                  <td
                    key={column.key}
                    className={`py-3 px-3 text-right font-mono tabular-nums ${
                      sortKey === column.key ? 'text-emerald-300 font-bold' : 'text-zinc-200'
                    }`}
                  >
                    {formatTeamMetric(column, team[column.key])}
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
