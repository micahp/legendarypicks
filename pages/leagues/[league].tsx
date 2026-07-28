import Head from 'next/head'
import Link from 'next/link'
import { useEffect } from 'react'
import ScheduleTab from '../../components/Leagues/ScheduleTab'
import StandingsTab from '../../components/Leagues/StandingsTab'
import StatsTab from '../../components/Leagues/StatsTab'
import UfcRankingsTab from '../../components/Leagues/UfcRankingsTab'
import PredictTab from '../../components/Leagues/PredictTab'
import NflCampHero from '../../components/Leagues/NflCampHero'
import NflOffseasonMovers from '../../components/Leagues/NflOffseasonMovers'
import NflDraftRoom from '../../components/Leagues/NflDraftRoom'
import NflScheduleTab from '../../components/Leagues/NflScheduleTab'
import { useLeagueRouteState } from '../../components/Leagues/hooks/useLeagueRouteState'
import { useScheduleData } from '../../components/Leagues/hooks/useScheduleData'
import { useScheduleAutoDate } from '../../components/Leagues/hooks/useScheduleAutoDate'
import { useScheduleNavigation } from '../../components/Leagues/hooks/useScheduleNavigation'
import { useNflScheduleWeeks } from '../../components/Leagues/hooks/useNflScheduleWeeks'
import { useStandingsData } from '../../components/Leagues/hooks/useStandingsData'
import { useStatsData } from '../../components/Leagues/hooks/useStatsData'
import { useUfcRankingsData } from '../../components/Leagues/hooks/useUfcRankingsData'
import { useUfcPredictData } from '../../components/Leagues/hooks/useUfcPredictData'
import { useNflSeasonContext } from '../../components/Leagues/hooks/useNflSeasonContext'
import { useNflTransactions } from '../../components/Leagues/hooks/useNflTransactions'
import {
  LEAGUE_EMOJIS,
  LEAGUE_NAMES,
  LEAGUE_SWITCHER,
  localToday,
} from '../../components/Leagues/presentation'
import type { HubTab } from '../../components/Leagues/types'

const TAB_LABELS: Record<HubTab, string> = {
  camp: 'Home',
  standings: 'Standings',
  stats: 'Stats',
  schedule: 'Schedule',
  rankings: 'Rankings',
  predict: 'Predict',
}

