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
