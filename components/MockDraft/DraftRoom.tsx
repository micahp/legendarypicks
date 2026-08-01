import { useMemo, useState, useEffect, useRef } from 'react'
import type { PoolPlayer } from '../Leagues/types'
import PlayerDetailOverlay from '../Leagues/PlayerDetailOverlay'
import type { DraftState, DraftPlayer } from '../../lib/mockDraft/engine'
import { isUserPick, getRosterState, userNextPick, nextTeam } from '../../lib/mockDraft/engine'
import { orderPositions } from '../../lib/nfl/positionLabel'
import { buildRosterSlots } from './roster'
import { sortOptions, sortPool, DEFAULT_SORT, type SortKey } from './sort'
import DraftHeader from './DraftHeader'
import DraftTabs, { type DraftTabId } from './DraftTabs'
import PlayersTab, { type PoolRow } from './PlayersTab'
import QueueTab from './QueueTab'
import BoardTab from './BoardTab'
import RostersTab from './RostersTab'

interface ScheduleTeam {
  team: string
  weeks_played: number[]
  bye_week: number | null
}

interface Props {
  pool: PoolPlayer[]
  /** The season the pool's statistics describe, from the payload. */
  referenceSeason?: number | null
  draftState: DraftState
  onUserPick: (playerId: number) => void
  onTimeout: () => void
  userPicking: boolean
  /** Exactly the player onTimeout will take at 0:00 — passed in rather than
   *  recomputed, so the header cannot promise one player and deliver another. */
  autoPick: DraftPlayer | null
  queue: number[]
  onAddToQueue: (playerId: number) => void
  onRemoveFromQueue: (playerId: number) => void
  onMoveQueueUp: (idx: number) => void
  onMoveQueueDown: (idx: number) => void
}

// The season being drafted. Matches pages/mock-draft.tsx's fetchPool(2026) and
// apiCreateDraft(2026, ...) — bye weeks must come from the same season as the draft.
const DRAFT_SEASON = 2026

const CLOCK_SECONDS = 30

// How many of your upcoming picks get a rule drawn in the list. Four is two
// snake turns ahead: enough to plan a round, few enough that the deeper ones do
// not pile up at the bottom of the pool where they would say nothing.
const DIVIDER_LOOKAHEAD = 4

/**
 * The draft room shell.
 *
 * It owns three things and delegates the rest: the clock, the pool derivation
 * (filter → sort → your-pick rules), and which tab is open. Everything that
 * renders lives in DraftHeader / PlayersTab / QueueTab / BoardTab / RostersTab.
 * This file was 1,053 lines with all of that inline, which is the same shape of
 * file in which a draft board ended up wired to a hook that was never called
 * while eight green gates said nothing.
 *
 * Design rules (honest-data-ui §5, §6.2):
 *   - Accent (amber) marks absence only — never on the clock, your pick, or a
 *     drafted row.
 *   - On the clock: weight + position + rule. NOT colour.
 *   - Clock: tabular figures, may change weight under 10s, never red.
 */
