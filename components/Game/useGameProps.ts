import { useState, useEffect } from 'react'

// `result` is null until the prop settles. An unsettled prop is NOT a miss, and the two
// have to stay distinguishable all the way to the pixel — a page that renders them the
// same is claiming a loss we never took.
export interface PropResult { actual: number | null; hit: boolean; settled_at: string; cashed: string }
export interface Prop { market: string; side: string; line: number; result?: PropResult | null }
export interface GamePropPlayer { player_id: number; name: string; team: string; props: Prop[] }
export interface Leader {
  player_id: number; name: string; team: string; market: string
  line: number; actual: number; cashed: string; margin: number
}

export interface GamePropsData {
  players: GamePropPlayer[]
  leaders: Leader[]
  settledLines: number
  edgeLabel: boolean
  loading: boolean
}

/**
 * ONE fetch of /api/game/{league}/{id}/props for the whole page.
 *
 * The props payload is the biggest thing the game page downloads — 14.6KB for 18
 * players and 86 props on a mid-size MLB game. Both the "What decided it" panel and
 * the Props tab are views over that same response, so fetching it per component meant
 * downloading all of it twice to render three leader cards on top. `docs/DEV-STANDARDS.md`:
 * a surface must not download more than it renders.
 */
export function useGameProps(league?: string, gameId?: string): GamePropsData {
  const [players, setPlayers] = useState<GamePropPlayer[]>([])
  const [leaders, setLeaders] = useState<Leader[]>([])
  const [settledLines, setSettledLines] = useState(0)
  const [edgeLabel, setEdgeLabel] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!league || !gameId) return
    let alive = true
    setLoading(true)
    setPlayers([]); setLeaders([]); setSettledLines(0); setEdgeLabel(false)

    fetch(`/api/game/${league}/${gameId}/props`)
      .then(r => r.json())
      .then(d => {
        if (d.players?.length) {
          if (alive) {
            setPlayers(d.players)
            setLeaders(d.leaders || [])
            setSettledLines(d.settled_lines || 0)
          }
          return
        }
        // NBA fallback: no Bovada props — show projected stat lines. There are no
        // settled results on a projection, so no leaders come with it.
        if (league === 'nba') {
          return fetch(`/api/game/${league}/${gameId}/edge`)
            .then(r => r.json())
            .then(e => { if (alive) { setPlayers(e.players || []); setEdgeLabel(true) } })
            .catch(() => {})
        }
      })
      .catch(() => {})
      .finally(() => { if (alive) setLoading(false) })

    return () => { alive = false }
  }, [league, gameId])

  return { players, leaders, settledLines, edgeLabel, loading }
}
