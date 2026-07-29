import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
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
  DEFAULT_TEAMS,
} from '../lib/mockDraft/engine'
import type { LeagueSize } from '../lib/mockDraft/engine'
import type { SeatChoice } from '../components/MockDraft/PoolList'
import {
  fetchPool,
  createDraft as apiCreateDraft,
  appendPicks,
  completeDraft,
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
  // The season the pool's statistics describe, straight from the payload —
  // never inferred from the drafted season.
  const [referenceSeason, setReferenceSeason] = useState<number | null>(null)
  const [poolError, setPoolError] = useState<string | null>(null)
  const [draftState, setDraftState] = useState<DraftState | null>(null)
  const [draftId, setDraftId] = useState<string | null>(null)
  const [userPicking, setUserPicking] = useState(false)
  const [creating, setCreating] = useState(false)

  // ── Draft setup ──
  //   Both of these used to be decided without asking: teams was a literal 12
  //   in the server's INSERT, and the seat was Math.random() at Start Draft.
  const [teams, setTeams] = useState<LeagueSize>(DEFAULT_TEAMS)
  const [seatChoice, setSeatChoice] = useState<SeatChoice>('random')

  // Shrinking the league can strand a chosen slot outside it — pick 13 in a
  // 10-team draft. Fall back to random rather than silently reassigning them to
  // a seat they did not choose, or sending the server a seat it will reject.
  const handleSetTeams = useCallback((next: LeagueSize) => {
    setTeams(next)
    setSeatChoice(prev => (prev !== 'random' && prev > next ? 'random' : prev))
  }, [])

  // ── Queue state ──
  const [queue, setQueue] = useState<number[]>([])

  // RNG ref — stable per draft
  const rngRef = useRef<(() => number) | null>(null)

  // ── Pick persistence ──
  // The server row is the only durable record of a draft; the React state dies
  // with the tab. These appends used to be `.catch(() => {})`, which is why a
  // dropped batch produced a permanent hole in the saved draft -- picks are
  // INSERT OR IGNORE on (draft_id, pick_no), so later batches still land and
  // nothing on either side ever raised. Retry once, then say so.
  const unsavedRef = useRef(0)
  const [unsavedPicks, setUnsavedPicks] = useState(0)
  // Tracked apart from unsaved picks: a draft whose picks all landed but whose
  // completion write failed is a different state, and saying "3 picks weren't
  // saved" when 0 picks were lost would be its own false claim.
  const [completionUnsaved, setCompletionUnsaved] = useState(false)

  const savePicks = useCallback(
    async (
      id: string,
      picks: Array<{ pick_no: number; team_no: number; player_id: number; auto?: boolean }>,
    ) => {
      try {
        await appendPicks(id, picks)
      } catch {
        try {
          await appendPicks(id, picks)
        } catch {
          unsavedRef.current += picks.length
          setUnsavedPicks(unsavedRef.current)
        }
      }
    },
    [],
  )

  // ── Load pool on mount ──
  useEffect(() => {
    let cancelled = false
    fetchPool(2026)
      .then(data => {
        if (!cancelled) {
          setPool(data.players)
          setReferenceSeason(data.reference_season ?? null)
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
        // The backend's vocabulary is 'active' / 'completed'. This read
        // 'complete' -- a string nothing ever writes -- so the branch was dead
        // and a finished draft would have been resumed as an in-progress one.
        if (draft.status === 'completed') {
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
      const seat =
        seatChoice === 'random' ? Math.floor(Math.random() * teams) + 1 : seatChoice
      const seed = Date.now()
      rngRef.current = seededRandom(seed)

      const { id } = await apiCreateDraft(2026, seat, seed, teams)
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

      const state = engineCreateDraft(id, seat, enginePlayers, seed, teams)
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
        await savePicks(id, botPicks)
      }

      setDraftState(current)
      setPhase('drafting')
      setUserPicking(true)
    } catch (err: any) {
      setPoolError(err.message || 'Failed to create draft')
    } finally {
      setCreating(false)
    }
  }, [pool, savePicks, teams, seatChoice])

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
    await savePicks(draftId, [userPick])

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
      await savePicks(draftId, batchPicks)
    }

    setDraftState(current)

    // Remove drafted players from queue
    setQueue(q => q.filter(id => current.availablePool.some(p => p.player_id === id)))

    if (isComplete(current)) {
      // Tell the server the draft finished. Without this the row stays
      // 'active' forever and an abandoned draft is indistinguishable from a
      // completed one -- which is the classification slice B's "your drafts"
      // list depends on.
      await completeDraft(draftId).catch(() => setCompletionUnsaved(true))
      setPhase('results')
    } else {
      setUserPicking(true)
    }
  }, [draftState, draftId, savePicks])

  const handleUserPick = useCallback(
    (playerId: number) => commitPick(playerId, false),
    [commitPick],
  )

  // ── What the clock would take at 0:00 ──
  //   Queue first (that is what the queue is for), else the engine's best
  //   available with zero jitter, per the autopick contract in engine.ts.
  //
  //   This is computed once and used twice: the draft room's header says "your
  //   auto pick would be X" from it, and the timeout below drafts it. Computing
  //   it separately in each place is how a header ends up naming a player the
  //   clock does not take — a promise the product breaks thirty seconds later.
  const autoPick = useMemo(() => {
    if (!draftState || !isUserPick(draftState) || isComplete(draftState)) return null
    const queued = queue.find(id =>
      draftState.availablePool.some(p => p.player_id === id),
    )
    if (queued != null) {
      return draftState.availablePool.find(p => p.player_id === queued) ?? null
    }
    return botPick(draftState, ZERO_JITTER)
  }, [draftState, queue])

  const handleTimeout = useCallback(() => {
    if (!draftState || !isUserPick(draftState) || isComplete(draftState)) return
    if (!autoPick) return
    void commitPick(autoPick.player_id, true)
  }, [draftState, autoPick, commitPick])

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
            referenceSeason={referenceSeason}
            teams={teams}
            onSetTeams={handleSetTeams}
            seat={seatChoice}
            onSetSeat={setSeatChoice}
            onStartDraft={handleStartDraft}
          />
        </>
      )}

      {phase === 'drafting' && draftState && (
        <DraftRoom
          pool={pool}
          referenceSeason={referenceSeason}
          draftState={draftState}
          onUserPick={handleUserPick}
          onTimeout={handleTimeout}
          userPicking={userPicking}
          autoPick={autoPick}
          queue={queue}
          onAddToQueue={handleAddToQueue}
          onRemoveFromQueue={handleRemoveFromQueue}
          onMoveQueueUp={handleMoveQueueUp}
          onMoveQueueDown={handleMoveQueueDown}
        />
      )}

      {/* An incomplete save is the user's business, not just ours: this is the
          screen where they might close the tab believing the draft is kept.
          Amber marks what is missing, per the data-UI doctrine. */}
      {phase === 'results' && (unsavedPicks > 0 || completionUnsaved) && (
        <p className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-2.5 text-sm text-amber-300">
          {unsavedPicks > 0
            ? `${unsavedPicks} ${unsavedPicks === 1 ? 'pick' : 'picks'} could not be saved to your account — this draft is on screen but incomplete on our side.`
            : 'This draft finished, but we could not record it as complete — it may show as unfinished later.'}
        </p>
      )}

      {phase === 'results' && draftState && (
        <ResultsScreen
          pool={pool}
          referenceSeason={referenceSeason}
          draftState={draftState}
        />
      )}
    </div>
  )
}
