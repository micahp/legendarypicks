# PLAN — MLS Props selector (2026-08-15)

## Scope

Expose MLS as a selectable league in the existing public `/props` league pills.
The MLS props API and the all-leagues Slate already publish MLS fixtures and
player markets; this change makes that supported data directly discoverable.

## Contract

- Add `MLS` to the Props league selector's accepted league values and rendered
  pill list.
- Selecting MLS sends `league=mls` through the existing Slate and market
  requests. Do not add a parallel endpoint or derive prop data in the client.
- Preserve existing league filters and the honest unsupported states in
  performance/model tabs where MLS-specific analytics do not exist.

## Acceptance

- A focused regression check asserts the selector contains MLS.
- On the isolated public candidate, selecting MLS shows only MLS slate games
  and expanding a game reveals the publisher-backed player prop lines.
- Managed `dev`, its database, and its tunnel are not merged, restarted, or
  otherwise changed by this candidate-only slice.
