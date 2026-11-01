import Link from 'next/link'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Game } from '../../services/sports'

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

export type ReplayPayload = {
  mode: 'replay'
  game: {
    game_id: string
    date: string | null
    status: string
    teams: {
      home: { team_id: string | null; abbreviation: string | null; name: string | null }
      away: { team_id: string | null; abbreviation: string | null; name: string | null }
    }
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
}

type Props = {
  roomMode?: boolean
  onBack?: () => void
  scoreboard?: { games: Game[]; age: number | null; loading: boolean; unavailable: boolean; source: string | null }
  loadReplay?: () => Promise<ReplayPayload>
}

async function loadBundledReplay(): Promise<ReplayPayload> {
  const imported = await import('../../backend/fixtures/pixel_red_zone/401772829.json')
  return (imported.default || imported) as unknown as ReplayPayload
}

export function chooseScoreboardDirectorGame(games: Game[]): Game | null {
  return [...games]
    .filter(game => game.status === 'LIVE')
    .sort((left, right) => Number(right.situation?.redZone === true) - Number(left.situation?.redZone === true)
      || left.gameId.localeCompare(right.gameId))[0] || null
}

export function diagrammaticFieldX(yardline100: number | null) {
  if (yardline100 === null || !Number.isInteger(yardline100) || yardline100 < 0 || yardline100 > 100) return null
  return 10 + (100 - yardline100) * 0.8
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

function Field({ event }: { event: PixelEvent | null }) {
  const spot = event?.confidence.field === 'verified' ? event.before.yardline_100 : null
  const down = event?.before.down
  const distance = event?.before.yards_to_go
  const ballLeft = diagrammaticFieldX(spot)
  const firstDownSpot = spot !== null && Number.isInteger(distance)
    ? Math.max(0, spot - (distance as number))
    : null
  const firstDownLeft = diagrammaticFieldX(firstDownSpot)

  return (
    <div className="lp-rz-field-wrap">
      <div className="lp-rz-field" aria-label="Diagrammatic football field, oriented toward the opponent end zone">
        <div className="lp-rz-endzone lp-rz-own-end">OWN<br />END ZONE</div>
        <div className="lp-rz-playfield">
          {Array.from({ length: 9 }, (_, index) => <i key={index} style={{ left: `${index * 10}%` }} />)}
          {firstDownLeft !== null && <b className="lp-rz-first-down" style={{ left: `${firstDownLeft}%` }} aria-label="Source verified first-down line" />}
          {ballLeft !== null && <b className="lp-rz-ball" style={{ left: `${ballLeft}%` }} aria-label="Source verified ball spot" />}
          <span className="lp-rz-yard-label lp-rz-yard-20">20</span>
          <span className="lp-rz-yard-label lp-rz-yard-50">50</span>
          <span className="lp-rz-yard-label lp-rz-yard-80">20</span>
          <span className="lp-rz-direction">OFFENSE → OPPONENT END ZONE</span>
        </div>
        <div className="lp-rz-endzone lp-rz-opponent-end">OPPONENT<br />END ZONE</div>
      </div>
      <p className="lp-rz-spot-status" aria-live="polite">
        {spot === null
          ? 'Ball spot unavailable for this event class.'
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

function ChannelLanding({ scoreboard, onWatchArchive, onBack }: {
  scoreboard?: Props['scoreboard']
  onWatchArchive: () => void
  onBack?: () => void
}) {
  const liveGames = scoreboard?.games.filter(game => game.status === 'LIVE') || []
  const [pinnedGameId, setPinnedGameId] = useState<string | null>(null)
  const [refreshVersion, setRefreshVersion] = useState(0)
  const [playByPlay, setPlayByPlay] = useState<PlayByPlaySnapshot | null>(null)
  const [playByPlayLoading, setPlayByPlayLoading] = useState(false)
  const [playByPlayUnavailable, setPlayByPlayUnavailable] = useState(false)
  const autoGame = chooseScoreboardDirectorGame(liveGames)
  const selectedGame = liveGames.find(game => game.gameId === pinnedGameId) || autoGame
  const isPinned = Boolean(selectedGame && pinnedGameId === selectedGame.gameId)
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
    <section className="lp-rz-player lp-rz-player-room" aria-label="Pixel Red Zone channel preview">
      <header className="lp-rz-topbar">
        <div>
          <p className="lp-rz-brand">LEGENDARY PICKS / PIXEL RED ZONE</p>
          <h2 id="pixel-red-zone-title" tabIndex={-1}>Pixel Red Zone</h2>
        </div>
        <div className="lp-rz-top-actions">
          <span className="lp-rz-replay-badge">{liveGames.length ? (isPinned ? 'PINNED GAME' : 'AUTO SELECT') : 'SCOREBOARD'}</span>
          {isPinned && <button type="button" className="lp-rz-button" onClick={() => setPinnedGameId(null)}>Auto select</button>}
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
              <p className="lp-rz-source-caption">{freshness} · Auto selection follows ESPN’s positive red-zone flag, then stable game ID. A pin overrides auto selection. Play-by-play refreshes once a minute while visible.</p>
                {selectedGame && <div className="lp-rz-event-panel lp-rz-channel-play">
                  <div className="lp-rz-event-meta">
                    <span>{playByPlay?.publisher || 'ESPN'} play-by-play · {selectedGame.awayTeam.teamId || selectedGame.awayTeam.name} at {selectedGame.homeTeam.teamId || selectedGame.homeTeam.name}</span>
                    <span>{playByPlay?.eventId ? `EVENT ${playByPlay.eventId}` : 'SOURCE EVENT ID UNAVAILABLE'}</span>
                  </div>
                  {playByPlayLoading ? <p role="status">Loading the selected game’s ESPN play-by-play snapshot…</p>
                    : playByPlayUnavailable || !playByPlay?.available ? <p className="lp-rz-unavailable-note">Play-by-play is unavailable for this snapshot. The scoreboard remains available.</p>
                      : lastPlay ? <>
                        <p className="lp-rz-caption">{lastPlay.type || 'Play'} · {lastPlay.text || 'Publisher play text unavailable.'}</p>
                        <p className="lp-rz-source-caption">Source play {lastPlay.playId}{lastPlay.sequenceNumber != null ? ` · sequence ${lastPlay.sequenceNumber}` : ''}{lastPlay.period ? ` · Q${lastPlay.period}` : ''}{lastPlay.clock ? ` · ${lastPlay.clock}` : ''}{lastPlay.wallclock ? ` · ${lastPlay.wallclock}` : ''}</p>
                        {playByPlay?.publisherUpdatedAt && <p className="lp-rz-source-caption">ESPN summary updated: {playByPlay.publisherUpdatedAt}</p>}
                      </> : <p className="lp-rz-unavailable-note">No identified source play is available in this snapshot.</p>}
                  <button type="button" className="lp-rz-button" onClick={() => setRefreshVersion(version => version + 1)} disabled={playByPlayLoading}>
                    Refresh play-by-play
                  </button>
                </div>}
            </> : <>
              <p className="lp-rz-channel-heading">No NFL games are live right now.</p>
              {nextGame && <p>Next up: {nextGame.awayTeam.teamId || nextGame.awayTeam.name} at {nextGame.homeTeam.teamId || nextGame.homeTeam.name} · {gameStatus(nextGame)}</p>}
              {!nextGame && <p>The channel is off air until an NFL game is scheduled.</p>}
              {scoreboard?.source && <p className="lp-rz-source-caption">Score source: {scoreboard.source} · {freshness}</p>}
            </>}
      </div>
      <div className="lp-rz-archive-choice">
        <p>Archived games are separate from live coverage.</p>
        <button type="button" className="lp-rz-button lp-rz-primary" onClick={onWatchArchive}>
          Watch archived ESPN replay
        </button>
      </div>
    </section>
  )
}

export default function PixelRedZonePlayer({ roomMode = false, onBack, scoreboard, loadReplay = loadBundledReplay }: Props) {
  const [payload, setPayload] = useState<ReplayPayload | null>(null)
  const [archiveSelected, setArchiveSelected] = useState(!roomMode)
  const [loading, setLoading] = useState(!roomMode)
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
    loadReplay().then(data => {
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
  }, [archiveSelected, loadReplay])

  useEffect(() => {
    if (!roomMode || !archiveSelected) return
    requestAnimationFrame(() => document.getElementById('pixel-red-zone-title')?.focus())
  }, [archiveSelected, roomMode])

  const events = payload?.events || []
  const event = events[index] || null
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

  if (roomMode && !archiveSelected) {
    return <ChannelLanding scoreboard={scoreboard} onWatchArchive={() => setArchiveSelected(true)} onBack={onBack} />
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
            <Field event={event} />

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
