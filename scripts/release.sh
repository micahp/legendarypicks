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
