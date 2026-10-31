import Link from 'next/link'
import { useState } from 'react'
import SportIcon from '../SportIcon'

const LEAGUES = [
  { id: 'nfl', label: 'NFL', detail: 'Football', href: '/leagues/nfl?tab=camp', research: '/props?league=nfl', color: 'football' },
  { id: 'nba', label: 'NBA', detail: 'Basketball', href: '/leagues/nba', research: '/props?league=nba', color: 'basketball' },
  { id: 'nhl', label: 'NHL', detail: 'Hockey', href: '/leagues/nhl', research: '/props?league=nhl', color: 'hockey' },
  { id: 'mlb', label: 'MLB', detail: 'Baseball', href: '/leagues/mlb', research: '/props?league=mlb', color: 'baseball' },
  { id: 'tennis', label: 'Tennis', detail: 'Tour', href: '/leagues/tennis', research: '/props?league=tennis', color: 'tennis' },
  { id: 'ufc', label: 'UFC', detail: 'MMA', href: '/leagues/ufc', research: '/props?league=ufc', color: 'mma' },
] as const

export default function LeagueLocker() {
  const [selected, setSelected] = useState<(typeof LEAGUES)[number] | null>(null)
  const featured = selected ?? LEAGUES[0]
  const isNflSelected = selected?.id === 'nfl'

  return (
    <section className="lp-locker" aria-labelledby="locker-title">
      <div className="lp-locker-topline">
        <Link href="/" className="lp-locker-brand" aria-label="Legendary Picks home">
          <span className="lp-locker-mark">LP</span>
          <span>LEGENDARY<br />PICKS</span>
        </Link>
        <span className="lp-locker-mode">LEAGUE SELECT</span>
      </div>

      <div className="lp-locker-intro">
        <p className="lp-locker-kicker">YOUR NEXT MOVE STARTS HERE</p>
        <h1 id="locker-title">Choose your league.</h1>
        <p>Pick a league to set your focus, then open its game world or research.</p>
      </div>

      <div className={`lp-locker-stage${isNflSelected ? ' is-nfl-selected' : ''}`} data-league={selected?.id ?? 'none'}>
        <div
          className="lp-locker-avatar-wrap"
          role="img"
          aria-label="Original fictional general manager in street clothes"
        >
          <span className="lp-locker-avatar" aria-hidden="true" />
        </div>
        {LEAGUES.map((league, index) => (
          <button
            key={league.id}
            type="button"
            className={`lp-locker-gear lp-locker-gear-${index + 1}${selected?.id === league.id ? ' is-selected' : ''}`}
            aria-pressed={selected?.id === league.id}
            aria-label={`Select ${league.label}`}
            onClick={() => setSelected(league)}
          >
            <span className="lp-locker-gear-icon"><SportIcon league={league.color} className="h-7 w-7" /></span>
            <span className="lp-locker-gear-label">{league.label}</span>
          </button>
        ))}
      </div>

      <div className="lp-locker-footer">
        <p className="lp-locker-prompt" aria-live="polite">
          {selected
            ? `${selected.label} selected${isNflSelected ? ' · game focus set' : ` · ${selected.detail}`}`
            : 'Choose a league, or start with NFL'}
        </p>
        <div className="lp-locker-actions">
          <Link className="lp-locker-cta lp-locker-cta-primary" href={featured.href}>
            {isNflSelected || !selected ? 'Enter NFL HQ' : `Explore ${featured.label}`} <span aria-hidden="true">↗</span>
          </Link>
          <Link className="lp-locker-cta lp-locker-cta-research" href={featured.research}>
            Research {featured.label} <span aria-hidden="true">→</span>
          </Link>
        </div>
      </div>
    </section>
  )
}
