export type LivePeriodType = 'inning' | 'period' | 'quarter' | 'round' | 'game' | 'half' | 'set'

export interface LivePeriod {
  number?: number | null
  type: LivePeriodType
  // Publisher wording for a phase when it is more precise than the number,
  // such as MLB's "Top 6th".
  display?: string | null
  // The running publisher clock. It stays separate from the phase so a detail
  // page can say both "Q4" and "1:51".
  clock?: string | null
}

const SOCCER_LEAGUES = new Set(['wc', 'unl', 'friendlies', 'lcup', 'mls', 'ligamx'])

export function isSoccerLeague(league?: string | null): boolean {
  return SOCCER_LEAGUES.has((league || '').toLowerCase())
}

export function livePeriodTypeForLeague(league?: string): LivePeriodType {
  switch ((league || '').toLowerCase()) {
    case 'mlb': return 'inning'
    case 'nba':
    case 'nfl':
    case 'ncaaf': return 'quarter'
    case 'nhl': return 'period'
    case 'ufc': return 'round'
    case 'cod': return 'game'
    case 'atp':
    case 'wta': return 'set'
    case 'wc':
    case 'unl':
    case 'friendlies':
    case 'lcup':
    case 'mls':
    case 'ligamx': return 'half'
    default: return 'period'
  }
}

function positiveNumber(value?: number | null): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null
}

function phaseLabel(period?: LivePeriod): string | null {
  if (!period) return null
  const number = positiveNumber(period.number)

  if (period.type === 'inning' && period.display) return period.display

  switch (period.type) {
    case 'inning': return number ? `Inning ${number}` : null
    case 'period': return number ? `P${number}` : null
    case 'quarter': return number ? `Q${number}` : null
    case 'round': return number ? `R${number}` : null
    case 'game': return number ? `Game ${number}` : null
    case 'set': return number ? `Set ${number}` : null
    case 'half':
      return number === 1 ? '1st Half' : number === 2 ? '2nd Half' : number ? `Half ${number}` : null
  }
}

function usableClock(period?: LivePeriod): string | null {
  if (!period || period.type === 'inning') return null
  const clock = period.clock?.trim()
  // ESPN publishes a literal 0:00 for a live baseball inning. It is not the
  // game state and must never displace the publisher's Top/Bot inning label.
  return clock && clock !== '0:00' ? clock : null
}

// ESPN says what is happening at a break in its own words: "Halftime" (NBA, NFL), "End of 2nd"
// (NHL, NBA), "Intermission". The running period number and a clock stuck at 0:00 read as
// "P2" / "Q2 · 0.0" there, which is wrong: the game is stopped between periods (Micah, 2026-10-08).
const BREAK_WORDING = /^(halftime|half time|intermission|end of (the )?(\d+(st|nd|rd|th)|first|second|third|fourth|regulation|ot|overtime)\b.*)$/i

const SPECIAL_STATUS = /^(delayed|suspended|postponed|cancelled|canceled|abandoned)\b/i

function footballClock(clock?: string | null, fallback?: string | null): string | null {
  const value = clock?.trim() || fallback?.trim().match(/^(\d{1,2}:\d{2})\s*-/)?.[1]
  const match = value?.match(/^(\d{1,2}):(\d{2})$/)
  return match ? `${match[1].padStart(2, '0')}:${match[2]}` : null
}

function ordinal(number: number): string {
  const lastTwo = number % 100
  const suffix = lastTwo >= 11 && lastTwo <= 13
    ? 'th'
    : number % 10 === 1 ? 'st' : number % 10 === 2 ? 'nd' : number % 10 === 3 ? 'rd' : 'th'
  return `${number}${suffix}`
}

function footballPhase(number: number): string {
  if (number <= 4) return ordinal(number)
  const overtime = number - 4
  return overtime === 1 ? 'OT' : `${overtime}OT`
}

function footballStatusFromDetail(detail?: string | null): string | null {
  const match = detail?.trim().match(/^(\d{1,2}:\d{2})\s*-\s*(\d+(?:st|nd|rd|th)|\d*OT)$/i)
  if (!match) return null
  const clock = footballClock(match[1])
  const phase = /OT$/i.test(match[2]) ? match[2].toUpperCase() : match[2]
  return clock ? `${clock} - ${phase}` : null
}

function nhlStatusFromDetail(detail?: string | null): string | null {
  const match = detail?.trim().match(/^(\d{1,2}:\d{2})\s*-\s*(\d+(?:st|nd|rd|th)|\d*OT)$/i)
  if (!match) return null
  const phase = match[2].toUpperCase().endsWith('OT')
    ? match[2].toUpperCase()
    : `P${parseInt(match[2], 10)}`
  return `${phase} · ${match[1]}`
}

function soccerMinute(period?: LivePeriod, fallback?: string | null): string | null {
  const value = period?.clock?.trim() || fallback?.trim()
  if (!value || /^(halftime|half time|full[ -]?time|ft)$/i.test(value)) return null
  const minute = value.match(/^(\d{1,3}(?:\+\d{1,2})?)(?:['’]|:\d{2})?$/)?.[1]
  return minute ? `${minute}'` : null
}

export function formatLiveStatus(period?: LivePeriod, fallback?: string | null, league?: string | null): string {
  const wording = fallback?.trim()
  if (wording && SPECIAL_STATUS.test(wording)) return wording

  const leagueCode = (league || '').toLowerCase()
  const number = positiveNumber(period?.number)

  if (leagueCode === 'nfl' || leagueCode === 'ncaaf') {
    if (wording && /^(halftime|half time)$/i.test(wording)) return wording
    if (!number) return footballStatusFromDetail(wording) || 'LIVE'

    const phase = footballPhase(number)
    let clock = footballClock(period?.clock, wording)
    // ESPN sometimes reports only "End of 1st" at the zero point. That wording
    // confirms the clock reached zero, so retain the football clock display.
    if (!clock && wording && /^end of (the )?\d+(st|nd|rd|th)\b/i.test(wording)) clock = '00:00'
    return clock ? `${clock} - ${phase}` : phase
  }

  if (isSoccerLeague(league)) {
    if (wording && /^(halftime|half time|full[ -]?time|ft)$/i.test(wording)) return wording
    return soccerMinute(period, wording) || 'LIVE'
  }

  if (leagueCode === 'nhl') {
    if (wording && /^intermission$/i.test(wording)) return wording
    if (!number) return nhlStatusFromDetail(wording) || 'LIVE'
    if (number > 3) {
      const overtime = number - 3
      const phase = overtime === 1 ? 'OT' : `${overtime}OT`
      const clock = usableClock(period)
      return clock ? `${phase} · ${clock}` : phase
    }
  }

  // "LIVE · Q4 · 1:51" says the same thing twice: a quarter number IS the game
  // being in progress, and the badge this renders into is already coloured for
  // live. So the phase wins whenever we have one, and the word is kept only for
  // the case where we know a game is live but not where it is — which is the
  // one time it carries information. Matches WCContext's `phaseLabel || 'Live'`.
  const phase = phaseLabel(period)
  const clock = usableClock(period)
  if (phase) {
    // Baseball keeps its own Top/Bot/Mid/End wording through `display`.
    if (period?.type !== 'inning' && wording && BREAK_WORDING.test(wording)) return wording
    return clock && clock !== phase ? `${phase} · ${clock}` : phase
  }

  const detail = fallback?.trim() || clock
  return detail && detail !== '0:00' ? `LIVE · ${detail}` : 'LIVE'
}
