import Link from 'next/link'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'
import ArcadeLeaderboard from './ArcadeLeaderboard'
import { getArcadeClaim } from './arcadeSession'
import { trackArcadeVisit, trackEvent } from '../../lib/analytics'

type Challenge = {
  schema_version: string
  challenge_id: string
  kind: 'field_goal'
  origin: 'fictional_practice' | 'observed_nfl_play'
  source_ref: null | {
    publisher: 'ESPN'
    game_id: string
    play_id: string
    event_id: string
    source_revision: string
  }
  source_verified_at_utc?: string
  last_observed_at_utc?: string
  publisher_updated_at?: string | null
  observed_context: null | {
    away_team: string
    away_team_id?: string | null
    home_team: string
    home_team_id?: string | null
    period: number | null
    clock: string | null
    game_date: string | null
    attempt_distance_yards: number
  }
  challenge_config: {
    attempt_distance_yards: number
    target_aim: number
    aim_tolerance: number
    timing_window: number
    range_min_margin_yards: number
    range_max_margin_yards: number
    weather_mode: 'neutral_arcade'
  }
  physics_version: string
  scoring_version: string
  config_hash: string
  state: 'available' | 'archived_verified' | 'observed_live' | 'source_corrected'
  superseded_by_challenge_id?: string | null
}

type DrillAttempt = {
  challenge_id: string
  yards: number
  target_aim: number
  target_label: string
}

type Drill = {
  id: string
  name: string
  description: string
  medal_thresholds: { bronze: number; silver: number; gold: number }
  attempts: DrillAttempt[]
}

type Catalog = {
  schema_version: string
  physics_version: string
  scoring_version: string
  origin: 'fictional_practice' | 'observed_nfl_play'
  drills: Drill[]
}

type AttemptResult = {
  attempt_id: string
  challenge_id: string
  origin: 'fictional_practice' | 'observed_nfl_play'
  config_hash: string
  physics_version: string
  scoring_version: string
  attempt_distance_yards: number
  made: boolean
  feedback: 'GOOD' | 'LEFT' | 'RIGHT' | 'SHORT' | 'LONG' | 'EARLY' | 'LATE'
  score: number
  score_breakdown: { base: number; precision: number; distance_execution: number }
  coaching: string
  estimated_arcade_range_yards: number
  real_game_outcome: null | { status: 'made' | 'missed' | 'blocked'; label: string }
  personal_best_score?: number | null
  training_set?: null | { drill_id: string; score: number; personal_best_score: number; medal: string | null }
  qualified_referral_activation?: boolean
}

type ChallengeProgress = {
  attempts: number
  average_score: number
  misses: number
  scores_600_799: number
  scores_800_plus: number
}

type TrainingProgress = {
  completed_sets: number
  average_score: number
  below_bronze: number
  bronze: number
  silver: number
  gold: number
}

type ArcadeProgress = {
  challenge_progress: Record<string, ChallengeProgress>
  training_bests: Record<string, {
    score: number
    medal: string | null
    completed_sets: number
    score_distribution: TrainingProgress
  }>
}

type Props = {
  challengeId?: string | null
  drillId?: string | null
  shareId?: string | null
}

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

function distanceBand(yards: number) {
  return yards <= 30 ? 'short' : yards <= 45 ? 'medium' : 'long'
}

function scoreBand(score: number) {
  return score === 0 ? 'zero' : score < 600 ? 'under_600' : score < 800 ? '600_799' : '800_1000'
}

function analyticsDrillName(id: string) {
  return id === 'aim-lab-v1' ? 'aim_lab' : id === 'precision-set-v1' ? 'precision_set' : 'other'
}

function analyticsMode(challenge: Challenge, drill: Drill | null) {
  if (drill) return analyticsDrillName(drill.id)
  if (challenge.origin === 'fictional_practice') return 'practice_kick'
  return challenge.state === 'observed_live' ? 'live_challenge' : 'archived_challenge'
}

function attemptFailureReason(status: number) {
  if (status === 401) return 'claim_rejected'
  if (status === 409) return 'attempt_conflict'
  if (status === 422) return 'invalid_input'
  if (status === 429) return 'rate_limited'
  if (status >= 500) return 'service_unavailable'
  return 'request_rejected'
}

export function normalizeKickGesture({
  startAim,
  startPower,
  deltaX,
  deltaY,
  elapsedMs,
  width,
  height,
}: {
  startAim: number
  startPower: number
  deltaX: number
  deltaY: number
  elapsedMs: number
  width: number
  height: number
}) {
  const quantizeControl = (value: number, min: number, max: number) =>
    clamp(Math.round(clamp(value, min, max) * 100) / 100, min, max)

  return {
    // Match the accessible range controls' 0.01 step so touch, mouse and
    // keyboard produce the same normalized resolution before server scoring.
    aim: quantizeControl(startAim + deltaX / Math.max(1, width / 2), -1, 1),
    power: quantizeControl(startPower - deltaY / Math.max(1, height * 0.7), 0, 1),
    release_timing: quantizeControl(elapsedMs / 1200, 0, 1),
  }
}

function previewFeedback(challenge: Challenge, input: { aim: number; power: number; release_timing: number }) {
  const config = challenge.challenge_config
  const range = 14 + input.power * 55
  const aimError = input.aim - config.target_aim
  const rangeError = range - config.attempt_distance_yards
  const timingError = input.release_timing - 0.5
  if (aimError < -config.aim_tolerance) return 'LEFT' as const
  if (aimError > config.aim_tolerance) return 'RIGHT' as const
  if (range < config.attempt_distance_yards - config.range_min_margin_yards) return 'SHORT' as const
  if (range > config.attempt_distance_yards + config.range_max_margin_yards) return 'LONG' as const
  if (timingError < -config.timing_window) return 'EARLY' as const
  if (timingError > config.timing_window) return 'LATE' as const
  return 'GOOD' as const
}

function formatArchiveDate(value: string | null | undefined) {
  if (!value) return 'ESPN archive date unavailable'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'ESPN archive date unavailable'
  return `Game ${date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })}`
}

function formatSourceTime(value: string | null | undefined) {
  if (!value) return 'time unavailable'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'time unavailable' : date.toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'UTC',
  }) + ' UTC'
}

function newAttemptId() {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, character => {
      const random = Math.floor(Math.random() * 16)
      return (character === 'x' ? random : (random & 0x3) | 0x8).toString(16)
    })
}

function readBest(key: string) {
  if (typeof window === 'undefined') return 0
  try {
    const value = Number(window.localStorage.getItem(key))
    return Number.isFinite(value) && value >= 0 ? value : 0
  } catch {
    return 0
  }
}

function writeBest(key: string, value: number) {
  try {
    window.localStorage.setItem(key, String(value))
  } catch {
    // The score remains visible for this session when browser storage is disabled.
  }
}

function readAudioPreference() {
  if (typeof window === 'undefined') return false
  try { return window.localStorage.getItem('lp-arcade-sound-v1') === 'on' } catch { return false }
}

