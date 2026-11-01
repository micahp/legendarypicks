import Head from 'next/head'
import Link from 'next/link'
import { useEffect } from 'react'
import ArchivedKickMoments from '../../../components/Arcade/ArchivedKickMoments'
import { trackArcadeVisit } from '../../../lib/analytics'

export default function NflArcadeLobby() {
  useEffect(() => { trackArcadeVisit('lobby') }, [])

  return (
    <>
      <Head>
        <title>LP Arcade · NFL | Legendary Picks</title>
        <meta name="description" content="Free, fictional NFL field-goal arcade practice and training drills." />
      </Head>
      <div className="lp-arcade-page">
        <header className="lp-arcade-page-heading">
          <Link href="/leagues/nfl?tab=camp">← NFL HQ</Link>
          <p className="lp-arcade-kicker">LEGENDARY PICKS · NFL</p>
          <h1>LP Arcade</h1>
          <p>Quick kicks. Clear feedback. Practice is free and separate from real NFL results.</p>
        </header>

        <section className="lp-arcade-lobby-group" aria-labelledby="lp-arcade-moments-title">
          <h2 id="lp-arcade-moments-title">Live Moments</h2>
          <p>Verified field-goal moments from in-progress games appear below when ESPN publishes an explicit attempt distance.</p>
        </section>

        <ArchivedKickMoments />

        <section className="lp-arcade-lobby-group" aria-labelledby="lp-arcade-training-title">
          <h2 id="lp-arcade-training-title">Training Camp</h2>
          <p>Build aim and release control with fixed, fictional scenarios. Every kick gets its own server-calculated result.</p>
          <div className="lp-arcade-lobby-actions">
            <Link className="lp-arcade-lobby-primary" href="/arcade/nfl/training/kicking?drill=aim-lab-v1">Play Aim Lab</Link>
            <Link className="lp-arcade-lobby-secondary" href="/arcade/nfl/training/kicking?drill=precision-set-v1">Play Precision Set</Link>
            <Link className="lp-arcade-lobby-secondary" href="/arcade/nfl/field-goal/practice-fg-35-v1">Quick 35-yard kick</Link>
          </div>
        </section>

        <section className="lp-arcade-lobby-group" aria-labelledby="lp-arcade-friends-title">
          <h2 id="lp-arcade-friends-title">Friends’ Challenges</h2>
          <p>After a kick, share its exact challenge and verified Arcade score. Friends can play without visiting HQ or signing in; anonymous best scores appear on the challenge board.</p>
          <Link className="lp-arcade-lobby-secondary" href="/arcade/nfl/field-goal/practice-fg-35-v1">Open the 35-yard challenge</Link>
        </section>

        <p className="lp-arcade-status-note">Field Goal Frenzy uses original 2D arcade rules. It does not simulate or predict NFL play outcomes.</p>
      </div>
    </>
  )
}
