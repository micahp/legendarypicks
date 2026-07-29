/* ── The mock draft's number columns ────────────────────────────────────────
   Lifted out of DraftRoom.tsx when the draft room was split into tabs. They are
   here rather than inside PlayersTab because three surfaces render the same
   numbers — the pre-draft pool, the in-draft pool, and the results screen — and
   the moment two of them own a private copy they start disagreeing about a
   player, which is precisely how the roster builder ended up existing twice
   with only one of the two carrying a D/ST slot. */

import type { PoolPlayer } from '../Leagues/types'
import { AvailabilityStrip } from '../Leagues/NflDraftRoom'
import { poolTeamGames } from '../../lib/mockDraft/availability'

/* ── The headline stat ──────────────────────────────────────────────────────
   The research board (camp tab) renders five position-aware stat columns, which
   is right for research. This is not research: at the moment of a pick you are
   choosing, not studying, and the pool sits in a two-thirds grid column that is
   full-width-but-cramped on a phone. So the draft room takes ONE decisive number
   per position and spends the width it saves on bye week, which decides more
   picks in rounds 8-15 than a third decimal of expected points ever will.

   Per position, the number a drafter actually acts on:
     QB RB WR TE  → PPR / game played
     PK           → kicking points / game
     DEF          → D/ST points / game
   Under the 'All' filter the header stays generic, because one column is
   spanning three different units and the row's position chip says which. */

/** What we can honestly say about a player with no games in the reference season.
 *
 * "Rookie" was an inference, and a wrong one for anyone who simply missed the
 * year: the pool told a drafter Odell Beckham Jr. was a rookie while holding
 * eight of his prior-season games in the same table. We publish whether a prior
 * NFL sample exists, so neither branch has to guess — a player we have never
 * recorded is "no NFL sample" (not necessarily a rookie), and a player we have
 * recorded before is one who did not play, which is the far more useful fact. */
export function noSampleLabel(
  position: string,
  hasPriorNflSample?: boolean | null,
  referenceSeason?: number | null,
): string {
  if (position === 'PK') return 'Kicker games not tracked'
  if (hasPriorNflSample) {
    return referenceSeason != null
      ? `No ${referenceSeason} games`
      : 'No games last season'
  }
  return 'No NFL sample'
}

/* The season label comes from the payload's reference_season, never from a
   hardcoded year: a literal "2025" is true today and silently false in twelve
   months, the same class of defect as a stale bye week. The pool contract used
   to publish only contract/season/count, so this hedged with "last completed
   season"; it now publishes reference_season and the year is rendered from it.
   The hedge remains the fallback, because a label may not invent a year the
   server did not state.

   The season is in the HEADER, not only in the tooltip. ESPN's equivalent column
   is `PROJ` — a 2026 forecast — and the single most likely way to get this
   surface wrong is to copy that header onto last season's actuals. A header that
   states its own year cannot be misread as a projection. */
export function headlineStatFor(
  position: string,
  referenceSeason?: number | null,
): { header: string; title: string } {
  const when = referenceSeason != null ? `${referenceSeason}` : 'last completed season'
  const prefix = referenceSeason != null ? `${referenceSeason} ` : ''
  if (position === 'DEF') {
    return { header: `${prefix}D/ST Pts/G`, title: `D/ST fantasy points per game, ${when}` }
  }
  if (position === 'PK') {
    return { header: `${prefix}K Pts/G`, title: `Kicking points per game, ${when}` }
  }
  if (position === 'ALL') {
    return {
      header: `${prefix}Pts/G`,
      title: `Fantasy points per game, ${when} — PPR for skill positions, kicking points for K, D/ST points for defenses`,
    }
  }
  return { header: `${prefix}PPR/G`, title: `PPR points per game played, ${when}` }
}

/** The one number, resolved per row so a mixed 'All' view stays correct.
 *  Null is null: it is never a zero, and it is what the sort orders last. */
export function headlineValue(player: PoolPlayer): number | null {
  const value =
    player.position === 'DEF'
      ? player.dst_pts_per_game
      : player.position === 'PK'
        ? player.pk_pts_per_game
        : player.ppr_per_game_played
  return value ?? null
}

export function HeadlineStat({ player }: { player: PoolPlayer }) {
  const value = headlineValue(player)

  // Absent (pre-job16 payload) and null (genuinely no sample) render the same.
  // Neither is zero and neither may be rendered as zero.
  if (value == null) return <span className="text-zinc-700">—</span>

  return (
    <span className={player.sample === 'thin' ? 'text-zinc-500' : 'text-zinc-300'}>
      {value.toFixed(1)}
    </span>
  )
}

/* ── Expected fantasy points ────────────────────────────────────────────────
   The published xFP series (nflverse `total_fantasy_points_exp`, PPR), averaged
   per game. It is an *opportunity* number — what the targets, carries and air
   yards a player was actually given are worth to an average player — so it sits
   next to the outcome number rather than replacing it. A back who scored 21.8
   on 19.3 of opportunity beat his usage; the two columns only mean something
   together, which is why both ship on every mock-draft surface.

   Not a projection. Nothing here forecasts 2026; the header carries the season.
   Structurally null for K and D/ST, which have no xFP series at all. */

export const EXPECTED_PTS_HEADER = 'Exp PPR/G'

export function expectedPtsTitle(referenceSeason?: number | null): string {
  const when = referenceSeason != null ? `${referenceSeason}` : 'last completed season'
  return `Expected PPR points per game, ${when} — what the player's opportunity (targets, carries, air yards) was worth, not what he scored. Not a projection. No value for K or D/ST.`
}

export function ExpectedPts({ player }: { player: PoolPlayer }) {
  const value = player.xfp_per_game
  if (value == null) return <span className="text-zinc-700">—</span>
  return (
    <span className={player.sample === 'thin' ? 'text-zinc-500' : 'text-zinc-300'}>
      {value.toFixed(1)}
    </span>
  )
}

/** Games played, when we measured them. Null when we did not — a player with no
 *  sample has no availability, and 0/17 would be a claim we cannot support. */
export function availabilityValue(player: PoolPlayer): number | null {
  if (player.sample === 'none') return null
  if (poolTeamGames(player) == null || player.games_missed == null) return null
  return player.games_played ?? null
}

/** Availability display for a pool player in the draft room. */
export function PoolAvailability({
  poolPlayer,
  referenceSeason,
}: { poolPlayer: PoolPlayer; referenceSeason?: number | null }) {
  const noSample = poolPlayer.sample === 'none'

  if (noSample) {
    return (
      <span className="text-[11px] text-zinc-500">
        {noSampleLabel(poolPlayer.position, poolPlayer.has_prior_nfl_sample, referenceSeason)}
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
