import Head from 'next/head'
import { useRouter } from 'next/router'
import { useEffect } from 'react'
import FieldGoalArcade from '../../../../components/Arcade/FieldGoalArcade'

export default function NflFieldGoalChallengePage() {
  const router = useRouter()
  const challengeId = typeof router.query.challengeId === 'string' ? router.query.challengeId : null
  const shareId = typeof router.query.share === 'string' ? router.query.share : null
  useEffect(() => {
    document.body.classList.add('lp-arcade-fullscreen')
    document.documentElement.classList.add('lp-arcade-fullscreen')
    return () => {
      document.body.classList.remove('lp-arcade-fullscreen')
      document.documentElement.classList.remove('lp-arcade-fullscreen')
    }
  }, [])
  return (
    <>
      <Head>
        <title>Field Goal Frenzy · LP Arcade</title>
        <meta name="description" content="Play a free, fictional field-goal practice challenge in LP Arcade." />
      </Head>
      <div className="lp-arcade-page lp-arcade-game-page">
        <header className="lp-arcade-page-heading">
          <a href="/arcade/nfl">← LP Arcade</a>
          <p className="lp-arcade-kicker">FIELD GOAL FRENZY</p>
          <h1>Take the kick</h1>
        </header>
        {router.isReady && challengeId && <FieldGoalArcade challengeId={challengeId} shareId={shareId} />}
      </div>
    </>
  )
}
