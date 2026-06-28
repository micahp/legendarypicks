import { useState, useEffect } from 'react'
import Head from 'next/head'
import { SportsService } from '../services/sports'

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

type SubView = 'players' | 'teams'

const LEAGUES = ['MLB', 'NBA', 'NHL', 'NFL', 'WC', 'UFC'] as const
type League = typeof LEAGUES[number]

// Columns to display per league (subset of what the backend returns)
const LEAGUE_COLS: Record<string, string[]> = {
  nba: ['pts', 'reb', 'ast', 'fg3m', 'stl', 'blk', 'minutes'],
  nfl: ['pass_yds_g', 'pass_td', 'rush_yds_g', 'rec_yds_g', 'receptions', 'fantasy_pts_g', 'fantasy_ppr_g'],
  nhl: ['goals', 'assists', 'points_nhl', 'shots', 'plus_minus', 'ppg', 'ppp'],
  mlb_batting: ['avg', 'hr', 'k_pct', 'bb_pct', 'woba', 'xwoba'],
  mlb_pitching: ['k_pct', 'whiff_pct', 'xwoba_against', 'exit_velo_against'],
}

function statLabel(k: string): string {
  return k.replace(/_g$/, '/G').replace(/_pct$/, '%').replace(/_nhl$/, '').replace(/_/g, ' ').toUpperCase()
}

// ── Stat prefix helper: round to 3 decimal places for AVG, 1 otherwise
function fmtStat(k: string, v: number | null | undefined): string {
  if (v == null) return '—'
  if (k === 'avg' || k === 'woba' || k === 'xwoba' || k === 'xwoba_against' || k === 'shooting_pct')
    return v.toFixed(3)
  return v.toFixed(1)
}

// Weight class → lbs for UFC division cards
const WEIGHT_CLASS_LBS: Record<string, number> = {
  Flyweight: 125, Bantamweight: 135, Featherweight: 145,
  Lightweight: 155, Welterweight: 170, Middleweight: 185,
  'Light Heavyweight': 205, Heavyweight: 265,
  "Women's Strawweight": 115, "Women's Flyweight": 125, "Women's Bantamweight": 135,
}

