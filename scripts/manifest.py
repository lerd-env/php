#!/usr/bin/env python3
"""Merge the per-build pin fragments into the manifest lerd publishes.

    scripts/manifest.py <tag> <distdir> <out.yaml>

Each build writes one pin-<minor>-<os>-<arch>.json describing the asset it just
produced. This collects them into tools.yaml's shape, keyed php-native-<minor>,
so lerd can be pointed at a new patch by editing a pin rather than a release.
"""
import json, pathlib, sys

tag, distdir, out = sys.argv[1], pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])

pins = {}
for f in sorted(distdir.glob("pin-*.json")):
    p = json.loads(f.read_text())
    pins.setdefault(p["minor"], []).append(p)

if not pins:
    sys.exit("manifest.py: no pin fragments in %s" % distdir)

lines = ["# Published by lerd-env/php. Pins the native PHP builds lerd downloads,",
         "# one entry per minor, each pointing at a single patch release.",
         "tools:"]
for minor in sorted(pins):
    entries = sorted(pins[minor], key=lambda p: p["platform"])
    versions = {p["version"] for p in entries}
    # Two architectures of one minor must be the same patch, or a machine's
    # PHP would depend on which one it happens to be.
    if len(versions) != 1:
        sys.exit("manifest.py: %s built as %s across platforms" % (minor, ", ".join(sorted(versions))))
    lines.append("  php-native-%s:" % minor)
    lines.append('    version: "%s"' % entries[0]["version"])
    lines.append("    url: https://github.com/lerd-env/php/releases/download/%s/{asset}" % tag)
    for field, key in (("assets", "asset"), ("digests", "sha256"), ("sizes", "size")):
        lines.append("    %s:" % field)
        for p in entries:
            lines.append("      %s: %s" % (p["platform"], p[key]))

out.write_text("\n".join(lines) + "\n")
print("\n".join(lines))
