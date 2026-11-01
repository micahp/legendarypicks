import Link from 'next/link'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Game } from '../../services/sports'
import replayArchiveCatalog from '../../backend/fixtures/pixel_red_zone/index.json'

type PixelEvent = {
  schema_version: string
  mode: 'replay' | 'live'
  game_id: string
  source: {
    publisher: string
    event_id: string
    play_id: string
    revision: string
    occurred_at_utc: string | null
    observed_at_utc: string | null
  }
  sequence: number | null
  period: number | null
  clock: string | null
  status: string | null
  offense_team_id: string | null
  before: {
    down: number | null
    yards_to_go: number | null
    yardline_100: number | null
    score: { away: number; home: number } | null
  }
  after: { score: { away: number; home: number } | null }
  event_type: string
  source_event_type: string | null
  score_kind?: string | null
  scoring_play: boolean | null
  is_turnover: boolean | null
  review_state: string
  point_after_attempt?: { text?: string; abbreviation?: string; value?: number } | null
  display_text: string | null
  confidence: { field: string; score: string }
}

type FieldTeam = { team_id: string | null; abbreviation: string | null; name: string | null }
type FieldTeams = { home: FieldTeam; away: FieldTeam }

export type ReplayPayload = {
  mode: 'replay'
  game: {
    game_id: string
    date: string | null
    status: string
    teams: FieldTeams
    score: { away: number | null; home: number | null }
  }
  archive: { label: string; captured_at_utc: string; raw_fixture_sha256: string }
  events: PixelEvent[]
}

type PlayByPlayPlay = {
  playId: string | number | null
  sequenceNumber: number | null
  period: number | null
  clock: string | null
  text: string | null
  type: string | null
  wallclock: string | null
}

type PlayByPlaySnapshot = {
  available: boolean
  publisher?: string
  eventId?: string
  publisherUpdatedAt?: string | null
  periods?: { label: string; plays: PlayByPlayPlay[] }[]
  pixel_red_zone?: {
    available?: boolean
    game?: { teams: FieldTeams }
    source?: { publisher_updated_at?: string | null; observed_at_utc?: string | null }
    events?: PixelEvent[]
  }
}

type Props = {
  roomMode?: boolean
  viewMode?: 'live' | 'replay'
  initialPinnedGameId?: string | null
  onBack?: () => void
  scoreboard?: { games: Game[]; age: number | null; loading: boolean; unavailable: boolean; source: string | null }
  loadReplay?: (gameId?: string) => Promise<ReplayPayload>
}

async function loadBundledReplay(gameId = '401772829'): Promise<ReplayPayload> {
  const replayLoaders: Record<string, () => Promise<{ default: unknown }>> = {
    '401772718': () => import('../../backend/fixtures/pixel_red_zone/401772718.json'),
    '401772719': () => import('../../backend/fixtures/pixel_red_zone/401772719.json'),
    '401772720': () => import('../../backend/fixtures/pixel_red_zone/401772720.json'),
    '401772721': () => import('../../backend/fixtures/pixel_red_zone/401772721.json'),
    '401772827': () => import('../../backend/fixtures/pixel_red_zone/401772827.json'),
    '401772828': () => import('../../backend/fixtures/pixel_red_zone/401772828.json'),
    '401772829': () => import('../../backend/fixtures/pixel_red_zone/401772829.json'),
    '401772830': () => import('../../backend/fixtures/pixel_red_zone/401772830.json'),
  }
  const loader = replayLoaders[gameId]
  if (!loader) throw new Error('Unknown archived game')
  const imported = await loader()
  return imported.default as ReplayPayload
}

export function chooseScoreboardDirectorGame(games: Game[]): Game | null {
  return [...games]
    .filter(game => game.status === 'LIVE')
    .sort((left, right) => Number(right.situation?.redZone === true) - Number(left.situation?.redZone === true)
      || left.gameId.localeCompare(right.gameId))[0] || null
}

export function latestCanonicalEvent(events: PixelEvent[]): PixelEvent | null {
  const sequenced = events.filter(event => Number.isInteger(event.sequence))
  if (sequenced.length) {
    return sequenced.reduce((latest, event) => (event.sequence as number) >= (latest.sequence as number) ? event : latest)
  }
  return events[events.length - 1] || null
}

export function shouldAdvanceCanonicalEvent(previous: PixelEvent | null, next: PixelEvent | null): boolean {
  if (!next) return false
  if (!previous) return true
  if (previous.source.event_id === next.source.event_id) {
    if (previous.source.revision === next.source.revision) return true
    const previousObserved = Date.parse(previous.source.observed_at_utc || '')
    const nextObserved = Date.parse(next.source.observed_at_utc || '')
    return Number.isFinite(previousObserved) && Number.isFinite(nextObserved) && nextObserved > previousObserved
  }
  if (previous.sequence === null || next.sequence === null) return false
  return next.sequence > previous.sequence
}

