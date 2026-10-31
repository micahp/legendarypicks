import Link from 'next/link'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { MouseEvent } from 'react'
import { normalizeGame, type Game } from '../../services/sports'
import type { NflSeasonContext } from './types'

type Props = {
  data: NflSeasonContext | null
  loading: boolean
  error: string | null
}

type Preview = 'scores' | 'forecast' | 'props' | 'players' | 'career' | 'arcade' | null

type ModelLock = {
  proj_home: number | null
  proj_away: number | null
  p_home_win: number | null
  locked_at: string | null
  previewed_at: string | null
  line: { captured_at: string | null; source: string; spread: number | null; total: number | null }
  pick: { label: string; status: string }
}

type ModelGame = {
  game_id: string
  week: number
  home: string
  away: string
  kickoff_utc: string | null
  final: { home: number; away: number } | null
  locks: Record<string, ModelLock>
}

type ModelPayload = {
  week: number | null
  models: { version: string; label: string; adopted: boolean }[]
  games: ModelGame[]
}

type ProjectionLine = { mean: number; p10: number | null; p90: number | null }
type ProjectedPlayer = {
  player_id: number
  name: string
  team: string
  position: string
  p_plays: number | null
  v2: Record<string, ProjectionLine>
}
type ProjectionPayload = { week: number | null; players: ProjectedPlayer[] }

type PropLine = { market: string; line: number; side: string; source: string; captured_at?: string | null }
type PropPlayer = { id: number; name: string; team: string; props: PropLine[] }
type PropGame = {
  game_id: number
  home: string
  away: string
  date: string
  start_time?: string | null
  prop_count: number
  players: PropPlayer[]
}
type PropHistory = { games: { date: string; value: number | null; opponent: string }[] }
const HISTORY_MARKETS = new Set([
  'passing_yards', 'rushing_yards', 'receiving_yards', 'receptions', 'passing_tds', 'rushing_tds',
  'receiving_tds', 'interceptions', 'total_touchdowns', 'passing_rushing_yards',
  'rushing_receiving_yards', 'carries', 'targets', 'rush_attempts', 'pass_attempts', 'pass_completions',
  'rushing_touchdowns',
])

function todayLocal() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

function formatDate(value?: string | null, withTime = false) {
  if (!value) return null
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return null
  return parsed.toLocaleString(undefined, withTime
    ? { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }
    : { month: 'short', day: 'numeric' })
}

function SeasonContext({ data, loading, error }: Props) {
  const nextEvent = data?.next_event
  const eventDate = nextEvent?.date ? formatDate(`${nextEvent.date}T12:00:00`) : null
  const source = data?.sources?.[0]
  const verified = source?.verified_at ? formatDate(source.verified_at) : null

  if (loading) return <p className="lp-hq-context" role="status">Loading NFL season context…</p>
  if (error || !data) return <p className="lp-hq-context" role="status">NFL season context is unavailable right now.</p>

  return (
    <p className="lp-hq-context" aria-live="polite">
      <span>{data.phase_label}</span>
      {nextEvent && <span>{nextEvent.label}{eventDate ? ` · ${eventDate}` : ''}</span>}
      {source && <small>{source.name}{verified ? ` · verified ${verified}` : ''}</small>}
    </p>
  )
}

function matchup(home: string, away: string) {
  return `${away} at ${home}`
}

function lockFor(game: ModelGame | null, modelVersion?: string) {
  return game && modelVersion ? game.locks?.[modelVersion] ?? null : null
}

function scoreStatus(game: Game) {
  if (game.status === 'LIVE') {
    const period = game.livePeriod?.display || (game.livePeriod?.number ? `Q${game.livePeriod.number}` : 'In progress')
    return `LIVE · ${period}`
  }
  if (game.status === 'FINAL') return game.statusDetail || 'FINAL'
  return formatDate(game.startTime, true) || 'Scheduled'
}