function readAudioVolume() {
  if (typeof window === 'undefined') return 0.55
  try {
    const stored = window.localStorage.getItem('lp-arcade-volume-v1')
    if (stored === null) return 0.55
    const volume = Number(stored)
    return Number.isFinite(volume) ? clamp(volume, 0, 1) : 0.55
  } catch { return 0.55 }
}

function useArcadeSound(enabled: boolean, volume: number) {
  const context = useRef<AudioContext | null>(null)
  const master = useRef<GainNode | null>(null)

  useEffect(() => () => {
    const current = context.current
    context.current = null
    master.current = null
    if (current && current.state !== 'closed') void current.close()
  }, [])

  useEffect(() => {
    if (master.current && context.current?.state === 'running') {
      master.current.gain.setTargetAtTime(volume, context.current.currentTime, 0.025)
    }
  }, [volume])

  function prepare() {
    if (typeof window === 'undefined' || document.visibilityState === 'hidden') return
    const AudioContextConstructor = window.AudioContext
    if (!AudioContextConstructor) return
    try {
      const audio = context.current || new AudioContextConstructor()
      context.current = audio
      if (!master.current) {
        master.current = audio.createGain()
        master.current.connect(audio.destination)
      }
      master.current.gain.value = volume
      if (audio.state === 'suspended') void audio.resume().catch(() => {})
    } catch {
      // Sound is optional. The kick controls and result remain available.
    }
  }

  function kick() {
    if (!enabled || typeof window === 'undefined' || document.visibilityState === 'hidden') return
    prepare()
    const audio = context.current
    if (!audio || audio.state !== 'running' || !master.current) return
    try {
      const oscillator = audio.createOscillator()
      const envelope = audio.createGain()
      const start = audio.currentTime
      oscillator.type = 'sine'
      oscillator.frequency.setValueAtTime(105, start)
      oscillator.frequency.exponentialRampToValueAtTime(48, start + 0.09)
      envelope.gain.setValueAtTime(0.0001, start)
      envelope.gain.exponentialRampToValueAtTime(0.18, start + 0.012)
      envelope.gain.exponentialRampToValueAtTime(0.0001, start + 0.12)
      oscillator.connect(envelope)
      envelope.connect(master.current)
      oscillator.start(start)
      oscillator.stop(start + 0.13)
    } catch { /* Audio remains optional. */ }
  }

  function play(made: boolean) {
    if (!enabled || typeof window === 'undefined' || document.visibilityState === 'hidden') return
    prepare()
    const audio = context.current
    if (!audio || audio.state !== 'running' || !master.current) return
    try {
      const oscillator = audio.createOscillator()
      const gain = audio.createGain()
      const start = audio.currentTime
      oscillator.type = 'triangle'
      oscillator.frequency.setValueAtTime(made ? 520 : 105, start)
      if (made) oscillator.frequency.exponentialRampToValueAtTime(780, start + 0.12)
      else oscillator.frequency.exponentialRampToValueAtTime(58, start + 0.11)
      gain.gain.setValueAtTime(0.0001, start)
      gain.gain.exponentialRampToValueAtTime(0.12, start + 0.015)
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.18)
      oscillator.connect(gain)
      gain.connect(master.current)
      oscillator.start(start)
      oscillator.stop(start + 0.19)
      if (made) {
        const clang = audio.createOscillator()
        const clangGain = audio.createGain()
        clang.type = 'square'
        clang.frequency.setValueAtTime(1180, start + 0.015)
        clang.frequency.exponentialRampToValueAtTime(760, start + 0.11)
        clangGain.gain.setValueAtTime(0.0001, start + 0.015)
        clangGain.gain.exponentialRampToValueAtTime(0.035, start + 0.022)
        clangGain.gain.exponentialRampToValueAtTime(0.0001, start + 0.14)
        clang.connect(clangGain)
        clangGain.connect(master.current)
        clang.start(start + 0.015)
        clang.stop(start + 0.15)

        const frameCount = Math.floor(audio.sampleRate * 0.16)
        const buffer = audio.createBuffer(1, frameCount, audio.sampleRate)
        const samples = buffer.getChannelData(0)
        for (let index = 0; index < frameCount; index += 1) {
          samples[index] = (Math.random() * 2 - 1) * (1 - index / frameCount)
        }
        const crowd = audio.createBufferSource()
        const crowdFilter = audio.createBiquadFilter()
        const crowdGain = audio.createGain()
        crowd.buffer = buffer
        crowdFilter.type = 'bandpass'
        crowdFilter.frequency.value = 720
        crowdFilter.Q.value = 0.55
        crowdGain.gain.setValueAtTime(0.0001, start + 0.025)
        crowdGain.gain.exponentialRampToValueAtTime(0.022, start + 0.05)
        crowdGain.gain.exponentialRampToValueAtTime(0.0001, start + 0.17)
        crowd.connect(crowdFilter)
        crowdFilter.connect(crowdGain)
        crowdGain.connect(master.current)
        crowd.start(start + 0.025)
        crowd.stop(start + 0.18)
      }
    } catch {
      // Audio is optional. The visible result and coaching carry the feedback.
    }
  }

  return { prepare, kick, play }
}

