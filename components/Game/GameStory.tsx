import { useState, useEffect } from 'react'

export default function GameStory({ league, gameId }: { league: string; gameId: string }) {
  const [story, setStory] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    fetch(`/api/game/${league}/${gameId}/story`)
      .then(r => r.json()).then(d => setStory(d.story || null)).catch(() => {})
      .finally(() => setLoading(false))
  }, [league, gameId])

  // Loading: a subdued shimmer bar that mirrors the story's own border-left accent —
  // not a generic spinner. The emerald line is already the story's signature, so we
  // keep it during loading to signal "content coming here."
  if (loading) return (
    <div className="border-l-2 border-emerald-600/40 pl-3 space-y-2 animate-pulse">
      <div className="h-3 bg-zinc-800 rounded w-full" />
      <div className="h-3 bg-zinc-800 rounded w-3/4" />
    </div>
  )

  if (!story) return null
  return (
    <p className="text-sm text-zinc-300 leading-relaxed border-l-2 border-emerald-600/60 pl-3">{story}</p>
  )
}
