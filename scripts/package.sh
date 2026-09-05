#!/usr/bin/env bash
# Turn a built version into the release assets lerd downloads: one tarball per
# SAPI plus a sha256, named the way internal/tools/tools.yaml expects.
#
#   scripts/package.sh 8.4 out/ dist/
set -euo pipefail

VERSION="${1:?usage: package.sh <php-minor> <outdir> <distdir>}"
OUTDIR="${2:?}"
DISTDIR="${3:?}"
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"   # arm64 or x86_64

mkdir -p "$DISTDIR"
base="lerd-php-$VERSION-$OS-$ARCH"

# PHP's licence and several of the statically linked libraries require their
# notice to travel with a binary distribution, so the tarball carries them.
if [ ! -f "$OUTDIR/THIRD-PARTY-NOTICES.txt" ]; then
  "$(dirname "$0")/notices.sh" source "$OUTDIR/THIRD-PARTY-NOTICES.txt"
fi

# The extensions travel with the binary they were built against: a .so from
# another build will not load.
tar -czf "$DISTDIR/$base.tar.gz" -C "$OUTDIR" \
  "php-native-$VERSION" "php-native-fpm-$VERSION" modules THIRD-PARTY-NOTICES.txt \
  $([ -f "$OUTDIR/BUILD-INFO.txt" ] && echo BUILD-INFO.txt)

shasum -a 256 "$DISTDIR/$base.tar.gz" | awk '{print $1}' > "$DISTDIR/$base.tar.gz.sha256"
echo "$DISTDIR/$base.tar.gz"
cat "$DISTDIR/$base.tar.gz.sha256"