export function canAnimateReplaySpotTransition(previous: PixelEvent | null, next: PixelEvent | null, isNextReplayStep = true): boolean {
  if (!isNextReplayStep) return false
  if (!previous || !next || previous.mode !== 'replay' || next.mode !== 'replay') return false
  if (previous.period === null || next.period === null || previous.period !== next.period) return false
  if (!previous.offense_team_id || previous.offense_team_id !== next.offense_team_id) return false
  if (previous.sequence === null || next.sequence === null || next.sequence <= previous.sequence) return false
  if (previous.confidence.field !== 'verified' || next.confidence.field !== 'verified') return false
  const previousSpot = diagrammaticFieldX(previous.before.yardline_100)
  const nextSpot = diagrammaticFieldX(next.before.yardline_100)
  return previousSpot !== null && nextSpot !== null && previousSpot !== nextSpot
}

export function diagrammaticFieldX(yardline100: number | null) {
  if (yardline100 === null || !Number.isInteger(yardline100) || yardline100 < 0 || yardline100 > 100) return null
  return 100 - yardline100
}

export function fieldBallPosition(yardline100: number | null) {
  const position = diagrammaticFieldX(yardline100)
  return {
    xPercent: position === null ? 50 : Math.max(0, Math.min(100, position)),
    sourceVerified: position !== null,
  }
}

function gameDate(value: string | null) {
  if (!value) return 'Date unavailable'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Date unavailable' : date.toLocaleDateString(undefined, {
    month: 'long', day: 'numeric', year: 'numeric',
  })
}

function scoreValue(value: number | null | undefined) {
  return Number.isInteger(value) ? value : '—'
}

