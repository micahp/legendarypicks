import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { DraftNotesResponse, NflDraftBoard, NflDraftNotes, NflDraftPlayer, NflDraftSort } from '../types'
import { getDeviceId } from '../../../lib/deviceId'
import { POSITION_ORDER } from '../../../lib/nfl/positionLabel'

/* The order was authored here and separately (badly) derived in the mock draft,
   where `.sort()` on the stored codes put D/ST and K ahead of the quarterback.
   It now comes from one constant so the two boards cannot drift: skill positions
   in the order they come off the board, FLEX where it sits in a lineup, then the
   two positions nobody drafts before round 13 — K then D/ST, last. */
const POSITIONS = ['all', ...POSITION_ORDER] as const
export type DraftPosition = typeof POSITIONS[number]

// Named for what the reader controls, not for how we compute it.
const SORT_LABELS: Record<NflDraftSort, string> = {
  adp: 'ADP',
  ppr_per_team_game: 'PPR / team game',
  ppr_per_game_played: 'PPR / game played',
  xfp_per_game: 'Expected PPR',
  games_played: 'Availability',
  snap_pct: 'Snap share',
  target_share: 'Target share',
  dst_pts_per_game: 'D/ST pts/g',
  pk_pts_per_game: 'K pts/g',
}

const STORAGE_KEY = 'lp_nfl_draft_notes'
const SEARCH_DEBOUNCE_MS = 250
const CURRENT_SEASON = 2026

function sanitizeNotes(raw: unknown): NflDraftNotes {
  const empty: NflDraftNotes = { rank: {}, watch: {}, fade: {} }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return empty

  const obj = raw as Record<string, unknown>
  const result: NflDraftNotes = { rank: {}, watch: {}, fade: {} }

  for (const bucket of ['rank', 'watch', 'fade'] as const) {
    const bucketVal = obj[bucket]
    if (!bucketVal || typeof bucketVal !== 'object' || Array.isArray(bucketVal)) continue
    const src = bucketVal as Record<string, unknown>
    for (const [key, val] of Object.entries(src)) {
      const pid = Number(key)
      if (!Number.isFinite(pid) || pid <= 0 || pid !== Math.floor(pid)) continue
      // Canonical positive decimal integer only — reject whitespace, 1e2, etc.
      if (!/^[1-9][0-9]*$/.test(key)) continue
      if (!Number.isSafeInteger(pid)) continue
      if (bucket === 'rank') {
        if (typeof val !== 'number' || val < 1 || val > 999 || val !== Math.floor(val)) continue
        result.rank[pid] = val
      } else {
        if (val !== true) continue
        result[bucket][pid] = true
      }
    }
  }
  return result
}

function loadNotes(): NflDraftNotes {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { rank: {}, watch: {}, fade: {} }
    return sanitizeNotes(JSON.parse(raw))
  } catch {
    return { rank: {}, watch: {}, fade: {} }
  }
}

function saveNotes(notes: NflDraftNotes) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(notes))
  } catch { /* storage full — silently degrade */ }
}

