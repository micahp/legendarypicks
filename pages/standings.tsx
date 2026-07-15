import { useState, useEffect } from 'react'
import Head from 'next/head'

interface StandingRow {
  rank: number; abbrev: string; name: string
  played: number; wins: number; draws: number; losses: number
  gf: number; ga: number; gd: number; points: number
}
interface Group {
  group: string; rows: StandingRow[]
}

export default function StandingsPage() {
  const [groups, setGroups] = useState<Group[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/wc/standings')
      .then(r => r.json()).then(d => { setGroups(Array.isArray(d) ? d : []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  return (
    <>
      <Head><title>Standings — Legendary Picks</title></Head>
      <div className="space-y-6">
        <h1 className="text-3xl font-extrabold tracking-tight">FIFA World Cup Standings</h1>
        {loading ? (
          <div className="text-zinc-500 text-sm">Loading...</div>
        ) : groups.length === 0 ? (
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
        )}
      </div>
    </>
  )
}
