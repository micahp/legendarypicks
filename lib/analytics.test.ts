import { trackArcadeVisit, trackPageView } from './analytics'

describe('trackPageView', () => {
  const originalGtag = window.gtag

  afterEach(() => {
    if (originalGtag) window.gtag = originalGtag
    else Reflect.deleteProperty(window, 'gtag')
  })

  it('removes bearer share IDs from analytics page paths and locations', () => {
    const gtag = jest.fn()
    window.gtag = gtag

    trackPageView('/arcade/nfl/field-goal/challenge-1?share=private-token&view=compact')

    expect(gtag).toHaveBeenCalledWith('event', 'page_view', expect.objectContaining({
      page_path: '/arcade/nfl/field-goal/challenge-1?view=compact',
      page_location: `${window.location.origin}/arcade/nfl/field-goal/challenge-1?view=compact`,
    }))
    expect(JSON.stringify(gtag.mock.calls)).not.toContain('private-token')
  })
})

describe('trackArcadeVisit', () => {
  const originalGtag = window.gtag

  beforeEach(() => {
    window.localStorage.clear()
    window.sessionStorage.clear()
  })

  afterEach(() => {
    if (originalGtag) window.gtag = originalGtag
    else Reflect.deleteProperty(window, 'gtag')
  })

  it('tracks first use once per session and records coarse D1 and D7 return windows', () => {
    const gtag = jest.fn()
    window.gtag = gtag
    const firstVisit = 1_800_000_000_000

    trackArcadeVisit('lobby', firstVisit)
    trackArcadeVisit('training', firstVisit + 1_000)

    expect(gtag).toHaveBeenCalledTimes(1)
    expect(gtag).toHaveBeenLastCalledWith('event', 'arcade_visit', expect.objectContaining({
      visit_type: 'first', return_window: 'first', surface: 'lobby',
    }))

    window.sessionStorage.clear()
    trackArcadeVisit('challenge', firstVisit + 86_400_000)
    expect(gtag).toHaveBeenLastCalledWith('event', 'arcade_visit', expect.objectContaining({
      visit_type: 'return', return_window: 'd1', surface: 'challenge', days_since_last_visit: 1,
    }))

    window.sessionStorage.clear()
    window.localStorage.setItem('lp-arcade-last-visit-at-v1', String(firstVisit))
    trackArcadeVisit('shared_challenge', firstVisit + 7 * 86_400_000)
    expect(gtag).toHaveBeenLastCalledWith('event', 'arcade_visit', expect.objectContaining({
      visit_type: 'return', return_window: 'd7', surface: 'shared_challenge', days_since_last_visit: 7,
    }))
    expect(JSON.stringify(gtag.mock.calls)).not.toContain('user_id')
  })
})
