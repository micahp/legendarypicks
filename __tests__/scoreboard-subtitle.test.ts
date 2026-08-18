import { normalizeGame } from '../services/sports'

/**
 * The board's section heading names the event, not just the segment.
 *
 * Tennis has always read "Cincinnati Open" because a tennis row carries only
 * `event`. A UFC row carries `card_segment` too, and the segment used to win --
 * so three different cards in one month all appeared under "MAIN CARD" and the
 * board never said which one you were looking at.
 */
describe('scoreboard section heading', () => {
  it('leads with the UFC event and keeps the card segment after it', () => {
    const g = normalizeGame({
      game_id: '401903488',
      date: '2026-08-18T23:00Z',
      state: 'pre',
      event: "Dana White's Contender Series: Season 10, Week 2",
      card_segment: 'Main Card',
      home: { abbrev: 'AAA', name: 'A' },
      away: { abbrev: 'BBB', name: 'B' },
    }, 'ufc')
    expect(g.subtitle).toBe("Dana White's Contender Series: Season 10, Week 2 · Main Card")
  })

  it('still separates prelims from the main card', () => {
    const base = { game_id: '1', date: '2026-08-18T21:00Z', state: 'pre',
                   event: 'UFC 330: Makhachev vs. Machado Garry' }
    const prelims = normalizeGame({ ...base, card_segment: 'Prelims' }, 'ufc')
    const main = normalizeGame({ ...base, card_segment: 'Main Card' }, 'ufc')
    expect(prelims.subtitle).not.toBe(main.subtitle)
    expect(prelims.subtitle).toContain('UFC 330')
    expect(main.subtitle).toContain('Main Card')
  })

  it('leaves tennis exactly as it was', () => {
    const g = normalizeGame({
      game_id: '181904', date: '2026-08-18T01:05Z', state: 'post',
      event: 'Cincinnati Open',
    }, 'atp')
    expect(g.subtitle).toBe('Cincinnati Open')
  })

  it('falls back to the segment when no event is published', () => {
    const g = normalizeGame({
      game_id: '2', date: '2026-08-18T23:00Z', state: 'pre',
      card_segment: 'Main Card',
    }, 'ufc')
    expect(g.subtitle).toBe('Main Card')
  })

  it('leaves a team-sport row with no subtitle at all', () => {
    const g = normalizeGame({
      game_id: '3', date: '2026-08-18T22:35Z', state: 'pre',
      home: { abbrev: 'NYY' }, away: { abbrev: 'BAL' },
    }, 'mlb')
    expect(g.subtitle).toBeUndefined()
  })
})


import { SportsService } from '../services/sports'

/**
 * The day arrows must not be gated by a league that cannot answer.
 *
 * Two defects, both measured 2026-08-18 by driving the real page.
 *
 *   1. `cod` was in the schedule-dates fan-out. It is breakingpoint.gg, not
 *      ESPN, so the endpoint 404s for it -- one guaranteed failure on every
 *      page load and every arrow click, with a console error each time.
 *   2. The click awaited `Promise.all`, so the slowest leg decided when the
 *      day changed. Clicks took 0.7s to 3.1s against a board that is
 *      otherwise pure SQLite reads; after `allSettled` they take ~0.3s.
 */
describe('day arrow discovery', () => {
  const anchor = '2026-08-18'

  it('still answers when one league rejects', async () => {
    const spy = jest.spyOn(SportsService, 'getScheduleDates')
    spy.mockImplementation(async (league: string) => {
      if (league === 'broken') throw new Error('404')
      return {
        contract: 'league-schedule-dates-v1',
        league,
        anchor_date: anchor,
        event_start_timezone: 'UTC',
        future_event_starts: [],
        past_event_starts: ['2026-08-15T22:00:00+00:00'],
      } as any
    })
    const target = await SportsService.getNeighbourGameDate(['mlb', 'broken'], anchor, -1)
    expect(target).toBe('2026-08-15')
    spy.mockRestore()
  })

  it('a single refusing league does not blank the navigation', async () => {
    const spy = jest.spyOn(SportsService, 'getScheduleDates')
    spy.mockRejectedValue(new Error('every league refused'))
    // Nothing answered, so there is no honest target. The board stays put
    // rather than inventing a calendar date.
    await expect(
      SportsService.getNeighbourGameDate(['mlb'], anchor, -1)
    ).resolves.toBeNull()
    spy.mockRestore()
  })
})
