#!/usr/bin/env bash
# Cut a release atomically: version bump, commit, tag, push.
#
# Exists because v0.6.1-v0.6.4 were each written to package.json and CHANGELOG.md
# by hand and never tagged -- four version numbers burned with no release behind
# them. Doing the steps separately by hand is what allowed them to drift apart.
# Preflight checks every failure it can see BEFORE touching anything; past that
# point the bump, commit and tag always happen together, and a failed push
# reports exactly how to finish or undo rather than going quiet.
#
# Deliberately does NOT write release notes. The CHANGELOG entry must already
# exist; a generated one would be worse than none.
#
#   scripts/release.sh 0.6.6
#   scripts/release.sh 0.6.6 --dry-run
set -euo pipefail

VERSION="${1:-}"
DRY_RUN=""
[ "${2:-}" = "--dry-run" ] && DRY_RUN=1

die() { echo "release: $*" >&2; exit 1; }
run() { if [ -n "$DRY_RUN" ]; then echo "  [dry-run] $*"; else "$@"; fi; }

[ -n "$VERSION" ] || die "usage: scripts/release.sh <version> [--dry-run]   e.g. 0.6.6"
echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' \
  || die "version must be bare semver without a leading v (got '$VERSION')"

cd "$(git rev-parse --show-toplevel)"

TAG="v$VERSION"
BRANCH=$(git rev-parse --abbrev-ref HEAD)

# ── preflight: every reason this could go wrong, before anything changes ──
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null 2>&1 \
  && die "$TAG already exists locally"
git ls-remote --tags origin "$TAG" 2>/dev/null | grep -q "$TAG" \
  && die "$TAG already exists on origin"

[ -z "$(git status --porcelain --untracked-files=no)" ] \
  || die "working tree has uncommitted changes -- commit them first"

grep -qE "^## +v?$VERSION\b" CHANGELOG.md \
  || die "CHANGELOG.md has no '## v$VERSION' section -- write the release notes first"

