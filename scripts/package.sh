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
# lerd names platforms with Go's arch, which calls this one amd64.
GOARCH="$ARCH"; [ "$ARCH" = "x86_64" ] && GOARCH="amd64"

# Assets are named by the full patch so a release can carry several of them per
# minor and a pin points at exactly one. The binaries inside keep the minor in
# their name: everything downstream (the shim, the launchd labels, the FPM
# port) is keyed by minor, which makes a patch bump a straight swap.
PATCH="$("$OUTDIR/php-native-$VERSION" -n -r 'echo PHP_VERSION;')"
case "$PATCH" in
  "$VERSION".*) ;;
  *) echo "package.sh: built binary reports $PATCH, which is not a $VERSION release" >&2; exit 1 ;;
esac

mkdir -p "$DISTDIR"
base="lerd-php-$PATCH-$OS-$ARCH"

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

# The pin lerd will publish, written by the build that produced the asset it
# describes. A digest transcribed by hand is a digest that eventually does not
# match the file, and the failure surfaces on a user's machine.
SHA="$(cat "$DISTDIR/$base.tar.gz.sha256")"
SIZE="$(wc -c < "$DISTDIR/$base.tar.gz" | tr -d ' ')"
cat > "$DISTDIR/pin-$VERSION-$OS-$GOARCH.json" <<JSON
{"minor":"$VERSION","version":"$PATCH","platform":"$OS/$GOARCH","asset":"$base.tar.gz","sha256":"$SHA","size":$SIZE}
JSON

echo "$DISTDIR/$base.tar.gz"
cat "$DISTDIR/pin-$VERSION-$OS-$GOARCH.json"