function Field({ event, teams, animateBall = false }: { event: PixelEvent | null; teams?: FieldTeams; animateBall?: boolean }) {
  const spot = event?.confidence.field === 'verified' ? event.before.yardline_100 : null
  const down = event?.before.down
  const distance = event?.before.yards_to_go
  const ball = fieldBallPosition(spot)
  const ballLeft = 10 + ball.xPercent * 0.8
  const firstDownSpot = spot !== null && Number.isInteger(distance) && (distance as number) >= 0
    ? Math.max(0, spot - (distance as number))
    : null
  const firstDownLeft = diagrammaticFieldX(firstDownSpot)
  const offenseTeam = event?.offense_team_id
    ? [teams?.home, teams?.away].find(team => team?.team_id === event.offense_team_id)
    : undefined
  const ownEndName = offenseTeam?.name || offenseTeam?.abbreviation || teams?.away.name || teams?.away.abbreviation || 'AWAY'
  const opponentTeam = offenseTeam === teams?.home ? teams?.away : teams?.home
  const opponentEndName = offenseTeam
    ? opponentTeam?.name || opponentTeam?.abbreviation || 'OPPONENT'
    : teams?.home.name || teams?.home.abbreviation || 'HOME'
  const offenseOrientationKnown = Boolean(offenseTeam)
  const teamTextLength = (name: string) => Math.min(224, Math.max(54, name.length * 13))
  const description = ball.sourceVerified
    ? offenseOrientationKnown
      ? `Diagrammatic field from ${ownEndName} toward ${opponentEndName}. Ball at ${spot} yards from the opponent end zone.`
      : `Diagrammatic field for ${ownEndName} and ${opponentEndName}. Ball at ${spot} yards from the opponent end zone; team orientation unavailable.`
    : offenseOrientationKnown
      ? `Diagrammatic field from ${ownEndName} toward ${opponentEndName}. Ball spot unavailable; the centered football is an illustrative placeholder.`
      : `Diagrammatic field for ${ownEndName} and ${opponentEndName}. Ball spot and team orientation unavailable; the centered football is an illustrative placeholder.`

  return (
    <div className="lp-rz-field-wrap">
      <div className="lp-rz-field" role="img" aria-label={description}>
        <svg className="lp-rz-field-art" viewBox="0 0 1000 240" preserveAspectRatio="none" aria-hidden="true">
          <rect width="1000" height="240" fill="#16251b" />
          <rect x="0" y="0" width="100" height="240" fill="#34243d" />
          <rect x="900" y="0" width="100" height="240" fill="#34243d" />
          {Array.from({ length: 10 }, (_, index) => <g key={`endzone-${index}`} opacity={index % 2 ? 0.12 : 0.24}>
            <rect x={index * 10} y="0" width="5" height="240" fill="#d5bd8c" />
            <rect x={900 + index * 10} y="0" width="5" height="240" fill="#d5bd8c" />
          </g>)}
          <rect x="100" y="0" width="800" height="240" fill="#286d3d" />
          {Array.from({ length: 10 }, (_, index) => <rect key={`turf-${index}`} x={100 + index * 80} y="0" width="80" height="240"
            fill={index % 2 ? '#3a854b' : '#286d3d'} opacity="0.72" />)}
          <rect x="100" y="12" width="800" height="216" fill="none" stroke="#e8efce" strokeWidth="4" opacity="0.85" />
          {Array.from({ length: 21 }, (_, index) => {
            const x = 100 + index * 40
            const major = index % 2 === 0
            return <line key={`yard-${index}`} x1={x} y1={major ? 12 : 32} x2={x} y2={major ? 228 : 208}
              stroke={major ? '#edf4d7' : '#d8eac7'} strokeWidth={major ? 3 : 2}
              strokeDasharray={major ? undefined : '5 5'} opacity={major ? 0.82 : 0.58} />
          })}
          {Array.from({ length: 9 }, (_, index) => {
            const x = 180 + index * 80
            const label = index < 5 ? (index + 1) * 10 : (9 - index) * 10
            return <g key={`number-${index}`} fill="#edf4d7" fontFamily="ui-monospace,monospace" fontSize="22" fontWeight="900" textAnchor="middle" opacity="0.9">
              <text x={x} y="44">{label}</text>
              <text x={x} y="205">{label}</text>
            </g>
          })}
          {Array.from({ length: 21 }, (_, index) => {
            if (index % 2 === 0) return null
            const x = 100 + index * 40
            return <g key={`hash-${index}`} stroke="#e5efd1" strokeWidth="2" opacity="0.68">
              <line x1={x} y1="77" x2={x} y2="88" />
              <line x1={x} y1="152" x2={x} y2="163" />
            </g>
          })}
          <line x1="500" y1="12" x2="500" y2="228" stroke="#f1d174" strokeWidth="4" opacity="0.75" />
          {firstDownLeft !== null && <line x1={100 + firstDownLeft * 8} y1="12" x2={100 + firstDownLeft * 8} y2="228"
            stroke="#ffd447" strokeWidth="5" opacity="0.98" />}
          <text x="50" y="120" transform="rotate(-90 50 120)" textAnchor="middle" dominantBaseline="central"
            textLength={teamTextLength(ownEndName)} lengthAdjust="spacingAndGlyphs" fill="#fff0c5" fontFamily="ui-monospace,monospace" fontSize="28" fontWeight="900">
            {ownEndName.toUpperCase()}
          </text>
          <text x="950" y="120" transform="rotate(90 950 120)" textAnchor="middle" dominantBaseline="central"
            textLength={teamTextLength(opponentEndName)} lengthAdjust="spacingAndGlyphs" fill="#fff0c5" fontFamily="ui-monospace,monospace" fontSize="28" fontWeight="900">
            {opponentEndName.toUpperCase()}
          </text>
          <text x="500" y="236" textAnchor="middle" fill="#ecf4d6" fontFamily="ui-monospace,monospace" fontSize="12" fontWeight="800" opacity="0.9">
            {offenseTeam ? 'OFFENSE → OPPONENT GOAL' : 'FIELD DIRECTION UNAVAILABLE'}
          </text>
        </svg>
        {spot !== null && <span className={`lp-rz-line-of-scrimmage${animateBall ? ' is-animated' : ''}`} style={{ left: `${ballLeft}%` }} />}
        {spot !== null && <span className="lp-rz-line-label lp-rz-los-label" style={{ left: `${ballLeft}%` }}>LINE OF SCRIMMAGE</span>}
        {firstDownLeft !== null && <span className="lp-rz-line-label lp-rz-first-down-label" style={{ left: `${10 + firstDownLeft * 0.8}%` }}>FIRST DOWN</span>}
        <svg className={`lp-rz-football${ball.sourceVerified ? '' : ' is-placeholder'}${animateBall ? ' is-animated' : ''}`} viewBox="0 0 56 34" aria-hidden="true"
          style={{ left: `${ballLeft}%` }}>
          <path d="M4 17C9 3 47 3 52 17 47 31 9 31 4 17Z" fill="#995126" stroke="#1b1712" strokeWidth="3" />
          <path d="M5 17C11 5 45 5 51 17 45 29 11 29 5 17Z" fill="none" stroke="#fff0d3" strokeWidth="1.5" />
          <path d="M14 17H42M25 11V23M29 11V23M21 12V22M33 12V22" fill="none" stroke="#fff4dd" strokeWidth="2.2" strokeLinecap="square" />
        </svg>
        {!ball.sourceVerified && <span className="lp-rz-ball-unknown" style={{ left: `${ballLeft}%` }} aria-hidden="true">?</span>}
      </div>
      <p className="lp-rz-spot-status" aria-live="polite">
        {spot === null
          ? 'Ball spot unavailable. Centered football is illustrative only.'
          : `${spot} yards to opponent end zone${down && distance !== null ? ` · ${down}${down === 1 ? 'st' : down === 2 ? 'nd' : down === 3 ? 'rd' : 'th'} & ${distance}` : ''}`}
      </p>
    </div>
  )
}

function AudioControl({ event, enabled, volume, onToggle, onVolumeChange }: {
  event: PixelEvent | null
  enabled: boolean
  volume: number
  onToggle: () => void
  onVolumeChange: (value: number) => void
}) {
  return (
    <div className="lp-rz-audio-controls">
      <button type="button" className="lp-rz-button" onClick={onToggle} aria-pressed={enabled}>
        Sound {enabled ? 'on' : 'off'}
      </button>
      <label className="lp-rz-volume">Volume
        <input aria-label="Sound volume" type="range" min="0" max="1" step="0.05"
          value={volume} onChange={event => onVolumeChange(Number(event.currentTarget.value))} />
      </label>
      <span className="lp-rz-sr-only" aria-live="polite">
        {event?.scoring_play && event.event_type === 'touchdown' ? 'Touchdown event caption available.' : ''}
      </span>
    </div>
  )
}

function gameStatus(game: Game) {
  if (game.status === 'LIVE') return `LIVE · ${game.livePeriod?.display || (game.livePeriod?.number ? `Q${game.livePeriod.number}` : 'In progress')}`
  if (game.status === 'FINAL') return game.statusDetail || 'FINAL'
  const start = game.startTime ? new Date(game.startTime) : null
  return start && !Number.isNaN(start.getTime())
    ? start.toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
    : 'Kickoff time unavailable'
}

