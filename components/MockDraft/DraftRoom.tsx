import { useMemo, useState, useEffect } from 'react'
import type { PoolPlayer } from '../Leagues/types'
import type { DraftState, DraftPlayer } from '../../lib/mockDraft/engine'
import {
  currentDrafter,
  isUserPick,
  getRosterState,
} from '../../lib/mockDraft/engine'
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
  userPicking: boolean
}

const TEAM_GAMES = 17  // fallback; prefer poolPlayer.team_games when available
const PICK_LEDGER_LIMIT = 15

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
export default function DraftRoom({ pool, draftState, onUserPick, userPicking }: Props) {
  // ── Filter state ──
  const [posFilter, setPosFilter] = useState<string>('ALL')
  const [teamFilter, setTeamFilter] = useState<string>('ALL')
  const [byeFilter, setByeFilter] = useState<string>('ALL')
  const [schedule, setSchedule] = useState<ScheduleTeam[] | null>(null)

  // Fetch schedule for bye filter
  useEffect(() => {
    let cancelled = false
    fetch('/api/nfl/schedule/2025')
      .then(r => r.json())
      .then(data => { if (!cancelled) setSchedule(data.teams ?? []) })
      .catch(() => { /* bye filter stays disabled */ })
    return () => { cancelled = true }
  }, [])

  // ── Filter options derived from pool + schedule ──
  const posOptions = useMemo(() => ['ALL', ...new Set(pool.map(p => p.position).sort())], [pool])
  const teamOptions = useMemo(() => ['ALL', ...new Set(pool.map(p => p.team).sort())], [pool])

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
    return ['ALL', ...[...weeks].sort((a, b) => a - b).map(String)]
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

  // Available pool, sorted by ADP
  const availablePool = useMemo(
    () => [...draftState.availablePool].sort((a, b) => a.adp - b.adp),
    [draftState.availablePool],
  )

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
  const drafter = currentDrafter(draftState)
  const round = Math.ceil(draftState.currentPick / draftState.teams)

  // Sort user's players into slot order
  const rosterSlots = useMemo(() => buildRosterSlots(userRoster.players, playerMap), [userRoster, playerMap])

  // Recent picks for the ledger
  const recentPicks = useMemo(() => {
    const all = [...draftState.picks].reverse().slice(0, PICK_LEDGER_LIMIT).reverse()
    return all
  }, [draftState.picks])

  return (
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
          ) : (
            <>
              <span className="text-sm font-semibold text-zinc-200">
                Team {drafter}
                {userTurn ? ' (you)' : ''}
              </span>
              <span className="text-xs text-zinc-500">on the clock</span>
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
                      className={`border-b border-zinc-800/40 transition-colors ${
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
                        {dp.adp.toFixed(1)}
                      </td>
                      <td className="py-2 pr-3 pl-1 text-center">
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
    </section>
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

  const tg = poolPlayer.team_games ?? TEAM_GAMES
  const missed = poolPlayer.games_missed ?? (tg - poolPlayer.games_played)
  return (
    <>
      <div className="flex items-baseline gap-1.5">
        <span
          className={`font-mono tabular-nums text-sm font-semibold ${
            missed > 0 ? 'text-amber-400' : 'text-zinc-300'
          }`}
        >
          {poolPlayer.games_played}/{tg}
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

  // Pad bench to 7 slots
  for (let i = remaining.length; i < 7; i++) {
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
          {slot.poolPlayer && slot.poolPlayer.sample !== 'none' && (
            <span className="text-[10px] text-zinc-600 tabular-nums shrink-0">
              {slot.poolPlayer.games_played}/{TEAM_GAMES}
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
