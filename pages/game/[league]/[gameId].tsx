import { useRouter } from 'next/router'
import { useState, useEffect, useMemo } from 'react'
import { SportsService } from '../../../services/sports'
import { GameDetail, Tab, isNBA, isNHL } from '../../../components/Game/types'
import ScoreStrip from '../../../components/Game/ScoreStrip'
import TabBar from '../../../components/Game/TabBar'
import { NBABoxScore, NHLBoxScore } from '../../../components/Game/BoxScore'
import PlayByPlay from '../../../components/Game/PlayByPlay'
import GameInfo from '../../../components/Game/GameInfo'
import GameProps from '../../../components/Game/GameProps'
import GameStory from '../../../components/Game/GameStory'

export default function GameDetailPage() {
  const router = useRouter()
  const { league, gameId } = router.query as { league?: string; gameId?: string }
  const [detail, setDetail] = useState<GameDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<Tab>('boxscore')

  useEffect(() => {
    if (!league || !gameId) return
    (async () => {
      setLoading(true)
      const d = await SportsService.getGameDetail(league, gameId)
      setDetail(d)
      setLoading(false)
    })()
  }, [league, gameId])

  // Show the final score when the game is over, the live score while in progress.
  const displayScore = useMemo(() => detail?.final_score ?? detail?.live_score ?? null, [detail])
  const gameState = detail?.state ?? null

  // No page-level wrapper here: Layout already provides bg-ink-900 + the max-w-6xl main + padding.
  // Skeletons use bg-zinc-800 so they're visible against the ink-900 page (zinc-900 would be invisible on the cards).
  if (loading) return <div className="max-w-4xl mx-auto animate-pulse space-y-3"><div className="h-28 bg-zinc-800 rounded-2xl"/><div className="h-64 bg-zinc-800 rounded-xl"/></div>
  // Full box-score detail is NBA/NHL only. For other leagues (e.g. MLB) still render
  // the player-props view if this game has props; otherwise show "not available".
  if (!detail || !detail.context) return (
    <div className="max-w-4xl mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <button onClick={() => router.back()} className="text-zinc-500 hover:text-white transition-colors text-sm">← Back</button>
        <span className="text-[10px] uppercase tracking-widest text-zinc-500 bg-zinc-900 px-2 py-0.5 rounded">{league?.toUpperCase()}</span>
      </div>
      {league && gameId && <GameStory league={league} gameId={gameId} />}
      {league && gameId ? <GameProps league={league} gameId={gameId} /> : null}
      {league && gameId
        ? <p className="text-zinc-600 text-xs text-center pt-2">Full box score for this league is coming soon.</p>
        : <p className="text-zinc-500 text-center py-8">Game data not available.</p>}
    </div>
  )

  const ctx = detail.context
  const sHome = detail.strength[ctx?.home_team || '']
  const sAway = detail.strength[ctx?.away_team || '']
  const homeRecord = sHome ? `${sHome.wins}-${sHome.losses}` : ''
  const awayRecord = sAway ? `${sAway.wins}-${sAway.losses}` : ''

  return (
    <div className="max-w-4xl mx-auto space-y-5">

        {/* Back + league badge */}
        <div className="flex items-center gap-3">
          <button onClick={() => router.back()} className="text-zinc-500 hover:text-white transition-colors text-sm">← Back</button>
          <span className="text-[10px] uppercase tracking-widest text-zinc-500 bg-zinc-900 px-2 py-0.5 rounded">{detail.league}</span>
        </div>

        {/* Score strip */}
        <ScoreStrip
          ctx={ctx} score={displayScore} state={gameState}
          homeName={sHome?.name || ctx?.home_team || ''}
          awayName={sAway?.name || ctx?.away_team || ''}
          homeRecord={homeRecord} awayRecord={awayRecord}
        />

        {/* AI matchup story (grounded in records/streaks) */}
        {league && gameId && <GameStory league={league} gameId={gameId} />}

        {/* Player props for this game (MLB) */}
        {league && gameId && <GameProps league={league} gameId={gameId} />}

        {/* Tabs */}
        <TabBar active={tab} onChange={setTab} />

        {/* Tab content */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
          {tab === 'boxscore' && (
            isNBA(detail.league) ? <NBABoxScore stats={detail.team_stats} />
            : isNHL(detail.league) ? <NHLBoxScore stats={detail.team_stats} />
            : <p className="text-zinc-500 text-sm">No box score data.</p>
          )}
          {tab === 'playbyplay' && (
            <PlayByPlay
              allPlays={detail.scoring_plays}
              homeTeam={ctx?.home_team || ''}
              awayTeam={ctx?.away_team || ''}
            />
          )}
          {tab === 'info' && (
            <GameInfo ctx={ctx} homeStrength={sHome} awayStrength={sAway} />
          )}
        </div>

      </div>
  )
}
