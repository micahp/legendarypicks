import { useEffect, useRef, useState } from 'react'

// One live game at a time: starting a stream pauses whichever card was playing.
let current: HTMLAudioElement | null = null

type State = 'idle' | 'loading' | 'playing' | 'error'

/**
 * Play button for a game's live radio, the same idea as the World Cup / MLS
 * ListenLive player: the browser plays the publisher's own stream directly and
 * nothing is relayed through LP. preload="none", so nothing loads until tapped.
 * A stream that fails says so instead of sitting silent.
 */
export default function GameRadioButton({ src, team, station, live = true, blackout = false }: {
  src: string; team: string; station: string; live?: boolean; blackout?: boolean
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [state, setState] = useState<State>('idle')

  useEffect(() => () => {
    const a = audioRef.current
    if (a) {
      a.pause()
      if (current === a) current = null
    }
  }, [])

  const toggle = (event: React.MouseEvent) => {
    event.stopPropagation()
    const a = audioRef.current
    if (!a) return
    if (state === 'playing' || state === 'loading') {
      a.pause()
      a.removeAttribute('src')
      a.load()
      setState('idle')
      return
    }
    if (current && current !== a) current.pause()
    current = a
    a.src = src
    setState('loading')
    a.play().catch(() => setState('error'))
  }

  const label = state === 'playing' || state === 'loading' ? 'Stop live radio' : 'Play live radio'

  // Before the game: no button, just the station, so people know they can listen once it starts.
  if (!live) return <span className="text-xs text-zinc-500">{station}</span>

  return (
    <div className="flex flex-row-reverse items-center gap-2">
      <button
        type="button"
        onClick={toggle}
        aria-label={`${label} (${team})`}
        aria-pressed={state === 'playing'}
        className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-zinc-700 bg-zinc-950/40 text-zinc-200 transition-colors hover:border-emerald-500/50 hover:text-emerald-400"
      >
        {state === 'playing' || state === 'loading' ? (
          <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4" aria-hidden="true">
            <path d="M6 5h4v14H6zM14 5h4v14h-4z" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4" aria-hidden="true">
            <path d="M8 5v14l11-7z" />
          </svg>
        )}
      </button>
      {/* One status slot beside the button: the station, or what is wrong with it right now. */}
      <span className={'text-xs ' + (state === 'playing' && !blackout ? 'text-emerald-400' : 'text-zinc-500')}>
        {state === 'error' ? 'Radio unavailable in this browser'
          : blackout ? 'Blackout'
          : state === 'loading' ? 'Connecting…'
          : station}
      </span>
      <audio
        ref={audioRef}
        preload="none"
        onPlaying={() => setState('playing')}
        onPause={() => setState((s) => (s === 'error' ? s : 'idle'))}
        onError={() => setState((s) => (s === 'idle' ? s : 'error'))}
      />
    </div>
  )
}
