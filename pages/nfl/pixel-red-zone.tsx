import Head from 'next/head'
import { useRouter } from 'next/router'
import PixelRedZonePlayer from '../../components/Leagues/PixelRedZonePlayer'
import { useNflScoreboard } from '../../components/Leagues/hooks/useNflScoreboard'

export default function PixelRedZonePage() {
  const router = useRouter()
  const liveMode = router.isReady && router.query.mode === 'live'
  const scoreboard = useNflScoreboard(liveMode)
  const gameId = typeof router.query.game === 'string' ? router.query.game : null
  const playId = typeof router.query.play === 'string' ? router.query.play : null
  const fromRoom = router.query.from === 'room'

  function backToRoom() {
    if (fromRoom && typeof window !== 'undefined' && window.history.length > 1) {
      router.back()
    } else {
      void router.push('/leagues/nfl?tab=camp')
    }
  }

  return (
    <>
      <Head>
        <title>{liveMode ? 'Pixel Red Zone | Legendary Picks' : 'Pixel Red Zone Replay | Legendary Picks'}</title>
        <meta name="description" content={liveMode
          ? 'A scoreboard-backed pixel football channel with ESPN play-by-play and a separate replay archive.'
          : 'A sourced, captioned pixel football replay built from archived ESPN play-by-play.'} />
      </Head>
      <div className="lp-rz-page">
        {router.isReady && <PixelRedZonePlayer
          viewMode={liveMode ? 'live' : 'replay'}
          initialPinnedGameId={gameId}
          initialPlayId={playId}
          scoreboard={liveMode ? scoreboard : undefined}
          onBack={backToRoom}
        />}
      </div>
    </>
  )
}
