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

# brand_php_src makes `php -v` report "Built by lerd" instead of the build
# tool's name. The value is a configure variable spc sets on its own command
# line, so it cannot be overridden from the environment, and spc runs buildconf
# before configure, which regenerates the generated `configure` from
# configure.ac. That leaves exactly one durable target: configure.ac inside the
# tarball spc extracts, since spc re-extracts php-src on every build.
brand_php_src() {
  local tarball inner staging
  tarball="$(ls downloads/php-"$VERSION"*.tar.* 2>/dev/null | head -1)"
  if [ -z "$tarball" ]; then
    echo "build.sh: no php-src tarball for $VERSION; skipping the build-provider brand" >&2
    return 0
  fi
  staging="$(mktemp -d)"
  tar -xf "$tarball" -C "$staging"
  inner="$(find "$staging" -maxdepth 1 -mindepth 1 -type d | head -1)"

  sed -i.bak 's|\["\$PHP_BUILD_PROVIDER"\]|["lerd"]|' "$inner/configure.ac"
  rm -f "$inner/configure.ac.bak"
  if ! grep -q '\["lerd"\]' "$inner/configure.ac"; then
    echo "build.sh: could not brand the build provider; php -v will name the build tool" >&2
    rm -rf "$staging"
    return 0
  fi

  ( cd "$staging" && tar -cJf "$OLDPWD/$tarball" "$(basename "$inner")" )
  rm -rf "$staging"
}

STATIC_EXTS="$(filter_exts < "$ROOT/extensions.txt" | tr '\n' ',' | sed 's/,$//')"
SHARED_EXTS="$(filter_exts < "$ROOT/shared-extensions.txt" | tr '\n' ',' | sed 's/,$//')"

# The libraries are the slow part and are shared across PHP versions, so a
# matrix job that caches buildroot/ and downloads/ spends about three minutes
# per version instead of fourteen.
# Always the newest stable static-php-cli, never nightly. fetch-spc.sh records
# which one it was, and that record ships with the release.
[ -x ./spc ] || "$ROOT/scripts/fetch-spc.sh" .

./spc doctor --auto-fix
download_args=(--with-php="$VERSION" --ignore-cache-sources=php-src)
if [ -n "$SHARED_EXTS" ]; then
  download_args+=(--for-extensions="$STATIC_EXTS,$SHARED_EXTS")
else
  download_args+=(--for-extensions="$STATIC_EXTS")
fi
[ -n "$CUSTOM_URL" ] && download_args+=(--custom-url="php-src:$CUSTOM_URL")
./spc download "${download_args[@]}"

brand_php_src
build_args=("$STATIC_EXTS" --build-cli --build-fpm)
# A prerelease drops the shared extensions entirely, so do not pass an empty
# --build-shared: spc reads that as a request to build nothing and errors.
[ -n "$SHARED_EXTS" ] && build_args+=(--build-shared="$SHARED_EXTS")
./spc build "${build_args[@]}"

mkdir -p "$OUTDIR/modules"
# The toolchain that produced this binary travels with it.
[ -f BUILD-INFO.txt ] && cp BUILD-INFO.txt "$OUTDIR/BUILD-INFO.txt"
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

# The Debug window's query lens needs this collector, and it only exists as a
# shared object here because the tree it compiles against is spc's. Absent
# source is not fatal: a binary without it is still a working PHP, and lerd's
# doctor reports the lens as unavailable rather than leaving it silently empty.
if [ -d "${LERD_DEVTOOLS_SRC:-}" ]; then
  "$ROOT/scripts/build-devtools.sh" source/php-src "$LERD_DEVTOOLS_SRC" "$OUTDIR" \
    || echo "build.sh: lerd_devtools was not built; the query lens will be unavailable" >&2
else
  echo "build.sh: LERD_DEVTOOLS_SRC unset, skipping the query-capture collector" >&2
fi

"$OUTDIR/php-native-$VERSION" --version

if ! "$OUTDIR/php-native-$VERSION" --version | grep -q "Built by lerd"; then
  echo "build.sh: warning, this binary does not report lerd as its build provider" >&2
fi
