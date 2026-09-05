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

# A prerelease has no GA tarball, so its source URL is pinned here, and the
# extensions that do not compile against it yet are dropped. Both mirror how
# lerd already treats a prerelease when it builds container images.
PRERELEASE_LINE="$(grep -E "^$VERSION " "$ROOT/prerelease.txt" 2>/dev/null || true)"
CUSTOM_URL=""
DROP=""
if [ -n "$PRERELEASE_LINE" ]; then
  CUSTOM_URL="$(echo "$PRERELEASE_LINE" | awk '{print $3}')"
  DROP="$(grep -vE '^#|^$' "$ROOT/unbuildable-prerelease.txt" | tr '\n' '|' | sed 's/|$//')"
  echo "build.sh: $VERSION is a prerelease, building from $CUSTOM_URL"
fi

filter_exts() {
  if [ -z "$DROP" ]; then cat; else grep -vE "^($DROP)$"; fi
}

STATIC_EXTS="$(filter_exts < "$ROOT/extensions.txt" | tr '\n' ',' | sed 's/,$//')"
SHARED_EXTS="$(filter_exts < "$ROOT/shared-extensions.txt" | tr '\n' ',' | sed 's/,$//')"

# The libraries are the slow part and are shared across PHP versions, so a
# matrix job that caches buildroot/ and downloads/ spends about three minutes
# per version instead of fourteen.
./spc doctor --auto-fix
download_args=(--with-php="$VERSION" --ignore-cache-sources=php-src)
if [ -n "$SHARED_EXTS" ]; then
  download_args+=(--for-extensions="$STATIC_EXTS,$SHARED_EXTS")
else
  download_args+=(--for-extensions="$STATIC_EXTS")
fi
[ -n "$CUSTOM_URL" ] && download_args+=(--custom-url="php-src:$CUSTOM_URL")
./spc download "${download_args[@]}"
build_args=("$STATIC_EXTS" --build-cli --build-fpm)
# A prerelease drops the shared extensions entirely, so do not pass an empty
# --build-shared: spc reads that as a request to build nothing and errors.
[ -n "$SHARED_EXTS" ] && build_args+=(--build-shared="$SHARED_EXTS")
./spc build "${build_args[@]}"

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
