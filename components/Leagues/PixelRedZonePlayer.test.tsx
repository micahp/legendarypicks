import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import PixelRedZonePlayer, { arcadeChallengeForEvent, type ReplayPayload } from './PixelRedZonePlayer'

const originalFetch = global.fetch
const originalAudioContext = window.AudioContext

function event(sequence: number, overrides: Record<string, unknown> = {}) {
  const touchdown = overrides.event_type === 'touchdown'
  const unavailableSpot = overrides.event_type === 'pass_reception'
  return {
    schema_version: 'lp-observed-nfl-event-v1', mode: 'replay' as const, game_id: '401772829',
    source: { publisher: 'ESPN', event_id: `401772829:ESPN:p${sequence}`, play_id: `p${sequence}`,
      revision: `revision-${sequence}`, occurred_at_utc: '2025-09-07T17:10:00Z', observed_at_utc: null,
      revision_basis: 'canonical_raw_play_sha256' },
    sequence, period: 1, clock: '10:00', status: 'replay', offense_team_id: '5',
    before: { down: 1, yards_to_go: 10, yardline_100: unavailableSpot ? null : 60, score: { away: 0, home: 0 } },
    after: { score: { away: 0, home: touchdown ? 7 : 0 } },
    event_type: touchdown ? 'touchdown' : unavailableSpot ? 'pass_reception' : 'rush',
    source_event_type: touchdown ? 'Passing Touchdown' : unavailableSpot ? 'Pass Reception' : 'Rush',
    score_kind: touchdown ? 'touchdown' : null,
    scoring_play: touchdown,
    is_turnover: false,
    review_state: 'none',
    point_after_attempt: touchdown ? { text: 'Extra Point Good', value: 1 } : null,
    display_text: touchdown ? 'Pass for a touchdown.' : 'Rush for four yards.',
    confidence: { identity: 'verified', field: unavailableSpot ? 'unavailable' : 'verified', score: 'verified' },
    ...overrides,
  }
}

function response(): ReplayPayload {
  return {
    mode: 'replay',
    game: {
      game_id: '401772829', date: '2025-09-07T17:00Z', status: 'replay',
      teams: {
        away: { team_id: '4', abbreviation: 'CIN', name: 'Cincinnati Bengals' },
        home: { team_id: '5', abbreviation: 'CLE', name: 'Cleveland Browns' },
      },
      score: { away: 17, home: 16 },
    },
    archive: { label: 'REPLAY', captured_at_utc: '2026-11-01T06:57:16Z', raw_fixture_sha256: 'hash' },
    events: [event(100), event(200, { event_type: 'touchdown' }), event(300, { event_type: 'pass_reception' })],
  }
}

function jsonResponse(body: unknown) {
  return { ok: true, json: async () => body } as Response
}

class FakeAudioContext {
  static instances: FakeAudioContext[] = []
  state = 'suspended'
  currentTime = 1
  destination = {}
  gainNode = {
    gain: {
      value: 0,
      setTargetAtTime: jest.fn(),
      setValueAtTime: jest.fn(),
      linearRampToValueAtTime: jest.fn(),
      exponentialRampToValueAtTime: jest.fn(),
    },
    connect: jest.fn(),
  }
  oscillator = {
    type: 'square',
    frequency: { setValueAtTime: jest.fn() },
    connect: jest.fn(),
    start: jest.fn(),
    stop: jest.fn(),
  }
  resume = jest.fn(async () => { this.state = 'running' })
  suspend = jest.fn(async () => { this.state = 'suspended' })
  close = jest.fn(async () => { this.state = 'closed' })
  createGain = jest.fn(() => this.gainNode)
  createOscillator = jest.fn(() => ({
    ...this.oscillator,
    frequency: { setValueAtTime: jest.fn() },
    connect: jest.fn(), start: jest.fn(), stop: jest.fn(),
  }))

  constructor() { FakeAudioContext.instances.push(this) }
}

