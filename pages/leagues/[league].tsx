import { useState, useEffect } from 'react'
import Head from 'next/head'
import { useRouter } from 'next/router'
import { SportsService, Game } from '../../services/sports'
import GameCard from '../../components/Scores/GameCard'

// ── Types ───────────────────────────────────────────────────
interface TeamStats {
  abbrev: string; name: string
  wins: number; losses: number; win_pct: number
  differential: number; streak: string; last10: string
  games_played: number
}

interface StandingRow {
  rank: number; abbrev: string; name: string
  played: number; wins: number; draws: number; losses: number
  gf: number; ga: number; gd: number; points: number
}
interface StandingGroup { group: string; rows: StandingRow[] }

interface Leader {
  player_id: number; name: string; team: string; games: number
  [stat: string]: number | string | null
}

interface LeadersData {
  league: string; season: number | string
  stat: string; stat_type: string | null
  leaders: Leader[]
}

// UFC types
interface UFCRanked { rank: number; fighter: string; champion?: boolean }
interface UFCDivision { division: string; champion: string; ranked: UFCRanked[] }
interface UFCRankings {
  pound_for_pound: { men: UFCRanked[]; women: UFCRanked[] }
  divisions: UFCDivision[]
}

// WC knockout types
interface KnockoutTeam { abbrev: string; name: string }
interface KnockoutMatch {
  home: KnockoutTeam; away: KnockoutTeam
  homeScore: number | null; awayScore: number | null
  winner: string | null; status: string; state: string
}
interface KnockoutRound { round: string; matches: KnockoutMatch[] }

type SubView = 'players' | 'teams'

// Columns to display per league (subset of what the backend returns)
const LEAGUE_COLS: Record<string, string[]> = {
  nba: ['pts', 'reb', 'ast', 'fg3m', 'stl', 'blk', 'minutes'],
  nfl: ['pass_yds_g', 'pass_td', 'rush_yds_g', 'rec_yds_g', 'receptions', 'fantasy_pts_g', 'fantasy_ppr_g'],
  nhl: ['goals', 'assists', 'points_nhl', 'shots', 'plus_minus', 'ppg', 'ppp'],
  mlb_batting: ['avg', 'hr', 'k_pct', 'bb_pct', 'woba', 'xwoba'],
  mlb_pitching: ['k_pct', 'whiff_pct', 'xwoba_against', 'exit_velo_against'],
}

const LEAGUE_NAMES: Record<string, string> = {
  mlb: 'MLB', nba: 'NBA', nhl: 'NHL', nfl: 'NFL', wc: 'World Cup', ufc: 'UFC',
}

const LEAGUE_EMOJIS: Record<string, string> = {
  mlb: '⚾', nba: '🏀', nhl: '🏒', nfl: '🏈', wc: '⚽', ufc: '🥊',
}

// Weight class → lbs for UFC division cards
const WEIGHT_CLASS_LBS: Record<string, number> = {
  Flyweight: 125, Bantamweight: 135, Featherweight: 145,
  Lightweight: 155, Welterweight: 170, Middleweight: 185,
  'Light Heavyweight': 205, Heavyweight: 265,
  "Women's Strawweight": 115, "Women's Flyweight": 125, "Women's Bantamweight": 135,
}

function statLabel(k: string): string {
  return k.replace(/_g$/, '/G').replace(/_pct$/, '%').replace(/_nhl$/, '').replace(/_/g, ' ').toUpperCase()
}

function fmtStat(k: string, v: number | null | undefined): string {
  if (v == null) return '—'
  if (k === 'avg' || k === 'woba' || k === 'xwoba' || k === 'xwoba_against' || k === 'shooting_pct')
    return v.toFixed(3)
  return v.toFixed(1)
}

type HubTab = 'standings' | 'stats' | 'schedule' | 'rankings'

const TAB_LABELS: Record<HubTab, string> = {
  standings: 'Standings',
  stats: 'Stats',
  schedule: 'Schedule',
  rankings: 'Rankings',
}

