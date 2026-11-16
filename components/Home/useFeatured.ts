import { useEffect, useState } from 'react'
import type { Featured, Load } from './types'

// Client-side read of the homepage's real numbers. A failed read is an 'error' state the
// sections render quietly; it is never turned into a zero or a placeholder figure.
export function useFeatured(): Load<Featured> {
  const [state, setState] = useState<Load<Featured>>({ status: 'loading' })
  useEffect(() => {
    const ctl = new AbortController()
    fetch('/api/home/featured', { signal: ctl.signal })
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status))
        return r.json()
      })
      .then((data: Featured) => setState({ status: 'ready', data }))
      .catch((e) => {
        if (e?.name !== 'AbortError') setState({ status: 'error' })
      })
    return () => ctl.abort()
  }, [])
  return state
}