// ── Page ────────────────────────────────────────────────────
export default function StatsPage() {
  const [league, setLeague] = useState<League>('NBA')
  const [subView, setSubView] = useState<SubView>('players')

  // Teams state
  const [teams, setTeams] = useState<TeamStats[]>([])
  const [groups, setGroups] = useState<StandingGroup[]>([])
  const [teamLoading, setTeamLoading] = useState(false)
  const [teamError, setTeamError] = useState<string | null>(null)

  // Players state
  const [leadersData, setLeadersData] = useState<LeadersData | null>(null)
  const [playerLoading, setPlayerLoading] = useState(false)
  const [playerError, setPlayerError] = useState<string | null>(null)
  const [mlbType, setMlbType] = useState<'batting' | 'pitching'>('batting')

  // UFC state
  const [ufcRankings, setUfcRankings] = useState<UFCRankings | null>(null)
  const [ufcLoading, setUfcLoading] = useState(false)
  const [ufcError, setUfcError] = useState<string | null>(null)

  // ── Load teams ──────────────────────────────────────────
  useEffect(() => {
    let ignore = false
    const load = async () => {
      setTeamLoading(true); setTeamError(null)
      try {
        if (league === 'WC') {
          const res = await fetch('/api/wc/standings')
          const data = await res.json()
          if (!ignore) setGroups(Array.isArray(data) ? data : [])
        } else {
          const data = await SportsService.getStrength(league.toLowerCase())
          if (!ignore) setTeams(Array.isArray(data) ? data : [])
        }
      } catch {
        if (!ignore) setTeamError('Unable to load team stats.')
      } finally {
        if (!ignore) setTeamLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [league])

  // ── Load players ─────────────────────────────────────────
  useEffect(() => {
    if (league === 'WC' || league === 'UFC') return  // no player stats for WC or UFC
    let ignore = false
    const load = async () => {
      setPlayerLoading(true); setPlayerError(null)
      try {
        const lg = league.toLowerCase()
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
  }, [league, mlbType])

  // ── Load UFC rankings ───────────────────────────────────
  useEffect(() => {
    if (league !== 'UFC') return
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
  }, [league])

  // ── Derived column list ─────────────────────────────────
  const lg = league.toLowerCase()
  const colKey = lg === 'mlb' ? `mlb_${mlbType}` : lg
  const cols = LEAGUE_COLS[colKey] || []

  return (
    <>
      <Head>
        <title>Stats — Legendary Picks</title>
      </Head>

      <div className="space-y-4">
        {/* Page header */}
        <h1 className="text-3xl font-extrabold tracking-tight">Stats</h1>

        {/* League selector */}
        <div className="flex items-center gap-2 flex-wrap">
          {LEAGUES.map((l) => (
            <button
              key={l}
              onClick={() => { setLeague(l); if (l === 'WC') setSubView('teams') }}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                league === l
                  ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                  : 'bg-zinc-900 text-zinc-400 border border-zinc-800 hover:text-zinc-200'
              }`}
            >
              {l}
            </button>
          ))}
        </div>

        {/* Sub-view toggle (Players | Teams) — hidden for WC and UFC */}
        {league !== 'WC' && league !== 'UFC' && (
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
        )}

        {/* MLB batting/pitching toggle (Players sub-view only) */}
        {league === 'MLB' && subView === 'players' && (
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

        {/* ── UFC Rankings view ──────────────────────────── */}
        {league === 'UFC' && (
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
                {/* ── Pound-for-Pound — the crown ────────── */}
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
                              f.champion
                                ? 'bg-emerald-500/5'
                                : ''
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
                              f.champion
                                ? 'bg-emerald-500/5'
                                : ''
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

                {/* ── Weight Divisions — weight class as hero ── */}
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
                        {/* Weight class hero */}
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

                        {/* Champion row */}
                        {div.champion && (
                          <div className="mx-4 mt-2 mb-1 flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-500/5 border border-emerald-500/10">
                            <span className="text-emerald-400 text-xs">◆</span>
                            <span className="text-sm text-emerald-300 font-semibold">
                              {div.champion}
                            </span>
                          </div>
                        )}

                        {/* Ranked contenders */}
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

        {/* ── Players sub-view ──────────────────────────── */}
        {subView === 'players' && league !== 'WC' && league !== 'UFC' && (
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
                No player data for {league}.
              </div>
            ) : (
              <div className="space-y-3">
                {/* Season + sort info */}
                <div className="flex items-center gap-3 text-xs text-zinc-500">
                  <span>Season {leadersData.season}</span>
                  <span>·</span>
                  <span>Sorted by {statLabel(leadersData.stat)}</span>
                </div>

                {/* Leaderboard table */}
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

        {/* ── Teams sub-view ─────────────────────────────── */}
        {subView === 'teams' && league !== 'UFC' && (
          <>
            {teamError && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 text-red-400 text-sm">
                {teamError}
              </div>
            )}

            {teamLoading ? (
              <div className="text-zinc-500 text-sm py-8 text-center">Loading...</div>
            ) : league === 'WC' ? (
              groups.length === 0 ? (
                <div className="text-zinc-500 text-sm">No standings available.</div>
              ) : (
                <div className="space-y-8">
                  {groups.map(g => (
                    <div key={g.group}>
                      <h2 className="text-lg font-bold text-white mb-3">{g.group}</h2>
                      <div className="overflow-x-auto rounded-xl border border-zinc-800">
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
                              <tr key={r.abbrev} className="border-b border-zinc-800/50 hover:bg-zinc-900/50">
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
              <div className="text-zinc-500 text-sm">No data available for {league}.</div>
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
                        <td className="py-3 px-3 text-right text-zinc-200">
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
                        <td className="py-3 pl-3 pr-4 text-right text-zinc-400">{t.last10}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </>
  )
}
