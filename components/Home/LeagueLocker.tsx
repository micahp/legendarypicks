import Link from 'next/link'
import { useState } from 'react'
import SportIcon from '../SportIcon'

const LEAGUES = [
  { id: 'nfl', label: 'NFL', detail: 'Football', href: '/leagues/nfl?tab=camp', color: 'football' },
  { id: 'nba', label: 'NBA', detail: 'Basketball', href: '/leagues/nba', color: 'basketball' },
  { id: 'nhl', label: 'NHL', detail: 'Hockey', href: '/leagues/nhl', color: 'hockey' },
  { id: 'mlb', label: 'MLB', detail: 'Baseball', href: '/leagues/mlb', color: 'baseball' },
  { id: 'tennis', label: 'Tennis', detail: 'Tour', href: '/leagues/tennis', color: 'tennis' },
  { id: 'ufc', label: 'UFC', detail: 'MMA', href: '/leagues/ufc', color: 'mma' },
] as const

function PixelAthlete() {
  return (
    <svg viewBox="0 0 160 220" role="img" aria-label="Original pixel art athlete avatar" className="lp-locker-avatar">
      <rect x="62" y="16" width="38" height="34" fill="#26232a" />
      <rect x="56" y="24" width="12" height="10" fill="#26232a" />
      <rect x="92" y="22" width="12" height="9" fill="#26232a" />
      <rect x="66" y="34" width="34" height="34" fill="#b87853" />
      <rect x="66" y="44" width="8" height="8" fill="#312522" />
      <rect x="92" y="44" width="8" height="8" fill="#312522" />
      <rect x="76" y="58" width="18" height="6" fill="#7c4136" />
      <rect x="70" y="68" width="28" height="12" fill="#b87853" />
      <rect x="48" y="78" width="70" height="66" fill="#282a31" />
      <rect x="38" y="84" width="22" height="54" fill="#b87853" />
      <rect x="108" y="84" width="20" height="54" fill="#b87853" />
      <rect x="42" y="130" width="16" height="22" fill="#b87853" />
      <rect x="110" y="130" width="16" height="22" fill="#b87853" />
      <rect x="64" y="92" width="38" height="8" fill="#a6ed4b" />
      <rect x="72" y="106" width="22" height="7" fill="#a6ed4b" />
      <rect x="54" y="144" width="58" height="22" fill="#17171c" />
      <rect x="58" y="166" width="22" height="34" fill="#b87853" />
      <rect x="88" y="166" width="22" height="34" fill="#b87853" />
      <rect x="54" y="196" width="32" height="10" fill="#24252b" />
      <rect x="84" y="196" width="34" height="10" fill="#24252b" />
      <rect x="52" y="206" width="38" height="8" fill="#17171c" />
      <rect x="82" y="206" width="40" height="8" fill="#17171c" />
    </svg>
  )
}

export default function LeagueLocker() {
  const [selected, setSelected] = useState<(typeof LEAGUES)[number] | null>(null)

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
        <h1 id="locker-title">Build your edge.</h1>
        <p>Choose a league to open its scores, forecasts, props, and research.</p>
      </div>

      <div className="lp-locker-stage">
        <div className="lp-locker-orbit lp-locker-orbit-one" aria-hidden="true" />
        <div className="lp-locker-orbit lp-locker-orbit-two" aria-hidden="true" />
        <div className="lp-locker-avatar-wrap"><PixelAthlete /></div>
        {LEAGUES.map((league, index) => (
          <button
            key={league.id}
            type="button"
            className={`lp-locker-gear lp-locker-gear-${index + 1}${selected?.id === league.id ? ' is-selected' : ''}`}
            aria-pressed={selected?.id === league.id}
            onClick={() => setSelected(league)}
          >
            <span className="lp-locker-gear-icon"><SportIcon league={league.color} className="h-7 w-7" /></span>
            <span className="lp-locker-gear-label">{league.label}</span>
          </button>
        ))}
      </div>

      <div className="lp-locker-footer">
        <p className="lp-locker-prompt" aria-live="polite">
          {selected ? `${selected.label} selected · ${selected.detail}` : 'Tap a league to build your edge'}
        </p>
        {selected ? (
          <Link className="lp-locker-cta" href={selected.href}>
            Enter {selected.label} HQ <span aria-hidden="true">↗</span>
          </Link>
        ) : (
          <span className="lp-locker-cta is-disabled" aria-disabled="true">Choose a league to continue</span>
        )}
      </div>
      {selected?.id === 'nfl' && (
        <nav className="lp-locker-shortcuts" aria-label="NFL quick links">
          <Link href="/props?league=nfl">Props</Link>
          <Link href="/leagues/nfl?tab=model">Forecasts</Link>
          <Link href="/nfl/projections">Projections</Link>
          <Link href="/props?league=nfl&tab=matchups">Matchups</Link>
          <Link href="/leagues/nfl?tab=stats">Stats</Link>
        </nav>
      )}
    </section>
  )
}
