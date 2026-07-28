import type { PoolPlayer } from '../../components/Leagues/types'

/**
 * The pool endpoint publishes the actual schedule weeks attached to each row.
 * Count that evidence instead of assuming every denominator is 17.
 */
export function poolTeamGames(
  player: Pick<PoolPlayer, 'team_weeks'>,
): number | null {
  return player.team_weeks.length > 0 ? player.team_weeks.length : null
}
