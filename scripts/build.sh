#!/usr/bin/env bash
# Build one static PHP for the native runtime: the CLI and FPM binaries, plus
# the extensions that can only exist as shared objects.
#
#   scripts/build.sh 8.4 out/
#
# Leaves in <outdir>: php-native-<v>, php-native-fpm-<v>, modules/*.so
set -euo pipefail

VERSION="${1:?usage: build.sh <php-minor> <outdir>}"
OUTDIR="${2:?usage: build.sh <php-minor> <outdir>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

STATIC_EXTS="$(tr '\n' ',' < "$ROOT/extensions.txt" | sed 's/,$//')"
SHARED_EXTS="$(tr '\n' ',' < "$ROOT/shared-extensions.txt" | sed 's/,$//')"

# The libraries are the slow part and are shared across PHP versions, so a
# matrix job that caches buildroot/ and downloads/ spends about three minutes
# per version instead of fourteen.
./spc doctor --auto-fix
./spc download --with-php="$VERSION" \
  --for-extensions="$STATIC_EXTS,$SHARED_EXTS" \
  --ignore-cache-sources=php-src
./spc build "$STATIC_EXTS" \
  --build-cli --build-fpm \
  --build-shared="$SHARED_EXTS"

mkdir -p "$OUTDIR/modules"
cp buildroot/bin/php     "$OUTDIR/php-native-$VERSION"
cp buildroot/bin/php-fpm "$OUTDIR/php-native-fpm-$VERSION"
cp buildroot/modules/*.so "$OUTDIR/modules/" 2>/dev/null || true

# Fail loudly here rather than shipping a binary that boots and then cannot run
# a framework. 7.4 and 8.0 fail this way: they compile only once the XML
# extensions are stripped, and nothing real runs without them.
for required in dom simplexml xml intl mbstring opcache; do
  if ! "$OUTDIR/php-native-$VERSION" -m | grep -qix "$required"; then
    echo "build.sh: php $VERSION is missing $required; refusing to publish it" >&2
    exit 1
  fi
done

"$OUTDIR/php-native-$VERSION" --version
