import { useRouter } from 'next/router'
import { useState, useEffect, useMemo } from 'react'
import { SportsService } from '../../../services/sports'

// ── types ──
interface TeamStat {
  team_abbrev: string; home_away: string
  fgm_fga?: string; fg_pct?: number; tpm_tpa?: string; tp_pct?: number
  ftm_fta?: string; ft_pct?: number
  rebounds?: number; off_rebounds?: number; def_rebounds?: number
  assists?: number; steals?: number; blocks?: number
  turnovers?: number; fouls?: number
  fast_break_pts?: number; pts_in_paint?: number; largest_lead?: number
  shots?: number; blocked_shots?: number; hits?: number
  takeaways?: number; giveaways?: number; faceoffs_won?: number; faceoff_pct?: number
  powerplay_goals?: number; powerplay_opps?: number
  penalties?: number; penalty_min?: number
}
interface ScoringPlay {
  period: number; period_disp: string; clock: string
  away_score: number; home_score: number
  team_abbrev: string; play_text: string; play_type: string
}
interface GameContext {
  venue_name: string; venue_city: string; attendance: number
  officials: string[]; home_team: string; away_team: string
}
interface StrengthRow {
  abbrev: string; name: string; wins: number; losses: number
  win_pct: number; differential: string; streak: string
}
interface GameDetail {
  game_id: string; league: string
  team_stats: TeamStat[]
  scoring_plays: ScoringPlay[]
  context: GameContext | null
  strength: Record<string, StrengthRow>
  final_score: { home: number; away: number } | null
}

type Tab = 'boxscore' | 'playbyplay' | 'info'

// ── helpers ──
function isNBA(lg: string) { return lg === 'nba' }
function isNHL(lg: string) { return lg === 'nhl' }
function fmt(v: any, dec?: boolean): string {
  if (v === null || v === undefined) return '-'
  if (typeof v === 'number') return dec ? v.toFixed(v % 1 ? 1 : 0) : String(v)
  return String(v)
}

// ── score strip (compact ESPN-style) ──
function ScoreStrip({ ctx, final, homeName, awayName, homeRecord, awayRecord }: {
  ctx: GameContext | null; final: { away: number; home: number } | null
  homeName: string; awayName: string; homeRecord: string; awayRecord: string
}) {
  const homeWon = final ? final.home > final.away : false
  const awayWon = final ? final.away > final.home : false
  return (
    <div className="flex items-center justify-center gap-4 md:gap-8 py-6">
      {/* Away */}
      <div className="flex flex-col items-center text-center min-w-0 flex-1 gap-0.5">
        <div className="text-xs font-bold text-zinc-400">{ctx?.away_team || 'AWAY'}</div>
        <span className={`text-4xl md:text-5xl font-black tabular-nums tracking-tight ${
          awayWon ? 'text-white' : 'text-zinc-500'
        }`}>
          {final?.away ?? '-'}
        </span>
        <div className={`text-xs ${awayWon ? 'text-zinc-400' : 'text-zinc-600'}`}>{awayRecord}</div>
        <div className={`text-sm font-semibold mt-0.5 truncate max-w-[140px] ${awayWon ? 'text-zinc-200' : 'text-zinc-500'}`}>{awayName}</div>
      </div>

      {/* Center: FINAL */}
      <div className="flex items-center shrink-0">
        <span className="text-xs font-bold uppercase text-zinc-500 tracking-widest">FINAL</span>
      </div>

      {/* Home */}
      <div className="flex flex-col items-center text-center min-w-0 flex-1 gap-0.5">
        <div className="text-xs font-bold text-zinc-400">{ctx?.home_team || 'HOME'}</div>
        <div className="flex items-center gap-0.5">
          <span className={`text-4xl md:text-5xl font-black tabular-nums tracking-tight ${
            homeWon ? 'text-white' : 'text-zinc-500'
          }`}>
            {final?.home ?? '-'}
          </span>
        </div>
        <div className={`text-xs ${homeWon ? 'text-zinc-400' : 'text-zinc-600'}`}>{homeRecord}</div>
        <div className={`text-sm font-semibold mt-0.5 truncate max-w-[140px] ${homeWon ? 'text-zinc-200' : 'text-zinc-500'}`}>{homeName}</div>
      </div>
    </div>
  )
}

