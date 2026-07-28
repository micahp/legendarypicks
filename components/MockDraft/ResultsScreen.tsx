import { useMemo } from 'react'
import type { PoolPlayer } from '../Leagues/types'
import type { DraftState, DraftPlayer } from '../../lib/mockDraft/engine'
import { getRosterState } from '../../lib/mockDraft/engine'
import { AvailabilityStrip } from '../Leagues/NflDraftRoom'

interface Props {
  pool: PoolPlayer[]
  draftState: DraftState
}

const TEAM_GAMES = 17

/**
 * Post-draft results screen.
 *
 * Design rules (honest-data-ui §6.4):
 *   - Roster by slot, scan-first: label, player, position, availability strip.
 *   - Headline: historical with n. "Your 2026 picks missed X of a possible Y games."
 *     NOT present-tense "averages 14.2 of 17 games available".
 *   - Both figures must exclude no-sample players from denominator, state n.
 *   - Best/worst value vs ADP as "picked at X, ADP Y", not a computed score.
 *   - PPR declared on surface.
 *   - Durable URL pattern.
 *   - No trophy iconography, no gradients, no card shadows.
 */
export default function ResultsScreen({ pool, draftState }: Props) {
  const playerMap = useMemo(() => {
    const m = new Map<number, PoolPlayer>()
    for (const p of pool) m.set(p.player_id, p)
    return m
  }, [pool])

  const userRoster = useMemo(
    () => getRosterState(draftState, draftState.seat),
    [draftState],
  )

  const slots = useMemo(
    () => buildResultsSlots(userRoster.players, playerMap),
    [userRoster, playerMap],
  )

  // ── Headline computation ──
  const { totalGamesPlayed, totalPossible, excludedCount, excludedNames } = useMemo(() => {
    let played = 0
    let possible = 0
    let excluded = 0
    const exNames: string[] = []

    for (const p of userRoster.players) {
      const pp = playerMap.get(p.player_id)
      if (!pp) continue
      if (pp.sample === 'none') {
        excluded++
        exNames.push(p.name)
        continue
      }
      played += pp.games_played
      possible += TEAM_GAMES
    }

    return {
      totalGamesPlayed: played,
      totalPossible: possible,
      excludedCount: excluded,
      excludedNames: exNames,
    }
  }, [userRoster, playerMap])

  // Field comparison (all 12 teams)
  const fieldStats = useMemo(() => {
    let fieldPlayed = 0
    let fieldPossible = 0
    let fieldExcluded = 0

    for (let t = 1; t <= draftState.teams; t++) {
      const roster = getRosterState(draftState, t)
      for (const p of roster.players) {
        const pp = playerMap.get(p.player_id)
        if (!pp) continue
        if (pp.sample === 'none') {
          fieldExcluded++
          continue
        }
        fieldPlayed += pp.games_played
        fieldPossible += TEAM_GAMES
      }
    }

    return { played: fieldPlayed, possible: fieldPossible, excluded: fieldExcluded }
  }, [draftState, playerMap])

  const totalMissed = totalPossible - totalGamesPlayed

  // ── Best / worst value vs ADP ──
  const bestValue = useMemo(() => findBestValue(userRoster.players, draftState, playerMap, 'best'), [userRoster, draftState, playerMap])
  const worstValue = useMemo(() => findBestValue(userRoster.players, draftState, playerMap, 'worst'), [userRoster, draftState, playerMap])

  // ── Durable URL — just the draft id ──
  const shareUrl = typeof window !== 'undefined'
    ? `${window.location.origin}/mock-draft?id=${draftState.id}`
    : ''

  return (
    <section className="space-y-6">
      {/* ── Headline — historical with n ── */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 px-6 py-5">
        <h2 className="text-lg font-bold text-zinc-100">
          Your 2026 picks missed {totalMissed} of a possible {totalPossible} games last season
          {excludedCount > 0 && (
            <span className="ml-1 text-sm font-normal text-zinc-500">
              (excluding {excludedCount} player{excludedCount !== 1 ? 's' : ''} with no NFL sample)
            </span>
          )}
        </h2>
        <p className="mt-2 text-sm text-zinc-500">
          League-wide, all 12 rosters missed {fieldStats.possible - fieldStats.played} of{' '}
          {fieldStats.possible} possible games
          {fieldStats.excluded > 0 && (
            <span> (excluding {fieldStats.excluded} without data)</span>
          )}
          . PPR scoring.
        </p>
      </div>

      {/* ── Roster by slot ── */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-hidden">
        <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-zinc-300">
            Your Roster
          </h3>
          <span className="text-xs text-zinc-500">
            PPR · 2026 season
          </span>
        </div>
        <div className="divide-y divide-zinc-800/50">
          {slots.map((slot, i) => (
            <ResultsSlotRow key={i} slot={slot} />
          ))}
        </div>
      </div>

      {/* ── Value vs ADP ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {bestValue && (
          <ValueCard label="Best value vs ADP" entry={bestValue} />
        )}
        {worstValue && (
          <ValueCard label="Worst value vs ADP" entry={worstValue} />
        )}
      </div>

      {/* ── Share URL ── */}
      {shareUrl && (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-3">
          <p className="text-xs text-zinc-500 mb-1">Share this draft</p>
          <code className="text-sm text-zinc-400 break-all">{shareUrl}</code>
        </div>
      )}
    </section>
  )
}

// ── Helpers ──

interface ResultsSlot {
  label: string
  player: DraftPlayer | null
  poolPlayer: PoolPlayer | null
  isStarter: boolean
  pickNo: number | null
}

function buildResultsSlots(
  players: DraftPlayer[],
  playerMap: Map<number, PoolPlayer>,
): ResultsSlot[] {
  const byPos: Record<string, DraftPlayer[]> = {}
  for (const p of players) {
    if (!byPos[p.position]) byPos[p.position] = []
    byPos[p.position].push(p)
  }

  const slots: ResultsSlot[] = []
  const used = new Set<number>()

  function addSlot(label: string, pos: string, isStarter: boolean) {
    const arr = byPos[pos] ?? []
    const player = arr.shift() ?? null
    if (player) used.add(player.player_id)
    slots.push({
      label,
      player,
      poolPlayer: player ? playerMap.get(player.player_id) ?? null : null,
      isStarter,
      pickNo: null,
    })
  }

  addSlot('QB', 'QB', true)
  addSlot('RB1', 'RB', true)
  addSlot('RB2', 'RB', true)
  addSlot('WR1', 'WR', true)
  addSlot('WR2', 'WR', true)
  addSlot('TE', 'TE', true)

  const flexPlayer =
    (byPos['RB'] ?? [])[0] ??
    (byPos['WR'] ?? [])[0] ??
    (byPos['TE'] ?? [])[0] ??
    null
  if (flexPlayer) {
    const flexArr = byPos[flexPlayer.position]
    if (flexArr) flexArr.shift()
    used.add(flexPlayer.player_id)
    slots.push({
      label: 'FLEX',
      player: flexPlayer,
      poolPlayer: playerMap.get(flexPlayer.player_id) ?? null,
      isStarter: true,
      pickNo: null,
    })
  } else {
    slots.push({ label: 'FLEX', player: null, poolPlayer: null, isStarter: true, pickNo: null })
  }
  addSlot('K', 'PK', true)

  const remaining = players.filter(p => !used.has(p.player_id))
  remaining.forEach((p, i) => {
    slots.push({
      label: `BE${i + 1}`,
      player: p,
      poolPlayer: playerMap.get(p.player_id) ?? null,
      isStarter: false,
      pickNo: null,
    })
  })

  for (let i = remaining.length; i < 7; i++) {
    slots.push({
      label: `BE${i + 1}`,
      player: null,
      poolPlayer: null,
      isStarter: false,
      pickNo: null,
    })
  }

  return slots
}

function ResultsSlotRow({ slot }: { slot: ResultsSlot }) {
  const pp = slot.poolPlayer
  const noSample = pp?.sample === 'none'
  const isKicker = pp?.position === 'PK'

  return (
    <div className={`flex items-center gap-3 px-4 py-2.5 ${slot.isStarter ? '' : 'opacity-60'}`}>
      <span
        className={`w-12 shrink-0 font-semibold text-xs tabular-nums ${
          slot.isStarter ? 'text-zinc-300' : 'text-zinc-500'
        }`}
      >
        {slot.label}
      </span>

      {slot.player && pp ? (
        <>
          <div className="flex-1 min-w-0">
            <span className="font-medium text-zinc-200 truncate block">
              {slot.player.name}
            </span>
            <span className="text-[10px] text-zinc-600">
              {pp.position} · {pp.team}
            </span>
          </div>

          {/* Availability strip */}
          <div className="shrink-0">
            {noSample ? (
              <span className="text-[10px] text-zinc-500">
                {isKicker ? 'Kicker games not tracked' : 'Rookie — no NFL sample'}
              </span>
            ) : (
              <AvailabilityStrip
                weeksPlayed={pp.weeks_played}
                teamWeeks={pp.team_weeks}
                name={pp.name}
              />
            )}
          </div>

          {/* Availability count */}
          <span className={`text-xs tabular-nums shrink-0 w-12 text-right ${
            noSample ? 'text-zinc-600' : 'text-zinc-400'
          }`}>
            {noSample ? '—' : `${pp.games_played}/${TEAM_GAMES}`}
          </span>

          {/* ADP */}
          <span className="text-xs text-zinc-600 tabular-nums shrink-0 w-14 text-right">
            ADP {pp.adp != null ? pp.adp.toFixed(1) : '—'}
          </span>
        </>
      ) : (
        <span className="text-zinc-700 flex-1">—</span>
      )}
    </div>
  )
}

interface ValueEntry {
  player: DraftPlayer
  poolPlayer: PoolPlayer
  pickNo: number
  adp: number
  diff: number  // pickNo - adp; negative means picked later than ADP (good value)
}

function findBestValue(
  players: DraftPlayer[],
  draftState: DraftState,
  playerMap: Map<number, PoolPlayer>,
  direction: 'best' | 'worst',
): ValueEntry | null {
  let best: ValueEntry | null = null

  for (const player of players) {
    const pp = playerMap.get(player.player_id)
    if (!pp || pp.adp == null) continue

    // Find which pick this was
    const pick = draftState.picks.find(p => p.player_id === player.player_id)
    if (!pick) continue

    const diff = pick.pick_no - pp.adp // negative = value (picked later than ADP)
    const entry: ValueEntry = { player, poolPlayer: pp, pickNo: pick.pick_no, adp: pp.adp, diff }

    if (!best) {
      best = entry
      continue
    }

    if (direction === 'best') {
      // Most negative diff = best value
      if (entry.diff < best.diff) best = entry
    } else {
      // Most positive diff = worst value (reached too early)
      if (entry.diff > best.diff) best = entry
    }
  }

  return best
}

function ValueCard({ label, entry }: { label: string; entry: ValueEntry }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-3">
      <p className="text-[11px] text-zinc-500 uppercase tracking-wider mb-1">{label}</p>
      <p className="text-sm font-semibold text-zinc-200">{entry.player.name}</p>
      <p className="text-xs text-zinc-400 mt-0.5">
        Picked at{' '}
        <span className="font-mono tabular-nums text-zinc-300">{entry.pickNo}</span>
        , ADP{' '}
        <span className="font-mono tabular-nums text-zinc-300">{entry.adp.toFixed(1)}</span>
        <span className={`ml-1 ${entry.diff < 0 ? 'text-emerald-400' : 'text-zinc-500'}`}>
          ({entry.diff < 0 ? '' : '+'}{entry.diff.toFixed(1)})
        </span>
      </p>
    </div>
  )
}
