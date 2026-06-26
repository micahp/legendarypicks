import { useState, useEffect } from 'react'
import Head from 'next/head'
import { SportsService } from '../services/sports'

interface TeamStats {
  abbrev: string
  name: string
  wins: number
  losses: number
  win_pct: number
  differential: number
  streak: string
  last10: string
  games_played: number
}

interface StandingRow {
  rank: number; abbrev: string; name: string
  played: number; wins: number; draws: number; losses: number
  gf: number; ga: number; gd: number; points: number
}
interface StandingGroup {
  group: string; rows: StandingRow[]
}

const LEAGUES = ['MLB', 'NBA', 'NHL', 'NFL', 'WC']

export default function StatsPage() {
  const [league, setLeague] = useState<string>('MLB')
  const [teams, setTeams] = useState<TeamStats[]>([])
  const [groups, setGroups] = useState<StandingGroup[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let ignore = false
    const load = async () => {
      setLoading(true)
      setError(null)
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
        if (!ignore) setError('Unable to load stats.')
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [league])

  return (
    <>
      <Head>
        <title>Team Stats — Legendary Picks</title>
      </Head>
      <div className="space-y-6">
        <h1 className="text-3xl font-extrabold tracking-tight">
          {league === 'WC' ? 'World Cup Standings' : 'Team Stats'}
        </h1>

        {/* League buttons */}
        <div className="flex items-center gap-2 flex-wrap">
          {LEAGUES.map((l) => (
            <button
              key={l}
              onClick={() => setLeague(l)}
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

        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 text-red-400 text-sm">
            {error}
          </div>
        )}

        {loading ? (
          <div className="text-zinc-500 text-sm">Loading...</div>
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
                          <th className="text-center py-3 px-2">P</th>
                          <th className="text-center py-3 px-2">W</th>
                          <th className="text-center py-3 px-2">D</th>
                          <th className="text-center py-3 px-2">L</th>
                          <th className="text-center py-3 px-2">GF</th>
                          <th className="text-center py-3 px-2">GA</th>
                          <th className="text-center py-3 px-2">GD</th>
                          <th className="text-center py-3 px-2 font-bold">Pts</th>
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
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-800 text-zinc-400 text-xs uppercase tracking-wider">
                  <th className="text-left py-3 pr-4">#</th>
                  <th className="text-left py-3 pr-4">Team</th>
                  <th className="text-right py-3 px-3">W</th>
                  <th className="text-right py-3 px-3">L</th>
                  <th className="text-right py-3 px-3">Win%</th>
                  <th className="text-right py-3 px-3">Diff</th>
                  <th className="text-right py-3 px-3">Streak</th>
                  <th className="text-right py-3 pl-3">L10</th>
                </tr>
              </thead>
              <tbody>
                {teams.map((t, i) => (
                  <tr key={t.abbrev} className="border-b border-zinc-800/50 hover:bg-zinc-900/50">
                    <td className="py-3 pr-4 text-zinc-500">{i + 1}</td>
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
                    <td className="py-3 pl-3 text-right text-zinc-400">{t.last10}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
