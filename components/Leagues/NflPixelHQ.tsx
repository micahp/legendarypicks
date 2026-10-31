import Link from 'next/link'
import SportIcon from '../SportIcon'
import type { NflSeasonContext } from './types'

type Props = {
  data: NflSeasonContext | null
  loading: boolean
  error: string | null
}

function FootballField() {
  return (
    <svg viewBox="0 0 320 120" className="lp-hq-field" role="img" aria-label="Decorative pixel football field">
      <rect width="320" height="120" fill="#28633c" />
      <path d="M12 0v120M52 0v120M92 0v120M132 0v120M172 0v120M212 0v120M252 0v120M292 0v120" stroke="#a7d48b" strokeWidth="2" opacity=".8" />
      <path d="M0 10h320M0 110h320" stroke="#e4ebcf" strokeWidth="3" />
      <circle cx="160" cy="60" r="20" fill="none" stroke="#e4ebcf" strokeWidth="2" opacity=".75" />
      <path d="M156 57h8v6h-8z" fill="#f3c875" />
    </svg>
  )
}

export default function NflPixelHQ({ data, loading, error }: Props) {
  const nextEvent = data?.next_event
  const eventDate = nextEvent?.date
    ? new Date(`${nextEvent.date}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    : null
  const seasonSource = data?.sources?.[0]
  const sourceVerified = seasonSource?.verified_at
    ? new Date(seasonSource.verified_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
    : null

  return (
    <div className="space-y-4">
      <section className="lp-hq" aria-labelledby="nfl-hq-title">
        <div className="lp-hq-copy">
          <p className="lp-hq-kicker">LEGENDARY PICKS / NFL HQ</p>
          <h2 id="nfl-hq-title">The War Room</h2>
          <p className="lp-hq-description">Your home base for the NFL slate, player props, forecasts, and player projections.</p>
          <div className="lp-hq-calendar" aria-live="polite">
            {loading ? (
              <span>Loading season context…</span>
            ) : error || !data ? (
              <span>Season context is unavailable right now.</span>
            ) : (
              <>
                <span className="lp-hq-phase">{data.phase_label}</span>
                {nextEvent && <span>{nextEvent.label}{eventDate ? ` · ${eventDate}` : ''}</span>}
                {seasonSource && <span className="lp-hq-source">{seasonSource.name}{sourceVerified ? ` · verified ${sourceVerified}` : ''}</span>}
              </>
            )}
          </div>
          <Link href="/leagues/nfl?tab=schedule" className="lp-hq-cta">Open NFL slate <span aria-hidden="true">→</span></Link>
        </div>

        <div className="lp-hq-room" role="img" aria-label="Pixel art football analysis room">
          <div className="lp-hq-window"><div className="lp-hq-skyline" /></div>
          <div className="lp-hq-wall-shelf"><span /><span /><span /></div>
          <div className="lp-hq-monitor"><FootballField /><div className="lp-hq-monitor-base" /></div>
          <div className="lp-hq-desk" />
          <div className="lp-hq-lamp"><i /><b /></div>
          <div className="lp-hq-plant"><i /><b /><span /></div>
          <div className="lp-hq-chair"><i /><b /><span /></div>
          <div className="lp-hq-floor-mark" aria-hidden="true">LP</div>
          <div className="lp-hq-room-label"><SportIcon league="nfl" className="h-4 w-4" /> NFL analysis room</div>
        </div>
      </section>

      <section className="lp-hq-rooms" aria-labelledby="nfl-rooms-title">
        <div className="lp-hq-rooms-heading">
          <p className="lp-hq-kicker">PICK A ROOM</p>
          <h3 id="nfl-rooms-title">Explore the NFL lab</h3>
        </div>
        <div className="lp-hq-room-links">
          <Link href="/leagues/nfl?tab=model" className="lp-hq-room-link">
            <span className="lp-hq-room-icon">↗</span>
            <span><b>Game forecasts</b><small>Model picks and outcomes</small></span>
            <span className="lp-hq-arrow">→</span>
          </Link>
          <Link href="/props?league=nfl" className="lp-hq-room-link">
            <span className="lp-hq-room-icon">▥</span>
            <span><b>Player props</b><small>Lines, trends, and hit history</small></span>
            <span className="lp-hq-arrow">→</span>
          </Link>
          <Link href="/nfl/projections" className="lp-hq-room-link">
            <span className="lp-hq-room-icon">⌁</span>
            <span><b>Player projections</b><small>Simulation ranges and availability</small></span>
            <span className="lp-hq-arrow">→</span>
          </Link>
          <Link href="/props?league=nfl&tab=matchups" className="lp-hq-room-link">
            <span className="lp-hq-room-icon">▦</span>
            <span><b>Matchup splits</b><small>Player results by opponent</small></span>
            <span className="lp-hq-arrow">→</span>
          </Link>
          <Link href="/leagues/nfl?tab=stats" className="lp-hq-room-link">
            <span className="lp-hq-room-icon">▤</span>
            <span><b>Player &amp; team stats</b><small>Season leaders and team totals</small></span>
            <span className="lp-hq-arrow">→</span>
          </Link>
        </div>
      </section>
    </div>
  )
}
