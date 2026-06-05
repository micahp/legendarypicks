// Phase-1 no-op stand-in for @onflow/fcl.
//
// Blockchain is disabled by default (NEXT_PUBLIC_ENABLE_FLOW !== 'true'). The real @onflow/fcl pulls in
// @onflow/transport-http, which currently crashes on load ("Cannot read properties of undefined (reading
// 'BLOCKS')") and takes every page down with it. next.config.js aliases '@onflow/fcl' to this stub when
// Flow is off, so the games/scores/predict app runs with zero chain dependency. Re-enable in phase 2 by
// setting NEXT_PUBLIC_ENABLE_FLOW=true (after upgrading the FCL deps to a working version).

const noop = () => {}

// config(...).load(...) is chainable in real FCL
const configChain = { load: () => configChain }
const config = () => configChain

const currentUser = {
  // Navbar/GameBrowser subscribe to auth state; report "signed out" once and return an unsubscribe fn.
  subscribe: (cb) => {
    try { cb({ addr: null, loggedIn: false, cid: null }) } catch (e) {}
    return noop
  },
  snapshot: async () => ({ addr: null, loggedIn: false, cid: null }),
  authenticate: noop,
  unauthenticate: noop,
}

const disabled = async () => {
  throw new Error('Flow/blockchain is disabled in phase 1 (set NEXT_PUBLIC_ENABLE_FLOW=true to enable).')
}

const fcl = {
  config,
  currentUser,
  authenticate: noop,
  unauthenticate: noop,
  mutate: disabled,
  query: disabled,
  tx: () => ({ onceSealed: async () => ({}), subscribe: () => noop }),
}

module.exports = fcl
module.exports.default = fcl