export default function LeagueHubPage() {
  const router = useRouter()
  const { league } = router.query
  const lg = (typeof league === 'string' ? league : '').toLowerCase()

  const leagueName = LEAGUE_NAMES[lg] || lg.toUpperCase()
  const leagueEmoji = LEAGUE_EMOJIS[lg] || ''

  // Determine valid tabs for this league
  const isWC = lg === 'wc'
  const isUFC = lg === 'ufc'

  const validTabs: HubTab[] = ['standings', 'stats', 'schedule']
  if (isUFC) validTabs.push('rankings')
  // WC has no player stats
  if (isWC) validTabs.splice(validTabs.indexOf('stats'), 1)
  // UFC has no team standings in the traditional sense
  if (isUFC) validTabs.splice(validTabs.indexOf('standings'), 1)

  const [activeTab, setActiveTab] = useState<HubTab>(validTabs[0] || 'standings')

  // ── Standings state ─────────────────────────────────────
  const [teams, setTeams] = useState<TeamStats[]>([])
  const [groups, setGroups] = useState<StandingGroup[]>([])
  const [knockout, setKnockout] = useState<KnockoutRound[]>([])
  const [standingsLoading, setStandingsLoading] = useState(false)
  const [standingsError, setStandingsError] = useState<string | null>(null)

  // ── Stats (leaders) state ────────────────────────────────
  const [subView, setSubView] = useState<SubView>('players')
  const [leadersData, setLeadersData] = useState<LeadersData | null>(null)
  const [playerLoading, setPlayerLoading] = useState(false)
  const [playerError, setPlayerError] = useState<string | null>(null)
  const [mlbType, setMlbType] = useState<'batting' | 'pitching'>('batting')

  // ── Schedule state ──────────────────────────────────────
  const [games, setGames] = useState<Game[]>([])
  const [scheduleLoading, setScheduleLoading] = useState(false)
  const [scheduleError, setScheduleError] = useState<string | null>(null)

  // ── UFC rankings state ──────────────────────────────────
  const [ufcRankings, setUfcRankings] = useState<UFCRankings | null>(null)
  const [ufcLoading, setUfcLoading] = useState(false)
  const [ufcError, setUfcError] = useState<string | null>(null)

  // ── Load standings ──────────────────────────────────────
  useEffect(() => {
    if (!lg) return
    if (isUFC) return // UFC uses rankings tab, not standings
    let ignore = false
    const load = async () => {
      setStandingsLoading(true); setStandingsError(null)
      try {
        if (isWC) {
          // Try knockout endpoint first; fall back to group standings
          const kres = await fetch('/api/wc/knockout')
          const kdata = await kres.json()
          if (!ignore) {
            if (Array.isArray(kdata) && kdata.length > 0 && kdata.some((r: any) => r.matches?.length > 0)) {
              setKnockout(kdata)
            } else {
              // Fall back to group standings
              const gres = await fetch('/api/wc/standings')
              const gdata = await gres.json()
              if (!ignore) setGroups(Array.isArray(gdata) ? gdata : [])
            }
          }
        } else {
          const data = await SportsService.getStrength(lg)
          if (!ignore) setTeams(Array.isArray(data) ? data : [])
        }
      } catch {
        if (!ignore) setStandingsError('Unable to load standings.')
      } finally {
        if (!ignore) setStandingsLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [lg, isWC, isUFC])

  // ── Load players ─────────────────────────────────────────
  useEffect(() => {
    if (!lg) return
    if (isWC || isUFC) return
    let ignore = false
    const load = async () => {
      setPlayerLoading(true); setPlayerError(null)
      try {
        let url = `/api/${lg}/leaders?limit=25`
        if (lg === 'mlb') url += `&type=${mlbType}`
        const res = await fetch(url)
        if (!res.ok) throw new Error(`${res.status}`)
        const data: LeadersData = await res.json()
        if (!ignore) setLeadersData(data)
      } catch (e: any) {
        if (!ignore) setPlayerError(e.message || 'Unable to load player stats.')
      } finally {
        if (!ignore) setPlayerLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [lg, mlbType, isWC, isUFC])

  // ── Load schedule ───────────────────────────────────────
  useEffect(() => {
    if (!lg) return
    let ignore = false
    const load = async () => {
      setScheduleLoading(true); setScheduleError(null)
      try {
        const data = await SportsService.getGames(lg)
        if (!ignore) setGames(data)
      } catch {
        if (!ignore) setScheduleError('Unable to load schedule.')
      } finally {
        if (!ignore) setScheduleLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [lg])

  // ── Load UFC rankings ───────────────────────────────────
  useEffect(() => {
    if (!isUFC || !lg) return
    let ignore = false
    const load = async () => {
      setUfcLoading(true); setUfcError(null)
      try {
        const res = await fetch('/api/ufc/rankings')
        if (!res.ok) throw new Error(`${res.status}`)
        const data: UFCRankings = await res.json()
        if (!ignore) setUfcRankings(data)
      } catch (e: any) {
        if (!ignore) setUfcError(e.message || 'Unable to load UFC rankings.')
      } finally {
        if (!ignore) setUfcLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [isUFC, lg])

  // ── Derived column list ─────────────────────────────────
  const colKey = lg === 'mlb' ? `mlb_${mlbType}` : lg
  const cols = LEAGUE_COLS[colKey] || []

  // ── Loading (no league yet) ─────────────────────────────
  if (!lg) {
    return (
      <div className="space-y-3 animate-pulse">
        <div className="h-8 bg-zinc-800 rounded w-48" />
        <div className="h-10 bg-zinc-800 rounded" />
      </div>
    )
  }

  return (
    <>
      <Head>
        <title>{leagueName} — Legendary Picks</title>
      </Head>

      <div className="space-y-4">
        {/* League header */}
        <div className="flex items-center gap-3">
          <span className="text-2xl">{leagueEmoji}</span>
          <h1 className="text-3xl font-extrabold tracking-tight">{leagueName}</h1>
        </div>

        {/* Tab bar */}
        <div className="flex gap-0 overflow-x-auto border-b border-zinc-800 -mx-4 px-4">
          {validTabs.map(t => (
            <button
              key={t}
              onClick={() => setActiveTab(t)}
              className={`px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px ${
                activeTab === t
                  ? 'border-emerald-500 text-white'
                  : 'border-transparent text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {TAB_LABELS[t]}
            </button>
          ))}
        </div>

        {/* ── Standings tab ──────────────────────────────── */}
        {activeTab === 'standings' && (
          <>
            {standingsError && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 text-red-400 text-sm">
                {standingsError}
              </div>
            )}

            {standingsLoading ? (
              <div className="text-zinc-500 text-sm py-8 text-center">Loading standings...</div>
            ) : isWC ? (
              // ── WC: knockout bracket or group tables ──
              knockout.length > 0 ? (
                <div className="space-y-8">
                  {knockout.map(round => (
                    <div key={round.round}>
                      <div className="flex items-center gap-3 mb-3">
                        <span className="text-[10px] text-emerald-500/60 bg-emerald-500/10 px-2 py-0.5 rounded font-bold uppercase tracking-widest">
                          {round.round}
                        </span>
                      </div>
                      <div className="space-y-2">
                        {round.matches.map((m, i) => {
                          const isFinal = m.state === 'post'
                          const homeWon = isFinal && m.winner === m.home.abbrev
                          const awayWon = isFinal && m.winner === m.away.abbrev
                          return (
                            <div key={i} className="bg-zinc-900 border border-zinc-800 rounded-lg px-4 py-3 flex items-center justify-between gap-3">
                              <div className="flex-1 min-w-0">
                                <span className={`font-semibold text-sm ${isFinal ? (homeWon ? 'text-white' : 'text-zinc-500') : 'text-zinc-200'}`}>
                                  {m.home.name || m.home.abbrev}
                                </span>
                              </div>
                              <div className="flex items-center gap-2 shrink-0">
                                {isFinal ? (
                                  <span className="font-mono tabular-nums text-lg font-bold text-zinc-100">
                                    {m.homeScore ?? '—'} – {m.awayScore ?? '—'}
                                  </span>
                                ) : (
                                  <span className="text-xs text-zinc-500">{m.status || 'Upcoming'}</span>
                                )}
                              </div>
                              <div className="flex-1 min-w-0 text-right">
                                <span className={`font-semibold text-sm ${isFinal ? (awayWon ? 'text-white' : 'text-zinc-500') : 'text-zinc-200'}`}>
                                  {m.away.name || m.away.abbrev}
                                </span>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              ) : groups.length === 0 ? (
                <div className="text-zinc-500 text-sm">No standings available.</div>
              ) : (
                // ── WC group tables ──
                <div className="space-y-8">
                  {groups.map(g => (
                    <div key={g.group}>
                      <h2 className="text-lg font-bold text-white mb-3">{g.group}</h2>
                      <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="border-b border-zinc-800 text-zinc-400 text-xs uppercase tracking-wider">
                              <th className="text-left py-3 px-3">#</th>
                              <th className="text-left py-3 px-3">Team</th>
                              <th className="text-center py-3 px-2">P</th><th className="text-center py-3 px-2">W</th>
                              <th className="text-center py-3 px-2">D</th><th className="text-center py-3 px-2">L</th>
                              <th className="text-center py-3 px-2">GF</th><th className="text-center py-3 px-2">GA</th>
                              <th className="text-center py-3 px-2">GD</th><th className="text-center py-3 px-2 font-bold">Pts</th>
                            </tr>
                          </thead>
                          <tbody>
                            {g.rows.map(r => (
                              <tr key={r.abbrev} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                                <td className="py-3 px-3 text-zinc-500">{r.rank}</td>
                                <td className="py-3 px-3">
                                  <span className="font-semibold text-zinc-200">{r.abbrev}</span>
                                  <span className="text-zinc-500 ml-2">{r.name}</span>
                                </td>
                                <td className="py-3 px-2 text-center text-zinc-300">{r.played}</td>
                                <td className="py-3 px-2 text-center text-zinc-300">{r.wins}</td>
                                <td className="py-3 px-2 text-center text-zinc-300">{r.draws}</td>
                                <td className="py-3 px-2 text-center text-zinc-300">{r.losses}</td>
                                <td className="py-3 px-2 text-center text-zinc-300">{r.gf}</td>
                                <td className="py-3 px-2 text-center text-zinc-300">{r.ga}</td>
                                <td className="py-3 px-2 text-center">
                                  <span className={r.gd > 0 ? 'text-emerald-400' : r.gd < 0 ? 'text-red-400' : 'text-zinc-400'}>
                                    {r.gd > 0 ? '+' : ''}{r.gd}
                                  </span>
                                </td>
                                <td className="py-3 px-2 text-center font-bold text-white">{r.points}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ))}
                </div>
              )
            ) : teams.length === 0 ? (
              <div className="text-zinc-500 text-sm">No data available for {leagueName}.</div>
            ) : (
              // ── US team sports standings ──
              <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-zinc-800 text-zinc-400 text-xs uppercase tracking-wider">
                      <th className="text-left py-3 pr-4 pl-4">#</th>
                      <th className="text-left py-3 pr-4">Team</th>
                      <th className="text-right py-3 px-3">W</th>
                      <th className="text-right py-3 px-3">L</th>
                      <th className="text-right py-3 px-3">Win%</th>
                      <th className="text-right py-3 px-3">Diff</th>
                      <th className="text-right py-3 px-3">Streak</th>
                      <th className="text-right py-3 pl-3 pr-4">L10</th>
                    </tr>
                  </thead>
                  <tbody>
                    {teams.map((t, i) => (
                      <tr key={t.abbrev} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                        <td className="py-3 pr-4 pl-4 text-zinc-500">{i + 1}</td>
                        <td className="py-3 pr-4">
                          <span className="font-semibold text-zinc-200">{t.abbrev}</span>
                          <span className="text-zinc-500 ml-2">{t.name}</span>
                        </td>
                        <td className="py-3 px-3 text-right text-zinc-200">{t.wins}</td>
                        <td className="py-3 px-3 text-right text-zinc-200">{t.losses}</td>
                        <td className="py-3 px-3 text-right text-zinc-200 font-mono tabular-nums">
                          {(t.win_pct * 100).toFixed(1)}%
                        </td>
                        <td className="py-3 px-3 text-right">
                          <span className={t.differential > 0 ? 'text-emerald-400' : t.differential < 0 ? 'text-red-400' : 'text-zinc-400'}>
                            {t.differential > 0 ? '+' : ''}{t.differential}
                          </span>
                        </td>
                        <td className="py-3 px-3 text-right">
                          <span className={t.streak?.startsWith('W') ? 'text-emerald-400' : 'text-red-400'}>
                            {t.streak}
                          </span>
                        </td>
                        <td className="py-3 pl-3 pr-4 text-right text-zinc-400 font-mono tabular-nums">{t.last10}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        {/* ── Stats tab ──────────────────────────────────── */}
        {activeTab === 'stats' && (
          <>
            {/* Sub-view toggle (Players | Teams) */}
            <div className="flex gap-0 border-b border-zinc-800 -mx-4 px-4">
              {(['players', 'teams'] as SubView[]).map(v => (
                <button key={v} onClick={() => setSubView(v)}
                  className={`px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px capitalize ${
                    subView === v ? 'border-emerald-500 text-white' : 'border-transparent text-zinc-500 hover:text-zinc-300'
                  }`}
                >
                  {v}
                </button>
              ))}
            </div>

            {/* MLB batting/pitching toggle (Players sub-view only) */}
            {lg === 'mlb' && subView === 'players' && (
              <div className="flex items-center gap-2">
                {(['batting', 'pitching'] as const).map(t => (
                  <button key={t} onClick={() => setMlbType(t)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors capitalize ${
                      mlbType === t
                        ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                        : 'bg-zinc-900 text-zinc-500 border border-zinc-800 hover:text-zinc-300'
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            )}

            {/* Players sub-view */}
            {subView === 'players' && (
              <>
                {playerError && (
                  <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 text-red-400 text-sm">
                    {playerError}
                  </div>
                )}

                {playerLoading ? (
                  <div className="text-zinc-500 text-sm py-8 text-center">Loading players...</div>
                ) : !leadersData?.leaders?.length ? (
                  <div className="text-center py-12 text-zinc-500 text-sm">
                    No player data for {leagueName}.
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="flex items-center gap-3 text-xs text-zinc-500">
                      <span>Season {leadersData.season}</span>
                      <span>·</span>
                      <span>Sorted by {statLabel(leadersData.stat)}</span>
                    </div>

                    <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-zinc-800 text-zinc-500 text-[11px] uppercase tracking-wider">
                            <th className="text-left px-4 py-3 font-medium w-10">#</th>
                            <th className="text-left px-3 py-3 font-medium">Player</th>
                            <th className="text-right px-3 py-3 font-medium">GP</th>
                            {cols.map(c => (
                              <th key={c} className="text-right px-3 py-3 font-medium">{statLabel(c)}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {leadersData.leaders.map((l, i) => (
                            <tr key={l.player_id} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                              <td className="px-4 py-2.5 text-zinc-500 text-xs">{i + 1}</td>
                              <td className="px-3 py-2.5">
                                <a href={`/player/${l.player_id}`} className="font-medium text-zinc-200 hover:text-emerald-400 transition-colors">
                                  {l.name}
                                </a>
                                {l.team && <span className="text-zinc-500 ml-1.5 text-xs">{l.team}</span>}
                              </td>
                              <td className="px-3 py-2.5 text-right font-mono tabular-nums text-zinc-400">{l.games}</td>
                              {cols.map(c => (
                                <td key={c} className={`px-3 py-2.5 text-right font-mono tabular-nums ${
                                  c === leadersData.stat ? 'text-emerald-300 font-bold' : 'text-zinc-300'
                                }`}>
                                  {fmtStat(c, l[c] as number)}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            )}

            {/* Teams sub-view — reuse standings table exactly */}
            {subView === 'teams' && (
              <>
                {standingsLoading ? (
                  <div className="text-zinc-500 text-sm py-8 text-center">Loading...</div>
                ) : teams.length === 0 ? (
                  <div className="text-zinc-500 text-sm">No data available for {leagueName}.</div>
                ) : (
                  <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-zinc-800 text-zinc-400 text-xs uppercase tracking-wider">
                          <th className="text-left py-3 pr-4 pl-4">#</th>
                          <th className="text-left py-3 pr-4">Team</th>
                          <th className="text-right py-3 px-3">W</th>
                          <th className="text-right py-3 px-3">L</th>
                          <th className="text-right py-3 px-3">Win%</th>
                          <th className="text-right py-3 px-3">Diff</th>
                          <th className="text-right py-3 px-3">Streak</th>
                          <th className="text-right py-3 pl-3 pr-4">L10</th>
                        </tr>
                      </thead>
                      <tbody>
                        {teams.map((t, i) => (
                          <tr key={t.abbrev} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                            <td className="py-3 pr-4 pl-4 text-zinc-500">{i + 1}</td>
                            <td className="py-3 pr-4">
                              <span className="font-semibold text-zinc-200">{t.abbrev}</span>
                              <span className="text-zinc-500 ml-2">{t.name}</span>
                            </td>
                            <td className="py-3 px-3 text-right text-zinc-200">{t.wins}</td>
                            <td className="py-3 px-3 text-right text-zinc-200">{t.losses}</td>
                            <td className="py-3 px-3 text-right text-zinc-200 font-mono tabular-nums">
                              {(t.win_pct * 100).toFixed(1)}%
                            </td>
                            <td className="py-3 px-3 text-right">
                              <span className={t.differential > 0 ? 'text-emerald-400' : t.differential < 0 ? 'text-red-400' : 'text-zinc-400'}>
                                {t.differential > 0 ? '+' : ''}{t.differential}
                              </span>
                            </td>
                            <td className="py-3 px-3 text-right">
                              <span className={t.streak?.startsWith('W') ? 'text-emerald-400' : 'text-red-400'}>
                                {t.streak}
                              </span>
                            </td>
                            <td className="py-3 pl-3 pr-4 text-right text-zinc-400 font-mono tabular-nums">{t.last10}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </>
        )}

        {/* ── Schedule tab ────────────────────────────────── */}
        {activeTab === 'schedule' && (
          <>
            {scheduleError && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 text-red-400 text-sm">
                {scheduleError}
              </div>
            )}

            {scheduleLoading ? (
              <div className="space-y-3 animate-pulse">
                {[...Array(4)].map((_, i) => (
                  <div key={i} className="h-24 bg-zinc-800 rounded-xl" />
                ))}
              </div>
            ) : games.length === 0 ? (
              <div className="text-center py-12 text-zinc-500 text-sm">
                No games scheduled for {leagueName}.
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {games.map(g => (
                  <GameCard key={g.gameId} {...g} />
                ))}
              </div>
            )}
          </>
        )}

        {/* ── Rankings tab (UFC only) ──────────────────────── */}
        {activeTab === 'rankings' && (
          <>
            {ufcError && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 text-red-400 text-sm">
                {ufcError}
              </div>
            )}

            {ufcLoading ? (
              <div className="space-y-4 animate-pulse">
                <div className="h-6 bg-zinc-800 rounded w-48" />
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {[...Array(4)].map((_, i) => (
                    <div key={i} className="h-48 bg-zinc-800 rounded-xl" />
                  ))}
                </div>
              </div>
            ) : !ufcRankings ? (
              <div className="text-center py-12 text-zinc-500 text-sm">
                No UFC rankings available.
              </div>
            ) : (
              <div className="space-y-8">
                {/* Pound-for-Pound */}
                <section>
                  <div className="flex items-center gap-3 mb-4">
                    <span className="text-[10px] text-emerald-500/60 bg-emerald-500/10 px-2 py-0.5 rounded font-bold uppercase tracking-widest">
                      Pound-for-Pound
                    </span>
                    <span className="text-[10px] text-zinc-600 uppercase tracking-wider">
                      The best across all weight classes
                    </span>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {/* Men's P4P */}
                    <div className="bg-zinc-900/80 border border-zinc-800/80 rounded-xl overflow-hidden">
                      <div className="px-4 py-2.5 border-b border-zinc-800/60 flex items-center gap-2">
                        <span className="text-[11px] font-semibold text-zinc-300 uppercase tracking-wider">Men's</span>
                      </div>
                      <ol className="divide-y divide-zinc-800/40">
                        {ufcRankings.pound_for_pound.men.map(f => (
                          <li key={f.rank}
                            className={`flex items-center gap-3 px-4 py-2 text-sm ${
                              f.champion ? 'bg-emerald-500/5' : ''
                            }`}
                          >
                            <span className={`w-5 text-right text-xs tabular-nums font-medium ${
                              f.champion ? 'text-emerald-400' : 'text-zinc-600'
                            }`}>
                              {f.champion ? '♛' : f.rank}
                            </span>
                            <span className={f.champion ? 'text-emerald-300 font-semibold' : 'text-zinc-300'}>
                              {f.fighter}
                            </span>
                          </li>
                        ))}
                      </ol>
                    </div>
                    {/* Women's P4P */}
                    <div className="bg-zinc-900/80 border border-zinc-800/80 rounded-xl overflow-hidden">
                      <div className="px-4 py-2.5 border-b border-zinc-800/60 flex items-center gap-2">
                        <span className="text-[11px] font-semibold text-zinc-300 uppercase tracking-wider">Women's</span>
                      </div>
                      <ol className="divide-y divide-zinc-800/40">
                        {ufcRankings.pound_for_pound.women.map(f => (
                          <li key={f.rank}
                            className={`flex items-center gap-3 px-4 py-2 text-sm ${
                              f.champion ? 'bg-emerald-500/5' : ''
                            }`}
                          >
                            <span className={`w-5 text-right text-xs tabular-nums font-medium ${
                              f.champion ? 'text-emerald-400' : 'text-zinc-600'
                            }`}>
                              {f.champion ? '♛' : f.rank}
                            </span>
                            <span className={f.champion ? 'text-emerald-300 font-semibold' : 'text-zinc-300'}>
                              {f.fighter}
                            </span>
                          </li>
                        ))}
                      </ol>
                    </div>
                  </div>
                </section>

                {/* Weight Divisions */}
                <section>
                  <div className="flex items-center gap-3 mb-4">
                    <span className="text-[10px] text-zinc-500 bg-zinc-900 px-2 py-0.5 rounded font-bold uppercase tracking-widest border border-zinc-800">
                      Divisions
                    </span>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {ufcRankings.divisions.map(div => {
                      const lbs = WEIGHT_CLASS_LBS[div.division]
                      return (
                      <div key={div.division}
                        className="bg-zinc-900/80 border border-zinc-800/80 rounded-xl overflow-hidden group"
                      >
                        <div className="px-4 pt-4 pb-1">
                          <div className="flex items-baseline gap-2">
                            <span className="text-3xl font-black text-zinc-200 tabular-nums tracking-tight">
                              {lbs}
                            </span>
                            <span className="text-xs text-zinc-600 font-medium uppercase tracking-widest">LBS</span>
                          </div>
                          <h3 className="text-[11px] font-semibold text-zinc-500 uppercase tracking-wider mt-0.5">
                            {div.division}
                          </h3>
                        </div>
                        {div.champion && (
                          <div className="mx-4 mt-2 mb-1 flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-500/5 border border-emerald-500/10">
                            <span className="text-emerald-400 text-xs">◆</span>
                            <span className="text-sm text-emerald-300 font-semibold">
                              {div.champion}
                            </span>
                          </div>
                        )}
                        <ol className="px-4 pb-3 pt-1 space-y-0.5">
                          {div.ranked.map(f => (
                            <li key={f.rank}
                              className="flex items-center gap-3 text-sm group-hover:text-zinc-300 transition-colors"
                            >
                              <span className="w-5 text-right text-[11px] tabular-nums text-zinc-600 font-medium">
                                {f.rank}
                              </span>
                              <span className="text-zinc-400">{f.fighter}</span>
                            </li>
                          ))}
                        </ol>
                      </div>
                    )})}
                  </div>
                </section>
              </div>
            )}
          </>
        )}
      </div>
    </>
  )
}
