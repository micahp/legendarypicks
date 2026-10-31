import Link from 'next/link'
import { useRef, useState } from 'react'
import type { NflSeasonContext } from './types'

type Props = {
  data: NflSeasonContext | null
  loading: boolean
  error: string | null
}

type RoomPanel = 'career' | 'arcade' | null

function SeasonContext({ data, loading, error }: Props) {
  const nextEvent = data?.next_event
  const eventDate = nextEvent?.date
    ? new Date(`${nextEvent.date}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    : null
  const source = data?.sources?.[0]
  const verified = source?.verified_at
    ? new Date(source.verified_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
    : null

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

export default function NflPixelHQ(props: Props) {
  const [panel, setPanel] = useState<RoomPanel>(null)
  const lastHotspot = useRef<HTMLButtonElement | null>(null)
  const panelCopy = panel === 'career'
    ? {
      title: 'Career receipts',
      body: 'Career tracking is not available yet. No records or rewards are being generated here.',
    }
    : {
      title: 'Arcade console',
      body: 'Mini-games are not available yet. This console has no game or rewards attached.',
    }

  function closePanel() {
    setPanel(null)
    requestAnimationFrame(() => lastHotspot.current?.focus())
  }

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
        <div className="lp-hq-window" aria-hidden="true"><span /><i /><b /></div>
        <div className="lp-hq-wall-lights" aria-hidden="true" />

        <Link className="lp-hq-hotspot lp-hq-hotspot-tv" href="/scores?league=nfl" aria-label="Open NFL scores from the television">
          <span className="lp-hq-tv-screen"><b>GAME CENTER</b><span>Scores &amp; play-by-play</span></span>
          <span className="lp-hq-hotspot-label">TV · SCORES</span>
        </Link>

        <Link className="lp-hq-hotspot lp-hq-hotspot-board" href="/leagues/nfl?tab=model" aria-label="Open NFL forecasts from the scouting board">
          <span className="lp-hq-board-paper">
            <b>SCOUTING BOARD</b>
            <span className="lp-hq-board-lines" aria-hidden="true"><i /><i /><i /></span>
            <small>Open forecasts →</small>
          </span>
          <span className="lp-hq-hotspot-label">SCOUTING · FORECASTS</span>
        </Link>

        <Link className="lp-hq-hotspot lp-hq-hotspot-cards" href="/nfl/projections" aria-label="Open NFL player projections from the player card wall">
          <span className="lp-hq-card-wall" aria-hidden="true"><i /><i /><i /><i /></span>
          <span className="lp-hq-hotspot-label">PLAYER CARDS · PROJECTIONS</span>
        </Link>

        <button
          ref={lastHotspot}
          type="button"
          className="lp-hq-hotspot lp-hq-hotspot-trophy"
          aria-controls="nfl-hq-info-panel"
          aria-expanded={panel === 'career'}
          onClick={() => setPanel('career')}
        >
          <span className="lp-hq-trophy-shelf" aria-hidden="true"><i /><i /><i /></span>
          <span className="lp-hq-hotspot-label">TROPHY SHELF · CAREER</span>
        </button>

        <span className="lp-hq-athlete" role="img" aria-label="Fictional NFL analyst wearing an unbranded football helmet" />
        <div className="lp-hq-rug" aria-hidden="true" />
        <div className="lp-hq-desk" aria-hidden="true"><span /><i /></div>
        <Link className="lp-hq-hotspot lp-hq-hotspot-computer" href="/props?league=nfl" aria-label="Open NFL player props from the desk computer">
          <span className="lp-hq-computer-screen"><b>PLAYER PROPS</b><small>Research board</small></span>
          <span className="lp-hq-hotspot-label">COMPUTER · PLAYER PROPS</span>
        </Link>
        <button
          type="button"
          className="lp-hq-hotspot lp-hq-hotspot-console"
          aria-controls="nfl-hq-info-panel"
          aria-expanded={panel === 'arcade'}
          onClick={event => { lastHotspot.current = event.currentTarget; setPanel('arcade') }}
        >
          <span className="lp-hq-console-screen" aria-hidden="true"><b>LP</b><i>ARCADE</i></span>
          <span className="lp-hq-hotspot-label">CONSOLE · MINI-GAMES</span>
        </button>

        <aside className="lp-hq-panel" id="nfl-hq-info-panel" aria-live="polite" aria-atomic="true" hidden={!panel}>
          {panel && (
            <>
              <div><b>{panelCopy.title}</b><p>{panelCopy.body}</p></div>
              <button type="button" onClick={closePanel} aria-label="Close information panel">Close</button>
            </>
          )}
        </aside>

        <p className="lp-hq-scene-label" aria-hidden="true">NFL · RESEARCH HQ</p>
      </div>
      <p className="lp-hq-audio-note">Room audio is off. No sound plays automatically.</p>
    </section>
  )
}
