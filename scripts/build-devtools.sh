#!/usr/bin/env bash
# Build lerd_devtools as a loadable module for a freshly built static PHP.
#
#   scripts/build-devtools.sh <php-src-dir> <extension-src-dir> <outdir>
#
# This is the engine-level collector behind the Debug window's query lens. The
# PHP image compiles it in; here it is a shared object beside the binary, the
# same shape Xdebug takes. It is a normal PHP module, so it loads with
# extension= rather than zend_extension=, despite using the zend_observer API.
#
# phpize is not available: it comes from an installed PHP and these builds are
# never installed. Compiling against the php-src tree spc leaves behind gives
# the same result, since that tree carries the generated php_config.h the
# module has to agree with.
set -euo pipefail

PHPSRC="${1:?usage: build-devtools.sh <php-src-dir> <ext-src-dir> <outdir>}"
EXTSRC="${2:?}"
OUTDIR="${3:?}"

if [ ! -f "$PHPSRC/main/php_config.h" ]; then
  echo "build-devtools.sh: $PHPSRC has no generated php_config.h; build PHP first" >&2
  exit 1
fi

staging="$(mktemp -d)"
cp "$EXTSRC"/*.c "$EXTSRC"/*.h "$staging/"
# The source includes "config.h", which is what php_config.h is called inside a
# configured extension build.
cp "$PHPSRC/main/php_config.h" "$staging/config.h"

( cd "$staging" && clang -shared -fPIC -O2 \
    -I . \
    -I "$PHPSRC" -I "$PHPSRC/main" -I "$PHPSRC/Zend" -I "$PHPSRC/TSRM" -I "$PHPSRC/ext" \
    -DHAVE_CONFIG_H -DCOMPILE_DL_LERD_DEVTOOLS=1 -DZEND_COMPILE_DL_EXT=1 \
    -undefined dynamic_lookup \
    lerd_devtools.c -o lerd_devtools.so )

mkdir -p "$OUTDIR/modules"
# Named per version: a module is built against one PHP's ABI and will not
# load into another.
cp "$staging/lerd_devtools.so" "$OUTDIR/modules/lerd_devtools-$(basename "$(ls "$OUTDIR"/php-native-* | grep -v fpm | head -1)" | sed 's/php-native-//').so"
rm -rf "$staging"

# A module that compiles but will not load is worse than none: it would warn on
# every request while the query lens stayed empty.
if ! "$OUTDIR/php-native-"* --version >/dev/null 2>&1; then
  echo "build-devtools.sh: no built binary to verify against, skipping the load check" >&2
  exit 0
fi
binary="$(ls "$OUTDIR"/php-native-* | grep -v fpm | head -1)"
if ! "$binary" -d "extension=$(ls "$OUTDIR"/modules/lerd_devtools-*.so | head -1)" \
     -r 'exit(extension_loaded("lerd_devtools") ? 0 : 1);'; then
  echo "build-devtools.sh: lerd_devtools.so built but will not load into this PHP" >&2
  exit 1
fi
echo "lerd_devtools.so built and loads"