export default function DraftRoom({
  pool, referenceSeason, draftState, onUserPick, onTimeout, userPicking, autoPick,
  queue, onAddToQueue, onRemoveFromQueue, onMoveQueueUp, onMoveQueueDown,
}: Props) {
  const [tab, setTab] = useState<DraftTabId>('players')
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null)
  const [posFilter, setPosFilter] = useState<string>('ALL')
  const [teamFilter, setTeamFilter] = useState<string>('ALL')
  const [byeFilter, setByeFilter] = useState<string>('ALL')
  const [sortKey, setSortKey] = useState<SortKey>(DEFAULT_SORT)
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

  // ── Filter options ──
  // Authored order, from the shared constant. Deriving this with `.sort()` is
  // what put D/ST and K ahead of the quarterback.
  // The backend contract already limits the pool to fantasy positions. Keep
  // the allowlist here so an invalid future payload cannot create a stray pill.
  const FANTASY_POSITIONS = new Set(['QB', 'RB', 'WR', 'TE', 'PK', 'DEF'])
  const posOptions = useMemo(
    () => ['ALL', ...orderPositions(pool.map(p => p.position)).filter(p => FANTASY_POSITIONS.has(p))],
    [pool],
  )
  const teamOptions = useMemo(
    () => ['ALL', ...Array.from(new Set(pool.map(p => p.team))).sort()],
    [pool],
  )

  const byeMap = useMemo(() => {
    const m = new Map<string, number | null>()
    for (const t of (schedule ?? [])) m.set(t.team, t.bye_week)
    return m
  }, [schedule])

  const byeOptions = useMemo(() => {
    const weeks = new Set<number>()
    for (const t of (schedule ?? [])) { if (t.bye_week != null) weeks.add(t.bye_week) }
    return ['ALL', ...Array.from(weeks).sort((a, b) => a - b).map(String)]
  }, [schedule])

  const playerMap = useMemo(() => {
    const m = new Map<number, PoolPlayer>()
    for (const p of pool) m.set(p.player_id, p)
    return m
  }, [pool])

  // Positional rank by ADP, over the WHOLE pool — not the available pool. "RB4"
  // has to keep meaning the 4th-best back all draft long; recomputing it against
  // what is left would renumber every remaining player after each pick and turn a
  // stable identifier into a countdown. Derived from ADP, so it is labelled as
  // ADP's ranking and not presented as ours.
  const posRank = useMemo(() => {
    const byPos = new Map<string, PoolPlayer[]>()
    for (const p of pool) {
      const list = byPos.get(p.position)
      if (list) list.push(p)
      else byPos.set(p.position, [p])
    }
    const m = new Map<number, number>()
    for (const list of Array.from(byPos.values())) {
      list
        .filter(p => p.adp != null)
        .sort((a, b) => (a.adp as number) - (b.adp as number))
        .forEach((p, i) => m.set(p.player_id, i + 1))
    }
    return m
  }, [pool])

  const draftedIds = useMemo(() => {
    const s = new Set<number>()
    for (const pick of draftState.picks) s.add(pick.player_id)
    return s
  }, [draftState.picks])

  // availablePool is ALREADY sorted by createDraft (numeric ADP ascending, null ADP
  // last) and applyPick filters, which preserves that order. Every other order goes
  // through sortPool, which keeps nulls last in both directions — a naive
  // `a.adp - b.adp` coerces null to 0 and floats all 32 D/ST above pick 1.
  const availablePool = draftState.availablePool

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

  const sortedPool = useMemo(
    () => sortPool(filteredPool, sortKey, { playerMap, byeMap }),
    [filteredPool, sortKey, playerMap, byeMap],
  )

  const userTurn = isUserPick(draftState)
  // Your turn is not the same as being able to pick. Between your click and the
  // state that comes back, commitPick has already taken your pick and is running
  // every bot up to your next turn — and through all of it draftState still says
  // it is your turn. A Draft button left live in that window applies a second
  // pick against a stale state. `userPicking` is the client's own "I am accepting
  // a pick" flag, and it is the honest one to render against.
  const onClock = userTurn && userPicking && !draftState.completed

  // ── Your upcoming picks, and the rules drawn where ADP expects them ──
  // Purely derived from userNextPick + ADP, so it is honest exactly as long as it
  // is labelled an ADP expectation rather than a promise — which the row says.
  const upcomingPicks = useMemo(() => {
    if (draftState.completed) return []
    const total = draftState.teams * draftState.rounds
    const out: number[] = []
    for (let p = draftState.currentPick; p <= total && out.length < DIVIDER_LOOKAHEAD; p++) {
      if (nextTeam(p, draftState.teams) === draftState.seat) out.push(p)
    }
    return out
  }, [
    draftState.currentPick, draftState.teams, draftState.rounds,
    draftState.seat, draftState.completed,
  ])

  const rows = useMemo<PoolRow[]>(() => {
    // The rules mark where ADP says your turn falls. Under any other sort the
    // list is no longer in ADP order, so the same rule would be pointing at
    // nothing — it is dropped rather than left to mislead.
    if (sortKey !== 'adp') return sortedPool.map(dp => ({ kind: 'player', dp }))

    const divider = (pickNo: number): PoolRow => ({
      kind: 'divider',
      pickNo,
      round: Math.ceil(pickNo / draftState.teams),
      inRound: ((pickNo - 1) % draftState.teams) + 1,
    })

    const out: PoolRow[] = []
    const pending = [...upcomingPicks]
    for (const dp of sortedPool) {
      // A null ADP is "no published expectation". It sorts last, so it is below
      // every one of your remaining picks by construction.
      while (pending.length > 0 && (dp.adp == null || dp.adp >= pending[0])) {
        out.push(divider(pending.shift() as number))
      }
      out.push({ kind: 'player', dp })
    }
    for (const p of pending) out.push(divider(p))
    return out
  }, [sortedPool, sortKey, upcomingPicks, draftState.teams])

  const userRoster = useMemo(() => getRosterState(draftState, draftState.seat), [draftState])
  const rosterSlots = useMemo(
    () => buildRosterSlots(userRoster.players, playerMap),
    [userRoster, playerMap],
  )
  const openStarters = rosterSlots.filter(s => s.isStarter && !s.player).length

  const queuePlayers = useMemo(() => {
    const lookup = new Map(draftState.playerPool.map(p => [p.player_id, p]))
    return queue
      .map(id => lookup.get(id))
      .filter((p): p is DraftPlayer => p != null && !draftedIds.has(p.player_id))
  }, [queue, draftState.playerPool, draftedIds])

  // ── Clock ──
  // The countdown carries the pick it belongs to. On the render where a new turn
  // begins, `seconds` still holds the *previous* turn's value — pairing the two in one
  // state object means a stale 0 can never be read as this turn's expiry. In a snake
  // draft the user can pick twice in a row (e.g. 22 then 27), and `userTurn` does not
  // change across those, so neither a boolean guard nor `currentPick` alone is enough.
  //
  // It lives here, above the tabs, and not inside PlayersTab: an effect that unmounts
  // with a tab is an effect that restarts at 0:30 every time you glance at the board,
  // which is a clock that never expires.
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

  return (
    <>
      <section className="space-y-3">
        <DraftHeader
          draftState={draftState}
          clockSeconds={userTurn ? clock.seconds : null}
          onClock={onClock}
          autoPick={autoPick}
        />

        <DraftTabs value={tab} onChange={setTab} queueCount={queuePlayers.length} />

        <div
          role="tabpanel"
          data-tab={tab}
          id={`panel-${tab}`}
          aria-labelledby={`tab-${tab}`}
          tabIndex={0}
        >
          {tab === 'players' && (
            <PlayersTab
              rows={rows}
              playerMap={playerMap}
              posRank={posRank}
              byeMap={byeMap}
              referenceSeason={referenceSeason}
              posOptions={posOptions}
              posFilter={posFilter}
              onPosFilter={setPosFilter}
              teamOptions={teamOptions}
              teamFilter={teamFilter}
              onTeamFilter={setTeamFilter}
              byeOptions={byeOptions}
              byeFilter={byeFilter}
              onByeFilter={setByeFilter}
              scheduleLoaded={schedule != null}
              sortOptions={sortOptions(referenceSeason)}
              sortKey={sortKey}
              onSort={key => setSortKey(key as SortKey)}
              onClearFilters={() => { setPosFilter('ALL'); setTeamFilter('ALL'); setByeFilter('ALL') }}
              shown={sortedPool.length}
              available={availablePool.length}
              drafted={draftedIds.size}
              queue={queue}
              onClock={onClock}
              completed={draftState.completed}
              onSelectPlayer={setSelectedPlayerId}
              onDraft={onUserPick}
              onQueue={onAddToQueue}
              onUnqueue={onRemoveFromQueue}
            />
          )}

          {tab === 'queue' && (
            <QueueTab
              players={queuePlayers}
              onRemove={onRemoveFromQueue}
              onMoveUp={onMoveQueueUp}
              onMoveDown={onMoveQueueDown}
              onSelect={setSelectedPlayerId}
            />
          )}

          {tab === 'board' && <BoardTab draftState={draftState} />}

          {tab === 'rosters' && (
            <RostersTab
              draftState={draftState}
              playerMap={playerMap}
              referenceSeason={referenceSeason}
            />
          )}
        </div>

        {/* What you still need is the question every pick is answering, so it
            stays one glance away from the list without costing the list a tab. */}
        {tab === 'players' && (
          <p className="text-xs text-zinc-600">
            {openStarters} starting slot{openStarters === 1 ? '' : 's'} still open · your next
            pick is #{userNextPick(draftState) ?? '—'}
          </p>
        )}
      </section>

      {selectedPlayerId != null && (() => {
        const p = playerMap.get(selectedPlayerId)
        return (
        <PlayerDetailOverlay
          playerId={selectedPlayerId}
          onClose={() => setSelectedPlayerId(null)}
          poolName={p?.name}
          currentPick={draftState.currentPick}
          posRank={posRank.get(selectedPlayerId)}
          byeWeek={byeMap.get(p?.team ?? '') ?? null}
          onDraft={onUserPick}
          onQueue={onAddToQueue}
          canDraft={onClock && !draftedIds.has(selectedPlayerId)}
          queued={queue.includes(selectedPlayerId)}
          stat_ranks={p?.stat_ranks ?? null}
        />
        )
      })()}
    </>
  )
}
