import { useState, useEffect, useRef } from 'react'
import type { AllDayCollectionResponse } from '../types'

const FLOW_ADDRESS_RE = /^0x[0-9a-fA-F]{16}$/
const LS_KEY = 'nfl-allday-address'

function loadSavedAddress(): string {
  if (typeof window === 'undefined') return ''
  return localStorage.getItem(LS_KEY) || ''
}

function saveAddress(address: string) {
  if (typeof window === 'undefined') return
  localStorage.setItem(LS_KEY, address)
}

export function useAllDayCollection() {
  const [address, setAddress] = useState(loadSavedAddress)
  const [inputValue, setInputValue] = useState('')
  const [data, setData] = useState<AllDayCollectionResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  // Fetch when address changes to a valid one
  useEffect(() => {
    if (!address || !FLOW_ADDRESS_RE.test(address)) return

    // Abort previous request
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError(null)

    const backend = process.env.NEXT_PUBLIC_API_BASE || ''
    fetch(`${backend}/api/nfl/allday/collection?address=${encodeURIComponent(address)}`, {
      signal: controller.signal,
    })
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then(json => {
        setData(json)
        setLoading(false)
      })
      .catch(err => {
        if (err.name === 'AbortError') return
        setError(err.message || 'Failed to load collection')
        setLoading(false)
      })

    return () => controller.abort()
  }, [address])

  const submit = (addr: string) => {
    const trimmed = addr.trim()
    if (!FLOW_ADDRESS_RE.test(trimmed)) {
      setError('Enter a valid Flow address (0x + 16 hex chars)')
      return
    }
    setError(null)
    saveAddress(trimmed)
    setAddress(trimmed)
  }

  const clear = () => {
    setAddress('')
    setInputValue('')
    setData(null)
    setError(null)
    saveAddress('')
  }

  return {
    address,
    inputValue,
    setInputValue,
    data,
    loading,
    error,
    submit,
    clear,
  }
}
