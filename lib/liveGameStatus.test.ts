import { formatLiveStatus } from './liveGameStatus'

// The badge these strings render into is already coloured for live, so the word
// "LIVE" beside a quarter number was saying the same thing twice (Micah,
// 2026-08-17). It survives in exactly one case: a live game whose phase the
// publisher has not given us.
describe('formatLiveStatus', () => {
  it('shows the phase alone, without the word LIVE', () => {
    expect(formatLiveStatus({ type: 'quarter', number: 4 })).toBe('Q4')
    expect(formatLiveStatus({ type: 'period', number: 2 })).toBe('P2')
    expect(formatLiveStatus({ type: 'half', number: 1 })).toBe('1st Half')
    expect(formatLiveStatus({ type: 'set', number: 3 })).toBe('Set 3')
  })

  it('keeps the clock alongside the phase', () => {
    expect(formatLiveStatus({ type: 'quarter', number: 4, clock: '1:51' })).toBe('Q4 · 1:51')
  })

  it('prefers the publisher wording for a baseball inning and never its 0:00 clock', () => {
    expect(formatLiveStatus({ type: 'inning', number: 6, display: 'Top 6th', clock: '0:00' }))
      .toBe('Top 6th')
  })

  it('says LIVE only when the phase is unknown', () => {
    expect(formatLiveStatus(undefined)).toBe('LIVE')
    expect(formatLiveStatus({ type: 'quarter', number: 0 })).toBe('LIVE')
    expect(formatLiveStatus({ type: 'quarter' }, 'Halftime')).toBe('LIVE · Halftime')
  })

  it('does not present a bare 0:00 as a status', () => {
    expect(formatLiveStatus({ type: 'quarter' }, '0:00')).toBe('LIVE')
  })
})
