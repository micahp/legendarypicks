import { act, fireEvent, render, screen } from '@testing-library/react'
import FieldGoalArcade, { normalizeKickGesture } from './FieldGoalArcade'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

const originalFetch = global.fetch
const originalGtag = window.gtag

const challenge = (id: string, yards: number, targetAim = 0) => ({
  schema_version: 'lp-arcade-challenge-v1',
  challenge_id: id,
  kind: 'field_goal',
  origin: 'fictional_practice',
  source_ref: null,
  observed_context: null,
  challenge_config: {
    attempt_distance_yards: yards,
    target_aim: targetAim,
    aim_tolerance: 0.24,
    timing_window: 0.26,
    range_min_margin_yards: 1.5,
    range_max_margin_yards: 8,
    weather_mode: 'neutral_arcade',
  },
  physics_version: 'fg-physics-v1',
  scoring_version: 'fg-score-v1',
  config_hash: `hash-${id}`,
  state: 'available',
})

const catalog = {
  schema_version: 'lp-arcade-training-v1',
  physics_version: 'fg-physics-v1',
  scoring_version: 'fg-score-v1',
  origin: 'fictional_practice',
  drills: [{
    id: 'aim-lab-v1',
    name: 'Aim Lab',
    description: 'Center, then line up two changing hash marks.',
    medal_thresholds: { bronze: 1500, silver: 2200, gold: 2700 },
    attempts: [
      { challenge_id: 'aim-25', yards: 25, target_aim: 0, target_label: 'CENTER' },
      { challenge_id: 'aim-35', yards: 35, target_aim: -0.34, target_label: 'LEFT HASH' },
      { challenge_id: 'aim-45', yards: 45, target_aim: 0.34, target_label: 'RIGHT HASH' },
    ],
  }],
}

const archivedChallenge = (id: string) => ({
  ...challenge(id, 45),
  schema_version: 'lp-arcade-challenge-v2',
  origin: 'observed_nfl_play' as const,
  source_ref: {
    publisher: 'ESPN' as const,
    game_id: '401772829',
    play_id: '4017728291916',
    event_id: '401772829:ESPN:4017728291916',
    source_revision: 'revision-1',
  },
  source_verified_at_utc: '2026-11-01T06:57:16Z',
  observed_context: {
    away_team: 'Cincinnati Bengals',
    home_team: 'Cleveland Browns',
    period: 1,
    clock: '10:12',
    game_date: '2025-09-07T17:00Z',
    attempt_distance_yards: 45,
  },
  state: 'archived_verified' as const,
})

let resultSequence = 0
const result = (id: string, score = 1000) => ({
  attempt_id: `test-attempt-${++resultSequence}`,
  challenge_id: id,
  origin: 'fictional_practice',
  config_hash: `hash-${id}`,
  physics_version: 'fg-physics-v1',
  scoring_version: 'fg-score-v1',
  attempt_distance_yards: 35,
  made: score > 0,
  feedback: score > 0 ? 'GOOD' : 'LEFT',
  score,
  score_breakdown: { base: score > 0 ? 600 : 0, precision: score > 0 ? 300 : 0, distance_execution: score > 0 ? 100 : 0 },
  coaching: 'Clean kick.',
  estimated_arcade_range_yards: 35,
  real_game_outcome: null,
})

const jsonResponse = (body: unknown, ok = true, status = ok ? 200 : 500) => ({
  ok,
  status,
  json: async () => body,
}) as Response

async function renderGame(props: React.ComponentProps<typeof FieldGoalArcade>) {
  let view!: ReturnType<typeof render>
  await act(async () => {
    view = render(<FieldGoalArcade {...props} />)
    await new Promise(resolve => setTimeout(resolve, 0))
  })
  return view
}

async function clickAndFlush(button: HTMLElement) {
  await act(async () => {
    fireEvent.click(button)
    await new Promise(resolve => setTimeout(resolve, 0))
  })
}