function PixelField({
  challenge,
  aim,
  result,
  preview,
}: {
  challenge: Challenge
  aim: number
  result: AttemptResult | null
  preview: AttemptResult['feedback'] | null
}) {
  const targetAim = challenge.challenge_config.target_aim
  const targetX = 480 + targetAim * 210
  const aimX = 480 + aim * 210
  const flightFeedback = result?.feedback || preview
  const flight = flightFeedback ? `lp-arcade-ball-flight-${flightFeedback.toLowerCase()}` : ''

  return (
    <div className="lp-arcade-pixel-field" role="img"
      aria-label={`${challenge.origin === 'fictional_practice' ? 'Fictional practice' : challenge.state === 'observed_live' ? 'ESPN live event challenge' : challenge.state === 'source_corrected' ? 'ESPN corrected-source challenge' : 'Archived ESPN play challenge'}, ${challenge.challenge_config.attempt_distance_yards} yards, target ${targetAim < -0.05 ? 'left hash' : targetAim > 0.05 ? 'right hash' : 'center'}`}>
      <svg viewBox="0 0 960 520" preserveAspectRatio="xMidYMid meet" shapeRendering="crispEdges" aria-hidden="true">
        <defs>
          <pattern id="lp-arcade-crowd-pixels" width="32" height="24" patternUnits="userSpaceOnUse">
            <rect width="32" height="24" fill="#282b3d" />
            <path d="M2 3h4v6H2zM12 5h5v7h-5zM23 2h4v8h-4zM6 16h5v6H6zM19 15h4v7h-4zM28 17h3v5h-3z" fill="#b98a58" />
            <path d="M8 2h3v5H8zM20 7h3v6h-3zM1 13h3v6H1zM14 17h3v5h-3zM25 13h2v5h-2z" fill="#6d8b79" />
            <path d="M17 1h2v4h-2zM4 10h2v4H4zM29 8h2v5h-2z" fill="#d3c8a4" />
          </pattern>
        </defs>
        <rect width="960" height="520" fill="#152235" />
        <path d="M0 126h960v84H0z" fill="#333246" />
        <rect className="lp-arcade-crowd" x="0" y="132" width="960" height="68" fill="url(#lp-arcade-crowd-pixels)" opacity=".92" />
        <path d="M0 138h960v12H0zM0 174h960v9H0z" fill="#524658" />
        <path d="M45 154h72v18H45zM158 154h58v18h-58zM742 154h58v18h-58zM844 154h72v18h-72z" fill="#d4a35c" />
        <path d="M45 159h72v3H45zM158 159h58v3h-58zM742 159h58v3h-58zM844 159h72v3h-72z" fill="#f2d991" />
        <path d="M0 205h960v18H0z" fill="#b85449" />
        <path d="M0 211h960v6H0z" fill="#e2a863" />
        <path d="M416 186V48h14v138zM530 186V48h14v138zM416 176h128v14H416z" fill="#f5d36c" />
        <path d="M422 52h8V38h10V26h12V14h48v12h12v12h10v14h8V32h-8V20h-12V8h-68v12h-12v12h-8z" fill="#f5d36c" />
        <path d="M0 223 960 223 960 520 0 520z" fill="#34754f" />
        <path d="M0 270 960 270v25H0zM0 345h960v25H0zM0 420h960v25H0zM0 495h960v25H0z" fill="#3e8358" />
        <path d="M0 223h960v5H0zM0 518h960v2H0z" fill="#e9e1c7" />
        <path d="M128 223 34 520M832 223l94 297M276 223 220 520M684 223l56 297" fill="none" stroke="#e9e1c7" strokeWidth="4" />
        <path d="M100 305h760M78 380h804M53 455h854" fill="none" stroke="#f4eed7" strokeWidth="5" opacity=".82" />
        <path d={`M480 457 L${Math.round(targetX)} 205`} fill="none" stroke="#f4d56e" strokeWidth="3" strokeDasharray="10 10" opacity=".8" />
        <path d={`M${Math.round(targetX - 14)} 206h28v12h-28z`} fill="#f4d56e" />
        <path d={`M${Math.round(aimX - 11)} 190h22v8h-22zM${Math.round(aimX - 5)} 184h10v20h-10z`} fill="#fff4cf" />
        <path d="M450 466h60v10h-60zM462 478h36v8h-36z" fill="#e9e1c7" />
        <g key={flightFeedback || 'idle'} className={`lp-arcade-football ${flightFeedback ? `lp-arcade-ball-flight ${flight}` : ''}`}>
          <ellipse cx="480" cy="454" rx="17" ry="10" fill="#7e432e" stroke="#231d25" strokeWidth="4" />
          <path d="M469 453h22M475 450v7M480 450v7M485 450v7" fill="none" stroke="#f5e8cc" strokeWidth="2" />
          <path d="M464 454h3M493 454h3" stroke="#f5e8cc" strokeWidth="2" />
        </g>
        {result?.made && <g className="lp-arcade-impact" transform={`translate(${Math.round(targetX)} 158)`}>
          <path d="M-39 0h8v-12h6v12h8v6h-8v8h-6V6h-8zM19 -16h6v10h10v6H25v10h-6V0H9v-6h10zM-4 -29h5v9h8v5H1v9h-5v-9h-8v-5h8z" fill="#fff0a8" />
          <path d="M-25 23h5v5h-5zM31 16h6v6h-6zM4 -35h4v4H4z" fill="#e2a863" />
        </g>}
        <path d="M12 12h236v48H12z" fill="#201f2d" />
        <path d="M20 20h220v5H20zM20 47h120v5H20z" fill="#4b8a66" />
        <text x="28" y="41" fill="#fff4cf" fontSize="18" fontFamily="monospace" fontWeight="700">LP ARCADE</text>
        <text x="760" y="40" fill="#fff4cf" fontSize="16" fontFamily="monospace" textAnchor="end">{challenge.origin === 'fictional_practice' ? 'PRACTICE FIELD' : challenge.state === 'observed_live' ? 'LIVE EVENT KICK' : challenge.state === 'source_corrected' ? 'CORRECTED SOURCE' : 'ARCHIVE KICK'}</text>
      </svg>
    </div>
  )
}