CURRENT=$(sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' package.json | head -1)
[ "$CURRENT" = "$VERSION" ] && die "package.json is already $VERSION -- nothing to bump"

echo "release: $CURRENT -> $VERSION on $BRANCH${DRY_RUN:+  (dry run)}"

# ── preflight: nothing deprecated is still reachable ──────────────────────
# A release is when superseded code gets shipped alongside its replacement and
# nobody notices. v0.7.3 retired two stats ingests that wrote the same table,
# the same league and the same source string as the ingests replacing them --
# whichever ran last owned every row, silently, and one of them blanked every
# goaltender to zeroes. `nba_service.py` is a whole deprecated FastAPI app that
# still binds port 8000, the port sports_service uses.
#
# Being present is fine; being REACHABLE is not. A module marked DEPRECATED or
# SUPERSEDED in its own docstring must be unreachable three ways: not imported,
# not scheduled, and -- if it can be run directly -- refusing to run.
deprecated_reachable=""
for f in $(git ls-files 'backend/*.py'); do
  head -20 "$f" | grep -qE '\b(DEPRECATED|SUPERSEDED)\b' || continue
  module=$(basename "$f" .py)

  # 1. imported by live code? (a docstring mention is not an import)
  if git grep -qE "^[[:space:]]*(import|from)[[:space:]]+$module\b" -- 'backend/*.py' \
     ':!'"$f" 2>/dev/null; then
    deprecated_reachable="$deprecated_reachable\n  $f — still imported"
  fi

  # 2. named by a systemd unit that could fire it unattended
  if systemctl list-units --all --no-pager --type=service 2>/dev/null \
       | grep -q "legendarypicks" \
     && systemctl cat $(systemctl list-units --all --no-pager --type=service 2>/dev/null \
          | grep -oE 'legendarypicks[a-z-]*\.service' | sort -u) 2>/dev/null \
        | grep -q "$module\.py"; then
    deprecated_reachable="$deprecated_reachable\n  $f — referenced by a systemd unit"
  fi

  # 3. runnable directly with nothing stopping it
  if grep -q '^if __name__ == "__main__"' "$f" \
     && ! grep -qE '_refuse_unless_forced|sys\.exit\(' "$f"; then
    deprecated_reachable="$deprecated_reachable\n  $f — runnable, no refusal guard"
  fi
done
if [ -n "$deprecated_reachable" ]; then
  echo "release: deprecated code is still reachable:" >&2
  printf "$deprecated_reachable\n" >&2
  die "retire it, guard it, or drop the DEPRECATED/SUPERSEDED marker if it is wrong"
fi

# ── preflight: what does PROD hold that DEV does not? ─────────────────────
# SCHEMA and SEASONS block, VOLUME does not (diff_databases.py splits them).
# A table, column or season present on one database and absent from the other
# is never "dev is deliberately ahead" -- it is a promotion that did not
# happen, and the cost of shipping over it is measured: on 2026-08-05, SIX
# defects were each correct in code and absent from production, found one at a
# time by hand over a night.
#
#   NFL rush_td/rec_td   0 rows in prod through three releases; v0.7.3
#                        announced "sort the board by touchdowns" anyway
#   NBA season stats     dev 576 rows, prod served 2023
#   MLB counting stats   23 columns dev-only -> `no such column: pa, era`
#   NHL goalie columns   11 columns dev-only
#   NHL season keys      48,017 prod rows still on nhle.com's raw 20252026,
#                        so a season-scoped join returned 0 for that league
#   NHL goalie logs      2,877 rows with `saves` on dev, 0 in prod
#
# Every one of them: fixed on dev, prod never re-run, both databases still
# answering 200. A changelog entry is a claim about PRODUCTION -- read this
# before writing one.
#
# VOLUME drift is legitimately divergent (live odds prod captures dev never
# sees; dev-only mock drafts) and stays advisory inside the tool -- failing on
# it would train people to skip the check.
if [ -f backend/diff_databases.py ] && [ -x backend/venv/bin/python ]; then
  echo
  echo "release: prod vs dev (schema/seasons BLOCK; volume is advisory)"
  if backend/venv/bin/python backend/diff_databases.py --quiet 2>&1 | sed 's/^/  /'; then
    echo "  no blocking divergence: schema and seasons agree"
  else
    echo
    die "prod and dev disagree on schema or seasons -- a promotion did not happen; migrate prod before releasing"
  fi
  echo
fi

# ── preflight: does PROD's own data pass the stats audit? ────────────────
# A release is a claim about production, so the audit that verify-gates.sh runs
# against dev must run against prod here -- and FAIL blocks, UNVERIFIED does
# not. UNVERIFIED is "nobody has fetched the evidence yet" (NFL trips it today
# for accepted nickname-vs-legal-name reasons) and blocking on it would just
# get the check disabled; FAIL is a measured defect in the data a release
# would ship.
if [ -f backend/audit_league_stats.py ] && [ -x backend/venv/bin/python ]; then
  echo
  echo "release: audit_league_stats vs prod (nfl/mlb/nba/nhl; FAIL blocks, UNVERIFIED does not)"
  audit_out=$(backend/venv/bin/python backend/audit_league_stats.py \
    --db backend/data/picks.db \
    --league nfl --league mlb --league nba --league nhl --quiet 2>&1) || true
  printf '%s\n' "$audit_out" | sed 's/^/  /'
  audit_fails=$(printf '%s\n' "$audit_out" | grep -c '^FAIL' || true)
  if [ "$audit_fails" -gt 0 ]; then
    echo
    die "$audit_fails audit check(s) FAIL against prod data -- promote or repair before releasing"
  fi
  echo
fi

# ── the atomic part ───────────────────────────────────────────────────────
if [ -n "$DRY_RUN" ]; then
  echo "  [dry-run] set package.json version to $VERSION"
else
  tmp=$(mktemp)
  sed "0,/\"version\"[[:space:]]*:[[:space:]]*\"$CURRENT\"/s//\"version\": \"$VERSION\"/" package.json > "$tmp"
  grep -q "\"version\": \"$VERSION\"" "$tmp" || { rm -f "$tmp"; die "failed to bump package.json"; }
  mv "$tmp" package.json
fi

run git add package.json CHANGELOG.md
run git commit -q -m "chore(release): $TAG"
run git tag -a "$TAG" -m "$TAG"

# The local half is done and consistent. A push can still fail for reasons the
# preflight cannot see (network, remote rejection), so say exactly how to finish
# or undo rather than leaving a half-released state to be discovered later.
push_failed() {
  echo >&2
  echo "release: $TAG is committed and tagged LOCALLY but the push failed." >&2
  echo "  finish:  git push origin $BRANCH && git push origin $TAG" >&2
  echo "  undo:    git tag -d $TAG && git reset --hard HEAD~1" >&2
  exit 1
}
if [ -z "$DRY_RUN" ]; then
  git push origin "$BRANCH" || push_failed
  git push origin "$TAG" || push_failed
else
  echo "  [dry-run] git push origin $BRANCH"
  echo "  [dry-run] git push origin $TAG"
fi

if [ -n "$DRY_RUN" ]; then
  echo "release: dry run complete, nothing changed"
else
  echo "release: $TAG pushed on $BRANCH"
fi
