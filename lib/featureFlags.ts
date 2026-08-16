/**
 * Build-time feature flags.
 *
 * `NEXT_PUBLIC_*` values are inlined by Next at BUILD time, not read at runtime,
 * so a flag is decided by the environment that built the bundle. That is what
 * makes this safe as a dev/prod split: the dev server builds with `.env.local`
 * present, and the production image cannot see that file at all —
 * `.dockerignore` excludes `.env.*` from the build context, and prod's build
 * args are an explicit allowlist in docker-compose.yml.
 *
 * Every flag here is OFF unless explicitly turned on. Absence must read as
 * hidden: a missing var is exactly what prod looks like, and a flag that
 * defaulted to visible would ship the feature the moment someone forgot to set
 * it. Compare against the string 'true' — `Boolean('false')` is `true`.
 */

/**
 * "From the Booth" — timestamp-matched broadcast reads on WC, Leagues Cup and
 * Call of Duty game pages. Dev-only (Micah, 2026-08-11): it depends on live
 * broadcast capture that production does not run.
 *
 * Turn on by putting `NEXT_PUBLIC_SHOW_BOOTH=true` in `.env.local`, which is
 * gitignored and never reaches an image.
 */
export const SHOW_BOOTH = process.env.NEXT_PUBLIC_SHOW_BOOTH === 'true'
