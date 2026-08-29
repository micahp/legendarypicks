/**
 * Radio station routing for game-detail live audio.
 *
 * Sourced from data/radio-mls.json (verified:true entries only). Each verified
 * club maps to `/api/stream/<key>`; the backend ffmpeg relay transcodes the
 * publisher stream to MP3 (see `_LCUP_RADIO` in backend/routers/games/contexts.py).
 *
 * Match keys cover the two shapes `context.home_team`/`away_team` takes:
 * abbreviations on the mls path ("ATX", "CLB") and full display names on the
 * lcup path ("Columbus Crew"). A team not in the map renders no player — an
 * unverified stream is never offered.
 */
export const TEAM_RADIO: Record<string, string> = {
  // verified 2026-08-27 (HTTP 200 audio probe per entry)
  ATX: '/api/stream/atx',
  CLB: '/api/stream/clb',
  CHI: '/api/stream/chi',
  CIN: '/api/stream/cin',
  CLT: '/api/stream/clt',
  COL: '/api/stream/col',
  DC: '/api/stream/dc',
  MTL: '/api/stream/mtl',
  NE: '/api/stream/ne',
  NSH: '/api/stream/nsh',
  ORL: '/api/stream/orl',
  PHI: '/api/stream/phi',
  POR: '/api/stream/por',
  SD: '/api/stream/sd',
  SEA: '/api/stream/sea',
  SJ: '/api/stream/sj',
  TOR: '/api/stream/tor',
  MIA: '/api/stream/mia',
}

/** Full display names as published on the lcup scoreboard path. */
export const TEAM_RADIO_BY_NAME: Record<string, string> = {
  'Austin FC': TEAM_RADIO.ATX,
  'Columbus Crew': TEAM_RADIO.CLB,
  'Chicago Fire': TEAM_RADIO.CHI,
  'Chicago Fire FC': TEAM_RADIO.CHI,
  'FC Cincinnati': TEAM_RADIO.CIN,
  'Charlotte FC': TEAM_RADIO.CLT,
  'Colorado Rapids': TEAM_RADIO.COL,
  'D.C. United': TEAM_RADIO.DC,
  'CF Montréal': TEAM_RADIO.MTL,
  'New England Revolution': TEAM_RADIO.NE,
  'Nashville SC': TEAM_RADIO.NSH,
  'Orlando City': TEAM_RADIO.ORL,
  'Orlando City SC': TEAM_RADIO.ORL,
  'Philadelphia Union': TEAM_RADIO.PHI,
  'Portland Timbers': TEAM_RADIO.POR,
  'San Diego FC': TEAM_RADIO.SD,
  'Seattle Sounders': TEAM_RADIO.SEA,
  'Seattle Sounders FC': TEAM_RADIO.SEA,
  'San Jose Earthquakes': TEAM_RADIO.SJ,
  'Toronto FC': TEAM_RADIO.TOR,
  'Inter Miami': TEAM_RADIO.MIA,
  'Inter Miami CF': TEAM_RADIO.MIA,
}

/** Labels shown on the ListenLive card, keyed by the stream key above. */
export const RADIO_LABELS: Record<string, string> = {
  atx: 'Alt 97.5 · Austin FC English radio',
  clb: '97.1 The Fan · Columbus Crew English radio',
  chi: 'WLS 890 AM · Chicago Fire English radio',
  cin: 'ESPN 1530 · FC Cincinnati English radio',
  clt: 'Sports Radio WFNZ · Charlotte FC English radio',
  col: 'Altitude Sports Radio · Colorado Rapids English radio',
  dc: '104.7 WONK FM · D.C. United English radio',
  mtl: 'TSN 690 · CF Montréal English radio',
  ne: '98.5 The Sports Hub · New England Revolution English radio',
  nsh: '104.5 The Zone · Nashville SC English radio',
  orl: 'FM 96.9 The Game · Orlando City English radio',
  phi: '97.5 The Fanatic · Philadelphia Union English radio',
  por: '750 The Game · Portland Timbers English radio',
  sd: 'San Diego Sports 760 · San Diego FC English radio',
  sea: 'Sports Radio 950 KJR · Seattle Sounders English radio',
  sj: 'KSFO 810 AM · San Jose Earthquakes English radio',
  tor: 'TSN 1050 · Toronto FC English radio',
  mia: 'ESPN 106.3 West Palm · Inter Miami English radio',
  lcup: 'English radio (free)',
}

/**
 * Resolve the radio stream for a matchup. Returns null when neither side has
 * a verified station — the caller hides the player rather than offering an
 * unverified stream.
 */
export function radioForMatchup(
  home?: string | null,
  away?: string | null
): { key: string; streamUrl: string } | null {
  if (!home && !away) return null
  for (const side of [home, away]) {
    const t = (side || '').trim()
    if (!t) continue
    const streamUrl = TEAM_RADIO[t.toUpperCase()] || TEAM_RADIO_BY_NAME[t]
    if (streamUrl) {
      const key = streamUrl.replace('/api/stream/', '')
      return { key, streamUrl }
    }
  }
  return null
}
