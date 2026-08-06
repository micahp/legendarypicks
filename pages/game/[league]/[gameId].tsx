import { useRouter } from 'next/router'
import { useState, useEffect, useMemo, useCallback } from 'react'
import { SportsService } from '../../../services/sports'
import {
  GameDetail, Tab, isNBA, isNHL, isMLB, isNFL, isWC, isSoccer,
  hasGameTabs, usesDetailEndpoint, usesPerTabEndpoints,
  BoxScoreData, PbPData, SoccerBoxScoreData, SoccerPbPData, GameInfoData,
} from '../../../components/Game/types'
import ScoreStrip from '../../../components/Game/ScoreStrip'
import TabBar from '../../../components/Game/TabBar'
import { NBABoxScore, NHLBoxScore, MLBBoxScore, NFLBoxScore } from '../../../components/Game/BoxScore'
import SoccerBoxScore from '../../../components/Game/SoccerBoxScore'
import PlayByPlay from '../../../components/Game/PlayByPlay'
import GameInfo from '../../../components/Game/GameInfo'
import GameProps from '../../../components/Game/GameProps'
import GameStory from '../../../components/Game/GameStory'
import WCContext from '../../../components/Game/WCContext'
import BoothFeed from '../../../components/Game/BoothFeed'
import ListenLive from '../../../components/ListenLive'

const TAB_DEFS: { key: Tab; label: string }[] = [
  { key: 'boxscore', label: 'Box Score' },
  { key: 'playbyplay', label: 'Play-by-Play' },
  { key: 'props', label: 'Props' },
  { key: 'info', label: 'Game Info' },
]

