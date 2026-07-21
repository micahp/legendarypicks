import Head from 'next/head'
import Link from 'next/link'
import ScheduleTab from '../../components/Leagues/ScheduleTab'
import StandingsTab from '../../components/Leagues/StandingsTab'
import StatsTab from '../../components/Leagues/StatsTab'
import UfcRankingsTab from '../../components/Leagues/UfcRankingsTab'
import PredictTab from '../../components/Leagues/PredictTab'
import NflCampHero from '../../components/Leagues/NflCampHero'
import NflDraftRoom from '../../components/Leagues/NflDraftRoom'
import { useLeagueRouteState } from '../../components/Leagues/hooks/useLeagueRouteState'
import { useScheduleData } from '../../components/Leagues/hooks/useScheduleData'
import { useStandingsData } from '../../components/Leagues/hooks/useStandingsData'
import { useStatsData } from '../../components/Leagues/hooks/useStatsData'
import { useUfcRankingsData } from '../../components/Leagues/hooks/useUfcRankingsData'
import { useUfcPredictData } from '../../components/Leagues/hooks/useUfcPredictData'
import { useNflSeasonContext } from '../../components/Leagues/hooks/useNflSeasonContext'
import { useNflDraftBoard } from '../../components/Leagues/hooks/useNflDraftBoard'
import {
  LEAGUE_EMOJIS,
  LEAGUE_NAMES,
  LEAGUE_SWITCHER,
  localToday,
} from '../../components/Leagues/presentation'
import type { HubTab } from '../../components/Leagues/types'

const NFL_TAB_LABELS: Record<string, string> = {
  camp: 'Training Camp',
  standings: '2025 Final',
  stats: '2025 Stats',
  schedule: '2026 Schedule',
}

const TAB_LABELS: Record<HubTab, string> = {
  camp: 'Training Camp',
  standings: 'Standings',
  stats: 'Stats',
  schedule: 'Schedule',
  rankings: 'Rankings',
  predict: 'Predict',
}

export default function LeagueHubPage() {
  const route = useLeagueRouteState()
  const standings = useStandingsData(route.league, route.isWorldCup, route.isUFC)
  const stats = useStatsData({
    league: route.league,
    activeTab: route.activeTab,
    isWorldCup: route.isWorldCup,
    isUFC: route.isUFC,
    supportsTeamStats: route.supportsTeamStats,
  })
  const schedule = useScheduleData(
    route.league,
    route.activeTab,
    route.scheduleDate,
  )
  const ufc = useUfcRankingsData(route.isUFC, route.league)
  const predict = useUfcPredictData(route.isUFC, route.activeTab)

  // NFL camp-mode data (cheap to call regardless — hooks ignore non-NFL)
  const isNFL = route.league === 'nfl'
  const seasonContext = useNflSeasonContext()
  const draftBoard = useNflDraftBoard()

  if (!route.league) return <LeagueHubSkeleton />

  const leagueName = LEAGUE_NAMES[route.league] || route.league.toUpperCase()
  const leagueEmoji = LEAGUE_EMOJIS[route.league] || ''

  const tabLabels = isNFL
    ? { ...TAB_LABELS, ...NFL_TAB_LABELS }
    : TAB_LABELS

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
          labels={tabLabels}
        />

        {/* ── NFL Camp-mode default ── */}
        {route.activeTab === 'camp' && (
          <div className="space-y-6">
            <NflCampHero
              data={seasonContext.data}
              loading={seasonContext.loading}
              error={seasonContext.error}
            />
            <NflDraftRoom
              data={draftBoard.data}
              loading={draftBoard.loading}
              error={draftBoard.error}
              position={draftBoard.position}
              sort={draftBoard.sort}
              offset={draftBoard.offset}
              notes={draftBoard.notes}
              onSelectPosition={draftBoard.selectPosition}
              onSelectSort={draftBoard.selectSort}
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
            onSelectStatCategory={stats.selectStatCategory}
            onSelectSortMetric={stats.selectSortMetric}
            onResetFilters={stats.resetStatsFilters}
            onSelectTeamCategory={stats.selectTeamCategory}
          />
        )}

        {route.activeTab === 'schedule' && (
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
            onShiftDay={route.shiftScheduleDay}
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