export default function NflPixelHQ(props: Props) {
  const [preview, setPreview] = useState<Preview>(null)
  const [scores, setScores] = useState<{ games: Game[]; source: string | null; age: number | null; loading: boolean; unavailable: boolean }>(
    { games: [], source: null, age: null, loading: true, unavailable: false },
  )
  const [model, setModel] = useState<{ data: ModelPayload | null; loading: boolean; unavailable: boolean }>(
    { data: null, loading: true, unavailable: false },
  )
  const [projections, setProjections] = useState<{ data: ProjectionPayload | null; loading: boolean; unavailable: boolean }>(
    { data: null, loading: true, unavailable: false },
  )
  const [propsBoard, setPropsBoard] = useState<{ games: PropGame[]; loading: boolean; unavailable: boolean }>(
    { games: [], loading: true, unavailable: false },
  )
  const [history, setHistory] = useState<{ data: PropHistory | null; loading: boolean; unavailable: boolean }>({
    data: null, loading: false, unavailable: false,
  })
  const lastHotspot = useRef<HTMLButtonElement | null>(null)
  const closeButton = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      try {
        const response = await fetch(`/api/nfl/games?date=${todayLocal()}`, { cache: 'no-store', signal: controller.signal })
        if (!response.ok) throw new Error(String(response.status))
        const payload = await response.json()
        const games = Array.isArray(payload) ? payload.map((game: unknown) => normalizeGame(game, 'nfl')) : []
        const source = response.headers.get('x-lp-data-source')
        const age = Number(response.headers.get('x-lp-data-age'))
        setScores({ games, source, age: Number.isFinite(age) && age > 0 ? age : null, loading: false, unavailable: source === 'unavailable' })
      } catch {
        if (!controller.signal.aborted) setScores({ games: [], source: null, age: null, loading: false, unavailable: true })
      }
    }
    load()
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/nfl/model/locks', { cache: 'no-store', signal: controller.signal })
      .then(response => response.ok ? response.json() as Promise<ModelPayload> : Promise.reject(new Error(String(response.status))))
      .then(data => setModel({ data, loading: false, unavailable: false }))
      .catch(() => { if (!controller.signal.aborted) setModel({ data: null, loading: false, unavailable: true }) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/nfl/projections', { cache: 'no-store', signal: controller.signal })
      .then(response => response.ok ? response.json() as Promise<ProjectionPayload> : Promise.reject(new Error(String(response.status))))
      .then(data => setProjections({ data, loading: false, unavailable: false }))
      .catch(() => { if (!controller.signal.aborted) setProjections({ data: null, loading: false, unavailable: true }) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      try {
        const response = await fetch('/api/props/slate?league=nfl&summary=1', { cache: 'no-store', signal: controller.signal })
        if (!response.ok) throw new Error(String(response.status))
        const summary = await response.json() as PropGame[]
        if (!Array.isArray(summary) || !summary.length) {
          setPropsBoard({ games: [], loading: false, unavailable: false })
          return
        }
        const detailsResponse = await fetch(`/api/props/slate?game_id=${summary[0].game_id}`, { cache: 'no-store', signal: controller.signal })
        if (!detailsResponse.ok) throw new Error(String(detailsResponse.status))
        let details = await detailsResponse.json() as PropGame[]
        const selectedGame = Array.isArray(details) ? details[0] : null
        const propCandidates = selectedGame?.players.flatMap(player => player.props.map(prop => ({ player, prop }))) || []
        const selectedSample = propCandidates.find(row => HISTORY_MARKETS.has(row.prop.market)) || propCandidates[0]
        const selectedPlayer = selectedSample?.player
        const selectedProp = selectedSample?.prop
        // Older prop-slate deployments omit captured_at. Recover the timestamp from the
        // existing, date- and player-filtered props endpoint instead of displaying "now".
        if (selectedGame && selectedPlayer && selectedProp && !selectedProp.captured_at) {
          const params = new URLSearchParams({
            league: 'nfl', date: selectedGame.date, player: selectedPlayer.name,
            market: selectedProp.market, limit: '100',
          })
          const sourceResponse = await fetch(`/api/props?${params}`, { cache: 'no-store', signal: controller.signal })
          if (sourceResponse.ok) {
            const sourceRows = await sourceResponse.json() as {
              player_id: number; market: string; line: number; side: string; captured_at?: string | null
            }[]
            const matched = sourceRows.find(row => row.player_id === selectedPlayer.id
              && row.market === selectedProp.market && Number(row.line) === Number(selectedProp.line)
              && row.side === selectedProp.side && row.captured_at)
            if (matched?.captured_at) {
              details = details.map(game => game.game_id !== selectedGame.game_id ? game : ({
                ...game,
                players: game.players.map(player => player.id !== selectedPlayer.id ? player : ({
                  ...player,
                  props: player.props.map(prop => prop === selectedProp ? { ...prop, captured_at: matched.captured_at } : prop),
                })),
              }))
            }
          }
        }
        setPropsBoard({ games: Array.isArray(details) && details.length ? details : summary, loading: false, unavailable: false })
      } catch {
        if (!controller.signal.aborted) setPropsBoard({ games: [], loading: false, unavailable: true })
      }
    }
    load()
    return () => controller.abort()
  }, [])

  const adoptedModel = useMemo(() => model.data?.models.find(candidate => candidate.adopted) || model.data?.models[0], [model.data])
  const nextGame = useMemo(() => {
    const now = Date.now()
    return [...(model.data?.games || [])]
      .filter(game => !game.final && game.kickoff_utc && new Date(game.kickoff_utc).getTime() >= now)
      .sort((a, b) => new Date(a.kickoff_utc as string).getTime() - new Date(b.kickoff_utc as string).getTime())[0] || null
  }, [model.data])
  const nextLock = lockFor(nextGame, adoptedModel?.version)
  const projectionRows = (projections.data?.players || []).filter(player => player.v2?.rec_yds)
  const propCandidates = propsBoard.games.flatMap(game => game.players.flatMap(player =>
    player.props.map(prop => ({ game, player, prop })),
  )).filter(row => row.prop.market && Number.isFinite(row.prop.line))
  const propSample = propCandidates.find(row => HISTORY_MARKETS.has(row.prop.market)) || propCandidates[0]
  const gameToday = scores.games.find(game => game.status === 'LIVE')
    || scores.games.find(game => game.status === 'SCHEDULED')
    || scores.games[0]

  useEffect(() => {
    if (!preview) return
    requestAnimationFrame(() => closeButton.current?.focus())
  }, [preview])

  useEffect(() => {
    if (preview !== 'props' || !propSample) {
      setHistory({ data: null, loading: false, unavailable: false })
      return
    }
    const controller = new AbortController()
    const params = new URLSearchParams({
      player_id: String(propSample.player.id),
      market: propSample.prop.market,
      line: String(propSample.prop.line),
      side: propSample.prop.side,
      league: 'nfl',
    })
    setHistory({ data: null, loading: true, unavailable: false })
    fetch(`/api/props/history?${params}`, { cache: 'no-store', signal: controller.signal })
      .then(response => response.ok ? response.json() as Promise<PropHistory> : Promise.reject(new Error(String(response.status))))
      .then(data => setHistory({ data, loading: false, unavailable: false }))
      .catch(() => { if (!controller.signal.aborted) setHistory({ data: null, loading: false, unavailable: true }) })
    return () => controller.abort()
  }, [preview, propSample?.player.id, propSample?.prop.market, propSample?.prop.line, propSample?.prop.side])

  function openPreview(value: Exclude<Preview, null>, event: MouseEvent<HTMLButtonElement>) {
    lastHotspot.current = event.currentTarget
    setPreview(value)
  }

  function closePreview() {
    setPreview(null)
    requestAnimationFrame(() => lastHotspot.current?.focus())
  }

  const previewTitle = preview === 'scores' ? 'Game center'
    : preview === 'forecast' ? 'Scouting report'
      : preview === 'props' ? 'Player prop board'
        : preview === 'players' ? 'Player projections'
          : preview === 'career' ? 'Career receipts'
            : 'Arcade console'

  return (
    <section className="lp-hq-shell" aria-labelledby="nfl-hq-title">
      <header className="lp-hq-header">
        <div>
          <p className="lp-hq-kicker">LEGENDARY PICKS / NFL HQ</p>
          <h1 id="nfl-hq-title">The War Room</h1>
          <SeasonContext {...props} />
        </div>
        <details className="lp-hq-menu">
          <summary>Research menu</summary>
          <nav aria-label="NFL research destinations">
            <Link href="/scores?league=nfl">Scores</Link>
            <Link href="/leagues/nfl?tab=schedule">NFL slate</Link>
            <Link href="/leagues/nfl?tab=model">Forecasts</Link>
            <Link href="/props?league=nfl">Player props</Link>
            <Link href="/nfl/projections">Player projections</Link>
            <Link href="/leagues/nfl?tab=stats">Season stats</Link>
            <Link href="/predict?sport=football&league=nfl">Predictions</Link>
            <Link href="/">Exit to home</Link>
          </nav>
        </details>
      </header>

      <div className="lp-hq-stage" role="group" aria-label="Interactive NFL analysis room">
        <div className="lp-hq-atmosphere" aria-hidden="true" />

        <button type="button" className="lp-hq-hotspot lp-hq-tv" aria-label="Open NFL scores from the television"
          aria-controls="nfl-hq-preview" aria-expanded={preview === 'scores'} onClick={event => openPreview('scores', event)}>
          <span className="lp-hq-tv-data">
            <b>{scores.loading ? 'GAME CENTER' : gameToday ? scoreStatus(gameToday) : 'NFL TODAY'}</b>
            {scores.loading ? <small>Loading official scoreboard…</small> : gameToday ? (
              <span className="lp-hq-tv-matchup">
                <span>{gameToday.awayTeam.teamId || gameToday.awayTeam.name} <strong>{gameToday.awayTeam.score ?? '—'}</strong></span>
                <span>{gameToday.homeTeam.teamId || gameToday.homeTeam.name} <strong>{gameToday.homeTeam.score ?? '—'}</strong></span>
              </span>
            ) : nextGame ? <>
              <small>{scores.unavailable ? 'Score feed unavailable · next up' : 'No game today · next up'}</small>
              <span className="lp-hq-tv-next">{matchup(nextGame.home, nextGame.away)} · {formatDate(nextGame.kickoff_utc, true) || 'time pending'}</span>
            </> : <small>{scores.unavailable ? 'Score feed unavailable' : 'No NFL games scheduled today'}</small>}
          </span>
          <span className="lp-hq-object-label">TV · GAME CENTER</span>
        </button>

        <button type="button" className="lp-hq-hotspot lp-hq-board" aria-label="Open NFL forecasts from the scouting board"
          aria-controls="nfl-hq-preview" aria-expanded={preview === 'forecast'} onClick={event => openPreview('forecast', event)}>
          <span className="lp-hq-board-data">
            <b>SCOUTING BOARD</b>
            {model.loading ? <small>Loading forecast…</small> : nextGame ? (
              <><span>{matchup(nextGame.home, nextGame.away)}</span>
                <small>{nextLock?.proj_home != null && nextLock.proj_away != null
                  ? `${Math.round(nextLock.proj_away)} — ${Math.round(nextLock.proj_home)} projected`
                  : 'Forecast not published'}</small></>
            ) : <small>{model.unavailable ? 'Forecast feed unavailable' : 'No upcoming matchup found'}</small>}
          </span>
          <span className="lp-hq-object-label">SCOUTING · FORECASTS</span>
        </button>

        <button type="button" className="lp-hq-hotspot lp-hq-cards" aria-label="Open NFL player projections from the player card wall"
          aria-controls="nfl-hq-preview" aria-expanded={preview === 'players'} onClick={event => openPreview('players', event)}>
          <span className="lp-hq-card-data">
            {projectionRows.slice(0, 4).map(player => (
              <span className="lp-hq-player-card" key={player.player_id}>
                <b>{player.name.split(' ').slice(-1)[0]}</b>
                <small>{player.team} · {player.position}</small>
                <strong>{player.v2.rec_yds.mean.toFixed(1)} yd</strong>
              </span>
            ))}
            {projections.loading && <small className="lp-hq-card-empty">Loading player projections…</small>}
            {!projections.loading && !projectionRows.length && <small className="lp-hq-card-empty">{projections.unavailable ? 'Projection feed unavailable' : 'No player projections published'}</small>}
          </span>
          <span className="lp-hq-object-label">PLAYER CARDS · PROJECTIONS</span>
        </button>

        <button type="button" className="lp-hq-hotspot lp-hq-trophy" aria-label="Open trophy shelf career status"
          aria-controls="nfl-hq-preview" aria-expanded={preview === 'career'} onClick={event => openPreview('career', event)}>
          <span className="lp-hq-object-label">CAREER · FUTURE FEATURE</span>
        </button>

        <span className="lp-hq-athlete" role="img" aria-label="Fictional general manager in street clothes" />

        <button type="button" className="lp-hq-hotspot lp-hq-computer" aria-label="Open NFL player props from the desk computer"
          aria-controls="nfl-hq-preview" aria-expanded={preview === 'props'} onClick={event => openPreview('props', event)}>
          <span className="lp-hq-computer-data">
            <b>PROP BOARD</b>
            {propsBoard.loading ? <small>Loading sourced lines…</small> : propSample ? (
              <><span>{propSample.player.name} · {propSample.prop.market.replaceAll('_', ' ')}</span>
                <strong>{propSample.prop.side.toUpperCase()} {propSample.prop.line}</strong>
                <small>{propSample.prop.source} · {formatDate(propSample.prop.captured_at, true) || 'time unavailable'}</small></>
            ) : <small>{propsBoard.unavailable ? 'Prop feed unavailable' : 'No upcoming prop lines'}</small>}
          </span>
          <span className="lp-hq-object-label">COMPUTER · PLAYER PROPS</span>
        </button>

        <button type="button" className="lp-hq-hotspot lp-hq-arcade" aria-label="Open arcade console future feature status"
          aria-controls="nfl-hq-preview" aria-expanded={preview === 'arcade'} onClick={event => openPreview('arcade', event)}>
          <span className="lp-hq-arcade-art" aria-hidden="true"><i /><b>LP</b><span>ARCADE</span></span>
          <span className="lp-hq-object-label">ARCADE · FUTURE DESTINATION</span>
        </button>

        <section className="lp-hq-panel" id="nfl-hq-preview" role="region" aria-labelledby="nfl-hq-preview-title" hidden={!preview}>
          {preview && <>
            <header className="lp-hq-panel-header">
              <div><small>IN-ROOM PREVIEW</small><h2 id="nfl-hq-preview-title">{previewTitle}</h2></div>
              <button ref={closeButton} type="button" onClick={closePreview}>Return to HQ</button>
            </header>

            {preview === 'scores' && <div className="lp-hq-preview-content">
              {scores.loading ? <p role="status">Loading today’s NFL scoreboard…</p>
                : scores.unavailable ? <p>Today’s NFL score feed is unavailable. No score is being estimated.</p>
                  : scores.games.length ? <ul className="lp-hq-data-list">{scores.games.map(game => (
                    <li key={game.gameId}>
                      <div><b>{matchup(game.homeTeam.name, game.awayTeam.name)}</b><small>{scoreStatus(game)}</small></div>
                      <strong>{game.awayTeam.score ?? '—'} – {game.homeTeam.score ?? '—'}</strong>
                    </li>
                  ))}</ul> : <p>No NFL games are scheduled today.{nextGame ? ` Next: ${matchup(nextGame.home, nextGame.away)} · ${formatDate(nextGame.kickoff_utc, true) || 'kickoff time pending'}.` : ' No upcoming matchup is published.'}</p>}
              {scores.source && <p className="lp-hq-data-source">Source: {scores.source}{scores.age !== null ? ` · captured ${Math.max(1, Math.round(scores.age / 60))} min ago` : ''}</p>}
              <Link className="lp-hq-full-link" href="/scores?league=nfl">Open full NFL scores →</Link>
            </div>}

            {preview === 'forecast' && <div className="lp-hq-preview-content">
              {model.loading ? <p role="status">Loading published NFL forecasts…</p>
                : model.unavailable ? <p>The forecast feed is unavailable right now.</p>
                  : nextGame ? <>
                    <p className="lp-hq-preview-matchup">{matchup(nextGame.home, nextGame.away)}</p>
                    <p>{formatDate(nextGame.kickoff_utc, true) || 'Kickoff time unavailable'} · Week {nextGame.week}</p>
                    {nextLock ? <div className="lp-hq-forecast-grid">
                      <span><small>{nextGame.away}</small><b>{nextLock.proj_away == null ? '—' : nextLock.proj_away.toFixed(1)}</b></span>
                      <span><small>{nextGame.home}</small><b>{nextLock.proj_home == null ? '—' : nextLock.proj_home.toFixed(1)}</b></span>
                      <span><small>{adoptedModel?.label || 'Model'} home win</small><b>{nextLock.p_home_win == null ? '—' : `${Math.round(nextLock.p_home_win * 100)}%`}</b></span>
                    </div> : <p>No forecast is published for this matchup yet.</p>}
                    {nextLock && <p className="lp-hq-data-source">{adoptedModel?.label || 'NFL model'}{formatDate(nextLock.locked_at || nextLock.previewed_at, true) ? ` · ${nextLock.locked_at ? 'locked' : 'preview published'} ${formatDate(nextLock.locked_at || nextLock.previewed_at, true)}` : ''}{nextLock.line.captured_at ? ` · line ${formatDate(nextLock.line.captured_at, true)}` : ''}</p>}
                  </> : <p>No upcoming NFL matchup is available in the published forecast feed.</p>}
              <Link className="lp-hq-full-link" href="/leagues/nfl?tab=model">Open full NFL forecasts →</Link>
            </div>}

            {preview === 'props' && <div className="lp-hq-preview-content">
              {propsBoard.loading ? <p role="status">Loading real player lines…</p>
                : propsBoard.unavailable ? <p>The player prop feed is unavailable. No lines are being filled in.</p>
                  : propSample ? <>
                    <p className="lp-hq-preview-matchup">{propSample.player.name} <small>{propSample.player.team}</small></p>
                    <p>{propSample.prop.market.replaceAll('_', ' ')} · {propSample.prop.side.toUpperCase()} {propSample.prop.line}</p>
                    <p className="lp-hq-data-source">{propSample.prop.source}{formatDate(propSample.prop.captured_at, true) ? ` · source time ${formatDate(propSample.prop.captured_at, true)}` : ' · source time unavailable'}</p>
                    <h3>Recent game history</h3>
                    {history.loading ? <p role="status">Loading game log…</p>
                      : history.unavailable ? <p>Player history is unavailable right now.</p>
                        : history.data?.games?.length ? <ul className="lp-hq-history-list">{history.data.games.slice(0, 6).map((game, index) => (
                          <li key={`${game.date}-${index}`}><span>{formatDate(`${game.date}T12:00:00`) || game.date} · {game.opponent || 'Opponent unavailable'}</span><b>{game.value ?? '—'}</b></li>
                        ))}</ul> : <p>No published game history is available for this line.</p>}
                  </> : <p>No upcoming NFL player lines are available from the prop feed.</p>}
              <Link className="lp-hq-full-link" href="/props?league=nfl">Open full NFL prop board →</Link>
            </div>}

            {preview === 'players' && <div className="lp-hq-preview-content">
              {projections.loading ? <p role="status">Loading published player projections…</p>
                : projections.unavailable ? <p>The projection feed is unavailable right now.</p>
                  : projectionRows.length ? <ul className="lp-hq-data-list">{projectionRows.slice(0, 8).map(player => (
                    <li key={player.player_id}>
                      <div><b>{player.name} <small>{player.team} · {player.position}</small></b><small>Week {projections.data?.week ?? '—'} · conditional on playing</small></div>
                      <strong>{player.v2.rec_yds.mean.toFixed(1)} rec yds</strong>
                    </li>
                  ))}</ul> : <p>No NFL player projections have been published for the current slate.</p>}
              <Link className="lp-hq-full-link" href="/nfl/projections">Open full NFL projections →</Link>
            </div>}

            {preview === 'career' && <div className="lp-hq-preview-content"><p>Career tracking is not available yet. No records, progression, or rewards are being generated here.</p></div>}
            {preview === 'arcade' && <div className="lp-hq-preview-content"><p>The arcade is a future destination. No mini-game or rewards are available yet.</p></div>}
          </>}
        </section>

        <p className="lp-hq-scene-label" aria-hidden="true">NFL · RESEARCH HQ</p>
      </div>
      <p className="lp-hq-audio-note">Room audio is off. No sound plays automatically.</p>
    </section>
  )
}