// ── Loading skeletons ──
function BoxScoreSkeleton({ league }: { league: string }) {
  const isMLBLeague = league === 'mlb'
  const isNFLLeague = league === 'nfl'
  const isWCLeague = league === 'wc'
  const isUS = isMLBLeague || isNFLLeague

  return (
    <div className="animate-pulse">
      {isUS && (
        <div className={isMLBLeague ? 'border-l-2 border-amber-500/40 pl-3' : 'border-t-2 border-amber-400/40 pt-3'}>
          <div className="h-4 bg-zinc-800 rounded w-1/2 mb-4" />
          {isMLBLeague ? (
            <>
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-3 bg-zinc-800 rounded w-full mb-3" />
              ))}
              <div className="mt-8">
                <div className="h-4 bg-zinc-800 rounded w-2/5 mb-4" />
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="h-3 bg-zinc-800 rounded w-full mb-3" />
                ))}
              </div>
            </>
          ) : (
            <>
              <div className="grid grid-cols-3 gap-4">
                {Array.from({ length: 3 }).map((_, ci) => (
                  <div key={ci}>
                    <div className="h-3 bg-zinc-800 rounded w-full mb-3" />
                    {Array.from({ length: 5 }).map((_, ri) => (
                      <div key={ri} className="h-3 bg-zinc-800 rounded w-full mb-2" />
                    ))}
                  </div>
                ))}
              </div>
              <div className="mt-8">
                <div className="h-4 bg-zinc-800 rounded w-1/3 mb-4" />
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="h-3 bg-zinc-800 rounded w-full mb-2" />
                ))}
              </div>
            </>
          )}
        </div>
      )}
      {isWCLeague && (
        <div className="border-l-2 border-emerald-500/40 pl-3">
          <div className="grid grid-cols-[1fr_280px] gap-6">
            <div>
              <div className="h-4 bg-zinc-800 rounded w-1/3 mb-4" />
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="h-3 bg-zinc-800 rounded w-full mb-3" />
              ))}
            </div>
            <div>
              <div className="h-4 bg-zinc-800 rounded w-2/3 mb-4" />
              <div className="bg-zinc-800/50 border border-zinc-800 rounded-lg p-3 mb-3">
                {Array.from({ length: 11 }).map((_, i) => (
                  <div key={i} className="h-3 bg-zinc-800 rounded w-full mb-2" />
                ))}
              </div>
              <div className="bg-zinc-800/50 border border-zinc-800 rounded-lg p-3">
                {Array.from({ length: 11 }).map((_, i) => (
                  <div key={i} className="h-3 bg-zinc-800 rounded w-full mb-2" />
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function PbPSkeleton({ league }: { league: string }) {
  const isWCLeague = league === 'wc'
  return (
    <div className="animate-pulse">
      {!isWCLeague ? (
        <div>
          <div className="h-5 bg-zinc-800 rounded w-1/3 mb-4" />
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex gap-2 mb-3">
              <div className="h-3 bg-zinc-800 rounded w-10 shrink-0" />
              <div className="h-3 bg-zinc-800 rounded flex-1" />
              <div className="h-3 bg-zinc-800 rounded w-12 shrink-0" />
            </div>
          ))}
        </div>
      ) : (
        <div className="border-l border-zinc-700 pl-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex items-start gap-3 py-2">
              <div className="w-14 shrink-0 flex flex-col items-center">
                <div className="h-4 w-4 bg-zinc-800 rounded-full" />
                <div className="h-2 bg-zinc-800 rounded w-8 mt-1" />
              </div>
              <div className="flex-1">
                <div className="h-3 bg-zinc-800 rounded w-3/4" />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function InfoSkeleton() {
  return (
    <div className="space-y-5 animate-pulse">
      <div className="space-y-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex justify-between">
            <div className="h-3 bg-zinc-800 rounded w-1/4" />
            <div className="h-3 bg-zinc-800 rounded w-1/2" />
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="bg-zinc-800/50 border border-zinc-800 rounded-lg px-4 py-3 min-w-[100px]">
            <div className="h-2 bg-zinc-800 rounded w-12 mb-2" />
            <div className="h-4 bg-zinc-800 rounded w-16" />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-4">
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
            <div className="h-3 bg-zinc-800 rounded w-1/4 mb-2" />
            <div className="h-4 bg-zinc-800 rounded w-1/2 mb-2" />
            <div className="h-3 bg-zinc-800 rounded w-1/3" />
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Per-tab data fetching hooks ──
function useTabData(league: string | undefined, gameId: string | undefined, active: boolean) {
  const [boxscore, setBoxscore] = useState<BoxScoreData | null>(null)
  const [soccerBoxscore, setSoccerBoxscore] = useState<SoccerBoxScoreData | null>(null)
  const [pbp, setPbp] = useState<PbPData | null>(null)
  const [soccerPbp, setSoccerPbp] = useState<SoccerPbPData | null>(null)
  const [gameInfo, setGameInfo] = useState<GameInfoData | null>(null)
  const [loadingBoxscore, setLoadingBoxscore] = useState(false)
  const [loadingPbp, setLoadingPbp] = useState(false)
  const [loadingInfo, setLoadingInfo] = useState(false)
  const [tabLoaded, setTabLoaded] = useState<Record<string, boolean>>({})

  const fetchTab = useCallback(async (tab: Tab) => {
    if (!league || !gameId) return
    if (tabLoaded[tab]) return

    setTabLoaded(prev => ({ ...prev, [tab]: true }))
    const lg = league.toLowerCase()

    if (tab === 'boxscore') {
      setLoadingBoxscore(true)
      try {
        const d = await SportsService.getBoxscore(league, gameId)
        if (isSoccer(lg)) {
          setSoccerBoxscore(d as SoccerBoxScoreData)
        } else {
          setBoxscore(d as BoxScoreData)
        }
      } finally {
        setLoadingBoxscore(false)
      }
    } else if (tab === 'playbyplay') {
      setLoadingPbp(true)
      try {
        const d = await SportsService.getPlayByPlay(league, gameId)
        if (isSoccer(lg)) {
          setSoccerPbp(d as SoccerPbPData)
        } else {
          setPbp(d as PbPData)
        }
      } finally {
        setLoadingPbp(false)
      }
    } else if (tab === 'info') {
      setLoadingInfo(true)
      try {
        const d = await SportsService.getGameInfo(league, gameId)
        setGameInfo(d as GameInfoData)
      } finally {
        setLoadingInfo(false)
      }
    }
  }, [league, gameId, tabLoaded])

  return { boxscore, soccerBoxscore, pbp, soccerPbp, gameInfo,
           loadingBoxscore, loadingPbp, loadingInfo, fetchTab }
}

export default function GameDetailPage() {
  const router = useRouter()
  const { league, gameId } = router.query as { league?: string; gameId?: string }
  const [detail, setDetail] = useState<GameDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<Tab>('boxscore')

  const lg = (league || '').toLowerCase()
  const showTabs = hasGameTabs(lg)
  // WC gets an extra "From the Booth" tab for the live broadcast reads.
  const tabDefs = lg === 'wc' ? [...TAB_DEFS, { key: 'booth' as Tab, label: 'From the Booth' }] : TAB_DEFS
  const usesDetail = usesDetailEndpoint(lg)
  const usesPerTab = usesPerTabEndpoints(lg)

  // Per-tab data
  const tabData = useTabData(league, gameId, !usesDetail)

  // Fetch detail (NBA/NHL path) or minimal context (other leagues)
  useEffect(() => {
    if (!league || !gameId) return
    ;(async () => {
      setLoading(true)
      if (usesDetail) {
        const d = await SportsService.getGameDetail(league, gameId)
        setDetail(d)
      } else {
        // For per-tab leagues, just get minimal context from detail endpoint (strength records)
        const d = await SportsService.getGameDetail(league, gameId)
        setDetail(d)
      }
      setLoading(false)
    })()
  }, [league, gameId])

  // Lazy-fetch tab data on first open for per-tab leagues
  useEffect(() => {
    if (usesPerTab && showTabs) {
      tabData.fetchTab(tab)
    }
  }, [tab, usesPerTab, showTabs, tabData.fetchTab])

  // Show the final score when the game is over, the live score while in progress.
  const displayScore = useMemo(() => detail?.final_score ?? detail?.live_score ?? null, [detail])
  const gameState = detail?.state ?? null

  // No page-level wrapper: Layout provides bg-ink-900 + max-w-6xl main + padding
  if (loading) return <div className="max-w-4xl mx-auto animate-pulse space-y-3"><div className="h-28 bg-zinc-800 rounded-2xl"/><div className="h-64 bg-zinc-800 rounded-xl"/></div>

  // League not supported at all
  if (!detail && !loading) {
    return (
      <div className="max-w-4xl mx-auto space-y-5">
        <div className="flex items-center gap-3">
          <button onClick={() => router.back()} className="text-zinc-500 hover:text-white transition-colors text-sm">← Back</button>
          <span className="text-[10px] uppercase tracking-widest text-zinc-500 bg-zinc-900 px-2 py-0.5 rounded">{lg.toUpperCase()}</span>
        </div>
        <p className="text-zinc-500 text-center py-8">Game data not available.</p>
      </div>
    )
  }

  const ctx = detail?.context
  const sHome = detail?.strength ? detail.strength[ctx?.home_team || ''] : undefined
  const sAway = detail?.strength ? detail.strength[ctx?.away_team || ''] : undefined
  const homeRecord = sHome ? `${sHome.wins}-${sHome.losses}` : ''
  const awayRecord = sAway ? `${sAway.wins}-${sAway.losses}` : ''

  return (
    <div className="max-w-4xl mx-auto space-y-5">

      {/* Back + league badge */}
      <div className="flex items-center gap-3">
        <button onClick={() => router.back()} className="text-zinc-500 hover:text-white transition-colors text-sm">← Back</button>
        <span className="text-[10px] uppercase tracking-widest text-zinc-500 bg-zinc-900 px-2 py-0.5 rounded">{detail?.league || lg.toUpperCase()}</span>
      </div>

      {/* Score strip */}
      <ScoreStrip
        ctx={ctx || null} score={displayScore} state={gameState}
        homeName={sHome?.name || ctx?.home_team || ''}
        awayName={sAway?.name || ctx?.away_team || ''}
        homeRecord={homeRecord} awayRecord={awayRecord}
      />

      {lg === 'wc' ? <ListenLive /> : null}

      {/* Game context: WC gets the broadcast+market+form summary; others the AI matchup story */}
      {league && gameId && (lg === 'wc'
        ? <WCContext gameId={gameId} />
        : <GameStory league={league} gameId={gameId} />)}

      {/* Tab gating: supported leagues get tabs; others get "not available" */}
      {showTabs ? (
        <>
          <TabBar active={tab} onChange={setTab} tabs={tabDefs} />

          {/* Tab content card */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
            {tab === 'boxscore' && (
              usesDetail ? (
                // NBA/NHL: existing detail path
                isNBA(lg) ? <NBABoxScore stats={detail?.team_stats || []} />
                : isNHL(lg) ? <NHLBoxScore stats={detail?.team_stats || []} />
                : <p className="text-zinc-500 text-sm">No box score data.</p>
              ) : usesPerTab ? (
                tabData.loadingBoxscore ? (
                  <BoxScoreSkeleton league={lg} />
                ) : isSoccer(lg) ? (
                  tabData.soccerBoxscore ? (
                    <SoccerBoxScore data={tabData.soccerBoxscore} />
                  ) : (
                    <div className="text-zinc-500 text-sm text-center py-12">Box score available at kickoff.</div>
                  )
                ) : tabData.boxscore ? (
                  isMLB(lg) ? <MLBBoxScore data={tabData.boxscore} />
                  : isNFL(lg) ? <NFLBoxScore data={tabData.boxscore} />
                  : <p className="text-zinc-500 text-sm">No box score data.</p>
                ) : (
                  <p className="text-zinc-500 text-sm">No box score data.</p>
                )
              ) : (
                <p className="text-zinc-500 text-sm">No box score data.</p>
              )
            )}

            {tab === 'playbyplay' && (
              usesDetail ? (
                // NBA/NHL: legacy detail path
                <PlayByPlay
                  legacyPlays={detail?.scoring_plays || []}
                  homeTeam={ctx?.home_team || ''}
                  awayTeam={ctx?.away_team || ''}
                />
              ) : usesPerTab ? (
                tabData.loadingPbp ? (
                  <PbPSkeleton league={lg} />
                ) : isSoccer(lg) ? (
                  <PlayByPlay soccerData={tabData.soccerPbp || undefined} />
                ) : (
                  <PlayByPlay data={tabData.pbp || undefined} />
                )
              ) : (
                <p className="text-zinc-500 text-sm">No play-by-play data.</p>
              )
            )}

            {tab === 'info' && (
              usesDetail ? (
                // NBA/NHL: existing info
                <GameInfo ctx={ctx || null} homeStrength={sHome} awayStrength={sAway} />
              ) : usesPerTab ? (
                tabData.loadingInfo ? (
                  <InfoSkeleton />
                ) : (
                  <GameInfo ctx={ctx || null} homeStrength={sHome} awayStrength={sAway} extraInfo={tabData.gameInfo} />
                )
              ) : (
                <GameInfo ctx={ctx || null} homeStrength={sHome} awayStrength={sAway} />
              )
            )}

            {tab === 'props' && league && gameId && (
              <GameProps league={league} gameId={gameId} inTab />
            )}

            {tab === 'booth' && gameId && <BoothFeed gameId={gameId} />}
          </div>
        </>
      ) : (
        <>
          {/* Leagues without detail tabs retain the existing standalone props surface. */}
          {league && gameId && <GameProps league={league} gameId={gameId} />}
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-12 text-center">
            <p className="text-zinc-500 text-sm">Detailed stats aren&apos;t available for this sport yet.</p>
            <p className="text-zinc-600 text-xs mt-2">Check back for future updates.</p>
          </div>
        </>
      )}
    </div>
  )
}
