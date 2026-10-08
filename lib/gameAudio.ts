/**
 * Live radio for scoreboard games: each team's own flagship, every day.
 *
 * Keyed by league and the scoreboard's team abbreviation (Game.teamId), so a
 * game gets its audio from the two teams playing it, not from a per-day list.
 * Source and verification are in data/radio-listen.json `_meta`: NHL uses
 * TuneIn's dedicated team stations; MLB uses the flagship MLB StatsAPI publishes
 * per game; NBA uses LP's flagship list. Every link was matched on the station's
 * own call sign and frequency and its page answered 200.
 *
 * The card plays the publisher's own direct stream in the page, like the World
 * Cup player; nothing is relayed through LP. A team with no verified stream has
 * no entry, and its games fall back to the other team's radio or show nothing.
 */
import listen from '../data/radio-listen.json'

export interface GameAudio {
  team: string
  label: string
  station: string
  href: string
  provider: string
  /** Direct HTTPS audio from the publisher, played in the page. */
  stream: string
}

type LeagueKey = 'nhl' | 'mlb' | 'nba'
type Entry = { label: string; station: string; href: string; provider: string; stream?: string }
const TABLE = listen as unknown as Record<LeagueKey, Record<string, Entry>>

// The scoreboard has used both spellings for these clubs.
const ALIAS: Record<string, Record<string, string>> = {
  nhl: { UTAH: 'UTA' },
  nba: { UTA: 'UTAH' },
}

export function teamAudio(league: string | undefined, team: string | undefined): GameAudio | null {
  const lg = (league || '').toLowerCase() as LeagueKey
  if (!team || !(lg in TABLE)) return null
  const key = ALIAS[lg]?.[team] ?? team
  const e = TABLE[lg][key]
  return e && e.stream ? { team, ...e, stream: e.stream } : null
}

/** Home team first, then away; teams without a verified player are left out. */
export function audioForGame(league: string | undefined, homeTeam: string | undefined, awayTeam: string | undefined): GameAudio[] {
  return [teamAudio(league, homeTeam), teamAudio(league, awayTeam)].filter((a): a is GameAudio => !!a)
}