export function useNflDraftBoard(enabled: boolean) {
  const [data, setData] = useState<NflDraftBoard | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [position, setPosition] = useState<DraftPosition>('all')
  const [sort, setSort] = useState<NflDraftSort>('adp')
  const [offset, setOffset] = useState(0)
  // What the input shows vs. what we've asked the server for. Typing a name is
  // eight keystrokes; without the delay that is eight round trips.
  const [query, setQuery] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [notes, setNotes] = useState<NflDraftNotes>(() => {
    if (typeof window === 'undefined') return { rank: {}, watch: {}, fade: {} }
    return loadNotes()
  })
  const [syncError, setSyncError] = useState<string | null>(null)
  const notesRef = useRef(notes)
  notesRef.current = notes

  useEffect(() => {
    const timer = setTimeout(() => {
      setSubmittedQuery(query)
      // A new search is a new list; page 4 of the old one means nothing.
      setOffset(0)
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [query])

  const buildUrl = useCallback(() => {
    const params = new URLSearchParams({ sort, limit: '50', offset: String(offset) })
    if (position !== 'all') params.set('position', position)
    // Searching narrows on the server, so a one-player search costs one player.
    const trimmed = submittedQuery.trim()
    if (trimmed) params.set('q', trimmed)
    return `/api/nfl/draft-board?${params.toString()}`
  }, [position, sort, offset, submittedQuery])

  useEffect(() => {
    if (!enabled) {
      setData(null)
      setError(null)
      setLoading(true) // ready for re-entry
      return
    }
    let ignore = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const response = await fetch(buildUrl())
        if (!response.ok) {
          if (!ignore) setError(`Draft board unavailable (${response.status})`)
          return
        }
        const json = await response.json()
        if (!ignore) setData(json)
      } catch {
        if (!ignore) setError('Unable to load draft board.')
      } finally {
        if (!ignore) setLoading(false)
      }
    }
    load()
    return () => { ignore = true }
  }, [enabled, buildUrl])

  // ── Server sync: read notes from the server on mount ──
  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return

    const deviceId = getDeviceId()
    if (!deviceId) return

    let ignore = false

    const sync = async () => {
      try {
        const res = await fetch(`/api/nfl/draft-notes?season=${CURRENT_SEASON}`, {
          headers: { 'X-Device-Id': deviceId },
        })
        if (!res.ok || ignore) return

        const json: DraftNotesResponse = await res.json()

        if (json.note_count > 0) {
          // Server wins — replace state and rewrite localStorage cache
          const serverNotes = sanitizeNotes(json.notes)
          if (!ignore) {
            notesRef.current = serverNotes
            setNotes(serverNotes)
            saveNotes(serverNotes)
          }
        } else {
          // Server has zero rows — import from localStorage if we have notes
          const localNotes = loadNotes()
          const hasLocalNotes =
            Object.keys(localNotes.rank).length > 0 ||
            Object.keys(localNotes.watch).length > 0 ||
            Object.keys(localNotes.fade).length > 0
          if (hasLocalNotes && !ignore) {
            await fetch('/api/nfl/draft-notes/import', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-Device-Id': deviceId,
              },
              body: JSON.stringify({ season: CURRENT_SEASON, notes: localNotes }),
            })
            // localStorage is already correct; notes are now on the server
          }
        }
      } catch {
        // GET failed — keep running on localStorage exactly as today
      }
    }

    sync()
    return () => { ignore = true }
  }, [enabled])

  const selectPosition = useCallback((next: DraftPosition) => {
    setPosition(next)
    setOffset(0)
  }, [])

  const selectSort = useCallback((next: NflDraftSort) => {
    setSort(next)
    setOffset(0)
  }, [])

  const setRank = useCallback((playerId: number, rank: number | null) => {
    const prev = notesRef.current

    const nextRank = { ...prev.rank }
    if (rank === null) {
      delete nextRank[playerId]
    } else {
      nextRank[playerId] = rank
    }
    const next: NflDraftNotes = { ...prev, rank: nextRank }

    notesRef.current = next
    setNotes(next)
    saveNotes(next)

    const deviceId = getDeviceId()
    if (deviceId) {
      fetch('/api/nfl/draft-notes', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-Device-Id': deviceId },
        body: JSON.stringify({
          season: CURRENT_SEASON,
          player_id: playerId,
          rank,
          watch: next.watch[playerId] ?? false,
          fade: next.fade[playerId] ?? false,
        }),
      }).then(res => {
        if (!res.ok) throw new Error(`${res.status}`)
      }).catch(() => {
        notesRef.current = prev
        setNotes(prev)
        saveNotes(prev)
        setSyncError('Failed to save rank')
        setTimeout(() => setSyncError(null), 5000)
      })
    }
  }, [])

  const toggleWatch = useCallback((playerId: number) => {
    const prev = notesRef.current

    const nextWatch = { ...prev.watch }
    if (nextWatch[playerId]) {
      delete nextWatch[playerId]
    } else {
      nextWatch[playerId] = true
    }
    const next: NflDraftNotes = { ...prev, watch: nextWatch }

    notesRef.current = next
    setNotes(next)
    saveNotes(next)

    const deviceId = getDeviceId()
    if (deviceId) {
      fetch('/api/nfl/draft-notes', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-Device-Id': deviceId },
        body: JSON.stringify({
          season: CURRENT_SEASON,
          player_id: playerId,
          rank: next.rank[playerId] ?? null,
          watch: nextWatch[playerId] ?? false,
          fade: next.fade[playerId] ?? false,
        }),
      }).then(res => {
        if (!res.ok) throw new Error(`${res.status}`)
      }).catch(() => {
        notesRef.current = prev
        setNotes(prev)
        saveNotes(prev)
        setSyncError('Failed to save watch')
        setTimeout(() => setSyncError(null), 5000)
      })
    }
  }, [])

  const toggleFade = useCallback((playerId: number) => {
    const prev = notesRef.current

    const nextFade = { ...prev.fade }
    if (nextFade[playerId]) {
      delete nextFade[playerId]
    } else {
      nextFade[playerId] = true
    }
    const next: NflDraftNotes = { ...prev, fade: nextFade }

    notesRef.current = next
    setNotes(next)
    saveNotes(next)

    const deviceId = getDeviceId()
    if (deviceId) {
      fetch('/api/nfl/draft-notes', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-Device-Id': deviceId },
        body: JSON.stringify({
          season: CURRENT_SEASON,
          player_id: playerId,
          rank: next.rank[playerId] ?? null,
          watch: next.watch[playerId] ?? false,
          fade: nextFade[playerId] ?? false,
        }),
      }).then(res => {
        if (!res.ok) throw new Error(`${res.status}`)
      }).catch(() => {
        notesRef.current = prev
        setNotes(prev)
        saveNotes(prev)
        setSyncError('Failed to save fade')
        setTimeout(() => setSyncError(null), 5000)
      })
    }
  }, [])

  const clearQuery = useCallback(() => setQuery(''), [])

  return {
    data,
    loading,
    error,
    position,
    sort,
    offset,
    query,
    notes,
    syncError,
    selectPosition,
    selectSort,
    setQuery,
    clearQuery,
    setOffset,
    setRank,
    toggleWatch,
    toggleFade,
  }
}

export { POSITIONS, SORT_LABELS }
