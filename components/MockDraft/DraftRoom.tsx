import { useMemo, useState, useEffect, useRef } from 'react'
import type { PoolPlayer } from '../Leagues/types'
import PlayerDetailOverlay from '../Leagues/PlayerDetailOverlay'
import type { DraftState, DraftPlayer } from '../../lib/mockDraft/engine'
import {
  currentDrafter,
  isUserPick,
  getRosterState,
  userNextPick,
} from '../../lib/mockDraft/engine'
import { poolTeamGames } from '../../lib/mockDraft/availability'
import { AvailabilityStrip } from '../Leagues/NflDraftRoom'

interface ScheduleTeam {
  team: string
  weeks_played: number[]
  bye_week: number | null
}

interface Props {
  pool: PoolPlayer[]
  draftState: DraftState
  onUserPick: (playerId: number) => void
  onTimeout: () => void
  userPicking: boolean
  queue: number[]
  onAddToQueue: (playerId: number) => void
  onRemoveFromQueue: (playerId: number) => void
  onMoveQueueUp: (idx: number) => void
  onMoveQueueDown: (idx: number) => void
}

// The season being drafted. Matches pages/mock-draft.tsx's fetchPool(2026) and
// apiCreateDraft(2026, ...) — bye weeks must come from the same season as the draft.
const DRAFT_SEASON = 2026

const PICK_LEDGER_LIMIT = 15
// 15-man roster: QB RB1 RB2 WR1 WR2 TE FLEX K DEF = 9 starters, rest bench.
const BENCH_SLOTS = 6

/**
 * Main draft UI — pool on left, roster + ledger on right.
 *
 * Design rules (honest-data-ui §6.2):
 *   - Accent (amber) marks absence only — never on clock, your pick, drafted row.
 *   - On the clock: weight + position + rule. NOT colour.
 *   - Your picks: left rule or fill one step lighter.
 *   - Drafted: dim + strike.
 *   - Clock: tabular figures, may change weight under 10s, never red.
 */
