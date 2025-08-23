import React from 'react'

interface Contest {
  contestId: number
  startTime: number
  endTime: number
}

interface LeaderboardEntry {
  rank: number
  address: string
  score: number
}

interface Props {
  contest: Contest
  entries?: LeaderboardEntry[]
}

export default function ContestLeaderboard({ contest, entries }: Props) {
  const fallback: LeaderboardEntry[] = (
    entries && entries.length > 0
      ? entries
      : [
          { rank: 1, address: '—', score: 0 },
          { rank: 2, address: '—', score: 0 },
          { rank: 3, address: '—', score: 0 },
        ]
  )

  return (
    <div className="space-y-3 p-4 border rounded-lg">
      <div className="flex items-center justify-between">
        <h3 className="text-xl font-semibold">Leaderboard</h3>
        <div className="text-xs text-zinc-500">
          Contest #{contest.contestId}
        </div>
      </div>

      <table className="min-w-full text-sm">
        <thead className="text-zinc-400">
          <tr>
            <th className="text-left font-medium w-12">#</th>
            <th className="text-left font-medium">Address</th>
            <th className="text-right font-medium">Score</th>
          </tr>
        </thead>
        <tbody>
          {fallback.map((e) => (
            <tr key={e.rank} className="border-t border-zinc-800">
              <td className="py-2 pr-2">{e.rank}</td>
              <td className="py-2 pr-2">{e.address}</td>
              <td className="py-2 pl-2 text-right font-semibold">{e.score.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="text-xs text-zinc-500">
        Live scoring will populate as games progress.
      </div>
    </div>
  )
}


