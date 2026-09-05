#!/usr/bin/env bash
# Fetch the newest stable static-php-cli release and record exactly which one
# it was.
#
#   scripts/fetch-spc.sh [outdir]
#
# Latest stable rather than a pinned version, so PHP support and fixes arrive
# without a bump here; stable rather than nightly, because nightly changes the
# build tooling under a release with no way to tell afterwards. The version and
# digest are written to BUILD-INFO so a published binary can always be traced
# back to the toolchain that produced it.
set -euo pipefail

OUTDIR="${1:-.}"
API="https://api.github.com/repos/crazywhalecc/static-php-cli/releases/latest"

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64)  asset="spc-macos-aarch64.tar.gz" ;;
  Darwin-x86_64) asset="spc-macos-x86_64.tar.gz" ;;
  Linux-aarch64) asset="spc-linux-aarch64.tar.gz" ;;
  Linux-x86_64)  asset="spc-linux-x86_64.tar.gz" ;;
  *) echo "fetch-spc.sh: unsupported platform $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac

tag="$(curl -fsSL "$API" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1)"
if [ -z "$tag" ]; then
  echo "fetch-spc.sh: could not resolve the latest static-php-cli release" >&2
  exit 1
fi

url="https://github.com/crazywhalecc/static-php-cli/releases/download/$tag/$asset"
curl -fsSL -o /tmp/spc.tar.gz "$url"
digest="$(shasum -a 256 /tmp/spc.tar.gz | awk '{print $1}')"

mkdir -p "$OUTDIR"
tar -xzf /tmp/spc.tar.gz -C "$OUTDIR"
chmod +x "$OUTDIR/spc"

{
  echo "static-php-cli: $tag"
  echo "asset: $asset"
  echo "sha256: $digest"
} > "$OUTDIR/BUILD-INFO.txt"

echo "static-php-cli $tag ($digest)"
"$OUTDIR/spc" --version
