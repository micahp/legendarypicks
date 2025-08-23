### [Decision 2]: Fix Top Shot metadata resolution (Cadence 1.0 + ViewResolver)
**Timestamp (UTC):** 2025-08-23T00:00:00Z
**Scope:** `services/nbaTopShot.ts`, `components/MomentGallery.tsx`, `config/fcl.ts`
**Change Summary:** Updated Cadence scripts to Cadence 1.0; removed unauthorized `getAuthAccount` usage and invalid `TopShot.MomentNFT` reference. Resolved `TopShot.TopShotMomentMetadataView` via `ViewResolver` from the public collection. UI now guards missing metadata and shows ID vs metadata counts.
**Rationale:** Cadence 1.0 deprecations and public-only reads required a compliant approach; prevents runtime errors and improves UX.
**Alternatives Considered:**
  - HybridCustody traversal for linked accounts — deferred; requires entitlement paths.
  - Off-chain metadata fetch — postponed to avoid centralization; may add as fallback.
**Trade-offs / Risks:**
  - Some moments still may not expose the view; UI handles nulls gracefully.
**Follow-ups / TODOs:**
  - Optional off-chain fallback for unresolved metadata.
**Source Prompt(s):** Top Shot metadata errors and request to keep testing before wallet connect.