export default function LeagueHubPage() {
  const route = useLeagueRouteState()
  const isNFL = route.league === 'nfl'
  const standings = useStandingsData(route.league, route.isWorldCup, route.isUFC)
  const stats = useStatsData({
    league: route.league,
    activeTab: route.activeTab,
    isWorldCup: route.isWorldCup,
    isUFC: route.isUFC,
    supportsTeamStats: route.supportsTeamStats,
  })
  const schedule = useScheduleData(
    isNFL ? '' : route.league,  // NFL uses weekly, not daily — suppress
    route.activeTab,
    route.scheduleDate,
  )

  // Auto-resolve schedule date when today is empty, intent is 'default',
  // and Schedule tab is active. resolutionKey prevents stale cross-league results.
  const autoDate = useScheduleAutoDate(
    !isNFL && route.activeTab === 'schedule',  // NFL never auto-resolves daily
    route.league,
    route.scheduleDate,
    schedule.games.length,
    schedule.loading,
    schedule.error,
    route.dateIntent,
  )

  // When auto-resolve picks a date, apply it — only if still on schedule tab
  // with default intent and the resolution matches current league+anchor.
  useEffect(() => {
    const currentKey = `${route.league}:${route.scheduleDate}`
    if (
      route.activeTab === 'schedule' &&
      route.dateIntent === 'default' &&
      autoDate.resolved &&
      autoDate.resolvedDate &&
      autoDate.resolutionKey === currentKey &&
      autoDate.resolvedDate !== route.scheduleDate
    ) {
      route.resolveScheduleDate(autoDate.resolvedDate)
    }
  }, [
    route.activeTab,
    route.dateIntent,
    route.league,
    route.scheduleDate,
    autoDate.resolved,
    autoDate.resolvedDate,
    autoDate.resolutionKey,
  ])

  // Explanation only shows for auto intent, cleared on user action
  const displayExplanation = route.dateIntent === 'auto' ? autoDate.explanation : null

  const seasonContext = useNflSeasonContext(isNFL && route.activeTab === 'camp')
  const transactions = useNflTransactions(isNFL && route.activeTab === 'camp')
  // Resolve prev/next game dates for arrow navigation (non-NFL only)
  const nav = useScheduleNavigation(isNFL || route.activeTab !== 'schedule', route.league, route.scheduleDate)

  const handleGoPrev = () => {
    if (nav.prevDate) route.selectScheduleDate(nav.prevDate)
  }
  const handleGoNext = () => {
    if (nav.nextDate) route.selectScheduleDate(nav.nextDate)
  }

  // ── NFL weekly schedule ──
  const nflSchedule = useNflScheduleWeeks(
    isNFL && route.activeTab === 'schedule',
    route.nflWeek || null,
  )

  // Canonicalize NFL URL when week differs from resolved selection
  useEffect(() => {
    if (!isNFL || route.activeTab !== 'schedule') return
    if (nflSchedule.catalogLoading) return
    if (!nflSchedule.selectedKey) return
    // Canonicalize if URL week is empty OR differs from catalog resolution
    if (route.nflWeek !== nflSchedule.selectedKey) {
      route.canonicalizeNflWeek(nflSchedule.selectedKey)
    }
  }, [isNFL, route.activeTab, route.nflWeek, nflSchedule.selectedKey, nflSchedule.catalogLoading])
  const ufc = useUfcRankingsData(route.isUFC, route.league)
  const predict = useUfcPredictData(route.isUFC, route.activeTab)

  if (!route.league) return <LeagueHubSkeleton />

  const leagueName = LEAGUE_NAMES[route.league] || route.league.toUpperCase()
  const leagueEmoji = LEAGUE_EMOJIS[route.league] || ''

  return (
    <>
      <Head>
        <title>{leagueName} — Legendary Picks</title>
      </Head>

      <div className="space-y-4">
        <LeagueSwitcher activeLeague={route.league} />
        <div className="flex items-center gap-3">
          <span className="text-2xl">{leagueEmoji}</span>
          <h1 className="text-3xl font-extrabold tracking-tight">{leagueName}</h1>
        </div>
        <HubTabs
          tabs={route.validTabs}
          activeTab={route.activeTab}
          onSelect={route.selectTab}
          labels={TAB_LABELS}
        />

        {/* ── NFL Camp-mode default ── */}
        {route.activeTab === 'camp' && (
          <div className="space-y-6">
            <NflCampHero
              data={seasonContext.data}
              loading={seasonContext.loading}
              error={seasonContext.error}
            />
            <NflOffseasonMovers
              data={transactions.data}
              loading={transactions.loading}
              error={transactions.error}
            />
            <NflDraftRoom enabled={isNFL && route.activeTab === 'camp'} />
          </div>
        )}

        {route.activeTab === 'standings' && (
          <StandingsTab
            error={standings.error}
            loading={standings.loading}
            isWorldCup={route.isWorldCup}
            knockout={standings.knockout}
            groups={standings.groups}
            teams={standings.teams}
            leagueName={leagueName}
          />
        )}

        {route.activeTab === 'stats' && (
          <StatsTab
            league={route.league}
            leagueName={leagueName}
            supportsTeamStats={route.supportsTeamStats}
            subView={stats.subView}
            mlbType={stats.mlbType}
            leaders={stats.leaders}
            playerLoading={stats.playerLoading}
            playerError={stats.playerError}
            playerFilterError={stats.playerFilterError}
            teamAggregates={stats.teamAggregates}
            teamLoading={stats.teamLoading}
            teamError={stats.teamError}
            teamCategory={stats.teamCategory}
            onSelectSubView={stats.selectSubView}
            onSelectMlbType={stats.selectMlbType}
            onSelectSeason={stats.selectSeason}
            onSelectStatCategory={stats.selectStatCategory}
            onSelectSortMetric={stats.selectSortMetric}
            onResetFilters={stats.resetStatsFilters}
            onSelectTeamCategory={stats.selectTeamCategory}
          />
        )}

        {route.activeTab === 'schedule' && isNFL && (
          <NflScheduleTab
            selectedKey={nflSchedule.selectedKey}
            weekEntry={nflSchedule.weekEntry}
            phaseLabel={nflSchedule.phaseLabel}
            phases={nflSchedule.catalog?.phases.map(p => ({ season_type: p.season_type, label: p.label })) || []}
            weeksInPhase={nflSchedule.catalog?.weeks || []}
            prevWeekKey={nflSchedule.prevWeekKey}
            nextWeekKey={nflSchedule.nextWeekKey}
            dateGroups={nflSchedule.dateGroups}
            games={nflSchedule.games}
            gamesLoading={nflSchedule.gamesLoading}
            gamesError={nflSchedule.gamesError}
            catalogLoading={nflSchedule.catalogLoading}
            catalogError={nflSchedule.catalogError}
            onSelectWeek={route.selectNflWeek}
          />
        )}

        {route.activeTab === 'schedule' && !isNFL && (
          <ScheduleTab
            scheduleDate={route.scheduleDate}
            formattedDate={schedule.formattedDate}
            isToday={schedule.isToday}
            isUFC={route.isUFC}
            leagueName={leagueName}
            games={schedule.games}
            groups={schedule.groups}
            loading={schedule.loading}
            error={schedule.error}
            explanation={displayExplanation}
            prevDate={nav.prevDate}
            nextDate={nav.nextDate}
            onGoPrev={handleGoPrev}
            onGoNext={handleGoNext}
            onSelectDate={route.selectScheduleDate}
            today={localToday}
          />
        )}

        {route.activeTab === 'rankings' && (
          <UfcRankingsTab
            rankings={ufc.rankings}
            loading={ufc.loading}
            error={ufc.error}
          />
        )}

        {route.activeTab === 'predict' && (
          <PredictTab
            fights={predict.fights}
            myPicks={predict.myPicks}
            record={predict.record}
            crowd={predict.crowd}
            loading={predict.loading}
            error={predict.error}
            actionError={predict.actionError}
            submittingKey={predict.submittingKey}
            onSubmitPick={predict.submitPick}
          />
        )}
      </div>
    </>
  )
}

