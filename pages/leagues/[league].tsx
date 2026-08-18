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
import NflMockDraftCard from '../../components/Leagues/NflMockDraftCard'
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
import { useNflDraftBoard } from '../../components/Leagues/hooks/useNflDraftBoard'
import {
  LEAGUE_EMOJIS,
  LEAGUE_NAMES,
  leagueLabel,
  orderLeagues,
  localToday,
} from '../../components/Leagues/presentation'
import { useCoverage } from '../../components/Leagues/hooks/useCoverage'
import NewsTab from '../../components/Leagues/NewsTab'
import { useNewsData } from '../../components/Leagues/hooks/useNewsData'
import type { HubTab } from '../../components/Leagues/types'

const TAB_LABELS: Record<HubTab, string> = {
  camp: 'Home',
  standings: 'Standings',
  stats: 'Stats',
  schedule: 'Schedule',
  news: 'News',
  rankings: 'Rankings',
  predict: 'Predict',
}

export default function LeagueHubPage() {
  const route = useLeagueRouteState()
  const isNFL = route.league === 'nfl'
  const standings = useStandingsData(route.league, route.isWorldCup, route.isUFC)
  // Fetched only while the tab is open — the hub already loads standings,
  // leaders and team aggregates on mount without anyone asking for them.
  const news = useNewsData(route.league, route.activeTab === 'news')
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
  const draftBoard = useNflDraftBoard(isNFL && route.activeTab === 'camp')
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
        {!route.offerable && !route.coverageLoading ? (
          <LeagueUnavailable league={route.league} />
        ) : (
        <>
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
            <NflMockDraftCard />
            <NflOffseasonMovers
              data={transactions.data}
              loading={transactions.loading}
              error={transactions.error}
            />
            <NflDraftRoom
              data={draftBoard.data}
              loading={draftBoard.loading}
              error={draftBoard.error}
              position={draftBoard.position}
              sort={draftBoard.sort}
              offset={draftBoard.offset}
              query={draftBoard.query}
              notes={draftBoard.notes}
              syncError={draftBoard.syncError}
              onSelectPosition={draftBoard.selectPosition}
              onSelectSort={draftBoard.selectSort}
              onSetQuery={draftBoard.setQuery}
              onClearQuery={draftBoard.clearQuery}
              onSetOffset={draftBoard.setOffset}
              onSetRank={draftBoard.setRank}
              onToggleWatch={draftBoard.toggleWatch}
              onToggleFade={draftBoard.toggleFade}
            />
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
            season={standings.season}
            availableSeasons={standings.availableSeasons}
            onSelectSeason={standings.selectSeason}
            leagueName={leagueName}
            league={route.league}
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

        {route.activeTab === 'news' && (
          <NewsTab
            league={route.league}
            news={news.news}
            loading={news.loading}
            error={news.error}
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
            league={route.league}
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
        </>
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
  // Built from the coverage registry, not from a constant. A league appears here only
  // once something verified a season of it against the publisher — the same mechanism
  // as ESPN's season dropdown, which lists exactly the seasons it can fill.
  //
  // While coverage is loading we show nothing rather than a hardcoded fallback: an
  // optimistic list that later shrinks is worse than a list that arrives late, and a
  // fallback is how the gate quietly stops being the gate.
  const { loading, offeredLeagues } = useCoverage()
  const leagues = orderLeagues(
    // The league being viewed stays reachable in the nav even mid-load, so the current
    // page never lacks its own tab.
    offeredLeagues.includes(activeLeague) || !activeLeague
      ? offeredLeagues
      : [...offeredLeagues, activeLeague],
  )

  if (loading || !leagues.length) return <nav aria-label="Leagues" className="h-5" />

  return (
    <nav
      aria-label="Leagues"
      className="-mx-4 flex items-center gap-3 overflow-x-auto overflow-y-hidden px-4 text-sm sm:gap-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    >
      {leagues.map(league => (
        <Link
          key={league}
          href={`/leagues/${league}`}
          aria-current={activeLeague === league ? 'page' : undefined}
          className="whitespace-nowrap text-zinc-500 transition-colors hover:text-emerald-400"
        >
          {leagueLabel(league)}
        </Link>
      ))}
    </nav>
  )
}

/**
 * What a league we cannot vouch for renders instead of a hub full of numbers.
 *
 * Deliberately quiet. Per honest-data-ui §4 and contract §2, our own gap is not
 * information about the sport, and the amber accent belongs to player absence — the
 * thing the product exists to show. Dressing our gaps in the same colour trains people
 * to discount the accent that carries the thesis.
 */
// There was a `SeasonInProgressNote` here that printed
// `2026 season in progress — checked through 2026-08-02 · 1682 games`.
// It is gone on purpose. Coverage still GATES what the hub offers — `useCoverage`
// and `LeagueUnavailable` below are untouched — but how thoroughly we checked our
// own ingest is our problem, not a line of copy above a leaderboard.

function LeagueUnavailable({ league }: { league: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 px-4 py-8 text-center">
      <p className="text-sm text-zinc-400">
        {leagueLabel(league)} isn&apos;t available yet.
      </p>
      <p className="mt-1 text-xs text-zinc-600">
        We only show a season once every game in it has been checked against the source.
      </p>
    </div>
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
    // `overflow-x-auto` alone makes the box scrollable on BOTH axes, and the buttons'
    // `-mb-px` against a `border-b-2` leaves it about a pixel of vertical overflow —
    // enough that the strip drags up and down under a thumb. Pin the y axis.
    <div className="flex gap-0 overflow-x-auto overflow-y-hidden border-b border-zinc-800 -mx-4 px-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
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