export default function FieldGoalArcade({ challengeId, drillId, shareId }: Props) {
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [loadingCatalog, setLoadingCatalog] = useState(true)
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [scenarioIndex, setScenarioIndex] = useState(0)
  const [drillRunId, setDrillRunId] = useState(newAttemptId)
  const [challenge, setChallenge] = useState<Challenge | null>(null)
  const [challengeLoading, setChallengeLoading] = useState(false)
  const [aim, setAim] = useState(0)
  const [power, setPower] = useState(0.5)
  const [timing, setTiming] = useState(0.5)
  const [result, setResult] = useState<AttemptResult | null>(null)
  const [flightPreview, setFlightPreview] = useState<AttemptResult['feedback'] | null>(null)
  const [gestureActive, setGestureActive] = useState(false)
  const [sessionResults, setSessionResults] = useState<AttemptResult[]>([])
  const [pending, setPending] = useState(false)
  const [attemptError, setAttemptError] = useState<string | null>(null)
  const [audioEnabled, setAudioEnabled] = useState(readAudioPreference)
  const [audioVolume, setAudioVolume] = useState(readAudioVolume)
  const [shareMessage, setShareMessage] = useState('')
  const [shareUrl, setShareUrl] = useState('')
  const [shareTarget, setShareTarget] = useState<number | null>(null)
  const [shareState, setShareState] = useState<'idle' | 'loading' | 'ready' | 'unavailable'>('idle')
  const [personalBest, setPersonalBest] = useState(0)
  const [arcadeProgress, setArcadeProgress] = useState<ArcadeProgress | null>(null)
  const playSound = useArcadeSound(audioEnabled, audioVolume)
  const trackedChallengeViewsRef = useRef(new Set<string>())
  const trackedSharedChallengesRef = useRef(new Set<string>())
  const trackedAttemptIdsRef = useRef(new Set<string>())
  const attemptInputMethodRef = useRef<'touch_gesture' | 'mouse_gesture' | 'pen_gesture' | 'controls' | 'keyboard'>('controls')
  const attemptStartedAtRef = useRef<number | null>(null)
  const firstChallengeStartedAtRef = useRef<number | null>(null)
  const trainingRunStartedAtRef = useRef<number | null>(null)
  const gestureRef = useRef<{
    pointerId: number
    startedAt: number
    startX: number
    startY: number
    startAim: number
    startPower: number
    width: number
    height: number
  } | null>(null)
  const gestureTimerRef = useRef<number | null>(null)
  const suppressGestureClickRef = useRef(false)
  const kickInProgressRef = useRef(false)
  const attemptDraft = useRef<{
    attempt_id: string
    challenge_id: string
    input: { aim: number; power: number; release_timing: number }
    share_id?: string
    drill_id?: string
    drill_run_id?: string
    drill_attempt_index?: number
  } | null>(null)

  useEffect(() => () => {
    if (gestureTimerRef.current !== null) window.clearInterval(gestureTimerRef.current)
  }, [])

  useEffect(() => {
    try { window.localStorage.setItem('lp-arcade-sound-v1', audioEnabled ? 'on' : 'off') } catch { /* Audio preference is optional. */ }
  }, [audioEnabled])

  useEffect(() => {
    try { window.localStorage.setItem('lp-arcade-volume-v1', String(audioVolume)) } catch { /* Volume preference is optional. */ }
  }, [audioVolume])

  useEffect(() => {
    const controller = new AbortController()
    setLoadingCatalog(true)
    fetch('/api/arcade/training', { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error('Training catalog unavailable')
        return response.json() as Promise<Catalog>
      })
      .then(payload => {
        setCatalog(payload)
        setCatalogError(null)
      })
      .catch(() => {
        if (!controller.signal.aborted) setCatalogError('The arcade rules could not be loaded. No kick has been scored.')
      })
      .finally(() => { if (!controller.signal.aborted) setLoadingCatalog(false) })
    return () => controller.abort()
  }, [])

  const drill = useMemo(() => catalog?.drills.find(item => item.id === drillId) || null, [catalog, drillId])
  const scenario = drill?.attempts[scenarioIndex] || null
  const activeChallengeId = challengeId || scenario?.challenge_id || 'practice-fg-35-v1'
  const totalAttempts = drill?.attempts.length || 1
  const activeChallengeVersionKey = challenge
    ? `${challenge.challenge_id}:${challenge.config_hash}`
    : activeChallengeId
  const sessionScore = sessionResults.reduce((sum, item) => sum + item.score, 0)
  const isSetComplete = Boolean(drill && result && sessionResults.length === totalAttempts)
  const medalThresholds = drill?.medal_thresholds
  const medal = isSetComplete && medalThresholds
    ? sessionScore >= medalThresholds.gold ? 'GOLD MEDAL'
      : sessionScore >= medalThresholds.silver ? 'SILVER MEDAL'
        : sessionScore >= medalThresholds.bronze ? 'BRONZE MEDAL' : 'KEEP PRACTICING'
    : null
  const bestStorageKey = drillId
    ? `lp-arcade-best:${drillId}:${challenge?.config_hash || 'unloaded'}`
    : `lp-arcade-best:${activeChallengeId}:${challenge?.config_hash || 'unloaded'}`

  useEffect(() => {
    if (loadingCatalog || (drillId && !drill)) return
    const controller = new AbortController()
    setChallenge(null)
    setChallengeLoading(true)
    setResult(null)
    setFlightPreview(null)
    setAttemptError(null)
    setShareMessage('')
    fetch(`/api/arcade/challenges/${encodeURIComponent(activeChallengeId)}`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error('Challenge unavailable')
        return response.json() as Promise<Challenge>
      })
      .then(payload => {
        setChallenge(payload)
        setAim(0)
        setPower(clamp((payload.challenge_config.attempt_distance_yards - 14) / 55 + 0.07, 0, 1))
        setTiming(0.5)
      })
      .catch(() => {
        if (!controller.signal.aborted) setAttemptError('This versioned practice challenge is unavailable.')
      })
      .finally(() => { if (!controller.signal.aborted) setChallengeLoading(false) })
    return () => controller.abort()
  }, [activeChallengeId, catalog, drill, drillId, loadingCatalog])

  useEffect(() => {
    setPersonalBest(readBest(bestStorageKey))
  }, [bestStorageKey])

  useEffect(() => {
    if (!challenge) return
    trackArcadeVisit(shareId ? 'shared_challenge' : drill ? 'training' : 'challenge')
  }, [challenge, drill, shareId])

  useEffect(() => {
    if (!challenge) return
    let active = true
    getArcadeClaim().then(token => fetch('/api/arcade/personal-bests', {
      headers: { 'X-Arcade-Claim': token },
    })).then(async response => {
      if (!response.ok) throw new Error('Personal best unavailable')
      return response.json() as Promise<{
        challenge_bests: Record<string, number>
        challenge_progress: Record<string, ChallengeProgress>
        training_bests: ArcadeProgress['training_bests']
      }>
    }).then(payload => {
      if (!active) return
      setArcadeProgress(payload)
      const best = drillId
        ? payload.training_bests?.[drillId]?.score
        : payload.challenge_bests?.[`${challenge.challenge_id}:${challenge.config_hash}`]
      if (typeof best === 'number' && Number.isFinite(best)) {
        setPersonalBest(best)
        writeBest(bestStorageKey, best)
      }
    }).catch(() => { /* A local best remains visible if the score store is offline. */ })
    return () => { active = false }
  }, [bestStorageKey, challenge, drillId])

  useEffect(() => {
    if (!challenge) return
    const viewKey = `${challenge.challenge_id}:${challenge.config_hash}:${drillRunId}:${scenarioIndex}`
    if (trackedChallengeViewsRef.current.has(viewKey)) return
    trackedChallengeViewsRef.current.add(viewKey)
    const mode = analyticsMode(challenge, drill)
    const entry = shareId ? 'shared_link'
      : drill ? 'training'
        : challenge.state === 'observed_live' ? 'live_moment'
          : challenge.origin === 'observed_nfl_play' ? 'archive_moment' : 'practice'
    trackEvent('arcade_challenge_viewed', {
      mode,
      origin: challenge.origin,
      source_state: challenge.state,
      entry,
      distance_band: distanceBand(challenge.challenge_config.attempt_distance_yards),
    })
    if (firstChallengeStartedAtRef.current === null) firstChallengeStartedAtRef.current = performance.now()
  }, [challenge, drill, drillRunId, scenarioIndex, shareId])

  useEffect(() => {
    trainingRunStartedAtRef.current = drill ? performance.now() : null
  }, [drill, drillRunId])

  useEffect(() => {
    if (!shareId || !challenge) {
      setShareTarget(null)
      setShareState('idle')
      return
    }
    const controller = new AbortController()
    setShareTarget(null)
    setShareState('loading')
    fetch(`/api/arcade/shares/${encodeURIComponent(shareId)}`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error('Shared kick target unavailable')
        return response.json() as Promise<{ challenge_id: string; config_hash: string; target_score: number }>
      })
      .then(payload => {
        if (payload.challenge_id !== challenge.challenge_id || payload.config_hash !== challenge.config_hash
          || !Number.isInteger(payload.target_score) || payload.target_score < 0 || payload.target_score > 1000) {
          throw new Error('Shared kick target does not match this challenge')
        }
        setShareTarget(payload.target_score)
        setShareState('ready')
        if (!trackedSharedChallengesRef.current.has(shareId)) {
          trackedSharedChallengesRef.current.add(shareId)
          trackEvent('arcade_shared_challenge_opened', {
            mode: analyticsMode(challenge, drill),
            origin: challenge.origin,
          })
        }
      })
      .catch(() => { if (!controller.signal.aborted) setShareState('unavailable') })
    return () => controller.abort()
  }, [challenge, drill, shareId])

  function updateGesture(event: ReactPointerEvent<HTMLButtonElement>, gesture = gestureRef.current) {
    if (!gesture || event.pointerId !== gesture.pointerId) return null
    const input = normalizeKickGesture({
      startAim: gesture.startAim,
      startPower: gesture.startPower,
      deltaX: event.clientX - gesture.startX,
      deltaY: event.clientY - gesture.startY,
      elapsedMs: performance.now() - gesture.startedAt,
      width: gesture.width,
      height: gesture.height,
    })
    setAim(input.aim)
    setPower(input.power)
    setTiming(input.release_timing)
    return input
  }

  function beginGesture(event: ReactPointerEvent<HTMLButtonElement>) {
    if (!challenge || pending || result || attemptError || event.isPrimary === false) return
    event.preventDefault()
    const bounds = event.currentTarget.getBoundingClientRect()
    const gesture = {
      pointerId: event.pointerId,
      startedAt: performance.now(),
      startX: event.clientX,
      startY: event.clientY,
      startAim: aim,
      startPower: power,
      width: Math.max(1, bounds.width),
      height: Math.max(1, bounds.height),
    }
    gestureRef.current = gesture
    setGestureActive(true)
    try {
      if (typeof event.currentTarget.setPointerCapture === 'function') {
        event.currentTarget.setPointerCapture(event.pointerId)
      }
    } catch { /* Pointer capture is optional; touch and mouse events still work. */ }
    if (gestureTimerRef.current !== null) window.clearInterval(gestureTimerRef.current)
    gestureTimerRef.current = window.setInterval(() => {
      const current = gestureRef.current
      if (!current) return
      setTiming(clamp((performance.now() - current.startedAt) / 1200, 0, 1))
    }, 40)
  }

  function finishGesture(event: ReactPointerEvent<HTMLButtonElement>, cancelled = false) {
    const gesture = gestureRef.current
    const input = updateGesture(event, gesture)
    if (!gesture || !input) return
    gestureRef.current = null
    setGestureActive(false)
    if (gestureTimerRef.current !== null) {
      window.clearInterval(gestureTimerRef.current)
      gestureTimerRef.current = null
    }
    if (cancelled) return
    suppressGestureClickRef.current = true
    window.setTimeout(() => { suppressGestureClickRef.current = false }, 0)
    const inputMethod = event.pointerType === 'touch' ? 'touch_gesture'
      : event.pointerType === 'pen' ? 'pen_gesture' : 'mouse_gesture'
    void kick(input, inputMethod)
  }

  async function kick(
    inputOverride?: { aim: number; power: number; release_timing: number },
    inputMethod: 'touch_gesture' | 'mouse_gesture' | 'pen_gesture' | 'controls' | 'keyboard' = 'controls',
  ) {
    if (!challenge || pending || result || kickInProgressRef.current) return
    kickInProgressRef.current = true
    setPending(true)
    setAttemptError(null)
    setShareMessage('')
    let failureReason = 'claim_unavailable'
    if (audioEnabled) {
      playSound.prepare()
      playSound.kick()
    }
    try {
      if (!attemptDraft.current) {
        attemptInputMethodRef.current = inputMethod
        attemptStartedAtRef.current = performance.now()
        attemptDraft.current = {
          attempt_id: newAttemptId(),
          challenge_id: challenge.challenge_id,
          input: inputOverride || { aim, power, release_timing: timing },
          ...(shareId ? { share_id: shareId } : {}),
          ...(drill ? {
            drill_id: drill.id,
            drill_run_id: drillRunId,
            drill_attempt_index: scenarioIndex,
          } : {}),
        }
      }
      const payload = attemptDraft.current
      setAim(payload.input.aim)
      setPower(payload.input.power)
      setTiming(payload.input.release_timing)
      setFlightPreview(previewFeedback(challenge, payload.input))
      const claim = await getArcadeClaim()
      failureReason = 'network_error'
      const response = await fetch('/api/arcade/attempts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Arcade-Claim': claim },
        body: JSON.stringify(payload),
      })
      if (!response.ok) {
        failureReason = attemptFailureReason(response.status)
        throw new Error('Attempt could not be scored')
      }
      failureReason = 'invalid_server_response'
      const scored = await response.json() as AttemptResult
      if (scored.challenge_id !== challenge.challenge_id || scored.config_hash !== challenge.config_hash
        || scored.origin !== challenge.origin || !Number.isInteger(scored.score)
        || scored.score < 0 || scored.score > 1000) {
        failureReason = 'response_mismatch'
        throw new Error('Arcade response did not match the frozen challenge')
      }
      setResult(scored)
      setFlightPreview(scored.feedback)
      attemptDraft.current = null
      playSound.play(scored.made)
      if (!trackedAttemptIdsRef.current.has(scored.attempt_id)) {
        trackedAttemptIdsRef.current.add(scored.attempt_id)
        const attemptDuration = attemptStartedAtRef.current === null
          ? null : Math.max(0, (performance.now() - attemptStartedAtRef.current) / 1000)
        const mode = analyticsMode(challenge, drill)
        trackEvent('arcade_kick_completed', {
          mode,
          origin: challenge.origin,
          source_state: challenge.state,
          distance_band: distanceBand(challenge.challenge_config.attempt_distance_yards),
          input_method: attemptInputMethodRef.current,
          made: scored.made,
          feedback: scored.feedback.toLowerCase(),
          score_band: scoreBand(scored.score),
          ...(attemptDuration === null ? {} : { attempt_duration_seconds: Math.round(attemptDuration * 10) / 10 }),
        })
        let firstKickCompleted = false
        try {
          firstKickCompleted = window.localStorage.getItem('lp-arcade-first-kick-completed-v1') !== '1'
          if (firstKickCompleted) window.localStorage.setItem('lp-arcade-first-kick-completed-v1', '1')
        } catch { /* Analytics deduplication is optional when local storage is unavailable. */ }
        if (firstKickCompleted) {
          const timeToFirst = firstChallengeStartedAtRef.current === null
            ? null : Math.max(0, (performance.now() - firstChallengeStartedAtRef.current) / 1000)
          trackEvent('arcade_first_kick_completed', {
            mode,
            origin: challenge.origin,
            ...(timeToFirst === null ? {} : { seconds_to_first_completed_kick: Math.round(timeToFirst * 10) / 10 }),
          })
        }
        if (scored.qualified_referral_activation === true) {
          trackEvent('arcade_qualified_referral_activation', { mode, origin: challenge.origin })
        }
        if (drill && scored.training_set && sessionResults.length + 1 === totalAttempts) {
          const duration = trainingRunStartedAtRef.current === null
            ? null : Math.max(0, (performance.now() - trainingRunStartedAtRef.current) / 1000)
          const previousSets = arcadeProgress?.training_bests?.[drill.id]?.completed_sets || 0
          const completedScores = [...sessionResults.map(item => item.score), scored.score]
          const scoreChange = completedScores[completedScores.length - 1] - completedScores[0]
          const scoreChangeBand = scoreChange >= 100 ? 'up_100_plus'
            : scoreChange > 0 ? 'up_1_99'
              : scoreChange === 0 ? 'no_change'
                : scoreChange > -100 ? 'down_1_99' : 'down_100_plus'
          trackEvent('arcade_training_set_completed', {
            drill: analyticsDrillName(drill.id),
            medal: scored.training_set.medal || 'none',
            average_kick_score_band: scoreBand(Math.round(scored.training_set.score / totalAttempts)),
            first_rep_score_band: scoreBand(completedScores[0]),
            final_rep_score_band: scoreBand(completedScores[completedScores.length - 1]),
            last_vs_first_score_band: scoreChangeBand,
            repeated: previousSets > 0,
            ...(duration === null ? {} : { set_duration_seconds: Math.round(duration * 10) / 10 }),
          })
        }
      }
      setSessionResults(previous => [...previous, scored])
      if (!drill) {
        const best = Math.max(readBest(bestStorageKey), scored.personal_best_score || 0, scored.score)
        writeBest(bestStorageKey, best)
        setPersonalBest(best)
        setArcadeProgress(previous => {
            const history = previous?.challenge_progress?.[activeChallengeVersionKey] || {
            attempts: 0, average_score: 0, misses: 0, scores_600_799: 0, scores_800_plus: 0,
          }
          const attempts = history.attempts + 1
          const bucket = scored.score === 0 ? 'misses'
            : scored.score < 800 ? 'scores_600_799' : 'scores_800_plus'
          return {
            challenge_progress: {
              ...(previous?.challenge_progress || {}),
              [activeChallengeVersionKey]: {
                attempts,
                average_score: Math.round((history.average_score * history.attempts + scored.score) / attempts),
                misses: history.misses + (bucket === 'misses' ? 1 : 0),
                scores_600_799: history.scores_600_799 + (bucket === 'scores_600_799' ? 1 : 0),
                scores_800_plus: history.scores_800_plus + (bucket === 'scores_800_plus' ? 1 : 0),
              },
            },
            training_bests: previous?.training_bests || {},
          }
        })
      } else if (sessionResults.length + 1 === totalAttempts) {
        const total = sessionScore + scored.score
        const best = Math.max(readBest(bestStorageKey), scored.training_set?.personal_best_score || 0, total)
        writeBest(bestStorageKey, best)
        setPersonalBest(best)
        if (scored.training_set) {
          setArcadeProgress(previous => {
            const history = previous?.training_bests?.[drill.id]?.score_distribution || {
              completed_sets: 0, average_score: 0, below_bronze: 0, bronze: 0, silver: 0, gold: 0,
            }
            const completedSets = history.completed_sets + 1
            const bucket = total >= drill.medal_thresholds.gold ? 'gold'
              : total >= drill.medal_thresholds.silver ? 'silver'
                : total >= drill.medal_thresholds.bronze ? 'bronze' : 'below_bronze'
            const previousBest = previous?.training_bests?.[drill.id]?.score || 0
            const personalBestSet = Math.max(previousBest, scored.training_set.personal_best_score, total)
            const bestMedal = personalBestSet >= drill.medal_thresholds.gold ? 'gold'
              : personalBestSet >= drill.medal_thresholds.silver ? 'silver'
                : personalBestSet >= drill.medal_thresholds.bronze ? 'bronze' : null
            return {
              challenge_progress: previous?.challenge_progress || {},
              training_bests: {
                ...(previous?.training_bests || {}),
                [drill.id]: {
                  score: personalBestSet,
                  medal: bestMedal,
                  completed_sets: completedSets,
                  score_distribution: {
                    completed_sets: completedSets,
                    average_score: Math.round((history.average_score * history.completed_sets + total) / completedSets),
                    below_bronze: history.below_bronze + (bucket === 'below_bronze' ? 1 : 0),
                    bronze: history.bronze + (bucket === 'bronze' ? 1 : 0),
                    silver: history.silver + (bucket === 'silver' ? 1 : 0),
                    gold: history.gold + (bucket === 'gold' ? 1 : 0),
                  },
                },
              },
            }
          })
        }
      }
    } catch {
      trackEvent('arcade_attempt_verification_failed', {
        mode: analyticsMode(challenge, drill),
        source_state: challenge.state,
        reason: failureReason,
      })
      setFlightPreview(null)
      setAttemptError('Couldn’t verify the kick right now. No score was recorded; try again.')
    } finally {
      setPending(false)
      kickInProgressRef.current = false
    }
  }

  function advance() {
    if (!drill || !result) return
    if (scenarioIndex + 1 >= totalAttempts) {
      setScenarioIndex(0)
      setDrillRunId(newAttemptId())
      attemptDraft.current = null
      setSessionResults([])
      setResult(null)
      setFlightPreview(null)
      setAttemptError(null)
      return
    }
    setScenarioIndex(index => index + 1)
    attemptDraft.current = null
    setResult(null)
    setFlightPreview(null)
    setAttemptError(null)
  }

  function retry() {
    attemptDraft.current = null
    setResult(null)
    setFlightPreview(null)
    setSessionResults([])
    setAttemptError(null)
  }

  async function challengeFriend() {
    if (!challenge || !result || typeof window === 'undefined') return
    const baseUrl = `${window.location.origin}/arcade/nfl/field-goal/${encodeURIComponent(challenge.challenge_id)}`
    try {
      const claim = await getArcadeClaim()
      const response = await fetch('/api/arcade/shares', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Arcade-Claim': claim },
        body: JSON.stringify({ attempt_id: result.attempt_id, challenge_id: challenge.challenge_id }),
      })
      if (!response.ok) throw new Error('Verified score could not be shared')
      const share = await response.json() as { share_id: string; challenge_id: string; config_hash: string; target_score: number }
      if (share.challenge_id !== challenge.challenge_id || share.config_hash !== challenge.config_hash
        || share.target_score !== result.score || typeof share.share_id !== 'string') {
        throw new Error('Share link did not match the scored kick')
      }
      trackEvent('arcade_share_created', {
        mode: analyticsMode(challenge, drill),
        origin: challenge.origin,
      })
      const url = `${baseUrl}?share=${encodeURIComponent(share.share_id)}`
      const sourceLabel = challenge.state === 'observed_live' ? 'live ESPN event'
        : challenge.state === 'source_corrected' ? 'frozen, corrected ESPN revision' : 'archived ESPN'
      const context = challenge.origin === 'observed_nfl_play'
        ? `Beat my ${share.target_score} on this ${sourceLabel} kick. The arcade result is separate from the real kick.`
        : `Beat my ${share.target_score} on this fictional practice kick.`
      setShareUrl(url)
      setShareMessage(context)
      if (navigator.share) {
        await navigator.share({ title: 'Beat my LP Arcade kick', text: context, url })
        setShareMessage(`Challenge shared. ${context}`)
      } else if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url)
        setShareMessage(`Challenge link copied. ${context}`)
      }
    } catch {
      const url = baseUrl
      setShareUrl(url)
      const fallback = 'A score-linked share is unavailable right now. This link still opens the exact same challenge setup.'
      try {
        if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(url)
      } catch { /* Keep the visible exact challenge link available for manual copy. */ }
      setShareMessage(fallback)
      trackEvent('arcade_share_failed', {
        mode: analyticsMode(challenge, drill),
        origin: challenge.origin,
      })
    }
  }

  if (loadingCatalog || challengeLoading) {
    return <section className="lp-arcade-unit" role="status"><p>Loading the practice rules…</p></section>
  }
  if (catalogError || !catalog || (drillId && !drill)) {
    return <section className="lp-arcade-unit" role="alert">
      <p>{catalogError || 'This training drill is unavailable.'}</p>
      <Link href="/arcade/nfl">Back to LP Arcade</Link>
    </section>
  }
  if (!challenge) {
    return <section className="lp-arcade-unit" role="alert">
      <p>{attemptError || 'This challenge is unavailable.'}</p>
      <Link href="/arcade/nfl">Back to LP Arcade</Link>
    </section>
  }

  const distance = challenge.challenge_config.attempt_distance_yards
  const context = challenge.observed_context
  const archivedTeams = context ? `${context.away_team} at ${context.home_team}` : ''
  const kickFeedback = result?.feedback.toLowerCase() || ''
  const setCap = totalAttempts * 1000
  const challengeHistory = arcadeProgress?.challenge_progress?.[activeChallengeVersionKey]
  const trainingHistory = drill ? arcadeProgress?.training_bests?.[drill.id]?.score_distribution : null

  return (
    <section className="lp-arcade-unit" aria-label="Field Goal Frenzy arcade game">
      <header className="lp-arcade-game-heading">
        <div>
          <p className="lp-arcade-kicker">FIELD GOAL FRENZY</p>
          <h2>{drill?.name || 'Your turn to kick'}</h2>
          {challenge.origin === 'fictional_practice'
            ? <p className="lp-arcade-provenance">FICTIONAL PRACTICE · {distance} YD · NEUTRAL CONDITIONS</p>
            : <p className="lp-arcade-provenance">{challenge.state === 'observed_live' ? 'ESPN LIVE EVENT'
              : challenge.state === 'source_corrected' ? 'ESPN CORRECTED PLAY · FROZEN CHALLENGE' : 'ARCHIVED ESPN PLAY'} · {distance} YD · {archivedTeams}</p>}
          {context && <p className="lp-arcade-source-caption">
            {formatArchiveDate(context.game_date)}{context.period ? ` · Q${context.period}` : ''}{context.clock ? ` · ${context.clock}` : ''}
            {challenge.source_ref ? ` · Source play ${challenge.source_ref.play_id}` : ''}
            {challenge.last_observed_at_utc
              ? ` · LP last observed ${formatSourceTime(challenge.last_observed_at_utc)}`
              : challenge.source_verified_at_utc
                ? ` · LP replay ingested ${formatSourceTime(challenge.source_verified_at_utc)}`
                : ''}
            {challenge.publisher_updated_at
              ? ` · ESPN summary updated ${formatSourceTime(challenge.publisher_updated_at)}`
              : ''}
          </p>}
        </div>
        <div className="lp-arcade-audio-controls">
          <button type="button" className="lp-arcade-audio-toggle" aria-pressed={audioEnabled}
            onClick={() => {
              if (!audioEnabled) playSound.prepare()
              setAudioEnabled(value => !value)
            }}>
            {audioEnabled ? 'Sound on' : 'Sound off'}
          </button>
          <label className="lp-arcade-volume-control">
            <span>Volume <output>{Math.round(audioVolume * 100)}%</output></span>
            <input aria-label="Sound volume" type="range" min="0" max="1" step="0.01" value={audioVolume}
              onChange={event => setAudioVolume(clamp(Number(event.currentTarget.value), 0, 1))} />
          </label>
        </div>
      </header>

      {challenge.state === 'source_corrected' && <p className="lp-arcade-source-correction" role="status">
        ESPN later corrected or withdrew this play. This shared kick keeps its original {distance}-yard rules.
        {challenge.superseded_by_challenge_id
          ? <> <Link href={`/arcade/nfl/field-goal/${encodeURIComponent(challenge.superseded_by_challenge_id)}`}>Play the corrected source version.</Link></>
          : ' No replacement field-goal challenge is available.'}
      </p>}

      <PixelField challenge={challenge} aim={aim} result={result} preview={flightPreview} />

      {shareId && shareState === 'loading' && <p className="lp-arcade-share-target" role="status">Loading the verified score to beat…</p>}
      {shareTarget !== null && <p className="lp-arcade-share-target" role="status">
        SCORE TO BEAT: <strong>{shareTarget}</strong> · same challenge version and settings
      </p>}
      {shareId && shareState === 'unavailable' && <p className="lp-arcade-error" role="alert">
        This score-linked challenge is unavailable. You can still play the same frozen kick.
      </p>}

      <div className="lp-arcade-under-field" aria-live="polite">
        {drill ? <span>{drill.description}</span> : <span>One kick. Immediate retry. Your arcade result is separate from any real game.</span>}
        {drill && <strong>KICK {scenarioIndex + 1} / {totalAttempts}</strong>}
      </div>

      <div className="lp-arcade-readouts" aria-label="Current kick settings">
        <span><small>AIM</small><b>{aim < -0.08 ? 'LEFT' : aim > 0.08 ? 'RIGHT' : 'CENTER'}</b></span>
        <span><small>POWER</small><b>{Math.round(power * 100)}%</b></span>
        <span><small>RELEASE</small><b>{timing < 0.42 ? 'EARLY' : timing > 0.58 ? 'LATE' : 'CENTER'}</b></span>
        <span><small>TARGET</small><b>{scenario?.target_label || 'UPRIGHTS'}</b></span>
      </div>

      <button className={`lp-arcade-gesture-pad${gestureActive ? ' is-active' : ''}`} type="button"
        aria-label="One-thumb kick gesture" aria-describedby="lp-arcade-one-thumb-help"
        onPointerDown={beginGesture}
        onPointerMove={event => { if (gestureRef.current) updateGesture(event) }}
        onPointerUp={event => finishGesture(event)}
        onPointerCancel={event => finishGesture(event, true)}
        onClick={event => {
          if (suppressGestureClickRef.current) {
            suppressGestureClickRef.current = false
            return
          }
          if (event.detail === 0) void kick(undefined, 'keyboard')
        }}
        disabled={pending || Boolean(result) || Boolean(attemptError) || !challenge}>
        <span className="lp-arcade-gesture-timing" aria-hidden="true">
          <span className="lp-arcade-gesture-target" />
          <i style={{ left: `${timing * 100}%` }} />
        </span>
        <strong>{gestureActive ? 'RELEASE IN THE CENTER' : 'PRESS · AIM · RELEASE'}</strong>
        <small>{gestureActive ? `Release timing ${Math.round(timing * 100)}%` : 'One-thumb kick'}</small>
      </button>
      <p id="lp-arcade-one-thumb-help" className="lp-arcade-gesture-help">
        Hold about 0.6 seconds for the timing window. Drag left or right to aim and upward for more power. Keyboard and screen-reader players can use the labeled controls below.
      </p>
      {pending && flightPreview && <p className="lp-arcade-flight-status" role="status">Predicted {flightPreview}. The server is confirming your arcade result…</p>}

      <div className="lp-arcade-controls" aria-label="Kick controls">
        <label className="lp-arcade-control">
          <span><b>Aim</b><output>{aim < -0.08 ? 'Left' : aim > 0.08 ? 'Right' : 'Center'}</output></span>
          <input aria-label="Aim" type="range" min="-1" max="1" step="0.01" value={aim}
            onChange={event => setAim(Number(event.currentTarget.value))} disabled={pending || Boolean(result) || Boolean(attemptError)} />
          <small>Move the kick toward the target mark.</small>
        </label>
        <label className="lp-arcade-control">
          <span><b>Power</b><output>{Math.round(power * 100)}%</output></span>
          <input aria-label="Power" type="range" min="0" max="1" step="0.01" value={power}
            onChange={event => setPower(Number(event.currentTarget.value))} disabled={pending || Boolean(result) || Boolean(attemptError)} />
          <small>{distance} yards · fictional target distance</small>
        </label>
        <label className="lp-arcade-control">
          <span><b>Release timing</b><output>{timing < 0.42 ? 'Early' : timing > 0.58 ? 'Late' : 'On time'}</output></span>
          <input aria-label="Release timing" type="range" min="0" max="1" step="0.01" value={timing}
            onChange={event => setTiming(Number(event.currentTarget.value))} disabled={pending || Boolean(result) || Boolean(attemptError)} />
          <small>Center the marker for the timing window.</small>
        </label>
      </div>

      {!drill && challengeHistory && <section className="lp-arcade-score-history" aria-label="Your kick score history">
        <strong>YOUR KICK HISTORY</strong>
        <span>{challengeHistory.attempts} {challengeHistory.attempts === 1 ? 'attempt' : 'attempts'} · average {challengeHistory.average_score}</span>
        <small>{challengeHistory.misses} misses · {challengeHistory.scores_600_799} scores from 600–799 · {challengeHistory.scores_800_plus} scores from 800–1000</small>
      </section>}
      {drill && trainingHistory && trainingHistory.completed_sets > 0 && <section className="lp-arcade-score-history" aria-label="Your training set history">
        <strong>YOUR SET HISTORY</strong>
        <span>{trainingHistory.completed_sets} completed {trainingHistory.completed_sets === 1 ? 'set' : 'sets'} · average {trainingHistory.average_score} / {setCap}</span>
        <small>{trainingHistory.below_bronze} below bronze · {trainingHistory.bronze} bronze · {trainingHistory.silver} silver · {trainingHistory.gold} gold</small>
      </section>}

      {!result && <button className="lp-arcade-kick-button" type="button"
        onClick={event => { void kick(undefined, event.detail === 0 ? 'keyboard' : 'controls') }} disabled={pending || !challenge}>
        {pending ? 'Scoring kick…' : attemptError ? 'RETRY SAME KICK' : 'KICK'}
      </button>}

      {attemptError && <p className="lp-arcade-error" role="alert">{attemptError}</p>}

      {result && <section className="lp-arcade-result" aria-live="polite" aria-label="Kick result">
        <div className="lp-arcade-result-heading">
          <p className={`lp-arcade-result-call lp-arcade-result-${kickFeedback}`}>{result.feedback}{result.made ? ' · MADE' : ' · MISSED'}</p>
          <p className="lp-arcade-score-label">ARCADE SCORE <span>{result.score} <small>/ 1000</small></span></p>
        </div>
        <p>{result.coaching}</p>
        {result.real_game_outcome && <p className="lp-arcade-real-outcome">{result.real_game_outcome.label} · reported separately from your arcade kick.</p>}
        <p className="lp-arcade-version">Rules {result.physics_version} · {result.scoring_version} · setup {result.config_hash.slice(0, 10)}</p>
        {drill ? <>
          <p className="lp-arcade-set-score">Set score <b>{sessionScore} / {setCap}</b></p>
          {medal && <p className="lp-arcade-medal" role="status">{medal}</p>}
          <p className="lp-arcade-best">Personal best set: {personalBest} / {setCap}</p>
          <button className="lp-arcade-next-button" type="button" onClick={advance}>
            {isSetComplete ? 'REPEAT SET' : 'NEXT KICK'}
          </button>
        </> : <>
          <p className="lp-arcade-best">Personal best: {personalBest} / 1000</p>
          <div className="lp-arcade-result-actions">
            <button className="lp-arcade-next-button" type="button" onClick={retry}>KICK AGAIN</button>
            <button className="lp-arcade-share-button" type="button" onClick={challengeFriend}>CHALLENGE A FRIEND</button>
          </div>
        </>}
        {shareMessage && <p className="lp-arcade-share-message" role="status">{shareMessage}</p>}
        {shareUrl && <p className="lp-arcade-share-url"><a href={shareUrl}>{shareUrl}</a></p>}
      </section>}

      {drill && <div className="lp-arcade-drill-history" aria-label="Kick set results">
        {drill.attempts.map((item, index) => {
          const saved = sessionResults[index]
          return <span key={item.challenge_id} className={saved ? 'is-complete' : ''}>
            <small>{index + 1} · {item.yards} YD</small><b>{saved ? saved.score : '—'}</b>
          </span>
        })}
      </div>}

      <ArcadeLeaderboard challengeId={challenge.challenge_id} configHash={challenge.config_hash} refreshKey={result?.attempt_id} />

      <p className="lp-arcade-status-note">Free arcade · your kick and score are separate from NFL results · anonymous claim, no signup · no paid advantages</p>
      <nav className="lp-arcade-research-links" aria-label="Legendary Picks research">
        {challenge.source_ref && <Link href={`/nfl/pixel-red-zone?mode=replay&game=${encodeURIComponent(challenge.source_ref.game_id)}&play=${encodeURIComponent(challenge.source_ref.play_id)}`}
          onClick={() => trackEvent('arcade_research_opened', { destination: 'pixel_red_zone', origin: challenge.origin })}>
          Watch this source play in Pixel Red Zone
        </Link>}
        <Link href="/scores?league=nfl" onClick={() => trackEvent('arcade_research_opened', { destination: 'scores' })}>NFL scores</Link>
        <Link href="/props?league=nfl" onClick={() => trackEvent('arcade_research_opened', { destination: 'props' })}>NFL props</Link>
        <Link href="/arcade/nfl" onClick={() => trackEvent('arcade_research_opened', { destination: 'arcade_lobby' })}>LP Arcade</Link>
        <Link href="/leagues/nfl?tab=camp" onClick={() => trackEvent('arcade_research_opened', { destination: 'nfl_hq' })}>NFL HQ</Link>
      </nav>
    </section>
  )
}
