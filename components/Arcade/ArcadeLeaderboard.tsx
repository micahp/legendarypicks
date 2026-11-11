import { useEffect, useState } from 'react'

type Entry = { rank: number; player: string; score: number }

export default function ArcadeLeaderboard({ challengeId, configHash, refreshKey }: {
  challengeId: string
  configHash: string
  refreshKey?: string
}) {
  const [entries, setEntries] = useState<Entry[]>([])
  const [state, setState] = useState<'loading' | 'ready' | 'unavailable'>('loading')

  useEffect(() => {
    const controller = new AbortController()
    setState('loading')
    fetch(`/api/arcade/leaderboard?challenge_id=${encodeURIComponent(challengeId)}&config_hash=${encodeURIComponent(configHash)}`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error('Leaderboard unavailable')
        return response.json() as Promise<{ entries: Entry[] }>
      })
      .then(payload => {
        setEntries(Array.isArray(payload.entries) ? payload.entries : [])
        setState('ready')
      })
      .catch(() => { if (!controller.signal.aborted) setState('unavailable') })
    return () => controller.abort()
  }, [challengeId, configHash, refreshKey])

  return <section className="lp-arcade-leaderboard" aria-label="Challenge leaderboard">
    <h3>BEST KICKS · THIS CHALLENGE</h3>
    {state === 'loading' ? <p role="status">Loading the anonymous score board…</p>
      : state === 'unavailable' ? <p role="status">The score board is temporarily unavailable.</p>
        : entries.length ? <ol>{entries.map(entry => <li key={`${entry.rank}-${entry.score}`}>
          <span>{entry.rank}. {entry.player}</span><strong>{entry.score}</strong>
        </li>)}</ol>
          : <p>No kicks have been recorded for this challenge yet. Play first and set the mark.</p>}
    <p>Best verified server scores · anonymous players · no signup</p>
  </section>
}