function LeagueHubSkeleton() {
  return (
    <div className="space-y-3 animate-pulse">
      <div className="h-8 bg-zinc-800 rounded w-48" />
      <div className="h-10 bg-zinc-800 rounded" />
    </div>
  )
}

function LeagueSwitcher({ activeLeague }: { activeLeague: string }) {
  return (
    <nav
      aria-label="Leagues"
      className="-mx-4 flex items-center gap-3 overflow-x-auto px-4 text-sm sm:gap-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    >
      {LEAGUE_SWITCHER.map(league => (
        <Link
          key={league}
          href={`/leagues/${league}`}
          aria-current={activeLeague === league ? 'page' : undefined}
          className="whitespace-nowrap text-zinc-500 transition-colors hover:text-emerald-400"
        >
          {LEAGUE_NAMES[league]}
        </Link>
      ))}
    </nav>
  )
}

function HubTabs({
  tabs,
  activeTab,
  onSelect,
  labels,
}: {
  tabs: HubTab[]
  activeTab: HubTab
  onSelect: (tab: HubTab) => void
  labels: Record<HubTab, string>
}) {
  return (
    <div className="flex gap-0 overflow-x-auto border-b border-zinc-800 -mx-4 px-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      {tabs.map(tab => (
        <button
          key={tab}
          type="button"
          onClick={() => onSelect(tab)}
          className={`px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px ${
            activeTab === tab
              ? 'border-emerald-500 text-white'
              : 'border-transparent text-zinc-500 hover:text-zinc-300'
          }`}
        >
          {labels[tab]}
        </button>
      ))}
    </div>
  )
}
