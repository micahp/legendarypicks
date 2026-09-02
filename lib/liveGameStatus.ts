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

export function livePeriodTypeForLeague(league?: string): LivePeriodType {
  switch ((league || '').toLowerCase()) {
    case 'mlb': return 'inning'
    case 'nba':
    case 'nfl': return 'quarter'
    case 'nhl': return 'period'
    case 'ufc': return 'round'
    case 'cod': return 'game'
    case 'atp':
    case 'wta': return 'set'
    case 'wc':
    case 'lcup':
    case 'mls': return 'half'
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

export function formatLiveStatus(period?: LivePeriod, fallback?: string | null): string {
  // "LIVE · Q4 · 1:51" says the same thing twice: a quarter number IS the game
  // being in progress, and the badge this renders into is already coloured for
  // live. So the phase wins whenever we have one, and the word is kept only for
  // the case where we know a game is live but not where it is — which is the
  // one time it carries information. Matches WCContext's `phaseLabel || 'Live'`.
  const phase = phaseLabel(period)
  const clock = usableClock(period)
  if (phase) {
    return clock && clock !== phase ? `${phase} · ${clock}` : phase
  }

  const detail = fallback?.trim() || clock
  return detail && detail !== '0:00' ? `LIVE · ${detail}` : 'LIVE'
}