describe('PixelRedZonePlayer', () => {
  beforeEach(() => {
    FakeAudioContext.instances = []
    global.fetch = jest.fn(async () => jsonResponse(response()))
  })

  async function renderLoaded(onBack?: () => void) {
    let view!: ReturnType<typeof render>
    const loadReplay = jest.fn(async () => response())
    await act(async () => {
      view = render(<PixelRedZonePlayer onBack={onBack} loadReplay={loadReplay} />)
      await new Promise(resolve => setTimeout(resolve, 0))
    })
    await screen.findByText(/Cincinnati Bengals at Cleveland Browns/)
    return view
  }

  afterEach(() => {
    global.fetch = originalFetch
    Object.defineProperty(window, 'AudioContext', { configurable: true, value: originalAudioContext })
  })

  it('redzone_audio_gesture_and_cleanup', async () => {
    Object.defineProperty(window, 'AudioContext', { configurable: true, value: FakeAudioContext })
    const view = await renderLoaded()

    expect(screen.getByRole('button', { name: 'Sound off' })).toBeTruthy()
    expect(FakeAudioContext.instances).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Sound off' }))
    await screen.findByRole('button', { name: 'Sound on' })
    expect(FakeAudioContext.instances).toHaveLength(1)
    expect(FakeAudioContext.instances[0].resume).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: 'Next play' }))
    await waitFor(() => expect(FakeAudioContext.instances[0].createOscillator).toHaveBeenCalledTimes(3))
    expect(screen.getByText(/ESPN try field: Extra Point Good/)).toBeTruthy()
    view.unmount()
    await waitFor(() => expect(FakeAudioContext.instances[0].close).toHaveBeenCalledTimes(1))
  })

  it('redzone_fullscreen_route_back', async () => {
    const onBack = jest.fn()
    await renderLoaded(onBack)

    expect(screen.getByRole('button', { name: 'Previous play' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Next play' })).toBeTruthy()
    expect(screen.getByRole('slider', { name: 'Replay play position' })).toBeTruthy()
    expect(screen.getByRole('slider', { name: 'Sound volume' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Fullscreen' }))
    expect(await screen.findByText(/Fullscreen is unavailable|Fullscreen was blocked/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Back to room' }))
    expect(onBack).toHaveBeenCalledTimes(1)
  })

  it('redzone_mobile_accessible', async () => {
    await renderLoaded()

    expect(screen.getByRole('region', { name: 'Pixel Red Zone historical replay' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Previous play' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Next play' })).toBeTruthy()
    expect(screen.getByRole('slider', { name: 'Replay play position' })).toBeTruthy()
    expect(screen.getByRole('slider', { name: 'Sound volume' })).toBeTruthy()
    expect(screen.getByText(/Caption source: ESPN play-by-play/)).toBeTruthy()
    expect(screen.getByText(/Muted by default/)).toBeTruthy()
  })

  it('redzone_missing_spot_remains_unknown_in_the_channel', async () => {
    render(<PixelRedZonePlayer loadReplay={async () => response()} />)
    await screen.findByText(/Cincinnati Bengals at Cleveland Browns/)
    fireEvent.click(screen.getByRole('button', { name: 'Next play' }))
    fireEvent.click(screen.getByRole('button', { name: 'Next play' }))
    expect(screen.getByText('Ball spot unavailable. Centered football is illustrative only.')).toBeTruthy()
  })

  it('opens a replay at the exact source play from a challenge link', async () => {
    const loadReplay = jest.fn(async () => response())
    await act(async () => {
      render(<PixelRedZonePlayer viewMode="replay" initialPinnedGameId="401772829"
        initialPlayId="p200" loadReplay={loadReplay} />)
      await new Promise(resolve => setTimeout(resolve, 0))
    })

    expect(await screen.findByText(/Pass for a touchdown\./)).toBeTruthy()
    expect((screen.getByRole('slider', { name: 'Replay play position' }) as HTMLInputElement).value).toBe('1')
  })

  it('offers Arcade only for a verified live field goal with published distance', () => {
    const verifiedKick = event(100, {
      mode: 'live',
      source_event_type: 'Field Goal Good',
      source: { publisher: 'ESPN', event_id: '401772829:ESPN:p100', play_id: 'p100',
        revision: 'a'.repeat(64), occurred_at_utc: null, observed_at_utc: '2026-10-01T00:00:00Z' },
      field_goal_attempt_distance_yards: 45,
      field_goal_distance_provenance: {
        confidence: 'verified', publisher: 'ESPN', basis: 'explicit_field_goal_yard_phrase',
      },
      arcade_challenge_id: `espn-fg-${'b'.repeat(24)}`,
    })

    expect(arcadeChallengeForEvent(verifiedKick, 'in')).toBe(`espn-fg-${'b'.repeat(24)}`)
    expect(arcadeChallengeForEvent(verifiedKick, 'post')).toBeNull()
    expect(arcadeChallengeForEvent(event(100), 'in')).toBeNull()
  })
})