export default function DraftRoom({ pool, draftState, onUserPick, onTimeout, userPicking, queue, onAddToQueue, onRemoveFromQueue, onMoveQueueUp, onMoveQueueDown }: Props) {
  // ── Filter state ──
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null)
  const [posFilter, setPosFilter] = useState<string>('ALL')
  const [teamFilter, setTeamFilter] = useState<string>('ALL')
  const [byeFilter, setByeFilter] = useState<string>('ALL')
  const [schedule, setSchedule] = useState<ScheduleTeam[] | null>(null)

  // Fetch the schedule for bye weeks. This MUST be the season being drafted, not
  // the season whose stats we show. Byes move every year: for 2026 vs 2025, DEN
  // 12→10, LAR 8→11, SEA 8→11, CIN 10→6, DAL 10→14. Reading 2025 here — as this
  // did through v0.6.12 — made the bye filter silently select the wrong teams.
  useEffect(() => {
    let cancelled = false
    fetch(`/api/nfl/schedule/${DRAFT_SEASON}`)
      .then(r => r.json())
      .then(data => { if (!cancelled) setSchedule(data.teams ?? []) })
      .catch(() => { /* bye filter stays disabled */ })
    return () => { cancelled = true }
  }, [])

  // ── Filter options derived from pool + schedule ──
  const posOptions = useMemo(
    () => ['ALL', ...Array.from(new Set(pool.map(p => p.position).sort()))],
    [pool],
  )
  const teamOptions = useMemo(
    () => ['ALL', ...Array.from(new Set(pool.map(p => p.team).sort()))],
    [pool],
  )

  // Bye → team lookup map
  const byeMap = useMemo(() => {
    if (!schedule) return new Map<string, number | null>()
    const m = new Map<string, number | null>()
    for (const t of schedule) m.set(t.team, t.bye_week)
    return m
  }, [schedule])

  const byeOptions = useMemo(() => {
    const weeks = new Set<number>()
    for (const t of (schedule ?? [])) { if (t.bye_week != null) weeks.add(t.bye_week) }
    return ['ALL', ...Array.from(weeks).sort((a, b) => a - b).map(String)]
  }, [schedule])

  // Build a lookup from player_id → PoolPlayer for O(1) resolution
  const playerMap = useMemo(() => {
    const m = new Map<number, PoolPlayer>()
    for (const p of pool) m.set(p.player_id, p)
    return m
  }, [pool])

  // Which players have been drafted
  const draftedIds = useMemo(() => {
    const s = new Set<number>()
    for (const pick of draftState.picks) s.add(pick.player_id)
    return s
  }, [draftState.picks])

  // availablePool is ALREADY sorted by createDraft (numeric ADP ascending, null ADP
  // last) and applyPick filters, which preserves that order. Do not re-sort here: a
  // naive `a.adp - b.adp` coerces null to 0 and floats all 32 D/ST above pick 1.
  const availablePool = draftState.availablePool

  // Apply filters to available pool
  const filteredPool = useMemo(() => {
    return availablePool.filter(dp => {
      if (posFilter !== 'ALL' && dp.position !== posFilter) return false
      if (teamFilter !== 'ALL' && dp.team !== teamFilter) return false
      if (byeFilter !== 'ALL') {
        const bye = byeMap.get(dp.team)
        if (bye == null || String(bye) !== byeFilter) return false
      }
      return true
    })
  }, [availablePool, posFilter, teamFilter, byeFilter, byeMap])

  // User's roster state
  const userRoster = useMemo(
    () => getRosterState(draftState, draftState.seat),
    [draftState],
  )

  const userTurn = isUserPick(draftState)
  const nextPick = userNextPick(draftState)
  const drafter = currentDrafter(draftState)
  const round = Math.ceil(draftState.currentPick / draftState.teams)

  // ── Clock: 30s countdown when user is on the clock ──
  const CLOCK_SECONDS = 30
  // The countdown carries the pick it belongs to. On the render where a new turn
  // begins, `seconds` still holds the *previous* turn's value — pairing the two in one
  // state object means a stale 0 can never be read as this turn's expiry. In a snake
  // draft the user can pick twice in a row (e.g. 22 then 27), and `userTurn` does not
  // change across those, so neither a boolean guard nor `currentPick` alone is enough.
  const [clock, setClock] = useState({ pick: draftState.currentPick, seconds: CLOCK_SECONDS })
  const clockRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (clockRef.current) clearInterval(clockRef.current)
    setClock({ pick: draftState.currentPick, seconds: CLOCK_SECONDS })

    if (userTurn && !draftState.completed) {
      clockRef.current = setInterval(() => {
        setClock(c => {
          if (c.seconds <= 1) {
            if (clockRef.current) clearInterval(clockRef.current)
            return { ...c, seconds: 0 }
          }
          return { ...c, seconds: c.seconds - 1 }
        })
      }, 1000)
    }
    return () => {
      if (clockRef.current) clearInterval(clockRef.current)
    }
  }, [userTurn, draftState.currentPick, draftState.completed])

  // At 0:00 the draft would otherwise stall forever waiting on a user who is not there.
  // Autopick for them instead — exactly once per pick.
  const timedOutPick = useRef<number | null>(null)
  useEffect(() => {
    if (
      clock.seconds === 0 &&
      clock.pick === draftState.currentPick &&
      timedOutPick.current !== draftState.currentPick &&
      userTurn &&
      userPicking &&
      !draftState.completed
    ) {
      timedOutPick.current = draftState.currentPick
      onTimeout()
    }
  }, [clock, draftState.currentPick, userTurn, userPicking, draftState.completed, onTimeout])

  // Sort user's players into slot order
  const rosterSlots = useMemo(() => buildRosterSlots(userRoster.players, playerMap), [userRoster, playerMap])

  // Recent picks for the ledger
  const recentPicks = useMemo(() => {
    const all = [...draftState.picks].reverse().slice(0, PICK_LEDGER_LIMIT).reverse()
    return all
  }, [draftState.picks])

  // Resolve queue IDs → DraftPlayer objects (only those still available)
  const queuePlayers = useMemo(() => {
    const playerLookup = new Map(draftState.playerPool.map(p => [p.player_id, p]))
    return queue
      .map(id => playerLookup.get(id))
      .filter((p): p is DraftPlayer => p != null && !draftedIds.has(p.player_id))
  }, [queue, draftState.playerPool, draftedIds])

  return (
    <>
    <section className="space-y-4">
      {/* Status bar — weight + position + rule, NO colour */}
      <div className="flex items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-3">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold text-zinc-300">
            Round {round}
          </span>
          <span className="text-xs text-zinc-500">·</span>
          <span className="text-sm text-zinc-400">
            Pick {draftState.currentPick} of {draftState.teams * draftState.rounds}
          </span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {draftState.completed ? (
            <span className="text-sm font-semibold text-zinc-300">Draft complete</span>
          ) : userTurn ? (
            <>
              <span className="text-sm font-semibold text-zinc-200">
                Your pick — Pick {draftState.currentPick}
              </span>
              <span className="text-xs text-zinc-500">·</span>
              <span
                className={`font-mono tabular-nums text-sm ${
                  clock.seconds <= 10 ? 'font-bold text-zinc-200' : 'font-medium text-zinc-400'
                }`}
              >
                0:{clock.seconds.toString().padStart(2, '0')}
              </span>
            </>
          ) : (
            <>
              <span className="text-sm text-zinc-400">
                Team {drafter} picking
              </span>
              <span className="text-xs text-zinc-500">·</span>
              <span className="text-sm text-zinc-400 tabular-nums">
                Your next: #{nextPick}
              </span>
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* ── Pool (left 2/3) ── */}
        <div className="lg:col-span-2 space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider">
              Player Pool
            </h4>
            <span className="text-xs text-zinc-600 tabular-nums">
              {filteredPool.length} of {availablePool.length} available · {draftedIds.size} drafted
            </span>
          </div>

          {/* ── Filter bar ── */}
          <div className="flex flex-wrap items-center gap-2">
            {/* Position pills */}
            <div className="flex items-center gap-1" role="radiogroup" aria-label="Filter by position">
              {posOptions.map(pos => (
                <button
                  key={pos}
                  type="button"
                  role="radio"
                  aria-checked={posFilter === pos}
                  onClick={() => setPosFilter(pos)}
                  className={`rounded-md border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide transition-colors ${
                    posFilter === pos
                      ? 'border-zinc-500 bg-zinc-700 text-zinc-200'
                      : 'border-zinc-800 bg-zinc-900 text-zinc-500 hover:border-zinc-700 hover:text-zinc-400'
                  }`}
                >
                  {pos === 'ALL' ? 'All' : pos}
                </button>
              ))}
            </div>

            <span className="text-zinc-700">|</span>

            {/* Team dropdown */}
            <select
              value={teamFilter}
              onChange={e => setTeamFilter(e.target.value)}
              className="rounded-md border border-zinc-800 bg-zinc-900 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-zinc-400 focus:border-zinc-600 focus:outline-none"
              aria-label="Filter by team"
            >
              {teamOptions.map(t => (
                <option key={t} value={t}>{t === 'ALL' ? 'All Teams' : t}</option>
              ))}
            </select>

            {/* Bye week dropdown */}
            <select
              value={byeFilter}
              onChange={e => setByeFilter(e.target.value)}
              disabled={!schedule}
              className={`rounded-md border border-zinc-800 bg-zinc-900 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide focus:border-zinc-600 focus:outline-none ${
                schedule ? 'text-zinc-400' : 'text-zinc-700 cursor-not-allowed'
              }`}
              aria-label="Filter by bye week"
            >
              <option value="ALL">{schedule ? 'Bye Week' : 'Bye (loading…)'}</option>
              {byeOptions.filter(b => b !== 'ALL').map(b => (
                <option key={b} value={b}>Week {b}</option>
              ))}
            </select>

            {/* Clear filters */}
            {(posFilter !== 'ALL' || teamFilter !== 'ALL' || byeFilter !== 'ALL') && (
              <button
                type="button"
                onClick={() => { setPosFilter('ALL'); setTeamFilter('ALL'); setByeFilter('ALL') }}
                className="rounded-md border border-zinc-800 px-2 py-0.5 text-[10px] font-medium text-zinc-500 transition-colors hover:border-zinc-600 hover:text-zinc-300"
              >
                Clear
              </button>
            )}
          </div>

          <div className="overflow-y-auto max-h-[calc(100vh-300px)] rounded-xl border border-zinc-800 bg-zinc-900">
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10 bg-zinc-900">
                <tr className="border-b border-zinc-800 text-zinc-500 text-[11px] uppercase tracking-wider">
                  <th className="text-left py-2.5 pl-3 pr-2 w-10">#</th>
                  <th className="text-left py-2.5 px-2">Player</th>
                  <th className="text-center py-2.5 px-2 w-12">Pos</th>
                  <th className="text-left py-2.5 px-2 min-w-[8rem]">Available</th>
                  <th className="text-right py-2.5 px-2 w-16">ADP</th>
                  <th className="w-16" />
                </tr>
              </thead>
              <tbody>
                {filteredPool.map((dp, i) => {
                  const poolPlayer = playerMap.get(dp.player_id)
                  if (!poolPlayer) return null
                  const drafted = draftedIds.has(dp.player_id)
                  return (
                    <tr
                      key={dp.player_id}
                      onClick={() => setSelectedPlayerId(dp.player_id)}
                      className={`border-b border-zinc-800/40 transition-colors cursor-pointer hover:bg-zinc-800/30 ${
                        drafted
                          ? 'opacity-30 line-through'
                          : ''
                      }`}
                    >
                      <td className="py-2 pl-3 pr-2 text-zinc-500 text-xs tabular-nums">
                        {i + 1}
                      </td>
                      <td className="py-2 px-2">
                        <span className={`font-medium ${drafted ? 'text-zinc-600' : 'text-zinc-200'}`}>
                          {dp.name}
                        </span>
                        <div className="text-[10px] text-zinc-600">{dp.team}</div>
                      </td>
                      <td className="py-2 px-2 text-center">
                        <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-zinc-400">
                          {dp.position}
                        </span>
                      </td>
                      <td className="py-2 px-2">
                        <PoolAvailability poolPlayer={poolPlayer} />
                      </td>
                      <td className="py-2 pr-3 pl-2 text-right font-mono tabular-nums text-xs text-zinc-400">
                        {dp.adp != null ? dp.adp.toFixed(1) : <span className="text-zinc-600">—</span>}
                      </td>
                      <td className="py-2 pr-3 pl-1 text-center">
                        <div className="flex items-center gap-1 justify-center">
                          {userTurn && !drafted && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                onUserPick(dp.player_id)
                              }}
                              className="rounded border border-zinc-700 bg-zinc-800 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-300 transition-colors hover:border-zinc-500 hover:bg-zinc-700"
                            >
                              Draft
                            </button>
                          )}
                          {!drafted && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                if (queue.includes(dp.player_id)) {
                                  onRemoveFromQueue(dp.player_id)
                                } else {
                                  onAddToQueue(dp.player_id)
                                }
                              }}
                              className={`rounded border px-2 py-1 text-[10px] font-semibold uppercase tracking-wider transition-colors ${
                                queue.includes(dp.player_id)
                                  ? 'border-amber-500/30 bg-amber-500/10 text-amber-400 hover:border-amber-400 hover:bg-amber-500/20'
                                  : 'border-zinc-800 bg-zinc-900 text-zinc-600 hover:border-zinc-700 hover:text-zinc-400'
                              }`}
                              title={queue.includes(dp.player_id) ? 'Remove from queue' : 'Add to queue'}
                            >
                              {queue.includes(dp.player_id) ? '−Q' : '+Q'}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Roster + Ledger (right 1/3) ── */}
        <div className="space-y-4">
          {/* Queue panel */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-hidden">
            <div className="px-4 py-3 border-b border-zinc-800">
              <h4 className="text-sm font-semibold text-zinc-300">
                Queue
                <span className="ml-2 text-xs font-normal text-zinc-500 tabular-nums">
                  {queuePlayers.length}
                </span>
              </h4>
            </div>
            <div className="divide-y divide-zinc-800/50 max-h-[280px] overflow-y-auto">
              {queuePlayers.map((qp, idx) => (
                <div key={qp.player_id} className="flex items-center gap-2 px-3 py-2 text-xs">
                  <span className="text-zinc-600 tabular-nums w-5 shrink-0 text-right">
                    {idx + 1}
                  </span>
                  <span className="truncate flex-1 font-medium text-zinc-300">
                    {qp.name}
                  </span>
                  <span className="text-[10px] text-zinc-500 shrink-0 uppercase">
                    {qp.position}
                  </span>
                  {/* Move up/down */}
                  <div className="flex items-center gap-0.5 shrink-0">
                    <button
                      type="button"
                      onClick={() => onMoveQueueUp(idx)}
                      disabled={idx === 0}
                      className="rounded px-1 text-[10px] text-zinc-600 hover:text-zinc-300 disabled:text-zinc-800 disabled:cursor-not-allowed"
                      aria-label="Move up"
                    >
                      ▲
                    </button>
                    <button
                      type="button"
                      onClick={() => onMoveQueueDown(idx)}
                      disabled={idx === queuePlayers.length - 1}
                      className="rounded px-1 text-[10px] text-zinc-600 hover:text-zinc-300 disabled:text-zinc-800 disabled:cursor-not-allowed"
                      aria-label="Move down"
                    >
                      ▼
                    </button>
                  </div>
                  {/* Remove */}
                  <button
                    type="button"
                    onClick={() => onRemoveFromQueue(qp.player_id)}
                    className="rounded px-1 text-[10px] text-zinc-600 hover:text-zinc-400 shrink-0"
                    aria-label="Remove from queue"
                  >
                    ✕
                  </button>
                </div>
              ))}
              {queuePlayers.length === 0 && (
                <div className="px-4 py-4 text-center text-xs text-zinc-600">
                  Add players with +Q
                </div>
              )}
            </div>
          </div>

          {/* Roster panel */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-hidden">
            <div className="px-4 py-3 border-b border-zinc-800">
              <h4 className="text-sm font-semibold text-zinc-300">
                Your Roster
                <span className="ml-2 text-xs font-normal text-zinc-500 tabular-nums">
                  {userRoster.totalPicks}/{draftState.rounds} picks
                </span>
              </h4>
            </div>
            <div className="divide-y divide-zinc-800/50">
              {rosterSlots.map((slot, i) => (
                <RosterSlotRow key={i} slot={slot} />
              ))}
              {rosterSlots.length === 0 && (
                <div className="px-4 py-6 text-center text-sm text-zinc-600">
                  No picks yet
                </div>
              )}
            </div>
          </div>

          {/* Pick ledger */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-hidden">
            <div className="px-4 py-3 border-b border-zinc-800">
              <h4 className="text-sm font-semibold text-zinc-300">
                Pick Ledger
                <span className="ml-2 text-xs font-normal text-zinc-500 tabular-nums">
                  {draftState.picks.length} picks
                </span>
              </h4>
            </div>
            <div className="max-h-[300px] overflow-y-auto">
              <div className="divide-y divide-zinc-800/30">
                {recentPicks.map(pick => {
                  const dp = draftState.playerPool.find(p => p.player_id === pick.player_id)
                  const isUser = pick.team_no === draftState.seat
                  return (
                    <div
                      key={pick.pick_no}
                      className={`flex items-center gap-2 px-4 py-2 text-xs ${
                        isUser ? 'border-l-2 border-l-zinc-600 bg-zinc-800/30' : ''
                      }`}
                    >
                      <span className="text-zinc-600 tabular-nums w-8 shrink-0">
                        {pick.pick_no}
                      </span>
                      <span className="text-zinc-500 tabular-nums w-8 shrink-0">
                        T{pick.team_no}
                      </span>
                      <span className={`truncate ${isUser ? 'font-semibold text-zinc-200' : 'text-zinc-400'}`}>
                        {dp?.name ?? `#${pick.player_id}`}
                      </span>
                      <span className="text-[10px] text-zinc-600 shrink-0">
                        {dp?.position ?? ''}
                      </span>
                      {pick.auto && (
                        <span className="text-[10px] text-zinc-600 shrink-0 ml-auto">auto</span>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Draft board grid: teams × rounds ── */}
      <DraftBoardGrid draftState={draftState} />

    </section>
    {selectedPlayerId != null && (
      <PlayerDetailOverlay
        playerId={selectedPlayerId}
        onClose={() => setSelectedPlayerId(null)}
      />
    )}
    </>
  )
}

// ── Draft board grid: teams (rows) × rounds (columns) ──

function DraftBoardGrid({ draftState }: { draftState: DraftState }) {
  const { teams, rounds, picks, playerPool, seat } = draftState

  // Build lookup: pick_by_team_round[team_no][round] = { pick_no, player }
  const grid = useMemo(() => {
    const g: Array<Array<{
      pick_no: number
      name: string
      position: string
      auto: boolean
    } | null>> = Array.from({ length: teams + 1 }, () => Array(rounds).fill(null))

    const playerLookup = new Map(playerPool.map(p => [p.player_id, p]))
    for (const pick of picks) {
      const r = Math.ceil(pick.pick_no / teams) - 1 // 0-based round
      const player = playerLookup.get(pick.player_id)
      g[pick.team_no][r] = {
        pick_no: pick.pick_no,
        name: player?.name ?? `#${pick.player_id}`,
        position: player?.position ?? '',
        auto: pick.auto,
      }
    }
    return g
  }, [teams, rounds, picks, playerPool])

  // Round headers
  const roundLabels = Array.from({ length: rounds }, (_, i) => `R${i + 1}`)

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-hidden">
      <div className="px-4 py-3 border-b border-zinc-800">
        <h4 className="text-sm font-semibold text-zinc-300">
          Draft Board
          <span className="ml-2 text-xs font-normal text-zinc-500 tabular-nums">
            {picks.length}/{teams * rounds} picks
          </span>
        </h4>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-500">
              <th className="text-left py-2 pl-4 pr-2 w-12 font-medium uppercase tracking-wider">Team</th>
              {roundLabels.map(r => (
                <th key={r} className="text-center py-2 px-1 w-14 font-medium tabular-nums text-[10px]">
                  {r}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: teams }, (_, i) => {
              const teamNo = i + 1
              const isUser = teamNo === seat
              return (
                <tr
                  key={teamNo}
                  className={`border-b border-zinc-800/30 ${
                    isUser ? 'border-l-2 border-l-zinc-500 bg-zinc-800/20' : ''
                  }`}
                >
                  <td className={`py-2 pl-4 pr-2 font-semibold tabular-nums ${
                    isUser ? 'text-zinc-200' : 'text-zinc-500'
                  }`}>
                    T{teamNo}
                    {isUser && <span className="ml-1 text-[9px] font-normal text-zinc-600">you</span>}
                  </td>
                  {Array.from({ length: rounds }, (_, r) => {
                    const cell = grid[teamNo][r]
                    return (
                      <td key={r} className="text-center py-2 px-1">
                        {cell ? (
                          <div className="leading-tight">
                            <div className={`font-medium truncate max-w-[4.5rem] mx-auto ${
                              isUser ? 'text-zinc-200' : 'text-zinc-400'
                            }`}>
                              {cell.name}
                            </div>
                            <span className={`text-[9px] uppercase ${
                              isUser ? 'text-zinc-500' : 'text-zinc-600'
                            }`}>
                              {cell.position}
                            </span>
                          </div>
                        ) : (
                          <span className="text-zinc-700">—</span>
                        )}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** Availability display for a pool player in the draft room. */
function PoolAvailability({ poolPlayer }: { poolPlayer: PoolPlayer }) {
  const noSample = poolPlayer.sample === 'none'
  const isKicker = poolPlayer.position === 'PK'

  if (noSample) {
    return (
      <span className="text-[11px] text-zinc-500">
        {isKicker ? 'Kicker games not tracked' : 'Rookie — no NFL sample'}
      </span>
    )
  }

  const teamGames = poolTeamGames(poolPlayer)
  const missed = poolPlayer.games_missed

  if (teamGames == null || missed == null) {
    return (
      <span className="text-[11px] text-zinc-500">
        Availability unavailable
      </span>
    )
  }

  return (
    <>
      <div className="flex items-baseline gap-1.5">
        <span
          className={`font-mono tabular-nums text-sm font-semibold ${
            missed > 0 ? 'text-amber-400' : 'text-zinc-300'
          }`}
        >
          {poolPlayer.games_played}/{teamGames}
        </span>
        {missed > 0 && (
          <span className="text-[10px] text-zinc-600">missed {missed}</span>
        )}
      </div>
      <AvailabilityStrip
        weeksPlayed={poolPlayer.weeks_played}
        teamWeeks={poolPlayer.team_weeks}
        name={poolPlayer.name}
      />
    </>
  )
}

// ── Roster slot helpers ──

interface RosterSlot {
  label: string
  player: DraftPlayer | null
  poolPlayer: PoolPlayer | null
  isStarter: boolean
}

function buildRosterSlots(
  players: DraftPlayer[],
  playerMap: Map<number, PoolPlayer>,
): RosterSlot[] {
  const byPos: Record<string, DraftPlayer[]> = {}
  for (const p of players) {
    if (!byPos[p.position]) byPos[p.position] = []
    byPos[p.position].push(p)
  }

  const slots: RosterSlot[] = []

  function addSlot(label: string, pos: string, isStarter: boolean) {
    const arr = byPos[pos] ?? []
    const player = arr.shift() ?? null
    slots.push({
      label,
      player,
      poolPlayer: player ? playerMap.get(player.player_id) ?? null : null,
      isStarter,
    })
  }

  // Starters in order
  addSlot('QB', 'QB', true)
  addSlot('RB1', 'RB', true)
  addSlot('RB2', 'RB', true)
  addSlot('WR1', 'WR', true)
  addSlot('WR2', 'WR', true)
  addSlot('TE', 'TE', true)
  // FLEX: next RB/WR/TE
  const flexPlayer =
    (byPos['RB'] ?? [])[0] ??
    (byPos['WR'] ?? [])[0] ??
    (byPos['TE'] ?? [])[0] ??
    null
  if (flexPlayer) {
    // Remove from its position array
    const flexArr = byPos[flexPlayer.position]
    if (flexArr) flexArr.shift()
    slots.push({
      label: 'FLEX',
      player: flexPlayer,
      poolPlayer: playerMap.get(flexPlayer.player_id) ?? null,
      isStarter: true,
    })
  } else {
    slots.push({ label: 'FLEX', player: null, poolPlayer: null, isStarter: true })
  }
  addSlot('K', 'PK', true)
  addSlot('DEF', 'DEF', true)

  // Bench — remaining players
  const remaining = players.filter(p => !slots.some(s => s.player?.player_id === p.player_id))
  remaining.forEach((p, i) => {
    slots.push({
      label: `BE${i + 1}`,
      player: p,
      poolPlayer: playerMap.get(p.player_id) ?? null,
      isStarter: false,
    })
  })

  // Empty bench rows keep the full roster construction visible while drafting.
  for (let i = remaining.length; i < BENCH_SLOTS; i++) {
    slots.push({
      label: `BE${i + 1}`,
      player: null,
      poolPlayer: null,
      isStarter: false,
    })
  }

  return slots
}

function RosterSlotRow({ slot }: { slot: RosterSlot }) {
  const teamGames = slot.poolPlayer
    ? poolTeamGames(slot.poolPlayer)
    : null

  return (
    <div
      className={`flex items-center gap-2 px-4 py-2 text-xs ${
        slot.isStarter ? '' : 'opacity-70'
      }`}
    >
      <span
        className={`w-12 shrink-0 font-semibold tabular-nums ${
          slot.isStarter ? 'text-zinc-300' : 'text-zinc-500'
        }`}
      >
        {slot.label}
      </span>
      {slot.player ? (
        <>
          <span className="truncate font-medium text-zinc-200 flex-1">
            {slot.player.name}
          </span>
          <span className="text-[10px] text-zinc-500 shrink-0">
            {slot.player.position}
          </span>
          {slot.poolPlayer &&
            slot.poolPlayer.sample !== 'none' &&
            teamGames != null &&
            slot.poolPlayer.games_missed != null && (
            <span className="text-[10px] text-zinc-600 tabular-nums shrink-0">
              {slot.poolPlayer.games_played}/{teamGames}
            </span>
          )}
          {slot.poolPlayer && slot.poolPlayer.sample === 'none' && (
            <span className="text-[10px] text-zinc-600 shrink-0">
              {slot.poolPlayer.position === 'PK'
                ? 'no logs'
                : 'rookie'}
            </span>
          )}
        </>
      ) : (
        <span className="text-zinc-700 flex-1">—</span>
      )}
    </div>
  )
}
