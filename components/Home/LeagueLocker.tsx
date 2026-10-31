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
  const isNflEquipped = selected?.id === 'nfl'

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
        <p>Select a league to gear up, enter its HQ, or go straight to research.</p>
      </div>

      <div className={`lp-locker-stage${isNflEquipped ? ' is-nfl-equipped' : ''}`}>
        <div
          className="lp-locker-avatar-wrap"
          role="img"
          aria-label={`Original fictional athlete ${isNflEquipped ? 'wearing a fictional football helmet' : 'without a helmet'}`}
        >
          <span className="lp-locker-avatar lp-locker-avatar-unhelmeted" aria-hidden="true" />
          <span className="lp-locker-avatar lp-locker-avatar-helmeted" aria-hidden="true" />
          {isNflEquipped && <span className="lp-locker-equip-flash" aria-hidden="true" />}
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
            ? `${selected.label} selected${isNflEquipped ? ' · fictional helmet equipped' : ` · ${selected.detail}`}`
            : 'Choose a league, or start with NFL'}
        </p>
        <div className="lp-locker-actions">
          <Link className="lp-locker-cta lp-locker-cta-primary" href={featured.href}>
            Enter {featured.label} HQ <span aria-hidden="true">↗</span>
          </Link>
          <Link className="lp-locker-cta lp-locker-cta-research" href={featured.research}>
            Research {featured.label} <span aria-hidden="true">→</span>
          </Link>
        </div>
      </div>
    </section>
  )
}
