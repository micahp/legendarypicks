const CLAIM_STORAGE_KEY = 'lp-arcade-claim-v1'
let memoryClaim: string | null = null
let pendingClaim: Promise<string> | null = null

function savedClaim() {
  if (typeof window === 'undefined') return memoryClaim
  try {
    return window.localStorage.getItem(CLAIM_STORAGE_KEY) || memoryClaim
  } catch {
    return memoryClaim
  }
}

function rememberClaim(token: string) {
  memoryClaim = token
  try {
    window.localStorage.setItem(CLAIM_STORAGE_KEY, token)
  } catch {
    // Keep the anonymous claim for this page session when storage is disabled.
  }
}

async function resolveArcadeClaim() {
  if (typeof window === 'undefined') throw new Error('Arcade sessions are available in a browser')
  let token = savedClaim()

  const requestSession = (claim?: string) => fetch('/api/arcade/session', {
    method: 'POST',
    headers: claim ? { 'X-Arcade-Claim': claim } : {},
  })
  let response = await requestSession(token || undefined)
  if (response.status === 401 && token) {
    token = null
    memoryClaim = null
    try { window.localStorage.removeItem(CLAIM_STORAGE_KEY) } catch { /* Storage is optional. */ }
    response = await requestSession()
  }
  if (!response.ok) throw new Error('Anonymous Arcade session unavailable')
  const payload = await response.json() as { claim_token?: unknown }
  if (typeof payload.claim_token !== 'string' || payload.claim_token.length < 32) {
    throw new Error('Arcade claim token was not issued')
  }
  rememberClaim(payload.claim_token)
  return payload.claim_token
}

export function getArcadeClaim() {
  if (!pendingClaim) {
    pendingClaim = resolveArcadeClaim().finally(() => { pendingClaim = null })
  }
  return pendingClaim
}
