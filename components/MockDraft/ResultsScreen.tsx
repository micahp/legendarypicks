import { useMemo } from 'react'
import type { PoolPlayer } from '../Leagues/types'
import type { DraftState, DraftPlayer } from '../../lib/mockDraft/engine'
import { getRosterState } from '../../lib/mockDraft/engine'
import { poolTeamGames } from '../../lib/mockDraft/availability'
import { AvailabilityStrip } from '../Leagues/NflDraftRoom'
import { noSampleLabel } from './columns'
import { buildRosterSlots, type RosterSlot } from './roster'
import { positionLabel } from '../../lib/nfl/positionLabel'

interface Props {
  pool: PoolPlayer[]
  /** The season the pool's statistics describe, from the payload. */
  referenceSeason?: number | null
  draftState: DraftState
}

/**
 * Post-draft results screen.
 *
 * Design rules (honest-data-ui §6.4):
 *   - Roster by slot, scan-first: label, player, position, availability strip.
 *   - Headline: historical with n. "Your 2026 picks missed X of a possible Y games."
 *     NOT present-tense "averages 14.2 of 17 games available".
 *   - Both figures exclude rows without measured availability and state n.
 *   - Best/worst value vs ADP as "picked at X, ADP Y", not a computed score.
 *   - PPR declared on surface.
 *   - Durable URL pattern.
 *   - No trophy iconography, no gradients, no card shadows.
 */
export default function ResultsScreen({ pool, draftState, referenceSeason }: Props) {
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
    () => buildRosterSlots(userRoster.players, playerMap),
    [userRoster, playerMap],
  )

  // ── Headline computation ──
  const { totalMissed, totalPossible, excludedCount } = useMemo(() => {
    let missed = 0
    let possible = 0
    let excluded = 0

    for (const p of userRoster.players) {
      const pp = playerMap.get(p.player_id)
      if (!pp) continue
      const teamGames = poolTeamGames(pp)
      if (
        pp.sample === 'none' ||
        teamGames == null ||
        pp.games_missed == null
      ) {
        excluded++
        continue
      }
      missed += pp.games_missed
      possible += teamGames
    }

    return {
      totalMissed: missed,
      totalPossible: possible,
      excludedCount: excluded,
    }
  }, [userRoster, playerMap])

  // Field comparison — every roster in the league, at whatever size it is.
  const fieldStats = useMemo(() => {
    let fieldMissed = 0
    let fieldPossible = 0
    let fieldExcluded = 0

    for (let t = 1; t <= draftState.teams; t++) {
      const roster = getRosterState(draftState, t)
      for (const p of roster.players) {
        const pp = playerMap.get(p.player_id)
        if (!pp) continue
        const teamGames = poolTeamGames(pp)
        if (
          pp.sample === 'none' ||
          teamGames == null ||
          pp.games_missed == null
        ) {
          fieldExcluded++
          continue
        }
        fieldMissed += pp.games_missed
        fieldPossible += teamGames
      }
    }

    return {
      missed: fieldMissed,
      possible: fieldPossible,
      excluded: fieldExcluded,
    }
  }, [draftState, playerMap])

  // ── Best / worst value vs ADP ──
  const bestValue = useMemo(() => findBestValue(userRoster.players, draftState, playerMap, 'best'), [userRoster, draftState, playerMap])
  const worstValue = useMemo(() => findBestValue(userRoster.players, draftState, playerMap, 'worst'), [userRoster, draftState, playerMap])

  return (
    <section className="space-y-6">
      {/* ── Headline — historical with n ── */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 px-6 py-5">
        <h2 className="text-lg font-bold text-zinc-100">
          Your 2026 picks missed {totalMissed} of a possible {totalPossible} games last season
          {excludedCount > 0 && (
            <span className="ml-1 text-sm font-normal text-zinc-500">
              (excluding {excludedCount} player{excludedCount !== 1 ? 's' : ''} without measured availability)
            </span>
          )}
        </h2>
        <p className="mt-2 text-sm text-zinc-500">
          League-wide, all {draftState.teams} rosters missed {fieldStats.missed} of{' '}
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
            PPR · last completed season
          </span>
        </div>
        <div className="divide-y divide-zinc-800/50">
          {slots.map((slot, i) => (
            <ResultsSlotRow key={i} slot={slot} referenceSeason={referenceSeason} />
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

    </section>
  )
}

// ── Helpers ──

/* The roster builder used to live here as a second copy of DraftRoom's. Two
   copies of the same slot order is how a D/ST starting slot came to exist on one
   screen and not the other, and how both had to be found before the bug was
   fixed. It is now imported from ./roster — one definition, both surfaces. */

function ResultsSlotRow({
  slot,
  referenceSeason,
}: { slot: RosterSlot; referenceSeason?: number | null }) {
  const pp = slot.poolPlayer
  const noSample = pp?.sample === 'none'
  const teamGames = pp ? poolTeamGames(pp) : null
  const hasAvailability =
    !noSample && teamGames != null && pp?.games_missed != null

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
            {/* "Detroit Lions D/ST — D/ST · DET" in a row already labelled D/ST
                says it three times. A defense's name carries its position, so the
                repeat is dropped rather than styled smaller. */}
            <span className="text-[10px] text-zinc-600">
              {slot.label === positionLabel(pp.position)
                ? pp.team
                : `${positionLabel(pp.position)} · ${pp.team}`}
            </span>
          </div>

          {/* Availability strip */}
          <div className="shrink-0">
            {noSample ? (
              <span className="text-[10px] text-zinc-500">
                {noSampleLabel(pp?.position ?? '', pp?.has_prior_nfl_sample, referenceSeason)}
              </span>
            ) : hasAvailability ? (
              <AvailabilityStrip
                weeksPlayed={pp.weeks_played}
                teamWeeks={pp.team_weeks}
                name={pp.name}
              />
            ) : (
              <span className="text-[10px] text-zinc-500">
                Availability unavailable
              </span>
            )}
          </div>

          {/* Availability count */}
          <span className={`text-xs tabular-nums shrink-0 w-12 text-right ${
            noSample ? 'text-zinc-600' : 'text-zinc-400'
          }`}>
            {hasAvailability ? `${pp.games_played}/${teamGames}` : '—'}
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
