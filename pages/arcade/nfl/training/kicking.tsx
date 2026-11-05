import Head from 'next/head'
import Link from 'next/link'
import { useRouter } from 'next/router'
import FieldGoalArcade from '../../../../components/Arcade/FieldGoalArcade'

export default function NflKickingTrainingPage() {
  const router = useRouter()
  const drillId = typeof router.query.drill === 'string' ? router.query.drill : 'aim-lab-v1'
  return (
    <>
      <Head>
        <title>Kicking Camp · LP Arcade</title>
        <meta name="description" content="Practice NFL-style field-goal aim and timing with original fictional arcade drills." />
      </Head>
      <div className="lp-arcade-page">
        <header className="lp-arcade-page-heading">
          <Link href="/arcade/nfl">← LP Arcade</Link>
          <p className="lp-arcade-kicker">FIELD GOAL ACADEMY</p>
          <h1>Kicking Camp</h1>
        </header>
        {router.isReady && <FieldGoalArcade drillId={drillId} />}
      </div>
    </>
  )
}
