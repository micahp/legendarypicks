import Head from 'next/head'
import { useRouter } from 'next/router'
import PixelRedZonePlayer from '../../components/Leagues/PixelRedZonePlayer'

export default function PixelRedZonePage() {
  const router = useRouter()

  function backToRoom() {
    if (typeof window !== 'undefined' && window.history.length > 1) {
      router.back()
    } else {
      void router.push('/leagues/nfl?tab=camp')
    }
  }

  return (
    <>
      <Head>
        <title>Pixel Red Zone Replay | Legendary Picks</title>
        <meta name="description" content="A sourced, captioned pixel football replay built from archived ESPN play-by-play." />
      </Head>
      <div className="lp-rz-page">
        <PixelRedZonePlayer onBack={backToRoom} />
      </div>
    </>
  )
}
