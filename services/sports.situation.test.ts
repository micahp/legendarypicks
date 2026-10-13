import { normalizeGame, normalizeSituation } from './sports'

// Shape of the backend game dict, from a real NCAAF scoreboard cached 2026-10-03.
const live = {
  game_id: '401', state: 'in', period: 1, clock: '0:40', home: { abbrev: 'UNC' }, away: { abbrev: 'ND' },
  situation: {
    down: 1, distance: 5, text: '1st & 5 at UNC 37', short_text: '1st & 5', ball_on: 'UNC 37',
    yard_line_from_home_goal: 37, field_pos_from_away_goal: 63, possession: 'away',
    goal_to_go: false, red_zone: false, home_timeouts: 3, away_timeouts: 3,
    last_play: { text: 'C.Carr pass incomplete ... NO PLAY', type: 'Penalty', team: 'away', score_value: 0 },
    drive: { description: '5 plays, 30 yards, 3:19', start: 'ND 23' },
    win_probability: { home: 0.0464, away: 0.9536, tie: 0, source: 'espn' },
  },
}

describe('football situation', () => {
  it('reaches the normalized game in camelCase', () => {
    const s = normalizeGame(live, 'ncaaf').situation!
    expect(s.text).toBe('1st & 5 at UNC 37')
    expect(s.fieldPosFromAwayGoal).toBe(63)
    expect(s.possession).toBe('away')
    expect(s.lastPlay?.team).toBe('away')
    expect(s.drive?.description).toBe('5 plays, 30 yards, 3:19')
    expect(s.winProbability?.source).toBe('espn')
  })

  it('is absent unless the game is live', () => {
    expect(normalizeGame({ ...live, state: 'post' }, 'ncaaf').situation).toBeUndefined()
    expect(normalizeGame({ ...live, situation: undefined }, 'ncaaf').situation).toBeUndefined()
  })

  it('keeps a missing spot missing between plays', () => {
    const s = normalizeSituation({ state: 'in', situation: { down: null, field_pos_from_away_goal: null, red_zone: true,
      last_play: { text: 'Rushing touchdown', type: 'Rushing Touchdown', team: 'away', score_value: 6 } } })!
    expect(s.down).toBeUndefined()
    expect(s.fieldPosFromAwayGoal).toBeUndefined()
    expect(s.lastPlay?.scoreValue).toBe(6)
  })
})
