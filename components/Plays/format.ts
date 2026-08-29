// Display helpers for the curated plays board. Pure formatting; no data fetching.

export function cents(p?: number | null): string {
  if (p == null) return '—'
  return `${Math.round(p * 100)}¢`
}

// Compact USD depth: 431176 -> "$431k", 13093152 -> "$13.1M".
export function money(n?: number | null): string {
  if (n == null) return '—'
  const abs = Math.abs(n)
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`
  if (abs >= 1_000) return `$${Math.round(n / 1_000)}k`
  return `$${Math.round(n)}`
}

export function ageFromSeconds(sec?: number | null): string {
  if (sec == null) return 'unknown age'
  if (sec < 60) return `${Math.round(sec)}s ago`
  const m = Math.round(sec / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  const rem = m % 60
  if (h < 24) return rem ? `${h}h ${rem}m ago` : `${h}h ago`
  const d = Math.floor(h / 24)
  return `${d}d ${h % 24}h ago`
}

// Render a UTC ISO string in the viewer's local zone (honest: no server tz assumption).
export function localTime(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit',
  })
}

export function titleCase(s: string): string {
  return s.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

// Category labels: keep sport acronyms uppercase, humanize the compound bucket.
export function categoryLabel(cat: string): string {
  const upper = new Set(['mlb', 'nba', 'nfl', 'nhl', 'ufc'])
  if (upper.has(cat.toLowerCase())) return cat.toUpperCase()
  if (cat === 'crypto_econ_weather_politics') return 'Crypto / econ / weather / politics'
  return titleCase(cat)
}

// "high_if_triggered" -> "High — if triggered"
export function confidenceLabel(c: string): string {
  const cleaned = c.replace(/_if_triggered$/, '')
  const base = titleCase(cleaned)
  return /_if_triggered$/.test(c) ? `${base} — if triggered` : base
}
