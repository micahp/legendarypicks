import { useState, useEffect } from 'react'

export default function GameStory({ league, gameId }: { league: string; gameId: string }) {
  const [story, setStory] = useState<string | null>(null)
  useEffect(() => {
    fetch(`/api/game/${league}/${gameId}/story`)
      .then(r => r.json()).then(d => setStory(d.story || null)).catch(() => {})
  }, [league, gameId])
  if (!story) return null
  return (
    <p className="text-sm text-zinc-300 leading-relaxed border-l-2 border-emerald-600/60 pl-3">{story}</p>
  )
}
