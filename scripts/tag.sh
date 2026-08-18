#!/usr/bin/env bash
# Mark a build. Not a release.
#
# `scripts/release.sh` is the heavyweight path and has to be: it bumps
# package.json, writes the version tag the pre-push hook then requires, runs the
# prod/dev divergence check and the per-league stats audit, and publishes GitHub
# release notes. That is right for a version. It is far too much ceremony for
# "mark where this build was", which is why marking a build kept feeling like
# cutting a release.
#
# So this writes a tag in its own namespace and does nothing else:
#
#   build/2026-08-18-0543-a1b2c3d          scripts/tag.sh
#   build/2026-08-18-0543-a1b2c3d-prod     scripts/tag.sh prod
#
# It REFUSES to write a vX.Y.Z tag. Version tags come from release.sh only --
# hand-tagging versions is the exact drift release.sh was written to stop
# (v0.6.1-v0.6.4 were burned that way), and a second door into it would undo
# that. Nothing here touches package.json or CHANGELOG.md, so the pre-push hook
# has no opinion on it either.
#
#   scripts/tag.sh                 tag HEAD
#   scripts/tag.sh nightly         tag HEAD, suffixed
#   scripts/tag.sh nightly --push  and push it
set -euo pipefail

LABEL="${1:-}"
PUSH=""
for arg in "$@"; do [ "$arg" = "--push" ] && PUSH=1; done
[ "$LABEL" = "--push" ] && LABEL=""

die() { echo "tag: $*" >&2; exit 1; }

cd "$(git rev-parse --show-toplevel)"

# A version is release.sh's job, whichever way it is spelled.
if echo "$LABEL" | grep -qE '^v?[0-9]+\.[0-9]+\.[0-9]+$'; then
  die "'$LABEL' is a version. Use scripts/release.sh $(echo "$LABEL" | sed 's/^v//') instead --
  version tags carry a package.json bump, a CHANGELOG entry and the prod audits."
fi
echo "$LABEL" | grep -qE '^[a-z0-9][a-z0-9._-]*$|^$' \
  || die "label must be lowercase alphanumeric with . _ - (got '$LABEL')"

SHA=$(git rev-parse --short HEAD)
STAMP=$(date -u +%Y-%m-%d-%H%M)
TAG="build/$STAMP-$SHA${LABEL:+-$LABEL}"

git rev-parse -q --verify "refs/tags/$TAG" >/dev/null 2>&1 && die "$TAG already exists"

# Recorded on the tag so a build can be traced without checking it out. A dirty
# tree is not blocked -- marking a build mid-work is a legitimate reason to
# reach for this -- but it IS written down, because a tag that silently means
# "plus whatever was uncommitted" is worse than no tag.
DIRTY=""
[ -n "$(git status --porcelain --untracked-files=no)" ] && DIRTY=" (tree was dirty)"

git tag -a "$TAG" -m "build $STAMP at $SHA on $(git rev-parse --abbrev-ref HEAD)$DIRTY"
echo "tag: $TAG$DIRTY"

if [ -n "$PUSH" ]; then
  git push origin "$TAG" && echo "tag: pushed"
else
  echo "tag: local only. push it with:  git push origin $TAG"
fi