describe('FieldGoalArcade', () => {
  let submitted: Record<string, unknown>[]

  beforeEach(() => {
    localStorage.clear()
    resultSequence = 0
    submitted = []
    global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/arcade/session') return jsonResponse({ claim_token: 'x'.repeat(43) })
      if (url === '/api/arcade/personal-bests') return jsonResponse({ challenge_bests: {}, training_bests: {} })
      if (url.startsWith('/api/arcade/leaderboard?')) return jsonResponse({ entries: [] })
      if (url === '/api/arcade/training') return jsonResponse(catalog)
      const id = decodeURIComponent(url.split('/').pop() || '')
      if (url.startsWith('/api/arcade/challenges/')) return jsonResponse(challenge(id, 35))
      if (url === '/api/arcade/shares') {
        const payload = JSON.parse(String(init?.body)) as { challenge_id: string }
        return jsonResponse({ share_id: 'share-fixture', challenge_id: payload.challenge_id,
          config_hash: `hash-${payload.challenge_id}`, target_score: 1000 })
      }
      if (url === '/api/arcade/attempts') {
        const payload = JSON.parse(String(init?.body)) as Record<string, unknown>
        submitted.push(payload)
        return jsonResponse(result(String(payload.challenge_id)))
      }
      return jsonResponse({ error: 'not found' }, false)
    })
  })

  afterEach(() => {
    global.fetch = originalFetch
    if (originalGtag) window.gtag = originalGtag
    else Reflect.deleteProperty(window, 'gtag')
  })

  it('normalizes one-thumb aim, power and release timing into the server input ranges', () => {
    expect(normalizeKickGesture({
      startAim: 0, startPower: 0.5, deltaX: 25, deltaY: -35,
      elapsedMs: 600, width: 100, height: 100,
    })).toEqual({ aim: 0.5, power: 1, release_timing: 0.5 })
    expect(normalizeKickGesture({
      startAim: 0.9, startPower: 0.1, deltaX: 200, deltaY: 200,
      elapsedMs: 1800, width: 100, height: 100,
    })).toEqual({ aim: 1, power: 0, release_timing: 1 })

    const compactSurface = normalizeKickGesture({
      startAim: 0, startPower: 0.5, deltaX: 10, deltaY: -10,
      elapsedMs: 600, width: 100, height: 100,
    })
    const wideSurface = normalizeKickGesture({
      startAim: 0, startPower: 0.5, deltaX: 20, deltaY: -20,
      elapsedMs: 600, width: 200, height: 200,
    })
    expect(wideSurface).toEqual(compactSurface)
  })

  it('submits one normalized attempt from a one-thumb pointer release', async () => {
    await renderGame({ challengeId: 'practice-fg-35-v1' })
    const pad = screen.getByRole('button', { name: 'One-thumb kick gesture' })
    const pointerEventDescriptor = Object.getOwnPropertyDescriptor(window, 'PointerEvent')
    class TestPointerEvent extends MouseEvent {
      pointerId: number
      isPrimary: boolean

      constructor(type: string, init: MouseEventInit & { pointerId?: number; isPrimary?: boolean } = {}) {
        super(type, init)
        this.pointerId = init.pointerId ?? 1
        this.isPrimary = init.isPrimary ?? true
      }
    }
    Object.defineProperty(window, 'PointerEvent', { configurable: true, value: TestPointerEvent })
    jest.spyOn(pad, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100,
      toJSON: () => ({}),
    } as DOMRect)
    jest.useFakeTimers()
    try {
      await act(async () => {
        fireEvent.pointerDown(pad, { pointerId: 7, isPrimary: true, clientX: 50, clientY: 50 })
        await jest.advanceTimersByTimeAsync(600)
        fireEvent.pointerMove(pad, { pointerId: 7, clientX: 60, clientY: 40 })
        fireEvent.pointerUp(pad, { pointerId: 7, clientX: 60, clientY: 40 })
        fireEvent.click(pad)
        for (let index = 0; index < 6; index += 1) await Promise.resolve()
      })
      expect(submitted).toHaveLength(1)
      expect(submitted[0].input).toEqual({
        aim: 0.2,
        power: expect.any(Number),
        release_timing: 0.5,
      })
      expect((submitted[0].input as { power: number }).power).toBeGreaterThan(0.45)
    } finally {
      jest.useRealTimers()
      if (pointerEventDescriptor) Object.defineProperty(window, 'PointerEvent', pointerEventDescriptor)
      else Reflect.deleteProperty(window, 'PointerEvent')
    }
  })

  it('supports a keyboard path through the labeled aim, power and timing controls', async () => {
    await renderGame({ challengeId: 'practice-fg-35-v1' })
    const pointerEquivalent = normalizeKickGesture({
      startAim: 0, startPower: (35 - 14) / 55 + 0.07,
      deltaX: 10, deltaY: -10, elapsedMs: 600, width: 100, height: 100,
    })
    fireEvent.change(screen.getByRole('slider', { name: 'Aim' }), { target: { value: String(pointerEquivalent.aim) } })
    fireEvent.change(screen.getByRole('slider', { name: 'Power' }), { target: { value: String(pointerEquivalent.power) } })
    fireEvent.change(screen.getByRole('slider', { name: 'Release timing' }), { target: { value: String(pointerEquivalent.release_timing) } })

    await clickAndFlush(screen.getByRole('button', { name: 'One-thumb kick gesture' }))

    expect(await screen.findByRole('region', { name: 'Kick result' })).toBeTruthy()
    expect(submitted).toHaveLength(1)
    expect(submitted[0].input).toEqual(pointerEquivalent)
  })

  it('exposes and persists the sound volume preference', async () => {
    localStorage.setItem('lp-arcade-volume-v1', '0.35')
    await renderGame({ challengeId: 'practice-fg-35-v1' })

    const volume = screen.getByRole('slider', { name: 'Sound volume' })
    expect((volume as HTMLInputElement).value).toBe('0.35')
    fireEvent.change(volume, { target: { value: '0.8' } })

    expect(screen.getByText('80%')).toBeTruthy()
    expect(localStorage.getItem('lp-arcade-volume-v1')).toBe('0.8')
  })

  it('starts muted with a usable default volume for an explicit later opt-in', async () => {
    await renderGame({ challengeId: 'practice-fg-35-v1' })

    expect(screen.getByRole('button', { name: 'Sound off' }).getAttribute('aria-pressed')).toBe('false')
    expect((screen.getByRole('slider', { name: 'Sound volume' }) as HTMLInputElement).value).toBe('0.55')
    expect(screen.getByText('55%')).toBeTruthy()
  })

  it('shows a clearly fictional kick and sends normalized controls for server scoring', async () => {
    const gtag = jest.fn()
    window.gtag = gtag
    await renderGame({ challengeId: 'practice-fg-35-v1' })
    expect(await screen.findByText(/FICTIONAL PRACTICE · 35 YD/)).toBeTruthy()
    expect(screen.getByRole('slider', { name: /Aim/ })).toBeTruthy()
    expect(screen.getByRole('slider', { name: /Power/ })).toBeTruthy()
    expect(screen.getByRole('slider', { name: /Release timing/ })).toBeTruthy()

    await clickAndFlush(screen.getByRole('button', { name: /^kick$/i }))
    const kickResult = await screen.findByRole('region', { name: 'Kick result' })
    expect(kickResult.textContent).toContain('1000')
    expect(submitted).toHaveLength(1)
    expect(Object.keys(submitted[0]).sort()).toEqual(['attempt_id', 'challenge_id', 'input'])
    expect(submitted[0].challenge_id).toBe('practice-fg-35-v1')
    expect(await screen.findByText(/arcade score/i)).toBeTruthy()
    expect(screen.getByText(/personal best/i)).toBeTruthy()
    expect(screen.getByText(/1 attempt · average 1000/)).toBeTruthy()
    expect(screen.getByText(/0 misses · 0 scores from 600–799 · 1 scores from 800–1000/)).toBeTruthy()
    expect(gtag).toHaveBeenCalledWith('event', 'arcade_challenge_viewed', expect.objectContaining({
      mode: 'practice_kick', origin: 'fictional_practice', entry: 'practice', distance_band: 'medium',
    }))
    expect(gtag).toHaveBeenCalledWith('event', 'arcade_kick_completed', expect.objectContaining({
      mode: 'practice_kick', input_method: 'keyboard', made: true, score_band: '800_1000',
      attempt_duration_seconds: expect.any(Number),
    }))
    expect(gtag).toHaveBeenCalledWith('event', 'arcade_first_kick_completed', expect.objectContaining({
      seconds_to_first_completed_kick: expect.any(Number),
    }))
    const analyticsPayloads = JSON.stringify(gtag.mock.calls)
    expect(analyticsPayloads).not.toContain('practice-fg-35-v1')
    expect(analyticsPayloads).not.toContain('test-attempt-')

    await clickAndFlush(screen.getByRole('button', { name: /challenge a friend/i }))
    expect(await screen.findByText(/beat my 1000/i)).toBeTruthy()
    expect(gtag).toHaveBeenCalledWith('event', 'arcade_share_created', expect.objectContaining({
      mode: 'practice_kick', origin: 'fictional_practice',
    }))
    expect(JSON.stringify(gtag.mock.calls)).not.toContain('share-fixture')
    expect(screen.getByRole('link', { name: /arcade\/nfl\/field-goal\/practice-fg-35-v1/ }).getAttribute('href'))
      .toContain('/arcade/nfl/field-goal/practice-fg-35-v1?share=share-fixture')
  })

  it('tracks categorized score verification failures without identifiers', async () => {
    const gtag = jest.fn()
    window.gtag = gtag
    global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/arcade/session') return jsonResponse({ claim_token: 'x'.repeat(43) })
      if (url === '/api/arcade/personal-bests') return jsonResponse({ challenge_bests: {}, training_bests: {} })
      if (url.startsWith('/api/arcade/leaderboard?')) return jsonResponse({ entries: [] })
      if (url === '/api/arcade/training') return jsonResponse(catalog)
      if (url.startsWith('/api/arcade/challenges/')) return jsonResponse(challenge('practice-fg-35-v1', 35))
      if (url === '/api/arcade/attempts') {
        submitted.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
        return jsonResponse({ error: 'invalid input' }, false, 422)
      }
      return jsonResponse({ error: 'not found' }, false)
    })

    await renderGame({ challengeId: 'practice-fg-35-v1' })
    await clickAndFlush(screen.getByRole('button', { name: /^kick$/i }))

    expect(await screen.findByText(/couldn’t verify the kick/i)).toBeTruthy()
    expect(gtag).toHaveBeenCalledWith('event', 'arcade_attempt_verification_failed', expect.objectContaining({
      mode: 'practice_kick', source_state: 'available', reason: 'invalid_input',
    }))
    const analyticsPayloads = JSON.stringify(gtag.mock.calls)
    expect(analyticsPayloads).not.toContain('practice-fg-35-v1')
    expect(analyticsPayloads).not.toContain('test-attempt-')
  })

  it('runs the three fixed Aim Lab scenarios and awards only the published medal threshold', async () => {
    const gtag = jest.fn()
    window.gtag = gtag
    global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/arcade/session') return jsonResponse({ claim_token: 'x'.repeat(43) })
      if (url === '/api/arcade/personal-bests') return jsonResponse({ challenge_bests: {}, training_bests: {} })
      if (url.startsWith('/api/arcade/leaderboard?')) return jsonResponse({ entries: [] })
      if (url === '/api/arcade/training') return jsonResponse(catalog)
      if (url.startsWith('/api/arcade/challenges/')) {
        const id = decodeURIComponent(url.split('/').pop() || '')
        return jsonResponse(challenge(id, 35))
      }
      if (url === '/api/arcade/attempts') {
        const payload = JSON.parse(String(init?.body)) as Record<string, unknown>
        submitted.push(payload)
        const scored = result(String(payload.challenge_id), 800)
        return jsonResponse(payload.drill_attempt_index === 2 ? {
          ...scored,
          training_set: { drill_id: 'aim-lab-v1', score: 2400, personal_best_score: 2400, medal: 'silver' },
        } : scored)
      }
      return jsonResponse({ error: 'not found' }, false)
    })

    await renderGame({ drillId: 'aim-lab-v1' })
    expect(await screen.findByText('Aim Lab')).toBeTruthy()

    for (let kick = 0; kick < 3; kick += 1) {
      await clickAndFlush(await screen.findByRole('button', { name: /^kick$/i }))
      expect(submitted).toHaveLength(kick + 1)
      await screen.findByRole('region', { name: 'Kick result' })
      if (kick < 2) await clickAndFlush(screen.getByRole('button', { name: /next kick/i }))
    }

    expect(await screen.findByText(/SILVER MEDAL/i)).toBeTruthy()
    expect(submitted.map(body => body.challenge_id)).toEqual(['aim-25', 'aim-35', 'aim-45'])
    expect(screen.getAllByText(/2400/).length).toBeGreaterThan(0)
    expect(screen.getByText(/1 completed set · average 2400/)).toBeTruthy()
    expect(screen.getByText(/0 below bronze · 0 bronze · 1 silver · 0 gold/)).toBeTruthy()
    expect(gtag).toHaveBeenCalledWith('event', 'arcade_training_set_completed', expect.objectContaining({
      drill: 'aim_lab', medal: 'silver', repeated: false, last_vs_first_score_band: 'no_change',
    }))
  })

  it('does not invent a result when the server cannot score the attempt', async () => {
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/arcade/session') return jsonResponse({ claim_token: 'x'.repeat(43) })
      if (url === '/api/arcade/training') return jsonResponse(catalog)
      if (url.startsWith('/api/arcade/challenges/')) return jsonResponse(challenge('practice-fg-35-v1', 35))
      return jsonResponse({ error: 'unavailable' }, false)
    })

    await renderGame({ challengeId: 'practice-fg-35-v1' })
    await screen.findByText(/FICTIONAL PRACTICE · 35 YD/)
    await clickAndFlush(screen.getByRole('button', { name: /^kick$/i }))
    expect(await screen.findByText(/couldn’t verify the kick/i)).toBeTruthy()
    expect(screen.queryByText(/arcade score/i)).toBeNull()
  })

  it('keeps the archived real result hidden until the user completes their own kick', async () => {
    global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/arcade/session') return jsonResponse({ claim_token: 'x'.repeat(43) })
      if (url === '/api/arcade/personal-bests') return jsonResponse({ challenge_bests: {}, training_bests: {} })
      if (url.startsWith('/api/arcade/leaderboard?')) return jsonResponse({ entries: [] })
      if (url === '/api/arcade/training') return jsonResponse(catalog)
      if (url.startsWith('/api/arcade/challenges/')) return jsonResponse(archivedChallenge('espn-fg-test'))
      if (url === '/api/arcade/attempts') {
        const payload = JSON.parse(String(init?.body)) as Record<string, unknown>
        return jsonResponse({
          ...result(String(payload.challenge_id)),
          origin: 'observed_nfl_play',
          attempt_distance_yards: 45,
          real_game_outcome: { status: 'missed', label: 'Real attempt: missed' },
        })
      }
      return jsonResponse({ error: 'not found' }, false)
    })

    await renderGame({ challengeId: 'espn-fg-test' })
    expect(await screen.findByText(/ARCHIVED ESPN PLAY · 45 YD · Cincinnati Bengals at Cleveland Browns/)).toBeTruthy()
    expect(screen.queryByText(/Real attempt:/i)).toBeNull()
    expect(screen.getByRole('link', { name: /watch this source play in pixel red zone/i }).getAttribute('href'))
      .toContain('game=401772829&play=4017728291916')

    await clickAndFlush(screen.getByRole('button', { name: /^kick$/i }))
    expect(await screen.findByText(/Real attempt: missed/)).toBeTruthy()
  })

  it('labels a live observed moment and discloses ESPN and LP timestamps', async () => {
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/arcade/session') return jsonResponse({ claim_token: 'x'.repeat(43) })
      if (url === '/api/arcade/personal-bests') return jsonResponse({ challenge_bests: {}, training_bests: {} })
      if (url.startsWith('/api/arcade/leaderboard?')) return jsonResponse({ entries: [] })
      if (url === '/api/arcade/training') return jsonResponse(catalog)
      if (url.startsWith('/api/arcade/challenges/')) return jsonResponse({
        ...archivedChallenge('espn-fg-live'),
        state: 'observed_live',
        last_observed_at_utc: '2026-11-01T20:01:00Z',
        publisher_updated_at: '2026-11-01T20:00:30Z',
      })
      return jsonResponse({ error: 'not found' }, false)
    })

    await renderGame({ challengeId: 'espn-fg-live' })
    expect(await screen.findByText(/ESPN LIVE EVENT · 45 YD/)).toBeTruthy()
    expect(screen.getByText(/LP last observed Nov 1, 8:01 PM UTC/)).toBeTruthy()
    expect(screen.getByText(/ESPN summary updated Nov 1, 8:00 PM UTC/)).toBeTruthy()
    expect(screen.getByRole('img', { name: /ESPN live event challenge, 45 yards/ })).toBeTruthy()
  })

  it('keeps a corrected source challenge frozen and links to its replacement', async () => {
    const fallbackFetch = (global.fetch as jest.Mock).getMockImplementation()!
    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/arcade/challenges/corrected-source-old') return Promise.resolve(jsonResponse({
        ...archivedChallenge('corrected-source-old'),
        state: 'source_corrected',
        superseded_by_challenge_id: 'espn-fg-0123456789abcdef01234567',
      }))
      return fallbackFetch(input, init)
    })

    await renderGame({ challengeId: 'corrected-source-old' })

    expect(screen.getByText(/ESPN later corrected or withdrew this play/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Play the corrected source version.' }).getAttribute('href'))
      .toBe('/arcade/nfl/field-goal/espn-fg-0123456789abcdef01234567')
  })

  it('loads the server-bound score target on a shared exact challenge link', async () => {
    const gtag = jest.fn()
    window.gtag = gtag
    global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/arcade/session') return jsonResponse({ claim_token: 'x'.repeat(43) })
      if (url === '/api/arcade/personal-bests') return jsonResponse({ challenge_bests: {}, training_bests: {} })
      if (url.startsWith('/api/arcade/leaderboard?')) return jsonResponse({ entries: [] })
      if (url === '/api/arcade/training') return jsonResponse(catalog)
      if (url === '/api/arcade/challenges/practice-fg-35-v1') return jsonResponse(challenge('practice-fg-35-v1', 35))
      if (url === '/api/arcade/shares/share-fixture') return jsonResponse({
        challenge_id: 'practice-fg-35-v1',
        config_hash: 'hash-practice-fg-35-v1',
        target_score: 930,
      })
      if (url === '/api/arcade/attempts') {
        const payload = JSON.parse(String(init?.body)) as Record<string, unknown>
        submitted.push(payload)
        return jsonResponse({ ...result(String(payload.challenge_id)), qualified_referral_activation: true })
      }
      return jsonResponse({ error: 'not found' }, false)
    })

    await renderGame({ challengeId: 'practice-fg-35-v1', shareId: 'share-fixture' })
    expect(await screen.findByText('930')).toBeTruthy()
    expect(gtag).toHaveBeenCalledWith('event', 'arcade_shared_challenge_opened', expect.objectContaining({
      mode: 'practice_kick', origin: 'fictional_practice',
    }))
    await clickAndFlush(screen.getByRole('button', { name: /^kick$/i }))
    expect(submitted[0].share_id).toBe('share-fixture')
    expect(gtag).toHaveBeenCalledWith('event', 'arcade_qualified_referral_activation', expect.objectContaining({
      mode: 'practice_kick', origin: 'fictional_practice',
    }))
    expect(JSON.stringify(gtag.mock.calls)).not.toContain('share-fixture')
  })
})