function ChannelLanding({ scoreboard, onWatchArchive, onBack, expanded, initialPinnedGameId, surfaceRef, onFullscreen }: {
  scoreboard?: Props['scoreboard']
  onWatchArchive: (gameId: string) => void
  onBack?: () => void
  expanded: boolean
  initialPinnedGameId?: string | null
  surfaceRef: React.RefObject<HTMLElement>
  onFullscreen: () => void
}) {
  const liveGames = scoreboard?.games.filter(game => game.status === 'LIVE') || []
  const [pinnedGameId, setPinnedGameId] = useState<string | null>(initialPinnedGameId || null)
  const [archiveGameId, setArchiveGameId] = useState('401772829')
  const [refreshVersion, setRefreshVersion] = useState(0)
  const [playByPlay, setPlayByPlay] = useState<PlayByPlaySnapshot | null>(null)
  const [playByPlayLoading, setPlayByPlayLoading] = useState(false)
  const [playByPlayUnavailable, setPlayByPlayUnavailable] = useState(false)
  const autoGame = chooseScoreboardDirectorGame(liveGames)
  const selectedGame = liveGames.find(game => game.gameId === pinnedGameId) || autoGame
  const isPinned = Boolean(selectedGame && pinnedGameId === selectedGame.gameId)
  const fieldTeams: FieldTeams | undefined = selectedGame
    ? playByPlay?.pixel_red_zone?.game?.teams || {
        home: { team_id: null, abbreviation: selectedGame.homeTeam.teamId || null, name: selectedGame.homeTeam.name || null },
        away: { team_id: null, abbreviation: selectedGame.awayTeam.teamId || null, name: selectedGame.awayTeam.name || null },
      }
    : undefined
  const scheduledGames = (scoreboard?.games || [])
    .filter(game => game.status === 'SCHEDULED')
    .sort((left, right) => (left.startTime || '').localeCompare(right.startTime || ''))
  const nextGame = scheduledGames[0]
  const freshness = scoreboard?.age === null || scoreboard?.age === undefined
    ? 'Scoreboard age unavailable'
    : `Scoreboard snapshot · ${Math.max(1, Math.round(scoreboard.age / 60))} min ago`
  const recentPlays = (playByPlay?.periods || []).flatMap(period => period.plays || [])
    .filter(play => play.playId !== null && play.playId !== undefined)
  const lastPlay = recentPlays[recentPlays.length - 1] || null
  const canonicalEvents = playByPlay?.pixel_red_zone?.events || []
  const candidateEvent = latestCanonicalEvent(canonicalEvents)
  const [canonicalEvent, setCanonicalEvent] = useState<PixelEvent | null>(null)
  const displayedEventRef = useRef<{ gameId: string; event: PixelEvent | null } | null>(null)

  useEffect(() => {
    if (!selectedGame) {
      displayedEventRef.current = null
      setCanonicalEvent(null)
      return
    }
    const next = playByPlay?.eventId === selectedGame.gameId ? candidateEvent : null
    const previous = displayedEventRef.current
    if (!previous || previous.gameId !== selectedGame.gameId) {
      displayedEventRef.current = { gameId: selectedGame.gameId, event: next }
      setCanonicalEvent(next)
      return
    }
    if (shouldAdvanceCanonicalEvent(previous.event, next)) {
      displayedEventRef.current = { gameId: selectedGame.gameId, event: next }
      setCanonicalEvent(next)
    }
  }, [candidateEvent, playByPlay?.eventId, selectedGame?.gameId])

  useEffect(() => {
    if (!selectedGame) {
      setPlayByPlay(null)
      setPlayByPlayLoading(false)
      setPlayByPlayUnavailable(false)
      return
    }
    const controller = new AbortController()
    setPlayByPlay(null)
    setPlayByPlayLoading(true)
    setPlayByPlayUnavailable(false)
    fetch(`/api/nfl/game/${encodeURIComponent(selectedGame.gameId)}/playbyplay`, {
      cache: 'no-store', signal: controller.signal,
    }).then(response => response.ok ? response.json() as Promise<PlayByPlaySnapshot> : Promise.reject(new Error(String(response.status))))
      .then(data => {
        setPlayByPlay(data)
        setPlayByPlayLoading(false)
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setPlayByPlayUnavailable(true)
          setPlayByPlayLoading(false)
        }
      })
    return () => controller.abort()
  }, [refreshVersion, selectedGame?.gameId])

  useEffect(() => {
    if (!selectedGame) return
    let timer: number | null = null
    const stop = () => {
      if (timer !== null) window.clearInterval(timer)
      timer = null
    }
    const start = () => {
      stop()
      if (document.visibilityState === 'visible') {
        timer = window.setInterval(() => setRefreshVersion(version => version + 1), 60_000)
      }
    }
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') setRefreshVersion(version => version + 1)
      start()
    }
    start()
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      stop()
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [selectedGame?.gameId])

  return (
    <section ref={surfaceRef} className={`lp-rz-player${expanded ? ' lp-rz-live-expanded' : ' lp-rz-player-room'}`} aria-label="Pixel Red Zone live channel">
      <header className="lp-rz-topbar">
        <div>
          <p className="lp-rz-brand">LEGENDARY PICKS / PIXEL RED ZONE</p>
          <h2 id="pixel-red-zone-title" tabIndex={-1}>Pixel Red Zone</h2>
        </div>
        <div className="lp-rz-top-actions">
          <span className="lp-rz-replay-badge">{liveGames.length ? (isPinned ? 'PINNED GAME' : 'AUTO SELECT') : 'SCOREBOARD'}</span>
          {isPinned && <button type="button" className="lp-rz-button" onClick={() => setPinnedGameId(null)}>Auto select</button>}
          {expanded
            ? <button type="button" className="lp-rz-button" onClick={onFullscreen}>Fullscreen</button>
            : <Link className="lp-rz-button" href={{
                pathname: '/nfl/pixel-red-zone',
                query: { mode: 'live', from: 'room', ...(pinnedGameId ? { game: pinnedGameId } : {}) },
              }}>Expand</Link>}
          <button type="button" className="lp-rz-button" onClick={onBack}>Back to room</button>
        </div>
      </header>
      <div className="lp-rz-channel-status" aria-live="polite">
        {scoreboard?.loading ? <p role="status">Loading the current NFL scoreboard…</p>
          : scoreboard?.unavailable ? <p role="status">The NFL scoreboard is unavailable. No live game is being inferred.</p>
            : liveGames.length ? <>
              <p className="lp-rz-channel-heading">NFL games in progress</p>
              <ul className="lp-rz-game-list">{liveGames.map(game => (
                  <li key={game.gameId} className={selectedGame?.gameId === game.gameId ? 'is-selected' : undefined}>
                    <span><strong>{game.awayTeam.teamId || game.awayTeam.name}</strong> at <strong>{game.homeTeam.teamId || game.homeTeam.name}</strong>
                      <small>{gameStatus(game)}{game.situation?.redZone === true ? ' · ESPN RED ZONE' : ''}</small></span>
                    <b>{game.awayTeam.score ?? '—'} – {game.homeTeam.score ?? '—'}</b>
                    <button type="button" className="lp-rz-pin-button"
                      aria-pressed={pinnedGameId === game.gameId}
                      onClick={() => setPinnedGameId(current => current === game.gameId ? null : game.gameId)}>
                      {pinnedGameId === game.gameId ? 'Unpin game' : 'Pin game'}
                    </button>
                </li>
              ))}</ul>
              <p className="lp-rz-source-caption">{freshness} · Auto selection follows ESPN’s positive red-zone flag, then stable game ID. A pin overrides auto selection. Scoreboard and play-by-play refresh once a minute while visible.</p>
                {selectedGame && <div className="lp-rz-event-panel lp-rz-channel-play">
                  <div className="lp-rz-event-meta">
                    <span>{playByPlay?.publisher || 'ESPN'} play-by-play · {selectedGame.awayTeam.teamId || selectedGame.awayTeam.name} at {selectedGame.homeTeam.teamId || selectedGame.homeTeam.name}</span>
                    <span>{playByPlay?.eventId ? `EVENT ${playByPlay.eventId}` : 'SOURCE EVENT ID UNAVAILABLE'}</span>
                  </div>
                  {playByPlayLoading ? <>
                    <p role="status">Loading the selected game’s ESPN play-by-play snapshot…</p>
                    <Field event={null} teams={fieldTeams} />
                  </>
                    : playByPlayUnavailable || !playByPlay?.available ? <>
                      <p className="lp-rz-unavailable-note">Play-by-play is unavailable for this snapshot. The scoreboard remains available.</p>
                      <Field event={null} teams={fieldTeams} />
                    </>
                      : canonicalEvent ? <>
                        <div className="lp-rz-gamebar">
                          <div><strong>{selectedGame.awayTeam.teamId || selectedGame.awayTeam.name}</strong><b>{canonicalEvent.after.score?.away ?? selectedGame.awayTeam.score ?? '—'}</b></div>
                          <span>{canonicalEvent.period ? `Q${canonicalEvent.period}` : 'LIVE'}{canonicalEvent.clock ? ` · ${canonicalEvent.clock}` : ''}</span>
                          <div><strong>{selectedGame.homeTeam.teamId || selectedGame.homeTeam.name}</strong><b>{canonicalEvent.after.score?.home ?? selectedGame.homeTeam.score ?? '—'}</b></div>
                        </div>
                        <Field event={canonicalEvent} teams={fieldTeams} />
                        <p className="lp-rz-caption">{canonicalEvent.source_event_type || 'ESPN play'} · {canonicalEvent.display_text || 'Publisher play text unavailable.'}</p>
                        <p className="lp-rz-source-caption">Source event {canonicalEvent.source.event_id} · sequence {canonicalEvent.sequence ?? 'unavailable'} · {canonicalEvent.source.occurred_at_utc || 'publisher event time unavailable'}</p>
                        {canonicalEvent.review_state === 'pending' && <p className="lp-rz-review">Source review pending.</p>}
                        {canonicalEvent.review_state === 'overturned' && <p className="lp-rz-review">Source correction: the prior ruling was overturned.</p>}
                        {playByPlay?.pixel_red_zone?.source?.publisher_updated_at && <p className="lp-rz-source-caption">ESPN summary updated: {playByPlay.pixel_red_zone.source.publisher_updated_at}</p>}
                        {playByPlay?.pixel_red_zone?.source?.observed_at_utc && <p className="lp-rz-source-caption">Observed by this service: {playByPlay.pixel_red_zone.source.observed_at_utc}</p>}
                      </> : lastPlay ? <>
                        <Field event={null} teams={fieldTeams} />
                        <p className="lp-rz-caption">{lastPlay.type || 'Play'} · {lastPlay.text || 'Publisher play text unavailable.'}</p>
                        <p className="lp-rz-source-caption">Source play {lastPlay.playId}{lastPlay.sequenceNumber != null ? ` · sequence ${lastPlay.sequenceNumber}` : ''}{lastPlay.period ? ` · Q${lastPlay.period}` : ''}{lastPlay.clock ? ` · ${lastPlay.clock}` : ''}{lastPlay.wallclock ? ` · ${lastPlay.wallclock}` : ''}</p>
                        {playByPlay?.publisherUpdatedAt && <p className="lp-rz-source-caption">ESPN summary updated: {playByPlay.publisherUpdatedAt}</p>}
                      </> : <>
                        <Field event={null} teams={fieldTeams} />
                        <p className="lp-rz-unavailable-note">No identified source play is available in this snapshot.</p>
                      </>}
                  <button type="button" className="lp-rz-button" onClick={() => setRefreshVersion(version => version + 1)} disabled={playByPlayLoading}>
                    Refresh play-by-play
                  </button>
                  <div className="lp-rz-footer-links">
                    <Link href={`/game/nfl/${selectedGame.gameId}`}>Game details</Link>
                  </div>
                </div>}
            </> : <>
              <p className="lp-rz-channel-heading">No NFL games are live right now.</p>
              {nextGame && <p>Next up: {nextGame.awayTeam.teamId || nextGame.awayTeam.name} at {nextGame.homeTeam.teamId || nextGame.homeTeam.name} · {gameStatus(nextGame)}</p>}
              {!nextGame && <p>The channel is off air until an NFL game is scheduled.</p>}
              {scoreboard?.source && <p className="lp-rz-source-caption">Score source: {scoreboard.source} · {freshness}</p>}
            </>}
      </div>
      <div className="lp-rz-archive-choice">
        <label className="lp-rz-archive-select" htmlFor="pixel-red-zone-archive-game">
          <span>Archived game · {replayArchiveCatalog.length} source-checked games</span>
          <select id="pixel-red-zone-archive-game" value={archiveGameId} onChange={event => setArchiveGameId(event.currentTarget.value)}>
            {replayArchiveCatalog.map(archive => <option key={archive.game_id} value={archive.game_id}>
              {archive.label} · {gameDate(archive.date)}
            </option>)}
          </select>
        </label>
        <button type="button" className="lp-rz-button lp-rz-primary" onClick={() => onWatchArchive(archiveGameId)}>
          Watch archived ESPN replay
        </button>
      </div>
    </section>
  )
}

