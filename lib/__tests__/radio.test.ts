import { radioForMatchup, TEAM_RADIO } from '../radio'

// Reported by Micah 2026-08-30: an NBA Raptors/Heat game page and an NHL Maple
// Leafs page both linked "Listen live" to Toronto FC's / Inter Miami's MLS radio
// stream. `radioForMatchup` itself has no notion of league -- it matches on bare
// abbreviation, and TOR/MIA/CHI/DC/COL/SD/SEA are shared by MLS and other
// leagues' team codes. The fix scopes the CALL to soccer leagues
// (pages/game/[league]/[gameId].tsx), not this function -- these tests pin the
// collision so a future caller can't reintroduce it by forgetting that guard.
describe('radioForMatchup', () => {
  it('resolves a verified MLS abbreviation', () => {
    expect(radioForMatchup('TOR', 'CLB')).toEqual({ key: 'tor', streamUrl: TEAM_RADIO.TOR })
  })

  it('the collision this map creates for other leagues: TOR/MIA are NOT sport-scoped', () => {
    // This is the trap, not the desired behavior -- callers outside mls/lcup must
    // not invoke this function with a non-MLS team's abbreviation.
    expect(radioForMatchup('TOR', 'MIA')).not.toBeNull()
  })

  it('returns null when neither side has a verified station', () => {
    expect(radioForMatchup('DAL', 'STL')).toBeNull()
  })
})