// ── tabs ──
function TabBar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  const tabs: { key: Tab; label: string }[] = [
    { key: 'boxscore', label: 'Box Score' },
    { key: 'playbyplay', label: 'Play-by-Play' },
    { key: 'info', label: 'Game Info' },
  ]
  return (
    <div className="flex gap-0 overflow-x-auto border-b border-zinc-800 -mx-4 px-4">
      {tabs.map(t => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={`px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors ${
            active === t.key
              ? 'text-white'
              : 'text-zinc-500 hover:text-zinc-300'
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

// ── NBA box score (team stats, two-column) ──
function NBABoxScore({ stats }: { stats: TeamStat[] }) {
  const away = stats.find(s => s.home_away === 'away')
  const home = stats.find(s => s.home_away === 'home')
  if (!home || !away) return null
  const rows: [string, keyof TeamStat, keyof TeamStat, boolean?][] = [
    ['Field Goals', 'fgm_fga', 'fgm_fga'],
    ['Field Goal %', 'fg_pct', 'fg_pct', true],
    ['3-Pointers', 'tpm_tpa', 'tpm_tpa'],
    ['3-Point %', 'tp_pct', 'tp_pct', true],
    ['Free Throws', 'ftm_fta', 'ftm_fta'],
    ['Free Throw %', 'ft_pct', 'ft_pct', true],
    ['Rebounds', 'rebounds', 'rebounds'],
    ['Offensive Rebounds', 'off_rebounds', 'off_rebounds'],
    ['Assists', 'assists', 'assists'],
    ['Steals', 'steals', 'steals'],
    ['Blocks', 'blocks', 'blocks'],
    ['Turnovers', 'turnovers', 'turnovers'],
    ['Fouls', 'fouls', 'fouls'],
    ['Fast Break Pts', 'fast_break_pts', 'fast_break_pts'],
    ['Points in Paint', 'pts_in_paint', 'pts_in_paint'],
    ['Largest Lead', 'largest_lead', 'largest_lead'],
  ]
  return (
    <div>
      {/* Column headers */}
      <div className="grid grid-cols-[1fr_100px_100px] gap-3 text-xs text-zinc-500 font-bold pb-2 border-b border-zinc-700 mb-1">
        <span></span>
        <span className="text-right">{away.team_abbrev}</span>
        <span className="text-right">{home.team_abbrev}</span>
      </div>
      {rows.map(([label, aKey, hKey, pct]) => {
        const av = away[aKey]; const hv = home[hKey]
        if (av === undefined && hv === undefined) return null
        if (av === null && hv === null) return null
        return (
          <div key={label} className="grid grid-cols-[1fr_100px_100px] gap-3 text-sm py-1.5 border-b border-zinc-800/40 last:border-0">
            <span className="text-zinc-400">{label}</span>
            <span className="text-right font-mono text-zinc-200">
              {pct && typeof av === 'number' ? av.toFixed(1) : fmt(av)}
            </span>
            <span className="text-right font-mono text-zinc-200">
              {pct && typeof hv === 'number' ? hv.toFixed(1) : fmt(hv)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function NHLBoxScore({ stats }: { stats: TeamStat[] }) {
  const away = stats.find(s => s.home_away === 'away')
  const home = stats.find(s => s.home_away === 'home')
  if (!home || !away) return null
  const rows: [string, keyof TeamStat, keyof TeamStat, boolean?][] = [
    ['Shots', 'shots', 'shots'],
    ['Blocked Shots', 'blocked_shots', 'blocked_shots'],
    ['Hits', 'hits', 'hits'],
    ['Faceoffs Won', 'faceoffs_won', 'faceoffs_won'],
    ['Faceoff %', 'faceoff_pct', 'faceoff_pct', true],
    ['Takeaways', 'takeaways', 'takeaways'],
    ['Giveaways', 'giveaways', 'giveaways'],
    ['Power Play Goals', 'powerplay_goals', 'powerplay_goals'],
    ['Power Play Opps', 'powerplay_opps', 'powerplay_opps'],
    ['Penalties', 'penalties', 'penalties'],
    ['Penalty Minutes', 'penalty_min', 'penalty_min'],
  ]
  return (
    <div>
      <div className="grid grid-cols-[1fr_100px_100px] gap-3 text-xs text-zinc-500 font-bold pb-2 border-b border-zinc-700 mb-1">
        <span></span>
        <span className="text-right">{away.team_abbrev}</span>
        <span className="text-right">{home.team_abbrev}</span>
      </div>
      {rows.map(([label, aKey, hKey, pct]) => {
        const av = away[aKey]; const hv = home[hKey]
        if (av === undefined && hv === undefined) return null
        if (av === null && hv === null) return null
        return (
          <div key={label} className="grid grid-cols-[1fr_100px_100px] gap-3 text-sm py-1.5 border-b border-zinc-800/40 last:border-0">
            <span className="text-zinc-400">{label}</span>
            <span className="text-right font-mono text-zinc-200">
              {pct && typeof av === 'number' ? av.toFixed(1) : fmt(av)}
            </span>
            <span className="text-right font-mono text-zinc-200">
              {pct && typeof hv === 'number' ? hv.toFixed(1) : fmt(hv)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ── play-by-play tab ──
function PlayByPlay({ allPlays, homeTeam, awayTeam }: {
  allPlays: ScoringPlay[]; homeTeam: string; awayTeam: string
}) {
  const [showAll, setShowAll] = useState(false)
  const scoringOnly = allPlays.filter(p => {
    const t = p.play_text?.toLowerCase() || ''
    return t.includes('made') || t.includes('goal') || t.includes('free throw')
  })
  const plays = showAll ? allPlays : scoringOnly

  const byQuarter: Record<number, ScoringPlay[]> = {}
  for (const p of plays) {
    if (!byQuarter[p.period]) byQuarter[p.period] = []
    byQuarter[p.period].push(p)
  }

  return (
    <div>
      {/* Toggle */}
      <div className="flex items-center justify-end gap-2 mb-4">
        <button
          onClick={() => setShowAll(false)}
          className={`px-3 py-1 rounded text-xs font-medium transition ${
            !showAll ? 'bg-white text-black' : 'text-zinc-400 hover:text-zinc-200'
          }`}
        >
          Scoring ({scoringOnly.length})
        </button>
        <button
          onClick={() => setShowAll(true)}
          className={`px-3 py-1 rounded text-xs font-medium transition ${
            showAll ? 'bg-white text-black' : 'text-zinc-400 hover:text-zinc-200'
          }`}
        >
          All ({allPlays.length})
        </button>
      </div>

      {/* Timeline */}
      <div className="max-h-[500px] overflow-y-auto">
        {Object.entries(byQuarter).map(([q, pplays]) => (
          <div key={q} className="mb-4">
            <div className="text-xs font-bold text-zinc-500 mb-2 sticky top-0 bg-zinc-900/90 py-1 backdrop-blur z-10">
              {pplays[0]?.period_disp || `Q${q}`}
            </div>
            {pplays.map((p, i) => {
              const isHome = p.team_abbrev === homeTeam
              const icon = isHome ? '◆' : '◆'
              return (
                <div key={i} className="flex items-start gap-2 py-1.5 border-b border-zinc-800/30 text-sm">
                  <span className="text-zinc-600 font-mono w-10 shrink-0 text-xs pt-0.5">{p.clock}</span>
                  <span className={`shrink-0 pt-0.5 text-[10px] ${isHome ? 'text-blue-400' : 'text-red-400'}`}>
                    {icon}
                  </span>
                  <span className="text-zinc-300 flex-1 leading-snug">{p.play_text}</span>
                  <span className="text-zinc-600 font-mono shrink-0 text-xs pt-0.5 tabular-nums">
                    {p.away_score}-{p.home_score}
                  </span>
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── game info tab ──
function GameInfo({ ctx, homeStrength, awayStrength }: {
  ctx: GameContext | null; homeStrength?: StrengthRow; awayStrength?: StrengthRow
}) {
  return (
    <div className="space-y-5">
      {ctx && (
        <div className="space-y-3">
          <div className="flex justify-between text-sm">
            <span className="text-zinc-500">Venue</span>
            <span className="text-zinc-200">{ctx.venue_name}{ctx.venue_city ? `, ${ctx.venue_city}` : ''}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-zinc-500">Attendance</span>
            <span className="text-zinc-200">{ctx.attendance?.toLocaleString() || '-'}</span>
          </div>
          {ctx.officials.length > 0 && (
            <div className="flex justify-between text-sm">
              <span className="text-zinc-500">Officials</span>
              <span className="text-zinc-200 text-right">{ctx.officials.join(', ')}</span>
            </div>
          )}
        </div>
      )}

      {/* Season records */}
      <div>
        <div className="text-xs text-zinc-500 font-bold uppercase tracking-wide mb-3">Season Records</div>
        <div className="grid grid-cols-2 gap-4">
          {[awayStrength, homeStrength].map((s, i) => s ? (
            <div key={i} className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
              <div className="text-[10px] text-zinc-600 uppercase tracking-widest mb-1">{i === 0 ? 'Away' : 'Home'}</div>
              <div className="font-bold text-sm">{s.name} ({s.abbrev})</div>
              <div className="text-sm text-zinc-400 mt-1">{s.wins}-{s.losses}</div>
              <div className="text-xs text-zinc-500 mt-0.5">Win%: {(s.win_pct * 100).toFixed(1)}% · Streak: {s.streak}</div>
            </div>
          ) : null)}
        </div>
      </div>
    </div>
  )
}

// ── page ──
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

  const finalScore = useMemo(() => {
    // Use the backend's authoritative reconciled final score (ESPN summary),
    // never derive from scoring_plays which may be incomplete.
    return detail?.final_score ?? null
  }, [detail])

  // No page-level wrapper here: Layout already provides bg-ink-900 + the max-w-6xl main + padding.
  // Skeletons use bg-zinc-800 so they're visible against the ink-900 page (zinc-900 would be invisible on the cards).
  if (loading) return <div className="max-w-4xl mx-auto animate-pulse space-y-3"><div className="h-28 bg-zinc-800 rounded-2xl"/><div className="h-64 bg-zinc-800 rounded-xl"/></div>
  if (!detail) return <div className="max-w-4xl mx-auto text-center py-16"><p className="text-zinc-500">Game data not available.</p><button onClick={() => router.back()} className="mt-4 text-blue-400 hover:underline text-sm">← Back</button></div>

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
          ctx={ctx} final={finalScore}
          homeName={sHome?.name || ctx?.home_team || ''}
          awayName={sAway?.name || ctx?.away_team || ''}
          homeRecord={homeRecord} awayRecord={awayRecord}
        />

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