export default function PixelRedZonePlayer({ roomMode = false, viewMode, initialPinnedGameId, onBack, scoreboard, loadReplay = loadBundledReplay }: Props) {
  const [payload, setPayload] = useState<ReplayPayload | null>(null)
  const [selectedReplayId, setSelectedReplayId] = useState('401772829')
  const [archiveSelected, setArchiveSelected] = useState(!roomMode && viewMode !== 'live')
  const [loading, setLoading] = useState(!roomMode && viewMode !== 'live')
  const [unavailable, setUnavailable] = useState(false)
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [soundEnabled, setSoundEnabled] = useState(false)
  const [volume, setVolume] = useState(0.35)
  const [fullScreenMessage, setFullScreenMessage] = useState('')
  const surfaceRef = useRef<HTMLElement | null>(null)
  const audioRef = useRef<AudioContext | null>(null)
  const gainRef = useRef<GainNode | null>(null)
  const lastIndexRef = useRef<number | null>(null)
  const playedCuesRef = useRef(new Set<string>())

  useEffect(() => {
    if (!archiveSelected) return
    let active = true
    setLoading(true)
    setUnavailable(false)
    loadReplay(selectedReplayId).then(data => {
        if (data.mode !== 'replay' || !Array.isArray(data.events) || data.events.length === 0) throw new Error('invalid replay')
        if (!active) return
        setPayload(data)
        setLoading(false)
      })
      .catch(() => {
        if (active) {
          setUnavailable(true)
          setLoading(false)
        }
      })
    return () => { active = false }
  }, [archiveSelected, loadReplay, selectedReplayId])

  useEffect(() => {
    if (!roomMode || !archiveSelected) return
    requestAnimationFrame(() => document.getElementById('pixel-red-zone-title')?.focus())
  }, [archiveSelected, roomMode])

  const events = payload?.events || []
  const event = events[index] || null
  const previousEvent = index > 0 && lastIndexRef.current === index - 1 ? events[index - 1] || null : null
  const animateReplaySpot = canAnimateReplaySpotTransition(previousEvent, event, lastIndexRef.current === index - 1)
  const beforeScore = event?.after.score || event?.before.score
  const homeScore = beforeScore?.home ?? payload?.game.score.home ?? null
  const awayScore = beforeScore?.away ?? payload?.game.score.away ?? null
  const home = payload?.game.teams.home
  const away = payload?.game.teams.away

  const sourceCaption = useMemo(() => {
    if (!event) return 'Source play caption unavailable.'
    const playTime = event.clock ? `${event.clock} remaining` : 'game clock unavailable'
    const quarter = event.period ? `Q${event.period}` : 'period unavailable'
    const review = event.review_state === 'overturned' ? ' · ruling overturned by source review'
      : event.review_state === 'pending' ? ' · source review pending'
        : ''
    return `${quarter} ${playTime} · ${event.display_text || 'Play description unavailable.'}${review}`
  }, [event])

  const playCue = useCallback((current: PixelEvent) => {
    if (!soundEnabled || !audioRef.current || !gainRef.current) return
    const confirmed = current.review_state === 'none' || current.review_state === 'confirmed'
    const cueKey = `${current.source.event_id}:${current.source.revision}`
    if (!confirmed || playedCuesRef.current.has(cueKey)) return
    let notes: number[] = []
    if (current.scoring_play === true && current.event_type === 'touchdown') notes = [587, 740, 880]
    else if (current.is_turnover === true) notes = [440, 330, 220]
    if (!notes.length) return
    playedCuesRef.current.add(cueKey)
    const context = audioRef.current
    const master = gainRef.current
    const startAt = context.currentTime + 0.015
    notes.forEach((frequency, noteIndex) => {
      const oscillator = context.createOscillator()
      const envelope = context.createGain()
      oscillator.type = 'square'
      oscillator.frequency.setValueAtTime(frequency, startAt + noteIndex * 0.13)
      envelope.gain.setValueAtTime(0, startAt + noteIndex * 0.13)
      envelope.gain.linearRampToValueAtTime(0.16, startAt + noteIndex * 0.13 + 0.025)
      envelope.gain.exponentialRampToValueAtTime(0.001, startAt + noteIndex * 0.13 + 0.16)
      oscillator.connect(envelope)
      envelope.connect(master)
      oscillator.start(startAt + noteIndex * 0.13)
      oscillator.stop(startAt + noteIndex * 0.13 + 0.17)
    })
  }, [soundEnabled])

  useEffect(() => {
    if (lastIndexRef.current !== null && index !== lastIndexRef.current && index > lastIndexRef.current && event) {
      playCue(event)
    }
    lastIndexRef.current = index
  }, [event, index, playCue])

  useEffect(() => {
    if (gainRef.current) gainRef.current.gain.setTargetAtTime(volume * 0.55, audioRef.current?.currentTime || 0, 0.04)
  }, [volume])

  useEffect(() => {
    if (!playing || events.length === 0) return
    const timeout = window.setTimeout(() => {
      setIndex(current => {
        if (current + 1 >= events.length) {
          setPlaying(false)
          return current
        }
        return current + 1
      })
    }, 2400)
    return () => window.clearTimeout(timeout)
  }, [events.length, index, playing])

  useEffect(() => {
    const pauseWhenHidden = () => {
      if (document.visibilityState !== 'hidden') return
      setPlaying(false)
      if (audioRef.current?.state === 'running') void audioRef.current.suspend()
    }
    document.addEventListener('visibilitychange', pauseWhenHidden)
    return () => document.removeEventListener('visibilitychange', pauseWhenHidden)
  }, [])

  useEffect(() => () => {
    const context = audioRef.current
    audioRef.current = null
    gainRef.current = null
    if (context && context.state !== 'closed') void context.close()
  }, [])

  async function toggleSound() {
    if (soundEnabled) {
      setSoundEnabled(false)
      return
    }
    const AudioContextConstructor = window.AudioContext
    if (!AudioContextConstructor) {
      setFullScreenMessage('Audio is unavailable in this browser. Captions remain on.')
      return
    }
    const context = audioRef.current || new AudioContextConstructor()
    audioRef.current = context
    if (!gainRef.current) {
      const gain = context.createGain()
      gain.gain.value = volume * 0.55
      gain.connect(context.destination)
      gainRef.current = gain
    }
    try {
      await context.resume()
      setSoundEnabled(true)
      setFullScreenMessage('Original event tones enabled. No broadcast audio is used.')
    } catch {
      setFullScreenMessage('Tap Sound on again to enable audio. Captions remain on.')
    }
  }

  async function requestFullScreen() {
    const element = surfaceRef.current
    if (!element?.requestFullscreen) {
      setFullScreenMessage('Fullscreen is unavailable. The expanded page remains usable.')
      return
    }
    try {
      await element.requestFullscreen()
      setFullScreenMessage('Fullscreen view enabled.')
    } catch {
      setFullScreenMessage('Fullscreen was blocked. The expanded page remains usable.')
    }
  }

  const previous = () => { setPlaying(false); setIndex(current => Math.max(0, current - 1)) }
  const next = () => { setPlaying(false); setIndex(current => Math.min(Math.max(0, events.length - 1), current + 1)) }
  const togglePlayback = () => {
    if (!events.length) return
    if (index >= events.length - 1) setIndex(0)
    setPlaying(value => !value)
  }

  if (!archiveSelected && (roomMode || viewMode === 'live')) {
    return <ChannelLanding
      scoreboard={scoreboard}
      onWatchArchive={gameId => {
        setSelectedReplayId(gameId)
        setArchiveSelected(true)
      }}
      onBack={onBack}
      expanded={!roomMode}
      initialPinnedGameId={initialPinnedGameId}
      surfaceRef={surfaceRef}
      onFullscreen={requestFullScreen}
    />
  }

  return (
    <section ref={surfaceRef} className={`lp-rz-player${roomMode ? ' lp-rz-player-room' : ''}`} aria-label="Pixel Red Zone historical replay">
      <header className="lp-rz-topbar">
        <div>
          <p className="lp-rz-brand">LEGENDARY PICKS / PIXEL RED ZONE</p>
          <h2 id={roomMode ? 'pixel-red-zone-title' : undefined} tabIndex={roomMode ? -1 : undefined}>
            {loading ? 'Loading replay…' : unavailable ? 'Replay unavailable' : 'Historical game replay'}
          </h2>
        </div>
        <div className="lp-rz-top-actions">
          <span className="lp-rz-replay-badge">REPLAY</span>
          {!roomMode && <button type="button" className="lp-rz-button" onClick={requestFullScreen}>Fullscreen</button>}
          {!roomMode && <button type="button" className="lp-rz-button" onClick={onBack}>Back to room</button>}
          {roomMode && <Link className="lp-rz-button" href="/nfl/pixel-red-zone">Expand</Link>}
          {roomMode && <button type="button" className="lp-rz-button" onClick={onBack}>Back to room</button>}
        </div>
      </header>

      {loading ? <p className="lp-rz-message" role="status">Loading frozen ESPN play-by-play…</p>
        : unavailable || !payload ? <p className="lp-rz-message" role="status">The archived replay is unavailable. No live data is being substituted.</p>
          : <>
            <div className="lp-rz-gamebar">
              <div><strong>{away?.abbreviation || 'AWAY'}</strong><b>{scoreValue(awayScore)}</b></div>
              <span>{event?.period ? `Q${event.period}` : 'FINAL'}{event?.clock ? ` · ${event.clock}` : ''}</span>
              <div><strong>{home?.abbreviation || 'HOME'}</strong><b>{scoreValue(homeScore)}</b></div>
            </div>
            <p className="lp-rz-replay-meta">{away?.name} at {home?.name} · {gameDate(payload.game.date)} · Frozen ESPN summary capture</p>
            <Field event={event} teams={payload.game.teams} animateBall={animateReplaySpot} />

            <div className="lp-rz-event-panel">
              <div className="lp-rz-event-meta">
                <span>{event?.source_event_type || 'Publisher event'}</span>
                <span>PLAY {index + 1} / {events.length}{event?.sequence !== null ? ` · ESPN SEQ ${event?.sequence}` : ''}</span>
                {event?.review_state === 'overturned' && <strong className="lp-rz-review">SOURCE CORRECTION</strong>}
                {event?.review_state === 'pending' && <strong className="lp-rz-review">UNDER REVIEW</strong>}
              </div>
              <p className="lp-rz-caption" aria-live="polite">{sourceCaption}</p>
              {event?.point_after_attempt?.text && <p className="lp-rz-source-caption">ESPN try field: {event.point_after_attempt.text}. This remains attached to the touchdown record.</p>}
              <p className="lp-rz-source-caption">Caption source: ESPN play-by-play · {event?.source.play_id || 'ID unavailable'} · {event?.source.occurred_at_utc || 'publisher event time unavailable'}</p>
              {event?.before.yardline_100 === null && <p className="lp-rz-unavailable-note">This event class has no independently verified ball spot.</p>}
            </div>

            <div className="lp-rz-controls" aria-label="Replay controls">
              <button type="button" className="lp-rz-button" onClick={previous} disabled={index === 0}>Previous play</button>
              <button type="button" className="lp-rz-button lp-rz-primary" onClick={togglePlayback}>
                {playing ? 'Pause replay' : index === events.length - 1 ? 'Replay from start' : 'Play replay'}
              </button>
              <button type="button" className="lp-rz-button" onClick={next} disabled={index >= events.length - 1}>Next play</button>
              <label className="lp-rz-timeline">Play {index + 1} of {events.length}
                <input aria-label="Replay play position" type="range" min="0" max={Math.max(0, events.length - 1)}
                  value={index} onChange={event => { setPlaying(false); setIndex(Number(event.currentTarget.value)) }} />
              </label>
              <AudioControl event={event} enabled={soundEnabled} volume={volume} onToggle={toggleSound} onVolumeChange={setVolume} />
            </div>
            <p className="lp-rz-audio-note">Muted by default. Original synthesized event tones only; no broadcast audio. Captions remain on.</p>
            <p className="lp-rz-status" role="status">{fullScreenMessage}</p>
            <div className="lp-rz-footer-links">
              <Link href={`/game/nfl/${payload.game.game_id}`}>Game details</Link>
              <Link href="/leagues/nfl?tab=camp">NFL War Room</Link>
              <Link href="/scores?league=nfl">NFL scores</Link>
            </div>
          </>}
    </section>
  )
}
