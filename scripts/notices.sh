#!/usr/bin/env bash
# Collect the licence texts that have to travel with a binary redistribution.
#
#   scripts/notices.sh source/ out/THIRD-PARTY-NOTICES.txt
#
# The binary statically links PHP and every library spc built, and PHP's own
# licence plus several of those libraries require their notice to be included
# with a binary distribution. Shipping the binaries alone does not satisfy that.
set -euo pipefail

SRCDIR="${1:?usage: notices.sh <spc-source-dir> <outfile>}"
OUT="${2:?usage: notices.sh <spc-source-dir> <outfile>}"

mkdir -p "$(dirname "$OUT")"
{
  echo "Third-party licences for the lerd native PHP build"
  echo
  echo "This binary statically links PHP and the libraries below. Each licence"
  echo "text is reproduced in full, as those licences require."
  echo
} > "$OUT"

found=0
for dir in "$SRCDIR"/*/; do
  name="$(basename "$dir")"
  # Licence files are spelled a dozen ways; take whatever is at the top level.
  for candidate in LICENSE LICENSE.txt LICENSE.md LICENCE COPYING COPYING.txt \
                   COPYRIGHT NOTICE LICENSE-MIT LICENSE.APACHE2; do
    if [ -f "$dir$candidate" ]; then
      {
        echo "================================================================"
        echo "$name ($candidate)"
        echo "================================================================"
        cat "$dir$candidate"
        echo
      } >> "$OUT"
      found=$((found + 1))
      break
    fi
  done
done

if [ "$found" -eq 0 ]; then
  echo "notices.sh: found no licence files under $SRCDIR; refusing to ship an empty notice" >&2
  exit 1
fi

echo "collected $found licence texts into $OUT"
