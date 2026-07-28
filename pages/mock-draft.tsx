import { useState, useEffect, useCallback, useRef } from 'react'
import type { PoolPlayer } from '../components/Leagues/types'
import type { DraftState, DraftPlayer as EngineDraftPlayer } from '../lib/mockDraft/engine'
import {
  createDraft as engineCreateDraft,
  applyPick,
  autopick,
  botPick,
  isUserPick,
  isComplete,
  seededRandom,
} from '../lib/mockDraft/engine'
import {
  fetchPool,
  createDraft as apiCreateDraft,
  appendPicks,
  fetchDraft,
} from '../lib/mockDraft/api'
import PoolList from '../components/MockDraft/PoolList'
import DraftRoom from '../components/MockDraft/DraftRoom'
import ResultsScreen from '../components/MockDraft/ResultsScreen'

type Phase = 'pool' | 'drafting' | 'results'

// A timeout pick should be the deterministic best available, not a jittered one:
// botPick maps rng() to jitter = (rng() - 0.5) * 0.2, so 0.5 → no jitter.
const ZERO_JITTER = () => 0.5

export default function MockDraftPage() {
  const [phase, setPhase] = useState<Phase>('pool')
  const [pool, setPool] = useState<PoolPlayer[]>([])
  const [poolLoading, setPoolLoading] = useState(true)
  const [poolError, setPoolError] = useState<string | null>(null)
  const [draftState, setDraftState] = useState<DraftState | null>(null)
  const [draftId, setDraftId] = useState<string | null>(null)
  const [userPicking, setUserPicking] = useState(false)
  const [creating, setCreating] = useState(false)

  // ── Queue state ──
  const [queue, setQueue] = useState<number[]>([])

  // RNG ref — stable per draft
  const rngRef = useRef<(() => number) | null>(null)

  // ── Load pool on mount ──
  useEffect(() => {
    let cancelled = false
    fetchPool(2026)
      .then(data => {
        if (!cancelled) {
          setPool(data.players)
          setPoolLoading(false)
        }
      })
      .catch(err => {
        if (!cancelled) {
          setPoolError(err.message)
          setPoolLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [])

  // ── Check for resume on mount ──
  useEffect(() => {
    if (typeof window === 'undefined') return
    const params = new URLSearchParams(window.location.search)
    const id = params.get('id')
    if (!id) return

    fetchDraft(id)
      .then(draft => {
        if (draft.status === 'complete') {
          // Need pool first
          return
        }
        // Build engine state from persisted data
        const enginePlayers: EngineDraftPlayer[] = draft.picks.map(p => ({
          player_id: p.player_id,
          name: '',
          position: '' as 'QB',
          team: '',
          adp: 0,
        }))
        // We need the full pool to resolve player names... complex.
        // For now, skip resume if pool isn't loaded yet.
      })
      .catch(() => {
        // Draft not found or device mismatch — ignore
      })
  }, [])

  // ── Start draft ──
  const handleStartDraft = useCallback(async () => {
    if (pool.length === 0) return
    setCreating(true)

    try {
      const seat = Math.floor(Math.random() * 12) + 1
      const seed = Date.now()
      rngRef.current = seededRandom(seed)

      const { id } = await apiCreateDraft(2026, seat, seed)
      setDraftId(id)

      // Build engine pool from PoolPlayer
      const enginePlayers: EngineDraftPlayer[] = pool.map(p => ({
        player_id: p.player_id,
        name: p.name,
        position: p.position as 'QB' | 'RB' | 'WR' | 'TE' | 'PK',
        team: p.team,
        // Pass the real value through, including null. This array is BOTH the
        // engine's input and the draft board's display source, so `?? 999` did
        // not just nudge bot ordering — it put a literal "999.0" in the ADP
        // column for all 32 D/ST. DraftRoom.tsx:356 already renders `—` for a
        // null; it never got the chance. EngineDraftPlayer.adp is `number | null`,
        // so the engine has always accepted the honest value.
        // A fabricated sentinel that reaches a user is a false measurement, not
        // a default. The remaining null-ADP ordering is job15's to remove.
        adp: p.adp,
      }))

      const state = engineCreateDraft(id, seat, enginePlayers, seed)
      setDraftState(state)

      // If user isn't first pick, autopick bot picks leading up to user's turn
      let current = state
      while (!isUserPick(current) && !isComplete(current)) {
        if (!rngRef.current) break
        current = autopick(current, rngRef.current)
      }

      // Save bot picks
      const botPicks = current.picks.filter(p => p.auto)
      if (botPicks.length > 0) {
        await appendPicks(id, botPicks).catch(() => {
          // Non-fatal — picks are best-effort
        })
      }

      setDraftState(current)
      setPhase('drafting')
      setUserPicking(true)
    } catch (err: any) {
      setPoolError(err.message || 'Failed to create draft')
    } finally {
      setCreating(false)
    }
  }, [pool])

  // ── Queue handlers ──
  const handleAddToQueue = useCallback((playerId: number) => {
    setQueue(q => { if (q.includes(playerId)) return q; return [...q, playerId] })
  }, [])

  const handleRemoveFromQueue = useCallback((playerId: number) => {
    setQueue(q => q.filter(id => id !== playerId))
  }, [])

  const handleMoveQueueUp = useCallback((idx: number) => {
    setQueue(q => { if (idx <= 0) return q; const next = [...q]; [next[idx-1], next[idx]] = [next[idx], next[idx-1]]; return next })
  }, [])

  const handleMoveQueueDown = useCallback((idx: number) => {
    setQueue(q => { if (idx >= q.length - 1) return q; const next = [...q]; [next[idx], next[idx+1]] = [next[idx+1], next[idx]]; return next })
  }, [])

  // ── Commit the user's pick, then run bots up to their next turn ──
  //   auto=true when the 30s clock expired and we picked for them.
  const commitPick = useCallback(async (playerId: number, auto: boolean) => {
    if (!draftState || !rngRef.current || !draftId) return

    setUserPicking(false)

    // Apply user's pick
    let current = applyPick(draftState, playerId, auto)

    // Save user's pick to server
    const userPick = current.picks[current.picks.length - 1]
    await appendPicks(draftId, [userPick]).catch(() => {})

    // Autopick all remaining bot picks until user's next turn or complete
    const batchPicks: Array<{ pick_no: number; team_no: number; player_id: number; auto: boolean }> = []
    while (!isUserPick(current) && !isComplete(current)) {
      current = autopick(current, rngRef.current)
      const lastPick = current.picks[current.picks.length - 1]
      batchPicks.push({
        pick_no: lastPick.pick_no,
        team_no: lastPick.team_no,
        player_id: lastPick.player_id,
        auto: true,
      })
    }

    // Save batch of bot picks
    if (batchPicks.length > 0) {
      await appendPicks(draftId, batchPicks).catch(() => {})
    }

    setDraftState(current)

    // Remove drafted players from queue
    setQueue(q => q.filter(id => current.availablePool.some(p => p.player_id === id)))

    if (isComplete(current)) {
      setPhase('results')
    } else {
      setUserPicking(true)
    }
  }, [draftState, draftId])

  const handleUserPick = useCallback(
    (playerId: number) => commitPick(playerId, false),
    [commitPick],
  )

  // ── Clock expired — pick for the user rather than stalling the draft ──
  //   Queue first (that is what the queue is for), else the engine's best
  //   available with zero jitter, per the autopick contract in engine.ts.
  const handleTimeout = useCallback(() => {
    if (!draftState || !isUserPick(draftState) || isComplete(draftState)) return
    const queued = queue.find(id =>
      draftState.availablePool.some(p => p.player_id === id),
    )
    const playerId = queued ?? botPick(draftState, ZERO_JITTER).player_id
    void commitPick(playerId, true)
  }, [draftState, queue, commitPick])

  // ── Loading / error states ──
  if (poolLoading) {
    return (
      <div className="space-y-3 animate-pulse">
        <div className="h-6 w-48 rounded bg-zinc-800" />
        <div className="h-96 rounded-xl bg-zinc-800" />
      </div>
    )
  }

  if (poolError) {
    return (
      <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-400">
        {poolError}
      </div>
    )
  }

  if (pool.length === 0) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-12 text-center">
        <p className="text-sm text-zinc-400">No players in the mock draft pool.</p>
      </div>
    )
  }

  // ── Render ──
  return (
    <div className="space-y-4">
      {phase === 'pool' && (
        <>
          {creating && (
            <div className="rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2 text-sm text-zinc-400 animate-pulse">
              Creating draft…
            </div>
          )}
          <PoolList
            players={pool}
            onStartDraft={handleStartDraft}
          />
        </>
      )}

      {phase === 'drafting' && draftState && (
        <DraftRoom
          pool={pool}
          draftState={draftState}
          onUserPick={handleUserPick}
          onTimeout={handleTimeout}
          userPicking={userPicking}
          queue={queue}
          onAddToQueue={handleAddToQueue}
          onRemoveFromQueue={handleRemoveFromQueue}
          onMoveQueueUp={handleMoveQueueUp}
          onMoveQueueDown={handleMoveQueueDown}
        />
      )}

      {phase === 'results' && draftState && (
        <ResultsScreen
          pool={pool}
          draftState={draftState}
        />
      )}
    </div>
  )
}
