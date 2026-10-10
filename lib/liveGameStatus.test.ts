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

  // 2026-10-08: an NHL game between periods read "P2" and an NBA game at the half read
  // "Q2 · 0.0". ESPN's own wording for the break wins over the period number and its clock.
  it('says what the break is when the publisher does', () => {
    expect(formatLiveStatus({ type: 'period', number: 2, clock: '0:00' }, 'End of 2nd')).toBe('End of 2nd')
    expect(formatLiveStatus({ type: 'period', number: 1 }, 'End of 1st Period')).toBe('End of 1st Period')
    expect(formatLiveStatus({ type: 'quarter', number: 2, clock: '0.0' }, 'Halftime')).toBe('Halftime')
    expect(formatLiveStatus({ type: 'quarter', number: 1, clock: '0.0' }, 'End of 1st')).toBe('End of 1st')
    expect(formatLiveStatus({ type: 'period', number: 2 }, 'Intermission')).toBe('Intermission')
  })

  it('keeps the period and clock while the game is running', () => {
    expect(formatLiveStatus({ type: 'period', number: 3, clock: '20:00' }, '20:00 - 3rd')).toBe('P3 · 20:00')
    expect(formatLiveStatus({ type: 'quarter', number: 3, clock: '11:57' }, '11:57 - 3rd')).toBe('Q3 · 11:57')
    expect(formatLiveStatus({ type: 'period', number: 2, clock: '5:12' }, null)).toBe('P2 · 5:12')
  })

  it('leaves a baseball inning to its own wording', () => {
    expect(formatLiveStatus({ type: 'inning', number: 6, display: 'Mid 6th' }, 'End of 6th')).toBe('Mid 6th')
  })

  it('says LIVE only when the phase is unknown', () => {
    expect(formatLiveStatus(undefined)).toBe('LIVE')
    expect(formatLiveStatus({ type: 'quarter', number: 0 })).toBe('LIVE')
    expect(formatLiveStatus({ type: 'quarter' }, 'Halftime')).toBe('LIVE · Halftime')
  })

  it('does not present a bare 0:00 as a status', () => {
    expect(formatLiveStatus({ type: 'quarter' }, '0:00')).toBe('LIVE')
  })

  it('uses football clocks and labels overtime after the fourth quarter', () => {
    expect(formatLiveStatus({ type: 'quarter', number: 3, clock: '0:00' }, null, 'nfl')).toBe('00:00 - 3rd')
    expect(formatLiveStatus({ type: 'quarter', number: 4, clock: '1:51' }, null, 'nfl')).toBe('01:51 - 4th')
    expect(formatLiveStatus({ type: 'quarter', number: 5, clock: '7:31' }, null, 'nfl')).toBe('07:31 - OT')
    expect(formatLiveStatus({ type: 'quarter', number: 6, clock: '3:12' }, null, 'ncaaf')).toBe('03:12 - 2OT')
    expect(formatLiveStatus({ type: 'quarter', number: 3 }, 'End of 3rd', 'nfl')).toBe('00:00 - 3rd')
    expect(formatLiveStatus({ type: 'quarter', number: 2 }, 'Halftime', 'nfl')).toBe('Halftime')
    expect(formatLiveStatus({ type: 'quarter', number: 2, clock: '0:00' }, 'Delayed', 'ncaaf')).toBe('Delayed')
    expect(formatLiveStatus(undefined, '0:00 - 3rd', 'nfl')).toBe('00:00 - 3rd')
  })

  it('labels NHL periods after the third as overtime', () => {
    expect(formatLiveStatus({ type: 'period', number: 4, clock: '12:34' }, null, 'nhl')).toBe('OT · 12:34')
    expect(formatLiveStatus({ type: 'period', number: 5, clock: '8:02' }, null, 'nhl')).toBe('2OT · 8:02')
    expect(formatLiveStatus(undefined, '8:02 - OT', 'nhl')).toBe('OT · 8:02')
  })

  it('shows only the running minute for soccer and preserves break wording', () => {
    expect(formatLiveStatus({ type: 'half', number: 1, clock: "6'" }, 'First Half', 'mls')).toBe("6'")
    expect(formatLiveStatus({ type: 'half', number: 2, clock: "73'" }, 'Second Half', 'lcup')).toBe("73'")
    expect(formatLiveStatus({ type: 'half', number: 2 }, 'Halftime', 'mls')).toBe('Halftime')
  })
})
